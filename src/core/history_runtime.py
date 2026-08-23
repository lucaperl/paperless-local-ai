from __future__ import annotations

import math
import os
import threading
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
from scipy.sparse import hstack
from sklearn.cluster import AgglomerativeClustering
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
from sklearn.neighbors import NearestNeighbors


REFRESH_SECONDS = 300
FAST_SIMILARITY = 0.60
FAMILY_SIMILARITY = 0.50
EXAMPLE_MIN_SIMILARITY = 0.08
TOP_VOTE_NEIGHBORS = 5
QUERY_NEIGHBORS = 30
MIN_SUPPORT = 2
MIN_WINNER_SHARE = 0.50
MAX_EXAMPLES = 5
MAX_EXAMPLES_PER_TAG_SET = 2
MAX_DIAGNOSTIC_DOCS = 2000
REFRESH_MARKER = Path(os.getenv("PLAI_HISTORY_REFRESH_MARKER", "/coordination/history-refresh"))


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _leaf_names_from_ids(tag_ids: list[int] | tuple[int, ...], tax: dict[str, Any]) -> list[str]:
    content_ids = set(tax.get("content_tag_ids", []))
    parent_by_id = tax.get("parent_by_id", {})
    name_by_id = tax.get("tag_by_id", {})
    selected = {int(tag_id) for tag_id in tag_ids if int(tag_id) in content_ids}
    parents_to_remove: set[int] = set()

    for tag_id in selected:
        parent = parent_by_id.get(tag_id)
        while parent:
            if parent in selected:
                parents_to_remove.add(parent)
            parent = parent_by_id.get(parent)

    return sorted(
        name_by_id[tag_id]
        for tag_id in selected - parents_to_remove
        if tag_id in name_by_id
    )


def _status_for_count(count: int) -> str:
    if count <= 0:
        return "No history"
    if count == 1:
        return "Very limited"
    if count < 5:
        return "Limited"
    if count < 10:
        return "Good"
    return "Strong"


def request_history_refresh() -> None:
    REFRESH_MARKER.parent.mkdir(parents=True, exist_ok=True)
    REFRESH_MARKER.touch()


