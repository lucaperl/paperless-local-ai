from prompt_runtime import DEFAULT_SYSTEM_PROMPT, PROMPT_PRESETS, normalize_result, validate_result


TAX = {
    "document_types": ["Rechnung"],
    "correspondents": ["Example GmbH"],
    "content_tags": ["Finanzen"],
}


def test_prompt_presets_include_english_default_and_german():
    assert DEFAULT_SYSTEM_PROMPT == PROMPT_PRESETS["en"]["system_prompt"]
    assert "primary language of the document" in PROMPT_PRESETS["en"]["classification_template"]
    assert "{{DOCUMENT_TEXT}}" in PROMPT_PRESETS["en"]["classification_template"]
    assert "{{DOCUMENT_TEXT}}" in PROMPT_PRESETS["de"]["classification_template"]


def test_month_normalizes_to_last_day():
    assert normalize_result({"created": "2024-02"})["created"] == "2024-02-29"
    assert normalize_result({"created": "2025-02"})["created"] == "2025-02-28"


def test_structured_result_contract():
    config = {"max_tags": 2}
    result = {
        "title": "Rechnung März 2026",
        "document_type": "Rechnung",
        "correspondent": "Example GmbH",
        "tags": ["Finanzen"],
        "created": "2026-03-31",
    }
    assert validate_result(result, TAX, config) == []


def test_unknown_taxonomy_value_is_rejected():
    config = {"max_tags": 2}
    result = {
        "title": "X",
        "document_type": "Unbekannt",
        "correspondent": "",
        "tags": [],
        "created": "",
    }
    errors = validate_result(result, TAX, config)
    assert any("document_type" in item for item in errors)
