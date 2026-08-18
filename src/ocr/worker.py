import fcntl
import json
import os
import re
import shutil
import subprocess
import time
import unicodedata
from contextlib import contextmanager
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path

import pymupdf
import requests

from app_config import load_config as load_app_config


URL = ""
TOKEN = os.environ["PAPERLESS_TOKEN"]
QUEUE_TAG_NAME = "PaddleOCR"
ERROR_TAG_NAME = "PaddleOCR Fehler"
NEXT_TAG_NAME = "LLM"
AI_LOCK_FILE = Path("/coordination/ai.lock")
INTERVAL = 10
OCR_LANGUAGE = "de"
OCR_VERSION = "PP-OCRv6"
OCR_DEVICE = "cpu"
TMP = Path("/ocr-data/tmp")
TMP.mkdir(parents=True, exist_ok=True)


def apply_app_config(cfg):
    global URL, QUEUE_TAG_NAME, ERROR_TAG_NAME, NEXT_TAG_NAME
    global INTERVAL, OCR_LANGUAGE, OCR_VERSION, OCR_DEVICE

    workflow = cfg["workflow"]
    ocr = cfg["ocr"]
    runtime = cfg["runtime"]

    URL = cfg["connections"]["paperless_url"].rstrip("/")
    QUEUE_TAG_NAME = workflow["ocr_queue_tag"]
    ERROR_TAG_NAME = workflow["ocr_error_tag"]
    NEXT_TAG_NAME = workflow["llm_queue_tag"]
    INTERVAL = runtime["poll_interval_seconds"]
    OCR_LANGUAGE = ocr["language"]
    OCR_VERSION = ocr["version"]
    OCR_DEVICE = ocr["device"]

# PDF-Seitenklassifikation. Die Werte sind konservative Toleranzen,
# keine PDF-Standards. Entscheidungen beruhen immer auf mehreren
# strukturellen Signalen statt nur auf Textmenge oder Bildpixeln.
MIN_NATIVE_CHARS = 10
SMALL_RASTER_PAGE = 0.08
SMALL_RASTER_CONTENT = 0.15
DOMINANT_RASTER_CONTENT = 0.75
HIGH_TEXT_ON_RASTER = 0.80
HIGH_TEXT_BBOX_COVERED = 0.80
LARGE_RASTER_CONTENT = 0.25
HIDDEN_TEXT_MIN = 5
COVERED_TEXT_RATIO = 0.10
BITONAL_SCAN_MIN_DPI = 120.0
PDF_RENDER_DPI = 300

s = requests.Session()
s.headers.update({
    "Authorization": f"Token {TOKEN}",
    "Accept": "application/json",
})


def log(msg):
    print(
        time.strftime("%Y-%m-%d %H:%M:%S"),
        msg,
        flush=True,
    )


@contextmanager
def ai_resource_lock(stage, doc_id):
    AI_LOCK_FILE.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    with AI_LOCK_FILE.open("a+") as lock_file:
        log(
            f"[LOCK] ID {doc_id}: "
            f"warte auf globalen AI-Lock ({stage})"
        )

        fcntl.flock(
            lock_file.fileno(),
            fcntl.LOCK_EX,
        )

        log(
            f"[LOCK] ID {doc_id}: "
            f"globaler AI-Lock aktiv ({stage})"
        )

        try:
            yield
        finally:
            fcntl.flock(
                lock_file.fileno(),
                fcntl.LOCK_UN,
            )


def api(method, path, **kwargs):
    last_error = None

    for attempt in range(1, 4):
        try:
            r = s.request(
                method,
                f"{URL}{path}",
                timeout=180,
                **kwargs,
            )

            r.raise_for_status()
            return r

        except requests.RequestException as e:
            last_error = e

            log(
                f"[API] Versuch {attempt}/3 "
                f"fehlgeschlagen: {e}"
            )

            if attempt < 3:
                time.sleep(5)

    raise last_error


