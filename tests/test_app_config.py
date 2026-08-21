from app_config import DEFAULT_CONFIG, technical_tag_names, validate_config


def test_default_config_is_valid():
    cfg = validate_config(DEFAULT_CONFIG)
    assert cfg["connections"]["paperless_url"] == "http://paperless:8000"
    assert cfg["connections"]["ollama_url"] == "http://ollama:11434"
    assert cfg["ocr"]["language"] == "en"
    assert cfg["runtime"]["poll_interval_seconds"] == 10


def test_technical_tags_no_longer_include_ocr_queue_tags():
    cfg = validate_config(DEFAULT_CONFIG)
    names = technical_tag_names(cfg)
    assert {"LLM", "LLM Error", "Inbox", "TODO"} <= names
    assert "PaddleOCR" not in names
    assert "PaddleOCR Error" not in names


def test_removed_ocr_queue_keys_are_ignored():
    raw = {
        **DEFAULT_CONFIG,
        "workflow": {
            **DEFAULT_CONFIG["workflow"],
            "ocr_queue_tag": "PaddleOCR",
            "ocr_error_tag": "PaddleOCR Fehler",
            "llm_error_tag": "LLM Fehler",
        },
        "ocr": {
            **DEFAULT_CONFIG["ocr"],
            "language": "de",
        },
    }
    validated = validate_config(raw)
    assert validated["ocr"]["language"] == "de"
    assert validated["workflow"]["llm_error_tag"] == "LLM Fehler"
    assert "ocr_queue_tag" not in validated["workflow"]
    assert "ocr_error_tag" not in validated["workflow"]


def test_duplicate_workflow_tag_names_are_rejected():
    cfg = validate_config(DEFAULT_CONFIG)
    cfg["workflow"]["llm_error_tag"] = cfg["workflow"]["llm_queue_tag"]
    try:
        validate_config(cfg)
    except ValueError as exc:
        assert "distinct names" in str(exc)
    else:
        raise AssertionError("duplicate workflow tags must be rejected")
