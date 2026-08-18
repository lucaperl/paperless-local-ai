import json

import review_store


def test_signature_is_normalization_stable():
    a = review_store.signature_material(
        "Invoice  2026.PDF",
        "Hello   WORLD 123",
    )
    b = review_store.signature_material(
        "invoice 2026.pdf",
        "hello world 123",
    )
    assert a == b


def test_prompt_content_signature_is_normalization_stable():
    a = review_store.prompt_content_signature(
        "Hello   WORLD 123"
    )
    b = review_store.prompt_content_signature(
        "hello world 123"
    )
    assert a == b


def test_record_v4_disambiguates_same_96_word_prefix_by_prompt_content(tmp_path, monkeypatch):
    monkeypatch.setattr(
        review_store,
        "REVIEW_DIR",
        tmp_path,
    )

    prefix = " ".join(
        f"word{i}"
        for i in range(96)
    )

    doc_a = {
        "id": 10,
        "content": prefix + " unique alpha ending",
        "original_file_name": "totally-unrelated-a.pdf",
    }
    doc_b = {
        "id": 11,
        "content": prefix + " unique beta ending",
        "original_file_name": "totally-unrelated-b.pdf",
    }

    a = review_store.write_review_record(doc_a)
    b = review_store.write_review_record(doc_b)

    assert a["version"] == 4
    assert b["version"] == 4
    assert a["content_signature"] == b["content_signature"]
    assert a["prompt_content_signature"] != b["prompt_content_signature"]

    record, reason = review_store.match_review_record(
        "internal/storage/name-that-api-does-not-expose.pdf",
        doc_b["content"],
    )

    assert record["document_id"] == 11
    assert reason == "prompt_content_signature"


def test_record_v4_fails_closed_for_identical_prompt_content(tmp_path, monkeypatch):
    monkeypatch.setattr(
        review_store,
        "REVIEW_DIR",
        tmp_path,
    )

    content = "identical document content"

    review_store.write_review_record({"id": 20, "content": content})
    review_store.write_review_record({"id": 21, "content": content})

    record, reason = review_store.match_review_record(
        "any.pdf",
        content,
    )

    assert record is None
    assert reason == "prompt_content_signature mehrdeutig (2)"


def test_atomic_write_is_real_and_valid_json(tmp_path, monkeypatch):
    monkeypatch.setattr(
        review_store,
        "REVIEW_DIR",
        tmp_path,
    )

    record = review_store.write_review_record(
        {
            "id": 42,
            "content": "hello world",
            "original_file_name": "hello.pdf",
        },
        correspondent_suggestion="Example GmbH",
    )

    stored = json.loads(
        (tmp_path / "42.json").read_text(
            encoding="utf-8"
        )
    )

    assert stored == record
    assert stored["version"] == 4
    assert not (tmp_path / "42.json.tmp").exists()
