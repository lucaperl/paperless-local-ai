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
    assert valid["conversation_history_messages"] == 8
    assert valid["show_retrieval_diagnostics"] is False
    with pytest.raises(ValueError):
        rag._validate_chat_settings({**valid, "top_k": 99})
    with pytest.raises(ValueError):
        rag._validate_chat_settings({**valid, "think": "sometimes"})
    with pytest.raises(ValueError):
        rag._validate_chat_settings({**valid, "conversation_history_messages": 25})
    with pytest.raises(ValueError):
        rag._validate_chat_settings({**valid, "show_retrieval_diagnostics": "yes"})


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
    messages, selected, prompt_stats = rag._bounded_prompt(request, retrieved, cfg)
    assert "untrusted" in messages[0]["content"].lower()
    assert "DOCUMENT EXCERPTS:" in messages[-1]["content"]
    assert "DOCUMENT EXCERPTS (untrusted data)" not in messages[-1]["content"]
    assert 1 <= len(selected) < len(retrieved)
    assert prompt_stats["conversation_history_messages_used"] == 2
    assert prompt_stats["selected_primary_chunks"] == len(selected)


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
            "_plai_username": "sample-user",
            "_plai_user_id": 42,
        },
        cfg,
    )
    rendered = rag.render_system_prompt(request, cfg)
    assert "{{" not in rendered
    assert "user=sample-user" in rendered
    assert "scope=tag: Contracts" in rendered
    assert "model=qwen3.5:4b" in rendered
    assert "tz=Europe/Berlin" in rendered


def test_unknown_system_prompt_variable_is_rejected():
    rag = module()
    with pytest.raises(ValueError, match="Unknown system_prompt placeholders"):
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
            "embedding_query_template": (
                "scope={{SEARCH_SCOPE}}\n{{CURRENT_QUESTION}}\n"
                "{{PREVIOUS_USER_CONTEXT}}\n{{PREVIOUS_HISTORY_CONTEXT}}"
            ),
            "document_embedding_template": "Title: {{DOCUMENT_TITLE}}\n{{CHUNK}}",
            "retrieval_history_turns": 1,
            "retrieval_history_mode": "user_only",
        }
    )
    request = rag.validate_chat_request(
        {
            "question": "What does the agreement say?",
            "scope": "all",
            "history": [
                {"role": "user", "content": "Old context that should be dropped"},
                {"role": "assistant", "content": "Old assistant context that should be dropped"},
                {"role": "user", "content": "Use the most recent service agreement"},
                {"role": "assistant", "content": "Recent assistant context"},
            ],
        },
        cfg,
    )
    rendered = rag.embedding_query_text(request, cfg)
    assert "What does the agreement say?" in rendered
    assert "Use the most recent service agreement" in rendered
    assert "Old context that should be dropped" not in rendered
    assert "Old assistant context that should be dropped" not in rendered
    assert "Recent assistant context" not in rendered

    cfg["retrieval_history_mode"] = "user_and_assistant"
    rendered_with_assistant = rag.embedding_query_text(request, cfg)
    assert "User: Use the most recent service agreement" in rendered_with_assistant
    assert "Assistant: Recent assistant context" in rendered_with_assistant
    assert "Old assistant context that should be dropped" not in rendered_with_assistant

    prepared = {"id": 42, "title": "Sample Agreement", "created": "2026-01-15"}
    assert rag.render_document_embedding_text(prepared, "Synthetic chunk text.", cfg) == "Title: Sample Agreement\nSynthetic chunk text."


def test_default_structural_signature_remains_backward_compatible():
    rag = module()
    cfg = rag.validate_config({})
    assert cfg["retrieval_history_mode"] == "user_only"
    assert cfg["retrieval_history_turns"] == 3
    assert cfg["adjacent_chunks"] == 0
    assert cfg["retrieval_context_percent"] is None
    assert cfg["answer_prompt_template"] == rag.DEFAULT_ANSWER_PROMPT_TEMPLATE
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
    with pytest.raises(ValueError, match="retrieval_history_mode"):
        rag.validate_config({"retrieval_history_mode": "unsupported"})
