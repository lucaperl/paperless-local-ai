from PIL import Image

import ocrmypdf_plai as plugin


def test_default_ocr_raster_limit_is_3000():
    assert plugin.PADDLE_DEFAULT_MAX_SIDE_PIXELS == 3000
    assert plugin.PADDLE_MIN_SIDE_PIXELS == 2000
    assert plugin.PADDLE_MAX_SIDE_PIXELS == 4000


def test_downsample_for_paddle_keeps_small_image_unchanged():
    image = Image.new("L", (1200, 800), color=255)
    image.info["dpi"] = (300, 300)
    filtered = plugin._downsample_for_paddle(image)
    assert filtered is image
    assert filtered.size == (1200, 800)
    assert filtered.info["dpi"] == (300, 300)


def test_filter_ocr_image_uses_runtime_limit_and_adjusts_dpi(monkeypatch):
    monkeypatch.setattr(plugin, "_configured_max_side_pixels", lambda: 3000)
    image = Image.new("L", (3100, 100), color=255)
    image.info["dpi"] = (300, 300)
    filtered = plugin.filter_ocr_image(None, image)
    assert filtered.size == (3000, 96)
    assert filtered.info["dpi"] == (290, 288)
    assert abs(image.width / 300 - filtered.width / 290) < 0.02
    assert abs(image.height / 300 - filtered.height / 288) < 0.02


def test_invalid_remote_limit_falls_back_to_safe_default():
    assert plugin._validated_max_side_pixels(None) == 3000
    assert plugin._validated_max_side_pixels(True) == 3000
    assert plugin._validated_max_side_pixels(1999) == 3000
    assert plugin._validated_max_side_pixels(4001) == 3000
    assert plugin._validated_max_side_pixels("3200") == 3200


def test_retry_delay_validation_preserves_empty_schedule():
    assert plugin._validated_retry_delays([]) == []
    assert plugin._validated_retry_delays([15, 60, 300, 600]) == [15, 60, 300, 600]
    assert plugin._validated_retry_delays([0]) == plugin.DEFAULT_RETRY_DELAYS_SECONDS


def test_remote_ocr_retries_service_authorized_failure(monkeypatch, tmp_path):
    image = tmp_path / "page.png"
    image.write_bytes(b"fake")
    calls = []
    waits = []

    monkeypatch.setattr(plugin, "_configured_retry_delays", lambda: [15, 60])
    monkeypatch.setattr(plugin, "_source_name", lambda options, input_file: "scan.pdf")
    monkeypatch.setattr(plugin, "_wait_for_retry", lambda delay, request_id: waits.append(delay))

    def fake_once(*args, **kwargs):
        calls.append(kwargs["attempt"])
        if len(calls) == 1:
            raise plugin.RetryableRemoteOCRError(
                "temporary",
                retry_after_seconds=15,
                service_authorized_retry=True,
            )
        return {"ok": True}

    monkeypatch.setattr(plugin, "_remote_ocr_once", fake_once)
    assert plugin._remote_ocr(image, None, 0) == {"ok": True}
    assert calls == [1, 2]
    assert waits == [15]


def test_remote_ocr_does_not_retry_final_http_error(monkeypatch, tmp_path):
    image = tmp_path / "page.png"
    image.write_bytes(b"fake")
    monkeypatch.setattr(plugin, "_configured_retry_delays", lambda: [15, 60])
    monkeypatch.setattr(plugin, "_source_name", lambda options, input_file: "scan.pdf")

    def fail_once(*args, **kwargs):
        raise RuntimeError("paperless-local-ai OCR HTTP 500: deterministic")

    monkeypatch.setattr(plugin, "_remote_ocr_once", fail_once)
    try:
        plugin._remote_ocr(image, None, 0)
    except RuntimeError as exc:
        assert "deterministic" in str(exc)
    else:
        raise AssertionError("final HTTP errors must fail immediately")