def tag_id(name):
    data = api(
        "GET",
        "/api/tags/",
        params={
            "page_size": 1000,
        },
    ).json()

    for tag in data["results"]:
        if tag["name"] == name:
            return tag["id"]

    raise RuntimeError(
        f'Tag "{name}" nicht gefunden'
    )


@dataclass
class PageFeatures:
    chars: int
    hidden_chars: int
    ignore_text_ops: int
    covered_chars: int
    raster_page: float
    raster_content: float
    text_on_raster: float
    text_bbox_covered: float
    max_effective_dpi: float
    one_bit_image: bool
    images: int
    drawings: int


@dataclass
class PagePlan:
    page_no: int
    decision: str
    reasons: list[str]
    native_text: str
    features: PageFeatures


@dataclass
class OcrResult:
    text: str
    mean_confidence: float | None
    lines: int


def rect_area(rect):
    r = pymupdf.Rect(rect)

    if r.is_empty or r.is_infinite:
        return 0.0

    return (
        max(0.0, r.width)
        * max(0.0, r.height)
    )


def clipped_rect(rect, limit):
    r = (
        pymupdf.Rect(rect)
        & pymupdf.Rect(limit)
    )

    if r.is_empty or r.is_infinite:
        return None

    return r


def bbox_union(rects):
    items = [
        pymupdf.Rect(r)
        for r in rects
        if r is not None
        and rect_area(r) > 0
    ]

    if not items:
        return None

    out = pymupdf.Rect(items[0])

    for rect in items[1:]:
        out |= rect

    return out


def union_area(rects):
    items = [
        pymupdf.Rect(r)
        for r in rects
        if r is not None
        and rect_area(r) > 0
    ]

    if not items:
        return 0.0

    xs = sorted({
        x
        for rect in items
        for x in (
            rect.x0,
            rect.x1,
        )
    })

    total = 0.0

    for x0, x1 in zip(
        xs,
        xs[1:],
    ):
        if x1 <= x0:
            continue

        intervals = sorted(
            (rect.y0, rect.y1)
            for rect in items
            if rect.x0 < x1
            and rect.x1 > x0
        )

        if not intervals:
            continue

        merged = []
        y0, y1 = intervals[0]

        for a, b in intervals[1:]:
            if a <= y1:
                y1 = max(y1, b)
            else:
                merged.append((y0, y1))
                y0, y1 = a, b

        merged.append((y0, y1))

        total += (
            (x1 - x0)
            * sum(
                max(0.0, b - a)
                for a, b in merged
            )
        )

    return total


def rect_covered_fraction(rect, covers):
    if rect is None:
        return 0.0

    target = pymupdf.Rect(rect)
    target_area = rect_area(target)

    if target_area <= 0:
        return 0.0

    intersections = []

    for cover in covers:
        inter = (
            target
            & pymupdf.Rect(cover)
        )

        if rect_area(inter) > 0:
            intersections.append(inter)

    return min(
        1.0,
        union_area(intersections)
        / target_area,
    )


def is_tagged_pdf(doc):
    try:
        kind, value = doc.xref_get_key(
            doc.pdf_catalog(),
            "StructTreeRoot",
        )

        return (
            kind != "null"
            and value != "null"
        )

    except Exception:
        return False


