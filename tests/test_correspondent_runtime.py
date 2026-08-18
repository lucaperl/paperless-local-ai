from correspondent_runtime import validate_result


def test_free_correspondent_name_is_valid():
    assert validate_result({"correspondent": "New Sender GmbH"}) == []


def test_empty_correspondent_is_valid():
    assert validate_result({"correspondent": ""}) == []


def test_extra_fields_are_rejected():
    errors = validate_result({"correspondent": "X", "tags": []})
    assert errors
