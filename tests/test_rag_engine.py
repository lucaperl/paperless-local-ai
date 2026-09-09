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
    messages, selected = rag._bounded_prompt(request, retrieved, cfg)
    assert "untrusted" in messages[0]["content"].lower()
    assert "DOCUMENT EXCERPTS:" in messages[-1]["content"]
    assert "DOCUMENT EXCERPTS (untrusted data)" not in messages[-1]["content"]
    assert 1 <= len(selected) < len(retrieved)


def test_job_ids_reject_path_traversal():
    rag = module()
    with pytest.raises(ValueError):
        rag._job_path("../../escape")
    assert rag._job_path("abc-123").name == "abc-123.json"


def test_embedding_query_uses_retrieval_instruction():
    rag = module()
    cfg = rag.validate_config({})
    request = rag.validate_chat_request(
        {
            "question": "What is the notice period?",
            "scope": "all",
            "history": [{"role": "user", "content": "Find the relevant service agreement"}],
        },
        cfg,
    )
    text = rag.embedding_query_text(request, cfg)
    assert text.startswith("Instruct: ")
    assert "personal document archive" in text
    assert "Previous user context:" in text
    assert text.endswith("Current question:\nWhat is the notice period?")


def test_system_prompt_variables_are_validated_and_rendered():
    rag = module()
    cfg = rag.validate_config(
        {
            "system_prompt": (
                "Date={{CURRENT_DATE}} user={{USERNAME}} scope={{SEARCH_SCOPE}} "
                "model={{CHAT_MODEL}} tz={{TIMEZONE}}"
            ),
            "timezone": "Europe/Berlin",
        }
    )
    request = rag.validate_chat_request(
        {
            "question": "When?",
            "scope": "tag",
            "scope_id": 7,
            "scope_label": "Contracts",
            "_plai_username": "luca",
            "_plai_user_id": 42,
        },
        cfg,
    )
    rendered = rag.render_system_prompt(request, cfg)
    assert "{{" not in rendered
    assert "user=luca" in rendered
    assert "scope=tag: Contracts" in rendered
    assert "model=qwen3.5:4b" in rendered
    assert "tz=Europe/Berlin" in rendered


def test_unknown_system_prompt_variable_is_rejected():
    rag = module()
    with pytest.raises(ValueError, match="Unknown RAG system prompt placeholders"):
        rag.validate_config({"system_prompt": "Hello {{NOT_A_REAL_VARIABLE}}"})


def test_generation_finish_metadata_marks_output_limit():
    rag = module()
    settings = rag._validate_chat_settings(
        {
            "model": "example:latest",
            "think": "on",
            "num_ctx": 8192,
            "top_k": 5,
            "temperature": 0.1,
            "num_predict": 512,
        }
    )
    limited = rag._generation_finish_metadata({"done_reason": "length"}, settings)
    assert limited == {
        "done_reason": "length",
        "output_limit_reached": True,
        "num_predict": 512,
    }
    stopped = rag._generation_finish_metadata({"done_reason": "stop"}, settings)
    assert stopped["output_limit_reached"] is False

def test_embedding_templates_and_retrieval_history_are_configurable():
    rag = module()
    cfg = rag.validate_config(
        {
            "embedding_query_template": "scope={{SEARCH_SCOPE}}\n{{CURRENT_QUESTION}}\n{{PREVIOUS_USER_CONTEXT}}",
            "document_embedding_template": "Title: {{DOCUMENT_TITLE}}\n{{CHUNK}}",
            "retrieval_history_turns": 1,
        }
    )
    request = rag.validate_chat_request(
        {
            "question": "What does the agreement say?",
            "scope": "all",
            "history": [
                {"role": "user", "content": "Old context that should be dropped"},
                {"role": "assistant", "content": "Assistant text is never retrieval context"},
                {"role": "user", "content": "Use the most recent service agreement"},
            ],
        },
        cfg,
    )
    rendered = rag.embedding_query_text(request, cfg)
    assert "What does the agreement say?" in rendered
    assert "Use the most recent service agreement" in rendered
    assert "Old context that should be dropped" not in rendered
    assert "Assistant text is never retrieval context" not in rendered
    prepared = {"id": 42, "title": "Sample Agreement", "created": "2026-01-15"}
    assert rag.render_document_embedding_text(prepared, "Synthetic chunk text.", cfg) == "Title: Sample Agreement\nSynthetic chunk text."


def test_default_structural_signature_remains_backward_compatible():
    rag = module()
    cfg = rag.validate_config({})
    assert rag.config_signature(cfg) == {
        "chunking_version": rag.CHUNKING_VERSION,
        "embedding_model": "qwen3-embedding:4b-q4_K_M",
        "chunk_target_chars": 2000,
        "chunk_overlap_chars": 400,
    }
    cfg["embedding_dimensions"] = 1024
    assert rag.config_signature(cfg)["embedding_dimensions"] == 1024


def test_advanced_generation_settings_are_optional_and_validated():
    rag = module()
    settings = rag._validate_chat_settings(
        {
            "model": "example:latest", "think": "medium", "num_ctx": 8192, "top_k": 5,
            "temperature": 0.1, "num_predict": 512, "sampler_top_k": 40,
            "top_p": 0.9, "min_p": 0.05, "repeat_penalty": 1.1,
            "repeat_last_n": 64, "seed": 42, "stop": ["END"],
        }
    )
    assert settings["think"] == "medium"
    assert settings["sampler_top_k"] == 40
    assert settings["stop"] == ["END"]
    with pytest.raises(ValueError):
        rag._validate_chat_settings({**settings, "top_p": 2.0})