def analyze_page(page):
    page_rect = page.rect
    page_area = rect_area(page_rect)

    traces = page.get_texttrace()

    visible_spans = []
    char_rects = []
    chars = 0
    hidden_chars = 0

    for span in traces:
        render_mode = int(
            span.get(
                "type",
                0,
            )
        )

        opacity = float(
            span.get(
                "opacity",
                1.0,
            )
        )

        hidden = (
            render_mode > 1
            or opacity <= 0.001
        )

        count = 0

        for char_info in span.get(
            "chars",
            (),
        ):
            try:
                char = chr(char_info[0])
            except (
                TypeError,
                ValueError,
            ):
                char = ""

            bbox = pymupdf.Rect(
                char_info[3]
            )

            if (
                not char
                or char.isspace()
                or rect_area(bbox) <= 0
            ):
                continue

            count += 1
            char_rects.append(bbox)

        chars += count

        if hidden:
            hidden_chars += count
        else:
            visible_spans.append(span)

    images = page.get_image_info(
        hashes=False,
        xrefs=False,
    )

    image_rects = []
    max_effective_dpi = 0.0
    one_bit_image = False

    for image in images:
        rect = clipped_rect(
            image["bbox"],
            page_rect,
        )

        if rect is None:
            continue

        image_rects.append(rect)

        if (
            rect.width > 0
            and rect.height > 0
        ):
            xdpi = (
                float(image["width"])
                / (rect.width / 72.0)
            )

            ydpi = (
                float(image["height"])
                / (rect.height / 72.0)
            )

            max_effective_dpi = max(
                max_effective_dpi,
                min(xdpi, ydpi),
            )

        one_bit_image |= (
            int(
                image.get(
                    "bpc",
                    8,
                )
                or 8
            )
            <= 1
        )

    bboxlog = page.get_bboxlog()

    ignore_text_ops = sum(
        1
        for entry in bboxlog
        if entry[0] == "ignore-text"
    )

    image_operations = [
        (
            seqno,
            pymupdf.Rect(entry[1]),
        )
        for seqno, entry
        in enumerate(bboxlog)
        if entry[0] in {
            "fill-image",
            "fill-imgmask",
        }
    ]

    covered_chars = 0

    for span in visible_spans:
        seqno = span.get("seqno")

        if seqno is None:
            continue

        later_images = [
            rect
            for image_seqno, rect
            in image_operations
            if image_seqno > seqno
        ]

        if not later_images:
            continue

        for char_info in span.get(
            "chars",
            (),
        ):
            try:
                char = chr(char_info[0])
            except (
                TypeError,
                ValueError,
            ):
                continue

            if char.isspace():
                continue

            if rect_covered_fraction(
                char_info[3],
                later_images,
            ) >= 0.90:
                covered_chars += 1

    raster_page = (
        union_area(image_rects)
        / page_area
        if page_area
        else 0.0
    )

    text_bbox = bbox_union(
        char_rects
    )

    content_rects = list(
        image_rects
    )

    if text_bbox is not None:
        content_rects.append(
            text_bbox
        )

    content_bbox = bbox_union(
        content_rects
    )

    if (
        content_bbox is not None
        and rect_area(content_bbox) > 0
    ):
        raster_content = (
            union_area([
                clipped_rect(
                    rect,
                    content_bbox,
                )
                for rect in image_rects
            ])
            / rect_area(content_bbox)
        )
    else:
        raster_content = 0.0

    chars_on_raster = sum(
        1
        for rect in char_rects
        if rect_covered_fraction(
            rect,
            image_rects,
        ) >= 0.50
    )

    text_on_raster = (
        chars_on_raster / chars
        if chars
        else 0.0
    )

    text_bbox_covered = (
        rect_covered_fraction(
            text_bbox,
            image_rects,
        )
        if text_bbox is not None
        else 0.0
    )

    try:
        drawings = len(
            page.get_cdrawings()
        )
    except Exception:
        drawings = len(
            page.get_drawings()
        )

    return PageFeatures(
        chars=chars,
        hidden_chars=hidden_chars,
        ignore_text_ops=ignore_text_ops,
        covered_chars=covered_chars,
        raster_page=raster_page,
        raster_content=raster_content,
        text_on_raster=text_on_raster,
        text_bbox_covered=text_bbox_covered,
        max_effective_dpi=max_effective_dpi,
        one_bit_image=one_bit_image,
        images=len(image_rects),
        drawings=drawings,
    )


