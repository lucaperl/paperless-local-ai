from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src" / "common"))
sys.path.insert(0, str(ROOT / "src" / "core"))


def module():
    sys.modules.pop("rag_engine", None)
    return importlib.import_module("rag_engine")


def test_chunking_is_bounded_and_overlapping():
    rag = module()
    text = ("Alpha beta gamma delta. " * 180) + "\n\n" + ("Second paragraph. " * 120)
    chunks = rag.chunks_for_text(text, 1000, 200)
    assert len(chunks) > 2
    assert all(1 <= len(chunk) <= 1000 for chunk in chunks)
    assert any(chunks[index][-80:] in chunks[index + 1] for index in range(len(chunks) - 1))


def test_chat_settings_are_bounded():
    rag = module()
    valid = rag._validate_chat_settings(
        {
            "model": "example:latest",
            "think": "auto",
            "num_ctx": 8192,
            "top_k": 5,
            "temperature": 0.1,
            "num_predict": 512,
        }
    )
    assert valid["top_k"] == 5
    with pytest.raises(ValueError):
        rag._validate_chat_settings({**valid, "top_k": 99})
    with pytest.raises(ValueError):
        rag._validate_chat_settings({**valid, "think": "sometimes"})


def test_request_scope_requires_document_id():
    rag = module()
    cfg = rag.validate_config({})
    with pytest.raises(ValueError):
        rag.validate_chat_request({"question": "When?", "scope": "document"}, cfg)
    request = rag.validate_chat_request(
        {"question": "When?", "scope": "document", "document_id": 42}, cfg
    )
    assert request["document_id"] == 42

    tag_request = rag.validate_chat_request(
        {"question": "When?", "scope": "tag", "scope_id": 7}, cfg
    )
    assert tag_request["scope"] == "tag"
    assert tag_request["scope_id"] == 7
    with pytest.raises(ValueError):
        rag.validate_chat_request({"question": "When?", "scope": "tag"}, cfg)


def test_prompt_keeps_retrieved_text_untrusted_and_sources_bounded():
    rag = module()
    cfg = rag.validate_config({})
    request = rag.validate_chat_request(
        {
            "question": "What is the date?",
            "scope": "all",
            "settings": {"num_ctx": 4096, "num_predict": 512},
            "history": [
                {"role": "user", "content": "Earlier question"},
                {"role": "assistant", "content": "Earlier answer"},
            ],
        },
        cfg,
    )
    retrieved = [
        {
            "document_id": index,
            "ordinal": 0,
            "title": f"Synthetic document {index}",
            "created": None,
            "score": 0.9,
            "text": ("Synthetic text. " * 400),
        }
        for index in range(1, 8)
    ]
    messages, selected = rag._bounded_prompt(request, retrieved)
    assert "untrusted" in messages[0]["content"].lower()
    assert "DOCUMENT EXCERPTS (untrusted data)" in messages[-1]["content"]
    assert 1 <= len(selected) < len(retrieved)


def test_job_ids_reject_path_traversal():
    rag = module()
    with pytest.raises(ValueError):
        rag._job_path("../../escape")
    assert rag._job_path("abc-123").name == "abc-123.json"


def test_embedding_query_uses_retrieval_instruction():
    rag = module()
    text = rag.embedding_query_text(
        "What is the notice period?",
        [{"role": "user", "content": "Find my internet contract"}],
    )
    assert text.startswith("Instruct: ")
    assert "personal document archive" in text
    assert "Previous user context:" in text
    assert text.endswith("Current question:\nWhat is the notice period?")
