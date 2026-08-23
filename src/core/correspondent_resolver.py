from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher
from typing import Any


FUZZY_MATCH_THRESHOLD = 0.93
FUZZY_MATCH_MARGIN = 0.04
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


def resolve_correspondent(candidate: str | None, existing: list[str]) -> dict[str, Any]:
    """
    Resolve one free-text sender/issuer extracted by the main LLM call.

    Exact normalized matches and deliberately conservative fuzzy matches are
    safe to apply automatically. Other plausible names remain suggestions for
    human review; they are never auto-created.
    """
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
    normalized_existing = [
        (name, normalize_correspondent_name(name))
        for name in existing
        if clean_candidate(name)
    ]

    exact = [name for name, normalized in normalized_existing if normalized == normalized_candidate]
    if len(exact) == 1:
        return {
            "extracted": candidate,
            "status": "existing_exact",
            "resolved": exact[0],
            "suggestion": "",
            "match_score": 1.0,
            "runner_up_score": None,
        }

    scored = sorted(
        (
            (
                SequenceMatcher(None, normalized_candidate, normalized).ratio(),
                name,
            )
            for name, normalized in normalized_existing
        ),
        reverse=True,
    )
    best_score, best_name = scored[0] if scored else (0.0, "")
    runner_up_score = scored[1][0] if len(scored) > 1 else 0.0
    margin = best_score - runner_up_score

    if (
        len(normalized_candidate) >= FUZZY_MIN_NORMALIZED_LENGTH
        and best_name
        and best_score >= FUZZY_MATCH_THRESHOLD
        and margin >= FUZZY_MATCH_MARGIN
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
