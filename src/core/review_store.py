from __future__ import annotations

import hashlib
import json
import os
import re
import unicodedata
from datetime import datetime
from pathlib import Path
from typing import Any

REVIEW_DIR = Path("/data/correspondent-suggestions")
SIGNATURE_WORDS = 96
PAPERLESS_PROMPT_CONTENT_CHARS = 4000
RECORD_VERSION = 4


def utc_now_iso() -> str:
    return datetime.now().astimezone().isoformat()


def normalize_signature_text(value: str | None) -> str:
    text = unicodedata.normalize(
        "NFKC",
        value or "",
    ).casefold()

    return " ".join(
        re.findall(
            r"\w+",
            text,
            flags=re.UNICODE,
        )
    )


def content_word_prefix(
    content: str | None,
) -> str:
    words = normalize_signature_text(
        content
    ).split()

    return " ".join(
        words[:SIGNATURE_WORDS]
    )


def paperless_prompt_content(
    content: str | None,
) -> str:
    """
    Normalize the portion of document content Paperless 3.0.5 feeds into its
    no-RAG classifier before token-budget truncation.

    Paperless 3.0.5 calls truncate_content(document.content[:4000], ...).
    With sufficient AI context this normalized value is therefore identical
    to the content visible to the suggestion bridge. If Paperless truncates it
    further, the exact signature deliberately does not match and the bridge
    falls back to the legacy 96-word identity / fail-closed path.
    """
    return normalize_signature_text(
        (content or "")[:PAPERLESS_PROMPT_CONTENT_CHARS]
    )


def _sha256_text(value: str) -> str:
    return hashlib.sha256(
        value.encode("utf-8")
    ).hexdigest()


def prompt_content_signature(
    content: str | None,
) -> str:
    return _sha256_text(
        paperless_prompt_content(content)
    )


def signature_material(
    filename: str | None,
    content: str | None,
) -> dict[str, str]:
    """Legacy v2/v3 signature helper retained for migration/tests."""
    normalized_filename = normalize_signature_text(
        filename
    )

    prefix = content_word_prefix(
        content
    )

    content_signature = _sha256_text(
        prefix
    )

    document_signature = _sha256_text(
        normalized_filename
        + "\0"
        + prefix
    )

    return {
        "document_signature": document_signature,
        "content_signature": content_signature,
    }


def build_review_record(
    document: dict[str, Any],
    *,
    correspondent_suggestion: str = "",
    correspondent_meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    doc_id = int(
        document["id"]
    )

    content = document.get(
        "content"
    )

    candidate = " ".join(
        (
            correspondent_suggestion
            or ""
        ).split()
    ).strip()

    if len(candidate) > 255:
        raise ValueError(
            "Correspondent suggestion is longer than 255 characters"
        )

    return {
        "version": RECORD_VERSION,
        "document_id": doc_id,
        "generated_at": utc_now_iso(),
        "signature_words": SIGNATURE_WORDS,
        "prompt_content_chars": PAPERLESS_PROMPT_CONTENT_CHARS,
        "content_signature": _sha256_text(
            content_word_prefix(content)
        ),
        "prompt_content_signature": prompt_content_signature(
            content
        ),
        "correspondent_suggestion": candidate,
        "correspondent_meta": correspondent_meta or {},
    }


def _atomic_write_json(
    path: Path,
    data: dict[str, Any],
) -> None:
    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    tmp = path.with_name(
        path.name + ".tmp"
    )

    tmp.write_text(
        json.dumps(
            data,
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    os.replace(
        tmp,
        path,
    )


def write_review_record(
    document: dict[str, Any],
    *,
    correspondent_suggestion: str = "",
    correspondent_meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    record = build_review_record(
        document,
        correspondent_suggestion=correspondent_suggestion,
        correspondent_meta=correspondent_meta,
    )

    _atomic_write_json(
        REVIEW_DIR
        / f"{record['document_id']}.json",
        record,
    )

    return record


def load_review_records() -> list[dict[str, Any]]:
    if not REVIEW_DIR.exists():
        return []

    records = []

    for path in sorted(
        REVIEW_DIR.glob("*.json")
    ):
        try:
            data = json.loads(
                path.read_text(
                    encoding="utf-8",
                )
            )
        except (
            OSError,
            json.JSONDecodeError,
        ):
            continue

        version = data.get(
            "version"
        ) if isinstance(data, dict) else None

        if version not in {
            2,
            3,
            RECORD_VERSION,
        }:
            continue

        try:
            data["document_id"] = int(
                data["document_id"]
            )
        except (
            KeyError,
            TypeError,
            ValueError,
        ):
            continue

        if not isinstance(
            data.get("content_signature"),
            str,
        ):
            continue

        if version in {2, 3}:
            if not isinstance(
                data.get("document_signature"),
                str,
            ):
                continue

        if version == RECORD_VERSION:
            if not isinstance(
                data.get("prompt_content_signature"),
                str,
            ):
                continue

        records.append(
            data
        )

    return records


def records_for_content(
    content: str | None,
    records: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    content_signature = _sha256_text(
        content_word_prefix(content)
    )

    source = (
        records
        if records is not None
        else load_review_records()
    )

    return [
        item
        for item in source
        if item.get("content_signature")
        == content_signature
    ]


def match_review_record(
    filename: str | None,
    content: str | None,
):
    # Paperless 3.0.5 puts its internal Document.filename in the AI prompt,
    # but that storage filename is not exposed by DocumentSerializer. Do not
    # pretend original_file_name/archived_file_name are equivalent. Identity
    # therefore uses prompt content only; `filename` stays in this signature
    # for API compatibility with the existing bridge call site.
    del filename

    records = load_review_records()

    strong_signature = prompt_content_signature(
        content
    )

    strong_matches = [
        item
        for item in records
        if item.get("prompt_content_signature")
        == strong_signature
    ]

    if len(strong_matches) == 1:
        return (
            strong_matches[0],
            "prompt_content_signature",
        )

    if len(strong_matches) > 1:
        return (
            None,
            "prompt_content_signature ambiguous "
            f"({len(strong_matches)})",
        )

    content_matches = records_for_content(
        content,
        records,
    )

    if len(content_matches) == 1:
        return (
            content_matches[0],
            "content_signature",
        )

    if len(content_matches) > 1:
        return (
            None,
            "content_signature ambiguous "
            f"({len(content_matches)})",
        )

    return (
        None,
        "no review record",
    )