def classify_page(features, tagged):
    f = features

    visual_content = (
        f.images > 0
        or f.drawings > 0
    )

    if f.chars < MIN_NATIVE_CHARS:
        if visual_content:
            return (
                "OCR_PAGE",
                [
                    f"nur {f.chars} "
                    "brauchbare native Zeichen"
                ],
            )

        return (
            "EMPTY",
            [
                "kein relevanter Text- "
                "oder Bildinhalt"
            ],
        )

    meaningful_raster = not (
        f.raster_page
        < SMALL_RASTER_PAGE
        and f.raster_content
        < SMALL_RASTER_CONTENT
    )

    if not meaningful_raster:
        return (
            "NATIVE",
            [
                "native Textseite ohne "
                "relevanten Rasteranteil"
            ],
        )

    hard_reasons = []

    if f.hidden_chars >= HIDDEN_TEXT_MIN:
        hard_reasons.append(
            f"{f.hidden_chars} versteckte "
            "Textzeichen + Raster"
        )

    if f.ignore_text_ops > 0:
        hard_reasons.append(
            f"{f.ignore_text_ops} "
            "ignore-text-Operation(en) + Raster"
        )

    covered_ratio = (
        f.covered_chars / f.chars
        if f.chars
        else 0.0
    )

    if covered_ratio >= COVERED_TEXT_RATIO:
        hard_reasons.append(
            f"{covered_ratio:.0%} des Texts "
            "wird später von Raster überdeckt"
        )

    if hard_reasons:
        return (
            "OCR_PAGE",
            hard_reasons,
        )

    raster_dominant = (
        f.raster_content
        >= DOMINANT_RASTER_CONTENT
        and f.text_on_raster
        >= HIGH_TEXT_ON_RASTER
        and f.text_bbox_covered
        >= HIGH_TEXT_BBOX_COVERED
    )

    bitonal_scan = (
        raster_dominant
        and f.one_bit_image
        and f.max_effective_dpi
        >= BITONAL_SCAN_MIN_DPI
    )

    if bitonal_scan:
        return (
            "OCR_PAGE",
            [
                "Raster dominiert den Inhaltsbereich",
                "Text liegt praktisch vollständig "
                "auf dem Raster",
                "hochaufgelöstes 1-Bit-Raster "
                f"({f.max_effective_dpi:.0f} dpi)",
            ],
        )

    # Tagged/strukturierte PDFs sind ein starkes positives Signal
    # für born-digital, aber nur wenn vorher kein harter Scan-Hinweis
    # gefunden wurde und die Rasterstruktur nicht dominiert.
    if (
        tagged
        and not raster_dominant
        and f.raster_content
        < 0.50
    ):
        return (
            "NATIVE",
            [
                "Tagged PDF ohne dominanten "
                "Scan-Hinweis"
            ],
        )

    # Relevante Rasterbereiche, deren Herkunft nicht sicher aus
    # der PDF-Struktur ableitbar ist, werden nur verifiziert.
    # Dadurch müssen normale born-digital Seiten nicht durch OCR.
    if (
        raster_dominant
        or f.raster_content
        >= LARGE_RASTER_CONTENT
        or f.text_on_raster > 0.20
    ):
        return (
            "VERIFY",
            [
                "mehrdeutige Text+Raster-Seite; "
                "OCR nur zur Verifikation"
            ],
        )

    return (
        "NATIVE",
        [
            "native Textseite mit begrenztem "
            "Rasteranteil"
        ],
    )


def normalize_text(text):
    normalized = unicodedata.normalize(
        "NFKC",
        text or "",
    ).casefold()

    normalized = re.sub(
        r"[^\w]+",
        " ",
        normalized,
        flags=re.UNICODE,
    )

    return " ".join(
        normalized.split()
    )


