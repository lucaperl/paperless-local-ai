from app_config import (
    DEFAULT_CONFIG,
    OCR_MAX_SIDE_PIXELS_DEFAULT,
    OCR_MAX_SIDE_PIXELS_MAX,
    OCR_MAX_SIDE_PIXELS_MIN,
    OCR_MODEL_PROFILES,
    technical_tag_names,
    validate_config,
)


def test_default_config_is_valid():
    cfg = validate_config(DEFAULT_CONFIG)
    assert cfg["connections"]["paperless_url"] == "http://paperless:8000"
    assert cfg["connections"]["ollama_url"] == "http://ollama:11434"
    assert cfg["ocr"]["language"] == "en"
    assert cfg["ocr"]["model_profile"] == "medium"
    assert cfg["ocr"]["max_side_pixels"] == 3000
    assert OCR_MAX_SIDE_PIXELS_DEFAULT == 3000
    assert OCR_MAX_SIDE_PIXELS_MIN == 2000
    assert OCR_MAX_SIDE_PIXELS_MAX == 4000
    assert OCR_MODEL_PROFILES == ("medium", "small", "tiny")
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


def test_existing_config_without_model_profile_defaults_to_medium():
    raw = {
        **DEFAULT_CONFIG,
        "ocr": {
            "language": "de",
            "version": "PP-OCRv6",
            "device": "cpu",
        },
    }
    validated = validate_config(raw)
    assert validated["ocr"]["model_profile"] == "medium"


def test_invalid_ocr_model_profile_is_rejected():
    raw = {
        **DEFAULT_CONFIG,
        "ocr": {
            **DEFAULT_CONFIG["ocr"],
            "model_profile": "large",
        },
    }
    try:
        validate_config(raw)
    except ValueError as exc:
        assert "model_profile" in str(exc)
    else:
        raise AssertionError("unsupported OCR model profile must be rejected")


def test_tiny_profile_rejects_japanese():
    raw = {
        **DEFAULT_CONFIG,
        "ocr": {
            **DEFAULT_CONFIG["ocr"],
            "language": "japan",
            "model_profile": "tiny",
        },
    }
    try:
        validate_config(raw)
    except ValueError as exc:
        assert "does not support Japanese" in str(exc)
    else:
        raise AssertionError("PP-OCRv6 Tiny must reject Japanese")


def test_existing_config_without_max_side_pixels_defaults_to_3000():
    raw = {
        **DEFAULT_CONFIG,
        "ocr": {
            "language": "de",
            "version": "PP-OCRv6",
            "model_profile": "medium",
            "device": "cpu",
        },
    }
    validated = validate_config(raw)
    assert validated["ocr"]["max_side_pixels"] == 3000


def test_ocr_max_side_pixels_bounds_are_enforced():
    for value in (1999, 4001):
        raw = {**DEFAULT_CONFIG, "ocr": {**DEFAULT_CONFIG["ocr"], "max_side_pixels": value}}
        try:
            validate_config(raw)
        except ValueError as exc:
            assert "max_side_pixels" in str(exc)
        else:
            raise AssertionError(f"max_side_pixels={value} must be rejected")
