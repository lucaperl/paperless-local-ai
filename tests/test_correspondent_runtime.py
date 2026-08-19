from correspondent_runtime import DEFAULT_CONFIG, PROMPT_PRESETS, validate_result


def test_correspondent_prompt_presets_include_english_default_and_german():
    assert DEFAULT_CONFIG["system_prompt"] == PROMPT_PRESETS["en"]["system_prompt"]
    assert DEFAULT_CONFIG["prompt_template"] == PROMPT_PRESETS["en"]["prompt_template"]
    assert "{{DOCUMENT_TEXT}}" in PROMPT_PRESETS["en"]["prompt_template"]
    assert "{{DOCUMENT_TEXT}}" in PROMPT_PRESETS["de"]["prompt_template"]


def test_free_correspondent_name_is_valid():
    assert validate_result({"correspondent": "New Sender GmbH"}) == []


def test_empty_correspondent_is_valid():
    assert validate_result({"correspondent": ""}) == []


def test_extra_fields_are_rejected():
    errors = validate_result({"correspondent": "X", "tags": []})
    assert errors
