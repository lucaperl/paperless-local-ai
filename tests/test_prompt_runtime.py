from prompt_runtime import (
    DEFAULT_CONFIG,
    DEFAULT_SYSTEM_PROMPT,
    PROMPT_PRESETS,
    make_schema,
    normalize_result,
    prune_parent_tag_names,
    render_prompts,
    validate_config,
    validate_result,
)


TAX = {
    "document_types": ["Invoice"],
    "correspondents": ["Example GmbH"],
    "content_tags": ["Bank", "Finance"],
    "content_tag_ids": [1, 2],
    "tag_by_name": {"Finance": 1, "Bank": 2},
    "tag_by_id": {1: "Finance", 2: "Bank"},
    "parent_by_id": {1: None, 2: 1},
    "tags": [
        {"id": 2, "name": "Bank", "parent": 1},
        {"id": 1, "name": "Finance", "parent": None},
    ],
}


def config(**overrides):
    value = dict(DEFAULT_CONFIG)
    value["tag_guidance"] = {}
    value.update(overrides)
    return validate_config(value)


def test_prompt_presets_include_english_default_and_german():
    assert DEFAULT_SYSTEM_PROMPT == PROMPT_PRESETS["en"]["system_prompt"]
    assert "primary language of the document" in PROMPT_PRESETS["en"]["classification_template"]
    assert "{{DOCUMENT_TEXT}}" in PROMPT_PRESETS["en"]["classification_template"]
    assert "{{DOCUMENT_TEXT}}" in PROMPT_PRESETS["de"]["classification_template"]


def test_month_normalizes_to_last_day():
    assert normalize_result({"created": "2024-02"})["created"] == "2024-02-29"
    assert normalize_result({"created": "2025-02"})["created"] == "2025-02-28"


def test_correspondent_is_free_text_but_tags_remain_constrained():
    schema = make_schema(TAX, config())
    assert "enum" not in schema["properties"]["correspondent"]
    assert schema["properties"]["tags"]["items"]["enum"] == TAX["content_tags"]
    result = {
        "title": "Invoice March 2026",
        "document_type": "Invoice",
        "correspondent": "Brand New Sender GmbH",
        "tags": ["Finance"],
        "created": "2026-03-31",
    }
    assert validate_result(result, TAX, config()) == []


def test_history_match_disables_llm_tag_output_and_skips_guidance():
    cfg = config(tag_guidance={"1": "Use for financial matters"})
    tagging = {
        "mode": "history_assisted",
        "route": "history_match",
        "llm_decides": False,
        "tag": "Finance",
        "examples": [],
    }
    rendered = render_prompts(
        {"id": 7, "title": "X", "created": "", "content": "invoice text"},
        TAX,
        cfg,
        tagging=tagging,
    )
    assert rendered["schema"]["properties"]["tags"]["maxItems"] == 0
    assert "User-provided tag guidance" not in rendered["user_prompt"]
    assert "return tags as an empty array" in rendered["user_prompt"]


def test_llm_fallback_receives_guidance_and_reviewed_examples():
    cfg = config(tag_guidance={"2": "Use when the bank account itself is the subject"})
    tagging = {
        "mode": "history_assisted",
        "route": "llm_fallback",
        "llm_decides": True,
        "examples": [
            {
                "id": 9,
                "title": "Account closure",
                "tags": ["Bank"],
                "similarity": 0.4,
                "excerpt": "bank account closure",
            }
        ],
    }
    rendered = render_prompts(
        {"id": 7, "title": "X", "created": "", "content": "invoice text"},
        TAX,
        cfg,
        tagging=tagging,
    )
    assert "User-provided tag guidance" in rendered["user_prompt"]
    assert "bank account closure" in rendered["user_prompt"]
    assert "Example 1:" in rendered["user_prompt"]


def test_parent_tag_is_pruned_when_child_is_returned():
    assert prune_parent_tag_names(["Finance", "Bank"], TAX) == ["Bank"]


def test_old_config_migrates_to_history_assisted_defaults():
    old = {k: v for k, v in DEFAULT_CONFIG.items() if k not in {"tagging_mode", "tag_guidance"}}
    cfg = validate_config(old)
    assert cfg["tagging_mode"] == "history_assisted"
    assert cfg["tag_guidance"] == {}
