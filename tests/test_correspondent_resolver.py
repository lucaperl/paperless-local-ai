from correspondent_resolver import resolve_correspondent


def test_exact_normalized_match_is_applied():
    result = resolve_correspondent("Example-GmbH", ["Example GmbH", "Other AG"])
    assert result["status"] == "existing_exact"
    assert result["resolved"] == "Example GmbH"
    assert result["suggestion"] == ""


def test_small_ocr_variation_can_match_conservatively():
    result = resolve_correspondent(
        "Example Consultng GmbH",
        ["Example Consulting GmbH", "Sample Insurance AG"],
    )
    assert result["status"] == "existing_fuzzy"
    assert result["resolved"] == "Example Consulting GmbH"
    assert result["suggestion"] == ""


def test_close_but_insufficient_match_stays_a_suggestion():
    result = resolve_correspondent(
        "Example Regional Services North",
        ["Example Regional Services", "Sample Services North"],
    )
    assert result["status"] == "new_suggestion"
    assert result["resolved"] == ""
    assert result["suggestion"] == "Example Regional Services North"


def test_new_sender_is_suggestion_not_auto_created():
    result = resolve_correspondent("New Sender GmbH", ["Existing AG"])
    assert result["status"] == "new_suggestion"
    assert result["resolved"] == ""
    assert result["suggestion"] == "New Sender GmbH"


def test_unreliable_sender_is_left_empty():
    result = resolve_correspondent("unknown", ["Existing AG"])
    assert result["status"] == "empty"
    assert result["resolved"] == ""
    assert result["suggestion"] == ""