def test_answer_prompt_history_limit_and_document_budget_are_configurable():
    rag = module()
    cfg = rag.validate_config(
        {
            "answer_prompt_template": (
                "Scope={{SEARCH_SCOPE}}\nSources={{SOURCE_COUNT}}\n"
                "{{DOCUMENT_EXCERPTS}}\nQuestion={{QUESTION}}"
            ),
            "retrieval_context_percent": 25,
        }
    )
    request = rag.validate_chat_request(
        {
            "question": "What does the sample record say?",
            "scope": "all",
            "settings": {
                "num_ctx": 4096,
                "num_predict": 512,
                "conversation_history_messages": 1,
            },
            "history": [
                {"role": "user", "content": "Earlier user message"},
                {"role": "assistant", "content": "Earlier assistant message"},
            ],
        },
        cfg,
    )
    retrieved = [
        {
            "document_id": 42,
            "ordinal": 1,
            "title": "Sample Record",
            "created": None,
            "score": 0.91,
            "text": "Synthetic passage. " * 300,
            "context_text": "Synthetic passage. " * 300,
            "neighbor_ordinals": [],
        }
    ]
    messages, selected, stats = rag._bounded_prompt(request, retrieved, cfg)
    assert len(messages) == 3
    assert messages[1]["content"] == "Earlier assistant message"
    assert "Scope=all" in messages[-1]["content"]
    assert "Question=What does the sample record say?" in messages[-1]["content"]
    assert len(selected) == 1
    assert stats["conversation_history_messages_limit"] == 1
    assert stats["document_context_percent"] == 25
    assert stats["document_budget_chars"] <= stats["input_budget_chars"] // 4


def test_adjacent_chunks_expand_context_without_changing_primary_hit(tmp_path, monkeypatch):
    rag = module()
    db_file = tmp_path / "rag.db"
    lock_file = tmp_path / "index.lock"
    monkeypatch.setattr(rag, "DB_FILE", db_file)
    monkeypatch.setattr(rag, "INDEX_LOCK_FILE", lock_file)

    connection = rag.db_connect(db_file)
    with connection:
        connection.execute(
            "INSERT INTO documents(id,modified,title,created,chunk_count) VALUES(?,?,?,?,?)",
            (42, "now", "Sample Record", None, 3),
        )
        for ordinal, text in enumerate(("Before.", "Primary.", "After.")):
            connection.execute(
                "INSERT INTO chunks(document_id,ordinal,text,embedding) VALUES(?,?,?,?)",
                (42, ordinal, text, b"x"),
            )
    connection.close()

    primary = [
        {
            "document_id": 42,
            "ordinal": 1,
            "title": "Sample Record",
            "created": None,
            "score": 0.9,
            "text": "Primary.",
        }
    ]
    expanded = rag.expand_retrieved_neighbors(primary, 1)
    assert len(expanded) == 1
    assert expanded[0]["ordinal"] == 1
    assert expanded[0]["neighbor_ordinals"] == [0, 2]
    assert expanded[0]["context_text"] == "Before.\n\nPrimary.\n\nAfter."


def test_new_retrieval_controls_are_validated():
    rag = module()
    with pytest.raises(ValueError, match="adjacent_chunks"):
        rag.validate_config({"adjacent_chunks": 4})
    with pytest.raises(ValueError, match="retrieval_context_percent"):
        rag.validate_config({"retrieval_context_percent": 5})
    with pytest.raises(ValueError, match="answer_prompt_template"):
        rag.validate_config({"answer_prompt_template": "{{UNKNOWN}}"})
