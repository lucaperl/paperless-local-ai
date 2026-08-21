"""OCRmyPDF engine plugin for paperless-local-ai.

Verified against OCRmyPDF 17.4.2 as bundled by Paperless-ngx 3.0.5.
OCRmyPDF rasterizes a page, this bridge preconditions oversized OCR-only
rasters to PaddleX's input limit, streams them to paperless-local-ai and returns
OCRmyPDF's native OcrElement tree. No hOCR/XML roundtrip is used.
"""
from __future__ import annotations

import http.client
import json
import logging
import os
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from PIL import Image
from ocrmypdf import BoundingBox, OcrElement, hookimpl
from ocrmypdf.imageops import calculate_downsample, downsample_image
from ocrmypdf.pluginspec import OcrEngine, OrientationConfidence


LOG = logging.getLogger(__name__)
PADDLE_DEFAULT_MAX_SIDE_PIXELS = 3000
PADDLE_MIN_SIDE_PIXELS = 2000
PADDLE_MAX_SIDE_PIXELS = 4000
CONFIG_LOOKUP_TIMEOUT_SECONDS = 1.5


def _downsample_for_paddle(
    image: Image.Image,
    *,
    max_side_pixels: int = PADDLE_DEFAULT_MAX_SIDE_PIXELS,
) -> Image.Image:
    """Fit the OCR-only raster to PaddleX while preserving page geometry."""
    if max_side_pixels < 1:
        raise ValueError("max_side_pixels must be >= 1")
    original_size = image.size
    size = calculate_downsample(
        image,
        max_size=(max_side_pixels, max_side_pixels),
    )
    filtered = downsample_image(image, size)
    if size != original_size:
        LOG.info(
            "OCR raster downsampled: %dx%d -> %dx%d (max_side_pixels=%d)",
            original_size[0], original_size[1], size[0], size[1], max_side_pixels,
        )
    else:
        LOG.debug(
            "OCR raster kept at %dx%d (max_side_pixels=%d)",
            original_size[0], original_size[1], max_side_pixels,
        )
    return filtered


def _endpoint_parts(endpoint: str = "/v1/ocr") -> tuple[str, str, int, str]:
    value = os.environ.get("PLAI_OCR_URL", "").rstrip("/")
    if not value:
        raise RuntimeError("PLAI_OCR_URL is required for paperless-local-ai OCR")
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise RuntimeError("PLAI_OCR_URL must be a complete http(s) URL")
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    if not endpoint.startswith("/"):
        raise ValueError("endpoint must start with /")
    base = parsed.path.rstrip("/")
    return parsed.scheme, parsed.hostname, port, f"{base}{endpoint}"


def _validated_max_side_pixels(value: Any) -> int:
    if isinstance(value, bool):
        return PADDLE_DEFAULT_MAX_SIDE_PIXELS
    try:
        pixels = int(value)
    except (TypeError, ValueError):
        return PADDLE_DEFAULT_MAX_SIDE_PIXELS
    if not PADDLE_MIN_SIDE_PIXELS <= pixels <= PADDLE_MAX_SIDE_PIXELS:
        return PADDLE_DEFAULT_MAX_SIDE_PIXELS
    return pixels


def _configured_max_side_pixels() -> int:
    conn = None
    try:
        scheme, host, port, path = _endpoint_parts("/health")
        connection_cls = http.client.HTTPSConnection if scheme == "https" else http.client.HTTPConnection
        conn = connection_cls(host, port, timeout=CONFIG_LOOKUP_TIMEOUT_SECONDS)
        conn.request("GET", path)
        response = conn.getresponse()
        body = response.read()
        if 200 <= response.status < 300:
            payload = json.loads(body.decode("utf-8"))
            if isinstance(payload, dict):
                return _validated_max_side_pixels(payload.get("max_side_pixels"))
        LOG.warning("OCR service config lookup returned HTTP %s; using %d px fallback", response.status, PADDLE_DEFAULT_MAX_SIDE_PIXELS)
    except Exception as exc:
        LOG.warning("OCR service config lookup failed (%s: %s); using %d px fallback", type(exc).__name__, exc, PADDLE_DEFAULT_MAX_SIDE_PIXELS)
    finally:
        if conn is not None:
            conn.close()
    return PADDLE_DEFAULT_MAX_SIDE_PIXELS