class HistoryIndex:
    """Read-only similarity index over reviewed Paperless documents."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._entries: list[dict[str, Any]] = []
        self._word_vectorizer: TfidfVectorizer | None = None
        self._char_vectorizer: TfidfVectorizer | None = None
        self._matrix = None
        self._neighbors: NearestNeighbors | None = None
        self._source_signature: tuple[int, str | None, tuple] | None = None
        self._last_checked_monotonic = 0.0
        self._refreshed_at: str | None = None
        self._last_error: str | None = None
        self._marker_mtime = 0.0
        self._status: dict[str, Any] = self._empty_status()

    @staticmethod
    def _empty_status() -> dict[str, Any]:
        return {
            "status": "Not built",
            "reviewed_documents": 0,
            "tags_represented": 0,
            "eligible_tags": 0,
            "estimated_reuse_count": 0,
            "estimated_reuse_percent": 0.0,
            "estimated_reuse_sample_size": 0,
            "retrospective_routed_count": 0,
            "retrospective_agreement_count": 0,
            "potential_inconsistencies": [],
            "potential_inconsistency_count": 0,
            "per_tag": [],
            "last_updated": None,
            "last_error": None,
            "refresh_seconds": REFRESH_SECONDS,
            "thresholds": {
                "history_match_similarity": FAST_SIMILARITY,
                "support": MIN_SUPPORT,
                "winner_share": MIN_WINNER_SHARE,
                "inconsistency_similarity": FAMILY_SIMILARITY,
            },
        }

    @staticmethod
    def _taxonomy_signature(tax: dict[str, Any]) -> tuple:
        return tuple(
            sorted(
                (
                    int(item["id"]),
                    str(item["name"]),
                    int(item["parent"]) if item.get("parent") else None,
                )
                for item in tax.get("tags", [])
            )
        )

    @staticmethod
    def _excluded_tag_ids(
        tax: dict[str, Any],
        excluded_tag_names: str | list[str] | tuple[str, ...],
    ) -> list[int]:
        if isinstance(excluded_tag_names, str):
            excluded_tag_names = [excluded_tag_names]
        ids = []
        missing = []
        for name in excluded_tag_names:
            tag_id = tax.get("tag_by_name", {}).get(name)
            if tag_id is None:
                missing.append(name)
            else:
                ids.append(int(tag_id))
        if missing:
            raise RuntimeError(
                "History exclusion tag(s) not found in Paperless: " + ", ".join(repr(x) for x in missing)
            )
        return sorted(set(ids))

    def _marker_changed(self) -> bool:
        try:
            mtime = REFRESH_MARKER.stat().st_mtime
        except OSError:
            return False
        if mtime > self._marker_mtime:
            self._marker_mtime = mtime
            return True
        return False

    def _source_state(self, client, tax: dict[str, Any], excluded_tag_names: str | list[str] | tuple[str, ...]) -> tuple[int, str | None, tuple]:
        excluded_tag_ids = self._excluded_tag_ids(tax, excluded_tag_names)
        data = client.request(
            "GET",
            "/api/documents/",
            params={
                "tags__id__none": ",".join(str(x) for x in excluded_tag_ids),
                "ordering": "-modified",
                "page_size": 1,
                "fields": "id,modified",
            },
        ).json()
        results = data.get("results", []) if isinstance(data, dict) else []
        modified = results[0].get("modified") if results else None
        return int(data.get("count", len(results))), modified, self._taxonomy_signature(tax)

    def _fetch_reviewed_documents(self, client, tax: dict[str, Any], excluded_tag_names: str | list[str] | tuple[str, ...]) -> list[dict[str, Any]]:
        excluded_tag_ids = self._excluded_tag_ids(tax, excluded_tag_names)
        entries: list[dict[str, Any]] = []
        page = 1
        while True:
            data = client.request(
                "GET",
                "/api/documents/",
                params={
                    "tags__id__none": ",".join(str(x) for x in excluded_tag_ids),
                    "ordering": "id",
                    "page_size": 100,
                    "page": page,
                    "fields": "id,title,content,tags,modified",
                },
            ).json()
            for doc in data.get("results", []):
                content = (doc.get("content") or "").strip()
                if not content:
                    continue
                entries.append(
                    {
                        "id": int(doc["id"]),
                        "title": doc.get("title") or f"Document {doc['id']}",
                        "content": content,
                        "tags": _leaf_names_from_ids(doc.get("tags", []), tax),
                        "modified": doc.get("modified"),
                    }
                )
            if not data.get("next"):
                break
            page += 1
        return entries

    @staticmethod
    def _fit_space(texts: list[str]):
        word = TfidfVectorizer(ngram_range=(1, 2), dtype=np.float32, norm="l2")
        char = TfidfVectorizer(
            analyzer="char_wb",
            ngram_range=(3, 5),
            dtype=np.float32,
            norm="l2",
        )
        word_matrix = None
        char_matrix = None
        try:
            word_matrix = word.fit_transform(texts)
        except ValueError:
            word = None
        try:
            char_matrix = char.fit_transform(texts)
        except ValueError:
            char = None

        parts = []
        if word_matrix is not None:
            parts.append(word_matrix)
        if char_matrix is not None:
            parts.append(char_matrix)
        if not parts:
            raise RuntimeError("Reviewed documents do not contain usable text for history matching")
        weight = 1.0 / math.sqrt(len(parts))
        matrix = hstack([part * weight for part in parts], format="csr", dtype=np.float32)
        return word, char, matrix, weight

    def _transform(self, content: str):
        parts = []
        if self._word_vectorizer is not None:
            parts.append(self._word_vectorizer.transform([content]))
        if self._char_vectorizer is not None:
            parts.append(self._char_vectorizer.transform([content]))
        if not parts:
            raise RuntimeError("History index is not ready")
        weight = 1.0 / math.sqrt(len(parts))
        return hstack([part * weight for part in parts], format="csr", dtype=np.float32)

    def _nearest_from_vector(self, vector, *, exclude_id: int | None = None, limit: int = QUERY_NEIGHBORS):
        if not self._entries or self._neighbors is None:
            return []
        extra = 1 if exclude_id is not None else 0
        count = min(len(self._entries), max(1, limit + extra))
        distances, indices = self._neighbors.kneighbors(vector, n_neighbors=count)
        result = []
        for distance, index in zip(distances[0], indices[0], strict=False):
            entry = self._entries[int(index)]
            if exclude_id is not None and entry["id"] == int(exclude_id):
                continue
            result.append((entry, max(0.0, min(1.0, 1.0 - float(distance)))))
            if len(result) >= limit:
                break
        return result

    @staticmethod
    def _decision(neighbors: list[tuple[dict[str, Any], float]]) -> dict[str, Any]:
        if not neighbors:
            return {
                "confident": False,
                "tag": None,
                "top_similarity": 0.0,
                "support": 0,
                "winner_share": 0.0,
            }
        top = neighbors[0]
        vote_neighbors = neighbors[:TOP_VOTE_NEIGHBORS]
        weights: defaultdict[str, float] = defaultdict(float)
        supports: Counter[str] = Counter()
        for entry, similarity in vote_neighbors:
            for tag in entry["tags"]:
                weights[tag] += similarity
                supports[tag] += 1
        if not weights:
            return {
                "confident": False,
                "tag": None,
                "top_similarity": top[1],
                "support": 0,
                "winner_share": 0.0,
            }
        winner = max(weights, key=lambda tag: (weights[tag], supports[tag], tag))
        total_weight = sum(weights.values())
        share = weights[winner] / total_weight if total_weight else 0.0
        top_tags = top[0]["tags"]
        confident = (
            top[1] >= FAST_SIMILARITY
            and len(top_tags) == 1
            and top_tags[0] == winner
            and supports[winner] >= MIN_SUPPORT
            and share >= MIN_WINNER_SHARE
        )
        return {
            "confident": confident,
            "tag": winner,
            "top_similarity": round(top[1], 4),
            "support": int(supports[winner]),
            "winner_share": round(share, 4),
            "top_document_id": int(top[0]["id"]),
            "top_document_title": top[0]["title"],
        }

    @staticmethod
    def _examples(neighbors: list[tuple[dict[str, Any], float]]) -> list[dict[str, Any]]:
        examples = []
        combo_counts: Counter[tuple[str, ...]] = Counter()
        for entry, similarity in neighbors:
            if similarity < EXAMPLE_MIN_SIMILARITY or not entry["tags"]:
                continue
            combo = tuple(entry["tags"])
            if combo_counts[combo] >= MAX_EXAMPLES_PER_TAG_SET:
                continue
            combo_counts[combo] += 1
            excerpt = " ".join(entry["content"].split())[:500]
            examples.append(
                {
                    "id": entry["id"],
                    "title": entry["title"],
                    "tags": list(entry["tags"]),
                    "similarity": round(similarity, 4),
                    "excerpt": excerpt,
                }
            )
            if len(examples) >= MAX_EXAMPLES:
                break
        return examples

    def _diagnostics(self, tax: dict[str, Any]) -> dict[str, Any]:
        n = len(self._entries)
        per_tag_counts: Counter[str] = Counter()
        for entry in self._entries:
            per_tag_counts.update(entry["tags"])
        per_tag = [
            {
                "id": item["id"],
                "name": item["name"],
                "count": int(per_tag_counts[item["name"]]),
                "status": _status_for_count(int(per_tag_counts[item["name"]])),
            }
            for item in tax.get("tags", [])
        ]
        per_tag.sort(key=lambda row: row["name"].casefold())

        if not n or self._neighbors is None or self._matrix is None:
            return {
                "estimated_reuse_count": 0,
                "estimated_reuse_percent": 0.0,
                "estimated_reuse_sample_size": 0,
                "retrospective_routed_count": 0,
                "retrospective_agreement_count": 0,
                "potential_inconsistencies": [],
                "per_tag": per_tag,
            }

        if n <= MAX_DIAGNOSTIC_DOCS:
            sample_indices = np.arange(n, dtype=int)
        else:
            sample_indices = np.unique(
                np.linspace(0, n - 1, MAX_DIAGNOSTIC_DOCS, dtype=int)
            )

        query_matrix = self._matrix[sample_indices]
        neighbor_count = min(n, QUERY_NEIGHBORS + 1)
        distances, indices = self._neighbors.kneighbors(query_matrix, n_neighbors=neighbor_count)
        routed = 0
        agreement = 0
        for row_pos, source_index in enumerate(sample_indices):
            neighbors = []
            for distance, idx in zip(distances[row_pos], indices[row_pos], strict=False):
                idx = int(idx)
                if idx == int(source_index):
                    continue
                neighbors.append(
                    (
                        self._entries[idx],
                        max(0.0, min(1.0, 1.0 - float(distance))),
                    )
                )
                if len(neighbors) >= QUERY_NEIGHBORS:
                    break
            decision = self._decision(neighbors)
            if decision["confident"]:
                routed += 1
                if self._entries[int(source_index)]["tags"] == [decision["tag"]]:
                    agreement += 1

        sample_size = len(sample_indices)
        reuse_percent = (agreement / sample_size * 100.0) if sample_size else 0.0

        # Potential-inconsistency families use the calibrated complete-linkage
        # rule at similarity >= 0.50.  Diagnostics are capped at
        # MAX_DIAGNOSTIC_DOCS so the dense similarity matrix stays bounded.
        diagnostic_matrix = self._matrix[sample_indices]
        similarities = cosine_similarity(diagnostic_matrix, dense_output=True)
        distances_complete = np.clip(1.0 - similarities, 0.0, 2.0)
        np.fill_diagonal(distances_complete, 0.0)
        if sample_size >= 2:
            clustering = AgglomerativeClustering(
                n_clusters=None,
                metric="precomputed",
                linkage="complete",
                distance_threshold=1.0 - FAMILY_SIMILARITY + 1e-9,
                compute_full_tree=True,
            )
            labels = clustering.fit_predict(distances_complete)
        elif sample_size == 1:
            labels = np.array([0], dtype=int)
        else:
            labels = np.array([], dtype=int)

        groups: defaultdict[int, list[int]] = defaultdict(list)
        for local_index, label in enumerate(labels):
            groups[int(label)].append(int(sample_indices[local_index]))

        inconsistencies = []
        for members in groups.values():
            if len(members) < 3:
                continue
            combos: Counter[tuple[str, ...]] = Counter(
                tuple(self._entries[idx]["tags"]) for idx in members
            )
            if len(combos) <= 1:
                continue
            documents = [
                {
                    "id": self._entries[idx]["id"],
                    "title": self._entries[idx]["title"],
                    "tags": list(self._entries[idx]["tags"]),
                }
                for idx in members[:20]
            ]
            inconsistencies.append(
                {
                    "documents": len(members),
                    "tag_sets": [
                        {
                            "tags": list(combo),
                            "count": count,
                        }
                        for combo, count in combos.most_common()
                    ],
                    "examples": documents,
                    "truncated": len(members) > len(documents),
                }
            )
        inconsistencies.sort(key=lambda item: item["documents"], reverse=True)

        return {
            "estimated_reuse_count": agreement,
            "estimated_reuse_percent": round(reuse_percent, 1),
            "estimated_reuse_sample_size": sample_size,
            "retrospective_routed_count": routed,
            "retrospective_agreement_count": agreement,
            "potential_inconsistencies": inconsistencies[:10],
            "per_tag": per_tag,
        }

    def refresh(self, client, tax: dict[str, Any], excluded_tag_names: str | list[str] | tuple[str, ...], *, force: bool = False) -> dict[str, Any]:
        with self._lock:
            now = time.monotonic()
            marker_force = self._marker_changed()
            if not force and not marker_force and self._entries and now - self._last_checked_monotonic < REFRESH_SECONDS:
                return self.status()
            try:
                source_signature = self._source_state(client, tax, excluded_tag_names)
                self._last_checked_monotonic = now
                if not force and not marker_force and self._source_signature == source_signature and self._matrix is not None:
                    return self.status()

                entries = self._fetch_reviewed_documents(client, tax, excluded_tag_names)
                self._entries = entries
                self._word_vectorizer = None
                self._char_vectorizer = None
                self._matrix = None
                self._neighbors = None

                if entries:
                    texts = [entry["content"] for entry in entries]
                    word, char, matrix, _weight = self._fit_space(texts)
                    neighbors = NearestNeighbors(metric="cosine", algorithm="brute")
                    neighbors.fit(matrix)
                    self._word_vectorizer = word
                    self._char_vectorizer = char
                    self._matrix = matrix
                    self._neighbors = neighbors

                diagnostics = self._diagnostics(tax)
                represented = len({tag for entry in entries for tag in entry["tags"]})
                self._refreshed_at = utc_now_iso()
                self._source_signature = source_signature
                self._last_error = None
                self._status = {
                    "status": "Ready" if len(entries) >= MIN_SUPPORT else "Not enough history",
                    "reviewed_documents": len(entries),
                    "tags_represented": represented,
                    "eligible_tags": len(tax.get("tags", [])),
                    "estimated_reuse_count": diagnostics["estimated_reuse_count"],
                    "estimated_reuse_percent": diagnostics["estimated_reuse_percent"],
                    "estimated_reuse_sample_size": diagnostics["estimated_reuse_sample_size"],
                    "retrospective_routed_count": diagnostics["retrospective_routed_count"],
                    "retrospective_agreement_count": diagnostics["retrospective_agreement_count"],
                    "potential_inconsistencies": diagnostics["potential_inconsistencies"],
                    "potential_inconsistency_count": len(diagnostics["potential_inconsistencies"]),
                    "per_tag": diagnostics["per_tag"],
                    "last_updated": self._refreshed_at,
                    "last_error": None,
                    "refresh_seconds": REFRESH_SECONDS,
                    "thresholds": {
                        "history_match_similarity": FAST_SIMILARITY,
                        "support": MIN_SUPPORT,
                        "winner_share": MIN_WINNER_SHARE,
                        "inconsistency_similarity": FAMILY_SIMILARITY,
                    },
                }
            except Exception as exc:
                self._last_checked_monotonic = now
                self._last_error = f"{type(exc).__name__}: {exc}"
                self._status = dict(self._status)
                self._status.update({"status": "Error", "last_error": self._last_error})
            return self.status()

    def status(self) -> dict[str, Any]:
        with self._lock:
            status = dict(self._status)
            status["potential_inconsistencies"] = [
                {
                    **item,
                    "tag_sets": [dict(x) for x in item.get("tag_sets", [])],
                    "examples": [dict(x) for x in item.get("examples", [])],
                }
                for item in self._status.get("potential_inconsistencies", [])
            ]
            status["per_tag"] = [dict(item) for item in self._status.get("per_tag", [])]
            return status

    def route(
        self,
        content: str,
        *,
        exclude_id: int | None = None,
    ) -> dict[str, Any]:
        with self._lock:
            if not self._entries or self._matrix is None:
                return {
                    "route": "llm_fallback",
                    "reason": "not_enough_history",
                    "examples": [],
                }
            vector = self._transform((content or "").strip())
            neighbors = self._nearest_from_vector(vector, exclude_id=exclude_id)
            decision = self._decision(neighbors)
            if decision["confident"]:
                return {
                    "route": "history_match",
                    "tag": decision["tag"],
                    "similarity": decision["top_similarity"],
                    "support": decision["support"],
                    "winner_share": decision["winner_share"],
                    "top_document_id": decision.get("top_document_id"),
                    "top_document_title": decision.get("top_document_title"),
                    "examples": [],
                }
            return {
                "route": "llm_fallback",
                "reason": "no_confident_history_match",
                "similarity": decision["top_similarity"],
                "support": decision["support"],
                "winner_share": decision["winner_share"],
                "candidate_tag": decision.get("tag"),
                "examples": self._examples(neighbors),
            }

    def tagging_context(
        self,
        client,
        tax: dict[str, Any],
        config: dict[str, Any],
        excluded_tag_names: str | list[str] | tuple[str, ...],
        document: dict[str, Any],
        *,
        force_refresh: bool = False,
    ) -> dict[str, Any]:
        mode = config.get("tagging_mode", "history_assisted")
        if mode == "llm_only":
            return {
                "mode": "llm_only",
                "route": "llm_only",
                "llm_decides": True,
                "examples": [],
            }
        self.refresh(client, tax, excluded_tag_names, force=force_refresh)
        if self._status.get("status") == "Error":
            return {
                "mode": "history_assisted",
                "route": "llm_fallback",
                "llm_decides": True,
                "reason": "history_error",
                "history_error": self._status.get("last_error"),
                "examples": [],
            }
        route = self.route(
            document.get("content") or "",
            exclude_id=int(document["id"]) if document.get("id") is not None else None,
        )
        route["mode"] = "history_assisted"
        route["llm_decides"] = route["route"] != "history_match"
        return route
