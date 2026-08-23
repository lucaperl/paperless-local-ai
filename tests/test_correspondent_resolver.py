from correspondent_resolver import resolve_correspondent


def test_exact_normalized_match_is_applied():
    result = resolve_correspondent("Example-GmbH", ["Example GmbH", "Other AG"])
    assert result["status"] == "existing_exact"
    assert result["resolved"] == "Example GmbH"
    assert result["suggestion"] == ""


def test_small_ocr_variation_can_match_conservatively():
    result = resolve_correspondent(
        "Heidelberger Volksbank eG",
        ["Heidelberger Volksbank eG", "Heidelberg Versicherung AG"],
    )
    assert result["resolved"] == "Heidelberger Volksbank eG"


def test_unique_extended_existing_name_is_applied():
    result = resolve_correspondent(
        "Landesamt für Besoldung und Versorgung Baden-Württemberg",
        ["Landesamt für Besoldung und Versorgung", "Deutsche Rentenversicherung"],
    )
    assert result["status"] == "existing_extended"
    assert result["resolved"] == "Landesamt für Besoldung und Versorgung"
    assert result["suggestion"] == ""


def test_short_generic_prefix_is_not_auto_collapsed():
    result = resolve_correspondent("Stadt Heidelberg Amt", ["Stadt Heidelberg"])
    assert result["status"] == "new_suggestion"
    assert result["resolved"] == ""


def test_added_legal_form_is_not_treated_as_harmless_extension():
    result = resolve_correspondent(
        "Example Financial Services GmbH",
        ["Example Financial Services"],
    )
    assert result["status"] == "new_suggestion"
    assert result["resolved"] == ""


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
