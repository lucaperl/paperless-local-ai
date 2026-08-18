from app_config import DEFAULT_CONFIG, blocking_tag_names, technical_tag_names, validate_config


def test_default_config_is_valid():
    cfg = validate_config(DEFAULT_CONFIG)
    assert cfg["connections"]["paperless_url"] == "http://paperless:8000"
    assert cfg["connections"]["ollama_url"] == "http://ollama:11434"
    assert cfg["ocr"]["language"] == "de"
    assert cfg["runtime"]["poll_interval_seconds"] == 10


def test_technical_tags_are_derived_once():
    cfg = validate_config(DEFAULT_CONFIG)
    names = technical_tag_names(cfg)
    assert {"PaddleOCR", "PaddleOCR Fehler", "LLM", "LLM Fehler", "Inbox", "TODO"} <= names
    assert blocking_tag_names(cfg) == {"PaddleOCR", "PaddleOCR Fehler"}


def test_duplicate_workflow_tag_names_are_rejected():
    cfg = validate_config(DEFAULT_CONFIG)
    cfg["workflow"]["llm_queue_tag"] = cfg["workflow"]["ocr_queue_tag"]
    try:
        validate_config(cfg)
    except ValueError as exc:
        assert "unterschiedliche Namen" in str(exc)
    else:
        raise AssertionError("duplicate workflow tags must be rejected")
