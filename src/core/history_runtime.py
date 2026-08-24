from __future__ import annotations

import math
import threading
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from typing import Any

import numpy as np
from scipy.sparse import hstack
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.preprocessing import normalize

from history_common import (
    EXAMPLE_MIN_SIMILARITY,
    FAMILY_SIMILARITY,
    FAST_SIMILARITY,
    MAX_DIAGNOSTIC_DOCS,
    MAX_EXAMPLES,
    MAX_EXAMPLES_PER_TAG_SET,
    MIN_SUPPORT,
    MIN_WINNER_SHARE,
    QUERY_NEIGHBORS,
    TOP_VOTE_NEIGHBORS,
    _leaf_names_from_ids,
    empty_history_status,
    fetch_reviewed_documents,
    history_source_state,
)


REFRESH_SECONDS = 300


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


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


class HistoryIndex:
    """Read-only TF-IDF similarity index over reviewed Paperless documents."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._entries: list[dict[str, Any]] = []
        self._word_vectorizer: TfidfVectorizer | None = None
        self._char_vectorizer: TfidfVectorizer | None = None
        self._matrix = None
        self._source_signature: dict[str, Any] | None = None
        self._last_checked_monotonic = 0.0
        self._refreshed_at: str | None = None
        self._last_error: str | None = None
        self._status: dict[str, Any] = empty_history_status()

    @staticmethod
    def _source_state(client, tax, excluded_tag_names):
        return history_source_state(client, tax, excluded_tag_names)

    @staticmethod
    def _fetch_reviewed_documents(client, tax, excluded_tag_names):
        return fetch_reviewed_documents(client, tax, excluded_tag_names)

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
        # Re-normalize the combined vector space. Individual TF-IDF branches
        # are L2-normalized, but a document can have an empty word or character
        # branch. Explicit row normalization keeps sparse dot products exactly
        # equivalent to cosine similarity for those edge cases too.
        matrix = normalize(matrix, norm="l2", copy=False)
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
        vector = hstack([part * weight for part in parts], format="csr", dtype=np.float32)
        return normalize(vector, norm="l2", copy=False)

    def _nearest_from_vector(
        self,
        vector,
        *,
        exclude_id: int | None = None,
        limit: int = QUERY_NEIGHBORS,
    ):
        if not self._entries or self._matrix is None:
            return []

        # Combined vectors are explicitly L2-normalized, including rows where
        # one TF-IDF branch is empty, so sparse dot product is cosine similarity.
        similarities = (self._matrix @ vector.T).toarray().ravel()
        order = np.argsort(-similarities, kind="stable")
        result = []
        for raw_index in order:
            index = int(raw_index)
            entry = self._entries[index]
            if exclude_id is not None and entry["id"] == int(exclude_id):
                continue
            similarity = max(0.0, min(1.0, float(similarities[index])))
            result.append((entry, similarity))
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
        # AgglomerativeClustering is only required while rebuilding diagnostics.
        # Keeping it out of module-level imports makes cache-only routing lighter.
        from sklearn.cluster import AgglomerativeClustering

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

        if not n or self._matrix is None:
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
            sample_indices = np.unique(np.linspace(0, n - 1, MAX_DIAGNOSTIC_DOCS, dtype=int))

        routed = 0
        agreement = 0
        for source_index in sample_indices:
            source_index = int(source_index)
            vector = self._matrix[source_index]
            neighbors = self._nearest_from_vector(
                vector,
                exclude_id=self._entries[source_index]["id"],
                limit=QUERY_NEIGHBORS,
            )
            decision = self._decision(neighbors)
            if decision["confident"]:
                routed += 1
                if self._entries[source_index]["tags"] == [decision["tag"]]:
                    agreement += 1

        sample_size = len(sample_indices)
        reuse_percent = (agreement / sample_size * 100.0) if sample_size else 0.0

        diagnostic_matrix = self._matrix[sample_indices]
        similarities = (diagnostic_matrix @ diagnostic_matrix.T).toarray()
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
                        {"tags": list(combo), "count": count}
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

    def refresh(
        self,
        client,
        tax: dict[str, Any],
        excluded_tag_names: str | list[str] | tuple[str, ...],
        *,
        force: bool = False,
    ) -> dict[str, Any]:
        with self._lock:
            now = time.monotonic()
            if not force and self._entries and now - self._last_checked_monotonic < REFRESH_SECONDS:
                return self.status()
            try:
                source_signature = history_source_state(client, tax, excluded_tag_names)
                self._last_checked_monotonic = now
                if not force and self._source_signature == source_signature and self._matrix is not None:
                    return self.status()

                entries = fetch_reviewed_documents(client, tax, excluded_tag_names)
                self._entries = entries
                self._word_vectorizer = None
                self._char_vectorizer = None
                self._matrix = None

                if entries:
                    texts = [entry["content"] for entry in entries]
                    word, char, matrix, _weight = self._fit_space(texts)
                    self._word_vectorizer = word
                    self._char_vectorizer = char
                    self._matrix = matrix

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

    def cache_payload(self) -> dict[str, Any]:
        with self._lock:
            compact_entries = [
                {
                    "id": entry["id"],
                    "title": entry["title"],
                    "content": " ".join(entry.get("content", "").split())[:500],
                    "tags": list(entry.get("tags", [])),
                    "modified": entry.get("modified"),
                }
                for entry in self._entries
            ]
            return {
                "entries": compact_entries,
                "word_vectorizer": self._word_vectorizer,
                "char_vectorizer": self._char_vectorizer,
                "matrix": self._matrix,
            }

    def load_cache_payload(
        self,
        payload: dict[str, Any],
        *,
        status: dict[str, Any],
        source_signature: dict[str, Any],
    ) -> None:
        if not isinstance(payload, dict):
            raise ValueError("History cache payload must be an object")
        entries = payload.get("entries")
        if not isinstance(entries, list):
            raise ValueError("History cache entries are missing")
        with self._lock:
            self._entries = entries
            self._word_vectorizer = payload.get("word_vectorizer")
            self._char_vectorizer = payload.get("char_vectorizer")
            self._matrix = payload.get("matrix")
            self._source_signature = source_signature
            self._status = dict(status)
            self._refreshed_at = status.get("last_updated")
            self._last_error = status.get("last_error")
            self._last_checked_monotonic = time.monotonic()

    def route(self, content: str, *, exclude_id: int | None = None) -> dict[str, Any]:
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