def choose_verified_text(
    native_text,
    ocr_result,
):
    native = normalize_text(
        native_text
    )

    ocr = normalize_text(
        ocr_result.text
    )

    if not ocr:
        return (
            "NATIVE",
            "OCR lieferte keinen Text",
        )

    if not native:
        return (
            "OCR",
            "native Extraktion leer",
        )

    native_tokens = {
        token
        for token in native.split()
        if len(token) >= 2
    }

    ocr_tokens = {
        token
        for token in ocr.split()
        if len(token) >= 2
    }

    native_covered = (
        len(
            native_tokens
            & ocr_tokens
        )
        / len(native_tokens)
        if native_tokens
        else 0.0
    )

    ocr_extra = (
        len(
            ocr_tokens
            - native_tokens
        )
        / len(ocr_tokens)
        if ocr_tokens
        else 0.0
    )

    length_ratio = (
        len(ocr)
        / max(1, len(native))
    )

    similarity = SequenceMatcher(
        None,
        native,
        ocr,
        autojunk=False,
    ).ratio()

    confidence = (
        ocr_result.mean_confidence
        if ocr_result.mean_confidence
        is not None
        else 1.0
    )

    if (
        confidence >= 0.60
        and length_ratio >= 1.80
        and len(ocr) >= 120
    ):
        return (
            "OCR",
            "OCR ist deutlich vollständiger "
            f"(Länge {length_ratio:.2f}x, "
            f"Konfidenz {confidence:.2f})",
        )

    if (
        confidence >= 0.65
        and length_ratio >= 1.35
        and native_covered >= 0.55
    ):
        return (
            "OCR",
            "OCR erweitert den nativen Text "
            f"(Länge {length_ratio:.2f}x, "
            f"native Abdeckung {native_covered:.0%})",
        )

    if (
        confidence >= 0.70
        and ocr_extra >= 0.35
        and native_covered >= 0.70
        and len(ocr) >= len(native) + 80
    ):
        return (
            "OCR",
            "OCR enthält viele zusätzliche "
            f"Texttokens ({ocr_extra:.0%})",
        )

    return (
        "NATIVE",
        "kein ausreichender Mehrwert durch OCR "
        f"(Länge {length_ratio:.2f}x, "
        f"Ähnlichkeit {similarity:.2f}, "
        f"Konfidenz {confidence:.2f})",
    )


def ocr_payload(obj):
    if isinstance(
        obj.get("res"),
        dict,
    ):
        return obj["res"]

    return obj


def page_number_from_result(
    json_file,
    payload,
):
    candidates = [
        str(
            payload.get(
                "input_path",
                "",
            )
        ),
        json_file.name,
    ]

    for candidate in candidates:
        match = re.search(
            r"page-(\d+)",
            candidate,
        )

        if match:
            return int(
                match.group(1)
            )

    return None


def parse_ocr_results(out):
    results = {}

    for json_file in sorted(
        out.rglob("*.json")
    ):
        obj = json.loads(
            json_file.read_text(
                encoding="utf-8",
            )
        )

        payload = ocr_payload(obj)

        page_no = page_number_from_result(
            json_file,
            payload,
        )

        texts = payload.get(
            "rec_texts",
            [],
        )

        scores = payload.get(
            "rec_scores",
            [],
        )

        clean_lines = [
            str(value).strip()
            for value in texts
            if str(value).strip()
        ]

        numeric_scores = []

        if isinstance(scores, list):
            for value in scores:
                try:
                    numeric_scores.append(
                        float(value)
                    )
                except (
                    TypeError,
                    ValueError,
                ):
                    pass

        mean_confidence = (
            sum(numeric_scores)
            / len(numeric_scores)
            if numeric_scores
            else None
        )

        result = OcrResult(
            text="\n".join(
                clean_lines
            ).strip(),
            mean_confidence=mean_confidence,
            lines=len(clean_lines),
        )

        if page_no is None:
            # Einzelbild-Modus: genau ein Ergebnis ohne Seitennummer.
            results.setdefault(
                None,
                result,
            )
        else:
            results[page_no] = result

    return results