def test_retrieved_source_template_exposes_document_metadata_variables():
    rag = module()
    cfg = rag.validate_config(
        {
            "source_prompt_template": (
                "[{{SOURCE_NUMBER}}] {{DOCUMENT_TITLE}} | {{DOCUMENT_CREATED}} | "
                "{{DOCUMENT_CORRESPONDENT}} | {{DOCUMENT_TYPE}} | {{DOCUMENT_TAGS}} | "
                "{{DOCUMENT_CUSTOM_FIELDS}} | {{DOCUMENT_MIME_TYPE}}\n{{CHUNK}}"
            )
        }
    )
    item = {
        "document_id": 42,
        "ordinal": 3,
        "title": "Sample Record",
        "created": "2026-01-15",
        "score": 0.912345,
        "context_text": "Synthetic retrieved passage.",
        "neighbor_ordinals": [2, 4],
        "document_values": {
            "DOCUMENT_ID": "42",
            "DOCUMENT_TITLE": "Sample Record",
            "DOCUMENT_CREATED": "2026-01-15",
            "DOCUMENT_CORRESPONDENT": "Example Organization",
            "DOCUMENT_TYPE": "Agreement",
            "DOCUMENT_TAGS": "Finance, Review",
            "DOCUMENT_CUSTOM_FIELDS": '[{"field":4,"field_name":"Reference","value":"ABC-123"}]',
            "DOCUMENT_MIME_TYPE": "application/pdf",
        },
    }
    rendered = rag.render_source_prompt(item, 1, cfg)
    assert rendered.startswith("[1] Sample Record | 2026-01-15 | Example Organization")
    assert "Agreement | Finance, Review" in rendered
    assert "application/pdf" in rendered
    assert rendered.endswith("Synthetic retrieved passage.")


def test_source_template_default_adds_useful_metadata_without_rebuild():
    rag = module()
    cfg = rag.validate_config({})
    assert "{{DOCUMENT_TITLE}}" in cfg["source_prompt_template"]
    assert "{{DOCUMENT_CREATED}}" in cfg["source_prompt_template"]
    assert "{{DOCUMENT_CORRESPONDENT}}" in cfg["source_prompt_template"]
    assert "{{DOCUMENT_TYPE}}" in cfg["source_prompt_template"]
    assert "{{DOCUMENT_ID}}" in cfg["source_prompt_template"]
    assert "{{CHUNK}}" in cfg["source_prompt_template"]
    with pytest.raises(ValueError, match="source_prompt_template"):
        rag.validate_config({"source_prompt_template": "{{NOT_A_DOCUMENT_FIELD}}"})


def test_source_placeholder_catalog_covers_readable_paperless_document_fields():
    rag = module()
    required = {
        "DOCUMENT_ID", "DOCUMENT_CORRESPONDENT", "DOCUMENT_TYPE",
        "DOCUMENT_STORAGE_PATH", "DOCUMENT_TITLE", "DOCUMENT_CONTENT",
        "DOCUMENT_TAGS", "DOCUMENT_CREATED", "DOCUMENT_CREATED_DATE",
        "DOCUMENT_MODIFIED", "DOCUMENT_ADDED", "DOCUMENT_DELETED_AT",
        "DOCUMENT_ARCHIVE_SERIAL_NUMBER", "DOCUMENT_ORIGINAL_FILE_NAME",
        "DOCUMENT_ARCHIVED_FILE_NAME", "DOCUMENT_DUPLICATE_DOCUMENTS",
        "DOCUMENT_OWNER", "DOCUMENT_PERMISSIONS", "DOCUMENT_USER_CAN_CHANGE",
        "DOCUMENT_IS_SHARED_BY_REQUESTER", "DOCUMENT_NOTES",
        "DOCUMENT_CUSTOM_FIELDS", "DOCUMENT_PAGE_COUNT", "DOCUMENT_MIME_TYPE",
        "DOCUMENT_ROOT_DOCUMENT", "DOCUMENT_VERSIONS",
    }
    assert required <= set(rag.SOURCE_PROMPT_PLACEHOLDERS)
    assert "DOCUMENT_RAW_JSON" in rag.SOURCE_PROMPT_PLACEHOLDERS

def test_legacy_literal_backslash_n_prompt_defaults_are_normalized():
    rag = module()
    cfg = rag.validate_config(
        {
            "source_prompt_template": rag.DEFAULT_SOURCE_PROMPT_TEMPLATE.replace(
                "\n", "\\n"
            ),
            "answer_prompt_template": rag.DEFAULT_ANSWER_PROMPT_TEMPLATE.replace(
                "\n", "\\n"
            ),
        }
    )
    assert cfg["source_prompt_template"] == rag.DEFAULT_SOURCE_PROMPT_TEMPLATE
    assert cfg["answer_prompt_template"] == rag.DEFAULT_ANSWER_PROMPT_TEMPLATE
    assert "\\n" not in cfg["source_prompt_template"]
    assert "\\n" not in cfg["answer_prompt_template"]


def test_retrieval_history_turns_default_is_three():
    rag = module()
    assert rag.validate_config({})["retrieval_history_turns"] == 3