def _token() -> str:
    value = os.environ.get("PLAI_OCR_TOKEN", "")
    if not value:
        raise RuntimeError("PLAI_OCR_TOKEN is required for paperless-local-ai OCR")
    return value


def _requested_languages(options: Any) -> list[str]:
    raw = getattr(options, "languages", None) if options is not None else None
    if raw is None:
        return []
    if isinstance(raw, str):
        return [raw]
    try:
        return [str(item) for item in raw if str(item).strip()]
    except TypeError:
        return []


def _remote_ocr(input_file: Path, options: Any) -> dict[str, Any]:
    scheme, host, port, path = _endpoint_parts()
    timeout = float(os.environ.get("PLAI_OCR_TIMEOUT_SECONDS", "1800"))
    connection_cls = (
        http.client.HTTPSConnection if scheme == "https" else http.client.HTTPConnection
    )
    conn = connection_cls(host, port, timeout=timeout)
    languages = _requested_languages(options)
    size = input_file.stat().st_size

    try:
        conn.putrequest("POST", path)
        conn.putheader("Authorization", f"Bearer {_token()}")
        conn.putheader("Content-Type", "application/octet-stream")
        conn.putheader("Content-Length", str(size))
        conn.putheader("X-PLAI-Filename", input_file.name)
        if languages:
            conn.putheader("X-PLAI-Language", ",".join(languages))
        conn.endheaders()

        with input_file.open("rb") as handle:
            while True:
                chunk = handle.read(1024 * 1024)
                if not chunk:
                    break
                conn.send(chunk)

        response = conn.getresponse()
        body = response.read()
        if response.status < 200 or response.status >= 300:
            detail = body.decode("utf-8", errors="replace")
            raise RuntimeError(
                f"paperless-local-ai OCR HTTP {response.status}: {detail}"
            )
        payload = json.loads(body.decode("utf-8"))
    except OSError as exc:
        raise RuntimeError(f"paperless-local-ai OCR unavailable: {exc}") from exc
    finally:
        conn.close()

    if not isinstance(payload, dict):
        raise RuntimeError("paperless-local-ai OCR returned a non-object response")
    return payload


def _bbox(poly: list[list[float]]) -> BoundingBox:
    xs = [float(point[0]) for point in poly]
    ys = [float(point[1]) for point in poly]
    return BoundingBox(min(xs), min(ys), max(xs), max(ys))


def _estimated_words(
    text: str,
    box: BoundingBox,
) -> list[dict[str, Any]]:
    words = text.split()
    if not words:
        return []
    width = max(1.0, box.width)
    total_chars = sum(len(word) for word in words)
    if total_chars <= 0:
        return []

    out: list[dict[str, Any]] = []
    cursor = box.left
    for index, word in enumerate(words):
        if index == len(words) - 1:
            right = box.right
        else:
            right = min(
                box.right,
                cursor + max(1.0, width * len(word) / total_chars),
            )
        out.append(
            {
                "text": word,
                "poly": [
                    [cursor, box.top],
                    [right, box.top],
                    [right, box.bottom],
                    [cursor, box.bottom],
                ],
            }
        )
        cursor = right
    return out


def _dpi(payload: dict[str, Any]) -> float | None:
    raw = payload.get("dpi")
    if isinstance(raw, (int, float)):
        return float(raw)
    if isinstance(raw, list) and raw:
        values = [float(x) for x in raw[:2] if isinstance(x, (int, float))]
        if values:
            return sum(values) / len(values)
    return None