def run_paddleocr(
    input_path,
    out,
):
    shutil.rmtree(
        out,
        ignore_errors=True,
    )

    out.mkdir(
        parents=True,
        exist_ok=True,
    )

    subprocess.run(
        [
            "paddleocr",
            "ocr",
            "-i",
            str(input_path),
            "--lang",
            OCR_LANGUAGE,
            "--ocr_version",
            OCR_VERSION,
            "--device",
            OCR_DEVICE,
            "--save_path",
            str(out),
        ],
        check=True,
    )

    return parse_ocr_results(
        out
    )


def render_page(
    page,
    target,
):
    pixmap = page.get_pixmap(
        dpi=PDF_RENDER_DPI,
        alpha=False,
    )

    pixmap.save(
        str(target)
    )


def selective_pdf_content(
    pdf,
    work,
    doc_id,
    ocr_runner=run_paddleocr,
):
    pages_dir = work / "pages"
    ocr_out = work / "results"

    shutil.rmtree(
        work,
        ignore_errors=True,
    )

    pages_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    plans = []

    with pymupdf.open(
        str(pdf)
    ) as document:
        tagged = is_tagged_pdf(
            document
        )

        log(
            f"[PDF] ID {doc_id}: "
            f"{document.page_count} Seite(n), "
            f"Tagged={tagged}"
        )

        for index, page in enumerate(
            document,
            start=1,
        ):
            native_text = (
                page.get_text(
                    "text",
                    sort=True,
                )
                or ""
            ).strip()

            features = analyze_page(
                page
            )

            decision, reasons = classify_page(
                features,
                tagged,
            )

            plans.append(
                PagePlan(
                    page_no=index,
                    decision=decision,
                    reasons=reasons,
                    native_text=native_text,
                    features=features,
                )
            )

            log(
                f"[PDF] ID {doc_id} Seite {index}: "
                f"{decision} | "
                f"chars={features.chars}, "
                f"raster_content="
                f"{features.raster_content:.0%}, "
                f"text_on_raster="
                f"{features.text_on_raster:.0%}, "
                f"dpi="
                f"{features.max_effective_dpi:.0f}, "
                f"1bit={features.one_bit_image}"
            )

            for reason in reasons:
                log(
                    f"[PDF] ID {doc_id} Seite {index}: "
                    f"{reason}"
                )

            if decision in {
                "OCR_PAGE",
                "VERIFY",
            }:
                render_page(
                    page,
                    pages_dir
                    / f"page-{index:04d}.png",
                )

    pages_for_ocr = [
        plan.page_no
        for plan in plans
        if plan.decision in {
            "OCR_PAGE",
            "VERIFY",
        }
    ]

    if not pages_for_ocr:
        return None

    log(
        f"[PDF] ID {doc_id}: "
        "PaddleOCR nur für Seite(n) "
        + ",".join(
            str(value)
            for value in pages_for_ocr
        )
    )

    ocr_results = ocr_runner(
        pages_dir,
        ocr_out,
    )

    final_pages = []
    used_ocr = False

    for plan in plans:
        if plan.decision == "EMPTY":
            final_pages.append("")
            continue

        if plan.decision == "NATIVE":
            final_pages.append(
                plan.native_text
            )
            continue

        result = ocr_results.get(
            plan.page_no
        )

        if result is None:
            raise RuntimeError(
                "Kein PaddleOCR-Ergebnis für "
                f"PDF-Seite {plan.page_no}"
            )

        if plan.decision == "OCR_PAGE":
            if not result.text:
                if plan.features.chars < MIN_NATIVE_CHARS:
                    final_pages.append("")
                    log(
                        f"[PDF] ID {doc_id} Seite "
                        f"{plan.page_no}: OCR ohne Text; "
                        "als leere Scan-Seite behandelt"
                    )
                    used_ocr = True
                    continue

                raise RuntimeError(
                    "PaddleOCR lieferte für zwingende "
                    f"OCR-Seite {plan.page_no} keinen Text"
                )

            final_pages.append(
                result.text
            )
            used_ocr = True

            log(
                f"[PDF] ID {doc_id} Seite "
                f"{plan.page_no}: OCR übernommen"
            )
            continue

        choice, reason = choose_verified_text(
            plan.native_text,
            result,
        )

        log(
            f"[VERIFY] ID {doc_id} Seite "
            f"{plan.page_no}: {choice} | {reason}"
        )

        if choice == "OCR":
            final_pages.append(
                result.text
            )
            used_ocr = True
        else:
            final_pages.append(
                plan.native_text
            )

    # Wenn OCR ausschließlich zur Verifikation lief und keine Seite
    # davon profitierte, Paperless-content unangetastet lassen.
    if not used_ocr:
        return None

    content = "\n\n".join(
        value.strip()
        for value in final_pages
        if value.strip()
    ).strip()

    if not content:
        raise RuntimeError(
            "Selektive PDF-OCR hat keinen Text geliefert"
        )

    return content


