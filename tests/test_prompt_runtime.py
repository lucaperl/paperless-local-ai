from prompt_runtime import (
    DEFAULT_CONFIG,
    DEFAULT_SYSTEM_PROMPT,
    DEFAULT_TAGGING_PROMPT,
    _LEGACY_030_GERMAN_CLASSIFICATION_TEMPLATE,
    _LEGACY_030_GERMAN_SYSTEM_PROMPT,
    PROMPT_PRESETS,
    make_schema,
    normalize_result,
    prompt_hashes,
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


def base_result():
    return {
        "title": "Invoice March 2026",
        "document_type": "Invoice",
        "correspondent": "Brand New Sender GmbH",
        "created": "2026-03-31",
    }


def test_prompt_presets_include_editable_system_base_and_tagging_prompts():
    assert DEFAULT_SYSTEM_PROMPT == PROMPT_PRESETS["en"]["system_prompt"]
    for key in ("en", "de"):
        preset = PROMPT_PRESETS[key]
        assert preset["system_prompt"]
        assert "{{DOCUMENT_TEXT}}" in preset["classification_template"]
        assert "{{TAGS_JSON}}" in preset["tagging_prompt"]
        assert "{{TAG_GUIDANCE}}" in preset["tagging_prompt"]
        assert "{{TAG_EXAMPLES}}" in preset["tagging_prompt"]


def test_month_normalizes_to_last_day():
    assert normalize_result({"created": "2024-02"})["created"] == "2024-02-29"
    assert normalize_result({"created": "2025-02"})["created"] == "2025-02-28"


def test_correspondent_is_free_text_and_llm_tags_are_constrained():
    schema = make_schema(TAX, config(), tags_enabled=True)
    assert "enum" not in schema["properties"]["correspondent"]
    assert schema["properties"]["tags"]["items"]["enum"] == TAX["content_tags"]
    result = {**base_result(), "tags": ["Finance"]}
    assert validate_result(result, TAX, config(), tags_enabled=True) == []


def test_hybrid_match_omits_tag_prompt_and_tags_schema_entirely():
    cfg = config(
        tag_guidance={"1": "Use for financial matters"},
        tagging_prompt="CUSTOM TAGGING {{TAGS_JSON}} {{TAG_GUIDANCE}} {{TAG_EXAMPLES}}",
    )
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
    assert "tags" not in rendered["schema"]["properties"]
    assert "tags" not in rendered["schema"]["required"]
    assert "CUSTOM TAGGING" not in rendered["user_prompt"]
    assert "Use for financial matters" not in rendered["user_prompt"]
    assert rendered["rendered_tagging_prompt"] == ""
    assert validate_result(base_result(), TAX, cfg, tags_enabled=False) == []


def test_hybrid_match_rejects_unexpected_tag_field():
    cfg = config()
    assert validate_result({**base_result(), "tags": []}, TAX, cfg, tags_enabled=False) == [
        "tags must be omitted when the LLM is not responsible for tag selection"
    ]


def test_llm_fallback_receives_editable_tagging_prompt_guidance_and_examples():
    cfg = config(
        tag_guidance={"2": "Use when the bank account itself is the subject"},
        tagging_prompt=(
            "MY TAG RULES\nAllowed={{TAGS_JSON}}\nMax={{MAX_TAGS}}\n"
            "Guidance={{TAG_GUIDANCE}}\nExamples={{TAG_EXAMPLES}}"
        ),
    )
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
    assert "MY TAG RULES" in rendered["user_prompt"]
    assert "Use when the bank account itself is the subject" in rendered["user_prompt"]
    assert "bank account closure" in rendered["user_prompt"]
    assert "Example 1:" in rendered["user_prompt"]
    assert rendered["schema"]["properties"]["tags"]["items"]["enum"] == TAX["content_tags"]


def test_llm_direct_gets_tagging_prompt_without_retrieved_examples():
    cfg = config(tagging_prompt="DIRECT TAGS {{TAGS_JSON}} / {{TAG_EXAMPLES}}")
    rendered = render_prompts(
        {"id": 7, "title": "X", "created": "", "content": "invoice text"},
        TAX,
        cfg,
        tagging={"mode": "llm_only", "route": "llm_only", "llm_decides": True, "examples": []},
    )
    assert "DIRECT TAGS" in rendered["user_prompt"]
    assert "Example 1:" not in rendered["user_prompt"]


def test_tagging_placeholders_belong_to_tagging_prompt():
    bad = dict(DEFAULT_CONFIG)
    bad["classification_template"] = "{{DOCUMENT_TEXT}} {{TAGS_JSON}}"
    try:
        validate_config(bad)
    except ValueError as exc:
        assert "Tagging placeholders" in str(exc)
    else:
        raise AssertionError("tagging placeholders in base prompt should be rejected")


def test_prompt_hashes_include_tagging_prompt():
    hashes = prompt_hashes(config())
    assert set(hashes) == {"system_sha256", "classification_sha256", "tagging_sha256", "config_sha256"}


def test_parent_tag_is_pruned_when_child_is_returned():
    assert prune_parent_tag_names(["Finance", "Bank"], TAX) == ["Bank"]


def test_old_config_gets_default_tagging_prompt():
    old = {k: v for k, v in DEFAULT_CONFIG.items() if k not in {"tagging_mode", "tag_guidance", "tagging_prompt"}}
    cfg = validate_config(old)
    assert cfg["tagging_mode"] == "history_assisted"
    assert cfg["tag_guidance"] == {}
    assert cfg["tagging_prompt"] == DEFAULT_TAGGING_PROMPT


def test_released_v030_german_preset_migrates_to_split_prompts():
    assert (
        "Wenn kein konkreter Tag vorhanden ist"
        in _LEGACY_030_GERMAN_CLASSIFICATION_TEMPLATE
    )

    old = {
        k: v
        for k, v in DEFAULT_CONFIG.items()
        if k not in {"tagging_prompt"}
    }
    old["system_prompt"] = _LEGACY_030_GERMAN_SYSTEM_PROMPT
    old["classification_template"] = _LEGACY_030_GERMAN_CLASSIFICATION_TEMPLATE

    cfg = validate_config(old)

    assert cfg["system_prompt"] == PROMPT_PRESETS["de"]["system_prompt"]
    assert (
        cfg["classification_template"]
        == PROMPT_PRESETS["de"]["classification_template"]
    )
    assert cfg["tagging_prompt"] == PROMPT_PRESETS["de"]["tagging_prompt"]
