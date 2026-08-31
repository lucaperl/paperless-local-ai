from app_config import (
    CORRESPONDENT_MATCH_MARGIN_DEFAULT,
    CORRESPONDENT_MATCH_SIMILARITY_DEFAULT,
    DEFAULT_CONFIG,
    HISTORY_MATCH_SIMILARITY_DEFAULT,
    HISTORY_MIN_SUPPORT_DEFAULT,
    HISTORY_MIN_WINNER_SHARE_DEFAULT,
    OCR_MAX_SIDE_PIXELS_DEFAULT,
    OCR_MAX_SIDE_PIXELS_MAX,
    OCR_MAX_SIDE_PIXELS_MIN,
    OCR_MODEL_PROFILES,
    OCR_RETRY_DELAYS_DEFAULT,
    OCR_RETRY_DELAYS_MAX_COUNT,
    OCR_RETRY_DELAY_MAX_SECONDS,
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
    assert cfg["ocr"]["retry_delays_seconds"] == [15, 60, 300, 600]
    assert OCR_RETRY_DELAYS_DEFAULT == (15, 60, 300, 600)
    assert OCR_RETRY_DELAYS_MAX_COUNT == 10
    assert OCR_RETRY_DELAY_MAX_SECONDS == 86400
    assert cfg["runtime"]["poll_interval_seconds"] == 10
    assert cfg["history"] == {
        "match_similarity": 0.62,
        "min_support": 2,
        "min_winner_share": 0.50,
    }
    assert HISTORY_MATCH_SIMILARITY_DEFAULT == 0.62
    assert HISTORY_MIN_SUPPORT_DEFAULT == 2
    assert HISTORY_MIN_WINNER_SHARE_DEFAULT == 0.50
    assert cfg["correspondent_matching"] == {
        "minimum_similarity": 0.91,
        "minimum_margin": 0.04,
    }
    assert CORRESPONDENT_MATCH_SIMILARITY_DEFAULT == 0.91
    assert CORRESPONDENT_MATCH_MARGIN_DEFAULT == 0.04


def test_existing_config_without_history_settings_gets_safe_defaults():
    raw = {key: value for key, value in DEFAULT_CONFIG.items() if key != "history"}
    validated = validate_config(raw)
    assert validated["history"] == DEFAULT_CONFIG["history"]


def test_existing_config_without_correspondent_matching_gets_safe_defaults():
    raw = {key: value for key, value in DEFAULT_CONFIG.items() if key != "correspondent_matching"}
    validated = validate_config(raw)
    assert validated["correspondent_matching"] == DEFAULT_CONFIG["correspondent_matching"]


def test_correspondent_matching_supports_full_unit_interval():
    valid = (
        {"minimum_similarity": 0.0, "minimum_margin": 0.0},
        {"minimum_similarity": 1.0, "minimum_margin": 1.0},
        {"minimum_similarity": 0.65, "minimum_margin": 0.04},
    )
    for matching in valid:
        raw = {**DEFAULT_CONFIG, "correspondent_matching": matching}
        assert validate_config(raw)["correspondent_matching"] == matching

    invalid = (
        {"minimum_similarity": -0.01, "minimum_margin": 0.04},
        {"minimum_similarity": 1.01, "minimum_margin": 0.04},
        {"minimum_similarity": 0.91, "minimum_margin": -0.01},
        {"minimum_similarity": 0.91, "minimum_margin": 1.01},
    )
    for matching in invalid:
        raw = {**DEFAULT_CONFIG, "correspondent_matching": matching}
        try:
            validate_config(raw)
        except ValueError as exc:
            assert "correspondent_matching." in str(exc)
        else:
            raise AssertionError(f"correspondent_matching={matching!r} must be rejected")


def test_history_matching_bounds_are_enforced():
    invalid = (
        {"match_similarity": 0.49, "min_support": 2, "min_winner_share": 0.5},
        {"match_similarity": 1.01, "min_support": 2, "min_winner_share": 0.5},
        {"match_similarity": 0.62, "min_support": 1, "min_winner_share": 0.5},
        {"match_similarity": 0.62, "min_support": 6, "min_winner_share": 0.5},
        {"match_similarity": 0.62, "min_support": 2, "min_winner_share": 0.49},
        {"match_similarity": 0.62, "min_support": 2, "min_winner_share": 1.01},
    )
    for history in invalid:
        raw = {**DEFAULT_CONFIG, "history": history}
        try:
            validate_config(raw)
        except ValueError as exc:
            assert "history." in str(exc)
        else:
            raise AssertionError(f"history={history!r} must be rejected")


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


def test_existing_config_without_retry_delays_gets_default_schedule():
    raw = {
        **DEFAULT_CONFIG,
        "ocr": {
            "language": "de",
            "version": "PP-OCRv6",
            "model_profile": "medium",
            "max_side_pixels": 3000,
            "device": "cpu",
        },
    }
    validated = validate_config(raw)
    assert validated["ocr"]["retry_delays_seconds"] == [15, 60, 300, 600]


def test_empty_retry_schedule_disables_automatic_retries():
    raw = {
        **DEFAULT_CONFIG,
        "ocr": {**DEFAULT_CONFIG["ocr"], "retry_delays_seconds": []},
    }
    assert validate_config(raw)["ocr"]["retry_delays_seconds"] == []


def test_retry_schedule_validation_is_bounded():
    invalid = ([0], [86401], [1] * 11, "15,60")
    for value in invalid:
        raw = {
            **DEFAULT_CONFIG,
            "ocr": {**DEFAULT_CONFIG["ocr"], "retry_delays_seconds": value},
        }
        try:
            validate_config(raw)
        except ValueError as exc:
            assert "retry_delays_seconds" in str(exc)
        else:
            raise AssertionError(f"retry_delays_seconds={value!r} must be rejected")