def current_tags(doc_id):
    doc = api(
        "GET",
        f"/api/documents/{doc_id}/",
    ).json()

    return list(
        doc.get(
            "tags",
            [],
        )
    )


def update_tags(
    doc_id,
    add=None,
    remove=None,
):
    add = set(
        add or []
    )

    remove = set(
        remove or []
    )

    tags = set(
        current_tags(doc_id)
    )

    tags -= remove
    tags |= add

    api(
        "PATCH",
        f"/api/documents/{doc_id}/",
        json={
            "tags": sorted(tags),
        },
    )


def mark_success(
    doc_id,
    queue_tag,
    error_tag,
    next_tag,
):
    update_tags(
        doc_id,
        add={
            next_tag,
        },
        remove={
            queue_tag,
            error_tag,
        },
    )

    log(
        f"[HANDOFF] ID {doc_id}: "
        f"'{QUEUE_TAG_NAME}' abgeschlossen, "
        f"'{NEXT_TAG_NAME}' gesetzt"
    )


def mark_error(
    doc_id,
    queue_tag,
    error_tag,
    error,
):
    log(
        f"[FAILED] ID {doc_id}: "
        f"{type(error).__name__}: {error}"
    )

    try:
        update_tags(
            doc_id,
            add={
                error_tag,
            },
            remove={
                queue_tag,
            },
        )

        log(
            f"[FAILED] ID {doc_id}: "
            f"mit '{ERROR_TAG_NAME}' markiert"
        )

    except Exception as tag_error:
        log(
            "[WARN] Fehlerstatus konnte "
            f"nicht gesetzt werden: {tag_error}"
        )


