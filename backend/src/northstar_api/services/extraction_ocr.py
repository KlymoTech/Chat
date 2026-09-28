"""Tesseract OCR as a third, independent reading of each rendered source page.

The PDF text layer, OCR and the vision model fail in different ways (broken font encodings,
glyph misreads, hallucinated values). OCR runs locally and deterministically, and returns the
pixel position and confidence of every word, so each region gets an OCR candidate that can be
compared with the other two readers.
"""

from __future__ import annotations

import asyncio
import io
from typing import Any

from PIL import Image, ImageChops, ImageFilter, ImageOps, ImageStat

from northstar_api.config import Settings

OCR_ENGINE = "tesseract"


def _run_tesseract(image: bytes, language: str) -> dict[str, Any]:
    import pytesseract  # type: ignore[import-untyped]

    with Image.open(io.BytesIO(image)) as bitmap:
        data = pytesseract.image_to_data(
            bitmap.convert("RGB"),
            lang=language,
            # psm 3: automatic page segmentation; preserve_interword_spaces keeps table columns apart.
            config="--oem 1 --psm 3 -c preserve_interword_spaces=1",
            output_type=pytesseract.Output.DICT,
        )
        version = str(pytesseract.get_tesseract_version())
    words = []
    for index, text in enumerate(data["text"]):
        text = (text or "").strip()
        confidence = float(data["conf"][index])
        if not text or confidence < 0:
            continue
        left, top = int(data["left"][index]), int(data["top"][index])
        words.append(
            {
                "text": text,
                "bbox_px": [left, top, left + int(data["width"][index]), top + int(data["height"][index])],
                "confidence": round(confidence, 1),
                # Tesseract's own reading order: block, paragraph, line, word.
                "line": [int(data["block_num"][index]), int(data["par_num"][index]), int(data["line_num"][index])],
                "order": index,
            }
        )
    return {"engine": OCR_ENGINE, "version": version, "language": language, "status": "complete", "words": words}


async def ocr_page(image: bytes, settings: Settings) -> dict[str, Any]:
    """Never raises: an unavailable OCR engine leaves the other two readers in charge."""
    if not settings.extraction_ocr_enabled:
        return {"engine": OCR_ENGINE, "status": "disabled", "words": []}
    try:
        async with asyncio.timeout(settings.extraction_ocr_timeout_seconds):
            return await asyncio.to_thread(_run_tesseract, image, settings.extraction_ocr_language)
    except Exception as exc:
        return {"engine": OCR_ENGINE, "status": "unavailable", "error": type(exc).__name__, "words": []}


def _run_region(image: bytes, box: list[int], language: str) -> dict[str, Any]:
    import pytesseract

    with Image.open(io.BytesIO(image)) as bitmap:
        x0, y0, x1, y1 = box
        crop = bitmap.convert("L").crop((x0, y0, x1, y1))
    # Light text on a dark band (table headers, callouts) defeats OCR. Invert dark bands locally,
    # strip by strip, so a table's white-on-green header and its dark-on-white rows both read.
    strip = 4
    for top in range(0, crop.height, strip):
        band = crop.crop((0, top, crop.width, min(crop.height, top + strip)))
        if ImageStat.Stat(band).median[0] < 128:  # median = background; letters are a minority
            crop.paste(ImageOps.invert(band), (0, top))
    crop = crop.resize((crop.width * 2, crop.height * 2), Image.Resampling.LANCZOS)
    # Adaptive threshold: a pixel is ink when it is darker than its own neighbourhood. Scans have
    # uneven backgrounds (inverted headers are grey, pages are white), which defeat one global cut.
    local = crop.filter(ImageFilter.BoxBlur(25))
    crop = ImageChops.subtract(local, crop).point(lambda darker: 0 if darker > 12 else 255)
    data = pytesseract.image_to_data(crop, lang=language, config="--oem 1 --psm 6", output_type=pytesseract.Output.DICT)
    words = []
    for index, text in enumerate(data["text"]):
        text = (text or "").strip()
        if not text or float(data["conf"][index]) < 0:
            continue
        word_left: float = int(data["left"][index]) / 2 + x0
        word_top: float = int(data["top"][index]) / 2 + y0
        words.append({
            "text": text,
            "bbox_px": [round(word_left), round(word_top), round(word_left + int(data["width"][index]) / 2),
                        round(word_top + int(data["height"][index]) / 2)],
            "confidence": round(float(data["conf"][index]), 1),
            "line": [int(data["block_num"][index]), int(data["par_num"][index]), int(data["line_num"][index])],
            "order": index,
        })
    return {"text": lines_text(words), "words": words}


async def ocr_region(image: bytes, box: list[int], settings: Settings) -> dict[str, Any] | None:
    """Second, region-level OCR pass (cropped, contrast-corrected, 2x) with page-coordinate words."""
    if not settings.extraction_ocr_enabled:
        return None
    try:
        async with asyncio.timeout(settings.extraction_ocr_timeout_seconds):
            return await asyncio.to_thread(_run_region, image, box, settings.extraction_ocr_language)
    except Exception:
        return None


def lines_text(words: list[dict[str, Any]]) -> str:
    """Join words into their source lines, keeping the reader's line breaks."""
    lines: list[list[str]] = []
    current: object = None
    for word in sorted(words, key=lambda w: w.get("order", 0)):
        key = tuple(word.get("line") or ())
        if key != current or not lines:
            lines.append([])
            current = key
        lines[-1].append(word["text"])
    return "\n".join(" ".join(line) for line in lines)
