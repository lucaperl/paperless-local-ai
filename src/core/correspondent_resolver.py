from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher
from typing import Any

from app_config import (
    CORRESPONDENT_MATCH_MARGIN_DEFAULT,
    CORRESPONDENT_MATCH_SIMILARITY_DEFAULT,
)


# Compatibility aliases for code/tests that referenced the pre-configurable constants.
FUZZY_MATCH_THRESHOLD = CORRESPONDENT_MATCH_SIMILARITY_DEFAULT
FUZZY_MATCH_MARGIN = CORRESPONDENT_MATCH_MARGIN_DEFAULT
FUZZY_MIN_NORMALIZED_LENGTH = 8


def normalize_correspondent_name(value: str | None) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).casefold()
    return " ".join(re.findall(r"\w+", text, flags=re.UNICODE))


def clean_candidate(value: str | None) -> str:
    return " ".join(str(value or "").split()).strip()


def _plausible_candidate(candidate: str) -> bool:
    if not candidate or len(candidate) > 255:
        return False
    normalized = normalize_correspondent_name(candidate)
    if len(normalized) < 2 or len(normalized.split()) > 20:
        return False
    if normalized in {
        "unknown",
        "unbekannt",
        "none",
        "null",
        "n a",
        "nicht erkennbar",
        "kein absender",
    }:
        return False
    return any(ch.isalpha() for ch in candidate)


def _score_candidates(normalized_candidate: str, existing: list[str]) -> list[tuple[float, str]]:
    return sorted(
        (
            (
                SequenceMatcher(None, normalized_candidate, normalize_correspondent_name(name)).ratio(),
                name,
            )
            for name in existing
            if clean_candidate(name)
        ),
        reverse=True,
    )


def resolve_correspondent(
    candidate: str | None,
    existing: list[str],
    *,
    minimum_similarity: float = FUZZY_MATCH_THRESHOLD,
    minimum_margin: float = FUZZY_MATCH_MARGIN,
) -> dict[str, Any]:
    """Resolve a free-text sender/issuer against existing Paperless correspondents."""
    candidate = clean_candidate(candidate)
    if not _plausible_candidate(candidate):
        return {
            "extracted": candidate,
            "status": "empty",
            "resolved": "",
            "suggestion": "",
            "match_score": None,
            "runner_up_score": None,
        }

    normalized_candidate = normalize_correspondent_name(candidate)
    exact = [
        name
        for name in existing
        if clean_candidate(name)
        and normalize_correspondent_name(name) == normalized_candidate
    ]
    if len(exact) == 1:
        return {
            "extracted": candidate,
            "status": "existing_exact",
            "resolved": exact[0],
            "suggestion": "",
            "match_score": 1.0,
            "runner_up_score": None,
        }

    scored = _score_candidates(normalized_candidate, existing)
    best_score, best_name = scored[0] if scored else (0.0, "")
    runner_up_score = scored[1][0] if len(scored) > 1 else 0.0
    margin = best_score - runner_up_score

    if (
        len(normalized_candidate) >= FUZZY_MIN_NORMALIZED_LENGTH
        and best_name
        and best_score >= minimum_similarity
        and margin >= minimum_margin
    ):
        return {
            "extracted": candidate,
            "status": "existing_fuzzy",
            "resolved": best_name,
            "suggestion": "",
            "match_score": round(best_score, 4),
            "runner_up_score": round(runner_up_score, 4),
        }

    return {
        "extracted": candidate,
        "status": "new_suggestion",
        "resolved": "",
        "suggestion": candidate,
        "match_score": round(best_score, 4) if scored else None,
        "runner_up_score": round(runner_up_score, 4) if len(scored) > 1 else None,
    }


def simulate_correspondent_match(
    candidate: str | None,
    existing: list[str],
    *,
    minimum_similarity: float = FUZZY_MATCH_THRESHOLD,
    minimum_margin: float = FUZZY_MATCH_MARGIN,
    limit: int = 3,
) -> dict[str, Any]:
    """Return a read-only explanation using the exact production matching logic."""
    candidate = clean_candidate(candidate)
    normalized_candidate = normalize_correspondent_name(candidate)
    resolution = resolve_correspondent(
        candidate,
        existing,
        minimum_similarity=minimum_similarity,
        minimum_margin=minimum_margin,
    )
    plausible = _plausible_candidate(candidate)
    scored = _score_candidates(normalized_candidate, existing) if plausible else []
    best_score = scored[0][0] if scored else None
    runner_up_score = scored[1][0] if len(scored) > 1 else None
    gate_runner_up = runner_up_score if runner_up_score is not None else 0.0
    winner_margin = (
        best_score - runner_up_score
        if best_score is not None and runner_up_score is not None
        else None
    )
    similarity_pass = best_score >= minimum_similarity if best_score is not None else None
    margin_pass = (
        best_score - gate_runner_up >= minimum_margin if best_score is not None else None
    )
    safe_limit = max(1, min(int(limit), 10))
    return {
        "candidate": candidate,
        "normalized_candidate": normalized_candidate,
        "normalized_length": len(normalized_candidate),
        "fuzzy_min_normalized_length": FUZZY_MIN_NORMALIZED_LENGTH,
        "length_pass": len(normalized_candidate) >= FUZZY_MIN_NORMALIZED_LENGTH,
        "minimum_similarity": minimum_similarity,
        "minimum_margin": minimum_margin,
        "thresholds_applied": resolution["status"] not in {"existing_exact", "empty"},
        "similarity_pass": similarity_pass,
        "margin_pass": margin_pass,
        "winner_margin": round(winner_margin, 4) if winner_margin is not None else None,
        "existing_count": sum(1 for name in existing if clean_candidate(name)),
        "candidates": [
            {"name": name, "score": round(score, 4)}
            for score, name in scored[:safe_limit]
        ],
        "resolution": resolution,
    }