def process(
    doc,
    queue_tag,
    error_tag,
    next_tag,
):
    doc_id = doc["id"]
    title = doc.get(
        "title",
        "",
    )

    log(
        f"[JOB] ID {doc_id}: {title}"
    )

    original = api(
        "GET",
        f"/api/documents/{doc_id}/download/",
        params={
            "original": "true",
        },
        headers={
            "Accept": "*/*",
        },
    )

    ctype = (
        original.headers
        .get(
            "Content-Type",
            "",
        )
        .split(";")[0]
        .lower()
    )

    if ctype == "application/pdf":
        ext = ".pdf"

    elif ctype in (
        "image/jpeg",
        "image/jpg",
    ):
        ext = ".jpg"

    elif ctype == "image/png":
        ext = ".png"

    elif ctype in (
        "image/tiff",
        "image/tif",
    ):
        ext = ".tiff"

    else:
        log(
            f"[SKIP] ID {doc_id}: "
            "nicht unterstützter Dokumenttyp: "
            f"{ctype or 'unbekannt'}"
        )

        mark_success(
            doc_id,
            queue_tag,
            error_tag,
            next_tag,
        )
        return

    source = TMP / f"{doc_id}{ext}"
    work = TMP / f"ocr-{doc_id}"

    source.write_bytes(
        original.content
    )

    try:
        started = time.monotonic()

        if ext == ".pdf":
            content = selective_pdf_content(
                source,
                work,
                doc_id,
            )

            if content is None:
                log(
                    f"[SKIP] ID {doc_id}: "
                    "PDF-Seiten benötigen keine "
                    "inhaltliche OCR-Ersetzung"
                )

                mark_success(
                    doc_id,
                    queue_tag,
                    error_tag,
                    next_tag,
                )
                return

        else:
            results = run_paddleocr(
                source,
                work,
            )

            result = results.get(None)

            if result is None:
                if len(results) == 1:
                    result = next(
                        iter(
                            results.values()
                        )
                    )
                else:
                    raise RuntimeError(
                        "PaddleOCR-Ergebnis für Bild "
                        "nicht eindeutig"
                    )

            content = result.text.strip()

            if not content:
                raise RuntimeError(
                    "PaddleOCR hat keinen Text geliefert"
                )

        tags = set(
            current_tags(doc_id)
        )

        tags.discard(
            queue_tag
        )

        tags.discard(
            error_tag
        )

        tags.add(
            next_tag
        )

        api(
            "PATCH",
            f"/api/documents/{doc_id}/",
            json={
                "content": content,
                "tags": sorted(tags),
            },
        )

        duration = (
            time.monotonic()
            - started
        )

        log(
            f"[OK] ID {doc_id}: "
            f"{len(content)} Zeichen, "
            f"{duration:.1f} Sekunden"
        )

        log(
            f"[HANDOFF] ID {doc_id}: "
            f"'{QUEUE_TAG_NAME}' abgeschlossen, "
            f"'{NEXT_TAG_NAME}' gesetzt"
        )

    finally:
        source.unlink(
            missing_ok=True
        )

        shutil.rmtree(
            work,
            ignore_errors=True,
        )


def main():
    app_cfg = load_app_config()
    apply_app_config(app_cfg)

    log(
        "[BOOT] PaddleOCR Worker"
    )
    log(
        f"[BOOT] AppConfig: /config/app-config.json (v{app_cfg['version']})"
    )
    log(
        f"[BOOT] OCR: {OCR_VERSION} / {OCR_LANGUAGE} / {OCR_DEVICE}"
    )

    log(
        f"[BOOT] Polling alle "
        f"{INTERVAL} Sekunden"
    )

    log(
        f"[BOOT] Erfolgs-Handoff: "
        f"{NEXT_TAG_NAME}"
    )

    log(
        f"[BOOT] AI-Lock: "
        f"{AI_LOCK_FILE}"
    )

    log(
        "[BOOT] PDF-Modus: "
        "selektive Seiten-OCR mit "
        "NATIVE/OCR_PAGE/VERIFY"
    )

    while True:
        try:
            app_cfg = load_app_config()
            apply_app_config(app_cfg)

            queue_tag = tag_id(
                QUEUE_TAG_NAME
            )

            error_tag = tag_id(
                ERROR_TAG_NAME
            )

            next_tag = tag_id(
                NEXT_TAG_NAME
            )

            docs = api(
                "GET",
                "/api/documents/",
                params={
                    "tags__id__all": queue_tag,
                    "ordering": "added",
                    "page_size": 20,
                },
            ).json()["results"]

            for doc in docs:
                try:
                    with ai_resource_lock(
                        "PaddleOCR",
                        doc["id"],
                    ):
                        process(
                            doc,
                            queue_tag,
                            error_tag,
                            next_tag,
                        )

                except Exception as e:
                    mark_error(
                        doc["id"],
                        queue_tag,
                        error_tag,
                        e,
                    )

        except Exception as e:
            log(
                "[ERROR] Worker/Polling: "
                f"{type(e).__name__}: {e}"
            )

        time.sleep(
            INTERVAL
        )


if __name__ == "__main__":
    main()
