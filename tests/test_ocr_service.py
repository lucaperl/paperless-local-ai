from service import _poly, _result_get, _seq


def test_poly_accepts_rectangle_and_polygon():
    assert _poly([1, 2, 3, 4]) == [
        [1.0, 2.0],
        [3.0, 2.0],
        [3.0, 4.0],
        [1.0, 4.0],
    ]
    assert _poly([[1, 2], [3, 2], [3, 4], [1, 4]]) == [
        [1.0, 2.0],
        [3.0, 2.0],
        [3.0, 4.0],
        [1.0, 4.0],
    ]


def test_result_helpers_are_defensive():
    assert _seq(None) == []
    assert _seq(("a", "b")) == ["a", "b"]
    assert _result_get({"x": 1}, "x") == 1
    assert _result_get({}, "missing", 7) == 7


def test_quality_profile_is_explicit_medium():
    from service import PP_OCRV6_MEDIUM_DET, PP_OCRV6_MEDIUM_REC

    assert PP_OCRV6_MEDIUM_DET == "PP-OCRv6_medium_det"
    assert PP_OCRV6_MEDIUM_REC == "PP-OCRv6_medium_rec"


def test_language_aliases_match_current_german_contract():
    from service import _language_header_matches

    assert _language_header_matches("deu", "de")
    assert _language_header_matches("eng,deu", "de")
    assert not _language_header_matches("eng", "de")
