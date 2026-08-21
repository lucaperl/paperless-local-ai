from PIL import Image

from ocrmypdf_plai import (
    PADDLE_MAX_SIDE_PIXELS,
    _downsample_for_paddle,
    filter_ocr_image,
)


def test_paddle_ocr_input_limit_matches_paddlex_37_contract():
    assert PADDLE_MAX_SIDE_PIXELS == 4000


def test_downsample_for_paddle_keeps_small_image_unchanged():
    image = Image.new("L", (1200, 800), color=255)
    image.info["dpi"] = (300, 300)

    filtered = _downsample_for_paddle(image)

    assert filtered is image
    assert filtered.size == (1200, 800)
    assert filtered.info["dpi"] == (300, 300)


def test_filter_ocr_image_downsamples_long_side_and_adjusts_dpi():
    image = Image.new("L", (4100, 100), color=255)
    image.info["dpi"] = (300, 300)

    filtered = filter_ocr_image(None, image)

    assert filtered.size == (4000, 97)
    assert filtered.info["dpi"] == (293, 291)

    original_width_inches = image.width / image.info["dpi"][0]
    filtered_width_inches = filtered.width / filtered.info["dpi"][0]
    original_height_inches = image.height / image.info["dpi"][1]
    filtered_height_inches = filtered.height / filtered.info["dpi"][1]
    assert abs(original_width_inches - filtered_width_inches) < 0.02
    assert abs(original_height_inches - filtered_height_inches) < 0.02