def _build_ocr_tree(
    payload: dict[str, Any],
    page_number: int,
) -> tuple[OcrElement, str]:
    width = float(payload["width"])
    height = float(payload["height"])
    if width <= 0 or height <= 0:
        raise RuntimeError("paperless-local-ai OCR returned invalid page dimensions")

    page = OcrElement(
        ocr_class="ocr_page",
        bbox=BoundingBox(0.0, 0.0, width, height),
        dpi=_dpi(payload),
        page_number=page_number,
    )

    plain_lines: list[str] = []
    for line in payload.get("lines") or []:
        text = str(line.get("text", "")).strip()
        poly = line.get("poly") or []
        if not text or len(poly) < 4:
            continue

        line_box = _bbox(poly)
        try:
            score = max(0.0, min(1.0, float(line.get("score", 0.0))))
        except (TypeError, ValueError):
            score = 0.0

        line_element = OcrElement(
            ocr_class="ocr_line",
            bbox=line_box,
            confidence=score,
        )

        words = line.get("words") or _estimated_words(text, line_box)
        for word in words:
            word_text = str(word.get("text", "")).strip()
            word_poly = word.get("poly") or []
            if not word_text or len(word_poly) < 4:
                continue
            line_element.children.append(
                OcrElement(
                    ocr_class="ocrx_word",
                    bbox=_bbox(word_poly),
                    text=word_text,
                    confidence=score,
                )
            )

        if not line_element.children:
            line_element.children.append(
                OcrElement(
                    ocr_class="ocrx_word",
                    bbox=line_box,
                    text=text,
                    confidence=score,
                )
            )

        paragraph = OcrElement(
            ocr_class="ocr_par",
            bbox=line_box,
            children=[line_element],
        )
        carea = OcrElement(
            ocr_class="ocr_carea",
            bbox=line_box,
            children=[paragraph],
        )
        page.children.append(carea)
        plain_lines.append(text)

    plain = str(payload.get("text") or "").strip() or "\n".join(plain_lines)
    return page, plain


class RemotePaddleEngine(OcrEngine):
    @staticmethod
    def version() -> str:
        return "paperless-local-ai"

    @staticmethod
    def creator_tag(options) -> str:
        return "paperless-local-ai PaddleOCR remote engine"

    def __str__(self) -> str:
        return "paperless-local-ai PaddleOCR remote engine"

    @staticmethod
    def languages(options) -> set[str]:
        requested = _requested_languages(options)
        return set(requested or ["eng"])

    @staticmethod
    def get_orientation(input_file: Path, options) -> OrientationConfidence:
        return OrientationConfidence(angle=0, confidence=0.0)

    @staticmethod
    def get_deskew(input_file: Path, options) -> float:
        return 0.0

    @staticmethod
    def supports_generate_ocr() -> bool:
        return True

    @staticmethod
    def generate_ocr(
        input_file: Path,
        options,
        page_number: int = 0,
    ) -> tuple[OcrElement, str]:
        return _build_ocr_tree(_remote_ocr(input_file, options), page_number)

    @staticmethod
    def generate_hocr(
        input_file: Path,
        output_hocr: Path,
        output_text: Path,
        options,
    ) -> None:
        raise NotImplementedError(
            "paperless-local-ai uses OCRmyPDF 17 generate_ocr(), not hOCR"
        )

    @staticmethod
    def generate_pdf(
        input_file: Path,
        output_pdf: Path,
        output_text: Path,
        options,
    ) -> None:
        raise NotImplementedError(
            "paperless-local-ai requires OCRmyPDF pdf_renderer=fpdf2"
        )


@hookimpl(tryfirst=True)
def filter_ocr_image(page, image: Image.Image) -> Image.Image:
    # OCRmyPDF explicitly allows OCR-engine plugins to resize this OCR-only
    # image when aspect ratio and DPI are preserved. downsample_image() adjusts
    # DPI proportionally, so the returned OcrElement geometry remains aligned
    # with the unchanged visible PDF page.
    return _downsample_for_paddle(image, max_side_pixels=_configured_max_side_pixels())


@hookimpl(tryfirst=True)
def get_ocr_engine(options=None):
    return RemotePaddleEngine()
