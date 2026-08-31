from correspondent_resolver import resolve_correspondent, simulate_correspondent_match


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


def test_configurable_similarity_can_accept_a_clear_lower_score():
    result = resolve_correspondent(
        "Beispielwerke Energieversorgung",
        ["Beispielwerke Energieversorgung GmbH", "Beispielwerke Netz GmbH"],
        minimum_similarity=0.92,
        minimum_margin=0.04,
    )
    assert result["status"] == "existing_fuzzy"
    assert result["resolved"] == "Beispielwerke Energieversorgung GmbH"


def test_winner_margin_blocks_ambiguous_high_similarity_match():
    result = resolve_correspondent(
        "Beispielwerke Main GmbH",
        ["Beispielwerke Mainz GmbH", "Beispielwerke Mainau GmbH", "Musterwerke Main GmbH"],
        minimum_similarity=0.93,
        minimum_margin=0.04,
    )
    assert result["status"] == "new_suggestion"
    assert result["match_score"] > 0.97
    assert result["match_score"] - result["runner_up_score"] < 0.04


def test_simulator_uses_same_decision_and_returns_top_three():
    existing = [
        "Beispielwerke Mainz GmbH",
        "Beispielwerke Mainau GmbH",
        "Musterwerke Main GmbH",
    ]
    simulation = simulate_correspondent_match(
        "Beispielwerke Main GmbH",
        existing,
        minimum_similarity=0.93,
        minimum_margin=0.04,
    )
    direct = resolve_correspondent(
        "Beispielwerke Main GmbH",
        existing,
        minimum_similarity=0.93,
        minimum_margin=0.04,
    )
    assert simulation["resolution"] == direct
    assert len(simulation["candidates"]) == 3
    assert simulation["similarity_pass"] is True
    assert simulation["margin_pass"] is False
    assert simulation["winner_margin"] < 0.04


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
