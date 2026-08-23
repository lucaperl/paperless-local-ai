from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher
from typing import Any


FUZZY_MATCH_THRESHOLD = 0.93
FUZZY_MATCH_MARGIN = 0.04
FUZZY_MIN_NORMALIZED_LENGTH = 8
EXTENDED_MIN_EXISTING_TOKENS = 3
EXTENDED_MIN_EXISTING_LENGTH = 16
EXTENDED_MAX_EXTRA_TOKENS = 2
LEGAL_FORM_TOKENS = {
    "ag", "gbr", "gmbh", "inc", "kg", "kgaa", "llc", "llp", "ltd", "ohg", "plc", "se", "ug"
}


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


def _unique_extended_match(
    normalized_candidate: str,
    normalized_existing: list[tuple[str, str]],
) -> str | None:
    candidate_tokens = normalized_candidate.split()
    matches: list[tuple[int, str]] = []
    for name, normalized in normalized_existing:
        existing_tokens = normalized.split()
        extra = len(candidate_tokens) - len(existing_tokens)
        if (
            len(existing_tokens) < EXTENDED_MIN_EXISTING_TOKENS
            or len(normalized) < EXTENDED_MIN_EXISTING_LENGTH
            or extra < 1
            or extra > EXTENDED_MAX_EXTRA_TOKENS
            or candidate_tokens[: len(existing_tokens)] != existing_tokens
        ):
            continue
        suffix = candidate_tokens[len(existing_tokens) :]
        if any(token in LEGAL_FORM_TOKENS for token in suffix):
            continue
        matches.append((len(existing_tokens), name))

    if not matches:
        return None
    longest = max(length for length, _name in matches)
    winners = sorted({name for length, name in matches if length == longest})
    return winners[0] if len(winners) == 1 else None


def resolve_correspondent(candidate: str | None, existing: list[str]) -> dict[str, Any]:
    """Resolve one free-text sender/issuer extracted by the main LLM call."""
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
            (SequenceMatcher(None, normalized_candidate, normalized).ratio(), name)
            for name, normalized in normalized_existing
        ),
        reverse=True,
    )
    best_score, best_name = scored[0] if scored else (0.0, "")
    runner_up_score = scored[1][0] if len(scored) > 1 else 0.0

    extended_name = _unique_extended_match(normalized_candidate, normalized_existing)
    if extended_name and best_name == extended_name:
        extended_score = next((score for score, name in scored if name == extended_name), 0.0)
        other_scores = [score for score, name in scored if name != extended_name]
        extended_runner_up = max(other_scores, default=0.0)
        return {
            "extracted": candidate,
            "status": "existing_extended",
            "resolved": extended_name,
            "suggestion": "",
            "match_score": round(extended_score, 4),
            "runner_up_score": round(extended_runner_up, 4) if other_scores else None,
        }

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
