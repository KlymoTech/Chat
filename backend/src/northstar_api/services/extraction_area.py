"""Extract only the part of a page a reviewer selects.

The reviewer draws a box on the original page; this reads just that box with the same readers
as the pipeline — the PDF text layer, a region-level OCR pass and, on request, the vision model —
and suggests text with the same 2-of-3 rule. Nothing is stored here: the reviewer places the
result into the page editor, and it is saved through the normal audited page review.
"""

from __future__ import annotations

from typing import Any

from northstar_api.config import Settings
from northstar_api.services.extraction_ocr import lines_text, ocr_region
from northstar_api.services.extraction_reconcile import inside
from northstar_api.services.extraction_regions import READING_PROMPT, crop_image
from northstar_api.services.extraction_schema import Reading, parse_response
from northstar_api.services.extraction_tables import table_grid, table_text
from northstar_api.services.extraction_validation import equivalent_text, ocr_confirms, same_text
from northstar_api.services.vision import read_evidence

MIN_AREA_PX = 8


def suggest(pdf_text: str, ocr_text: str, vision_text: str | None) -> dict[str, Any]:
    """The text to offer, and how well independent readers back it (same rule as the pipeline)."""
    if pdf_text and ocr_text and ocr_confirms(pdf_text, ocr_text):
        return {"text": pdf_text, "source": "pdf_text_confirmed_by_ocr", "confirmed": True}
    if pdf_text and vision_text and same_text(pdf_text, vision_text):
        return {"text": pdf_text, "source": "pdf_text_confirmed_by_vision", "confirmed": True}
    if not pdf_text and ocr_text and vision_text and equivalent_text(ocr_text, vision_text):
        return {"text": vision_text, "source": "ocr_confirmed_by_vision", "confirmed": True}
    if pdf_text:
        return {"text": pdf_text, "source": "pdf_text_unconfirmed", "confirmed": False}
    if vision_text:
        return {"text": vision_text, "source": "vision_only", "confirmed": False}
    if ocr_text:
        return {"text": ocr_text, "source": "ocr_only", "confirmed": False}
    return {"text": "", "source": "nothing_read", "confirmed": False}


def _clamp(box: list[float], page: dict[str, Any]) -> list[int]:
    width, height = int(page.get("width_px") or 0), int(page.get("height_px") or 0)
    x0, y0, x1, y1 = (round(v) for v in box)
    x0, x1 = sorted((max(0, min(width, x0)), max(0, min(width, x1))))
    y0, y1 = sorted((max(0, min(height, y0)), max(0, min(height, y1))))
    if x1 - x0 < MIN_AREA_PX or y1 - y0 < MIN_AREA_PX:
        raise ValueError("Select a larger area of the page")
    return [x0, y0, x1, y1]


async def extract_area(
    page: dict[str, Any],
    image: bytes,
    box: list[float],
    settings: Settings,
    *,
    cells: list[dict[str, Any]] | None = None,
    use_vision: bool = False,
) -> dict[str, Any]:
    area = _clamp(box, page)
    words = [w for w in page.get("native_words", []) if inside(w["bbox_px"], area)]
    pdf_text = lines_text(words)
    recovered = await ocr_region(image, area, settings)
    ocr_words = (recovered or {}).get("words") or [w for w in page.get("ocr_words", []) if inside(w["bbox_px"], area)]
    ocr_text = lines_text(ocr_words)

    vision_text: str | None = None
    vision_status = "not_requested"
    if use_vision:
        try:
            evidence = await read_evidence(crop_image(image, area), settings, READING_PROMPT)
            if evidence.get("finish_reason") != "stop":
                raise ValueError("incomplete")
            try:
                reading = parse_response(evidence.get("raw"), Reading)
                assert isinstance(reading, Reading)
                vision_text, vision_status = str(reading.text), "complete"
            except ValueError:
                # Charts and diagrams often get a plain-text answer instead of JSON. A reviewer
                # sees it before placing anything, so keep it, clearly marked as unstructured.
                raw = evidence.get("raw")
                if not isinstance(raw, str) or not raw.strip():
                    raise
                vision_text, vision_status = raw.strip(), "complete_unstructured"
        except Exception as exc:  # the other readers still answer
            vision_status = f"failed:{type(exc).__name__}"

    result: dict[str, Any] = {
        "page": page["number"],
        "bbox_px": area,
        "readings": {
            "pdf_text": pdf_text,
            "ocr": ocr_text,
            "ocr_min_confidence": min((w["confidence"] for w in ocr_words if "confidence" in w), default=None),
            "ocr_status": "complete" if recovered else "unavailable",
            "vision": vision_text,
            "vision_status": vision_status,
        },
        "suggestion": suggest(pdf_text, ocr_text, vision_text),
        "words": [{"text": w["text"], "bbox_px": w["bbox_px"]} for w in words],
        "table": None,
        "cells": [],
    }
    grid = table_grid(words) if words else table_grid(ocr_words) if ocr_words else None
    if grid:
        result["table"] = {"text": table_text(grid), "rows": grid["rows"], "columns": grid["columns"],
                           "cells": [{k: c[k] for k in ("row", "column", "text", "header", "column_span")} for c in grid["cells"]]}
    for cell in cells or []:
        cell_box = [float(v) for v in cell["bbox_px"]]
        cell_pdf = lines_text([w for w in page.get("native_words", []) if inside(w["bbox_px"], cell_box)])
        cell_ocr = lines_text([w for w in ocr_words if inside(w["bbox_px"], cell_box)])
        result["cells"].append({"row": cell["row"], "column": cell["column"], "pdf_text": cell_pdf, "ocr": cell_ocr,
                                "suggestion": suggest(cell_pdf, cell_ocr, None)})
    return result
