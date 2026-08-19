from app_config import DEFAULT_CONFIG, blocking_tag_names, technical_tag_names, validate_config


def test_default_config_is_valid():
    cfg = validate_config(DEFAULT_CONFIG)
    assert cfg["connections"]["paperless_url"] == "http://paperless:8000"
    assert cfg["connections"]["ollama_url"] == "http://ollama:11434"
    assert cfg["ocr"]["language"] == "en"
    assert cfg["runtime"]["poll_interval_seconds"] == 10


def test_technical_tags_are_derived_once():
    cfg = validate_config(DEFAULT_CONFIG)
    names = technical_tag_names(cfg)
    assert {"PaddleOCR", "PaddleOCR Error", "LLM", "LLM Error", "Inbox", "TODO"} <= names
    assert blocking_tag_names(cfg) == {"PaddleOCR", "PaddleOCR Error"}


def test_existing_language_and_tag_values_are_preserved_by_validation():
    cfg = {
        **DEFAULT_CONFIG,
        "workflow": {
            **DEFAULT_CONFIG["workflow"],
            "ocr_error_tag": "PaddleOCR Fehler",
            "llm_error_tag": "LLM Fehler",
        },
        "ocr": {
            **DEFAULT_CONFIG["ocr"],
            "language": "de",
        },
    }
    validated = validate_config(cfg)
    assert validated["ocr"]["language"] == "de"
    assert validated["workflow"]["ocr_error_tag"] == "PaddleOCR Fehler"
    assert validated["workflow"]["llm_error_tag"] == "LLM Fehler"


def test_duplicate_workflow_tag_names_are_rejected():
    cfg = validate_config(DEFAULT_CONFIG)
    cfg["workflow"]["llm_queue_tag"] = cfg["workflow"]["ocr_queue_tag"]
    try:
        validate_config(cfg)
    except ValueError as exc:
        assert "distinct names" in str(exc)
    else:
        raise AssertionError("duplicate workflow tags must be rejected")
