import service as ocr_service
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


def test_ppocrv6_model_profiles_map_matching_detection_and_recognition_models():
    from service import (
        PP_OCRV6_MEDIUM_DET,
        PP_OCRV6_MEDIUM_REC,
        PP_OCRV6_MODEL_PROFILES,
        _ppocrv6_model_names,
    )

    assert PP_OCRV6_MEDIUM_DET == "PP-OCRv6_medium_det"
    assert PP_OCRV6_MEDIUM_REC == "PP-OCRv6_medium_rec"
    assert PP_OCRV6_MODEL_PROFILES == {
        "medium": ("PP-OCRv6_medium_det", "PP-OCRv6_medium_rec"),
        "small": ("PP-OCRv6_small_det", "PP-OCRv6_small_rec"),
        "tiny": ("PP-OCRv6_tiny_det", "PP-OCRv6_tiny_rec"),
    }
    assert _ppocrv6_model_names("medium") == (
        "PP-OCRv6_medium_det",
        "PP-OCRv6_medium_rec",
    )
    assert _ppocrv6_model_names("small") == (
        "PP-OCRv6_small_det",
        "PP-OCRv6_small_rec",
    )
    assert _ppocrv6_model_names("tiny") == (
        "PP-OCRv6_tiny_det",
        "PP-OCRv6_tiny_rec",
    )


def test_language_aliases_match_current_german_contract():
    from service import _language_header_matches

    assert _language_header_matches("deu", "de")
    assert _language_header_matches("eng,deu", "de")
    assert not _language_header_matches("eng", "de")


def test_run_paddle_enforces_configured_detection_limit(tmp_path):
    from PIL import Image
    from service import _run_paddle

    class FakeModel:
        def __init__(self):
            self.calls = []
        def predict(self, path, **kwargs):
            self.calls.append((path, kwargs))
            return []

    image_path = tmp_path / "page.png"
    Image.new("L", (1200, 800), color=255).save(image_path, dpi=(300, 300))
    model = FakeModel()
    payload = _run_paddle(image_path, model, 3000)
    assert payload["width"] == 1200
    assert payload["height"] == 800
    _, kwargs = model.calls[0]
    assert kwargs["return_word_box"] is True
    assert kwargs["text_det_limit_type"] == "max"
    assert kwargs["text_det_limit_side_len"] == 3000


def test_transient_ocr_error_classifier_is_narrow():
    assert ocr_service._is_transient_ocr_error_text("MemoryError: allocation failed")
    assert ocr_service._is_transient_ocr_error_text("std::bad_alloc")
    assert not ocr_service._is_transient_ocr_error_text("ValueError: invalid image")
    assert not ocr_service._is_transient_ocr_error_text("language mismatch")


def test_retryable_ocr_error_is_distinct():
    exc = ocr_service.RetryableOCRError("worker exited")
    assert isinstance(exc, RuntimeError)



def test_json_socket_connection_round_trip():
    import socket

    from service import _JsonSocketConnection

    left_sock, right_sock = socket.socketpair()
    left = _JsonSocketConnection(left_sock)
    right = _JsonSocketConnection(right_sock)
    try:
        left.send({"type": "probe", "value": "ä"})
        assert right.poll(0.5)
        assert right.recv() == {"type": "probe", "value": "ä"}
    finally:
        left.close()
        right.close()
