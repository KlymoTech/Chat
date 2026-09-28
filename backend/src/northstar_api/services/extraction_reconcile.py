"""Three-reader reconciliation of one region: PDF text layer, OCR and the vision model.

A region's text is accepted automatically only when two independent readers agree (with OCR
allowed only its known look-alike glyph confusions when confirming the text layer). Otherwise the
region gets the most reliable draft plus a reviewable issue. Tables are reconciled cell by cell.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Awaitable, Callable, Sequence
from typing import Any

from northstar_api.config import Settings
from northstar_api.services.extraction_ocr import lines_text, ocr_region
from northstar_api.services.extraction_tables import table_grid, table_text
from northstar_api.services.extraction_validation import (
    disagreement,
    equivalent_text,
    ocr_confirms,
    same_text,
)

Issue = Callable[..., None]
LOOKALIKE_NOTE = " apart from OCR look-alike characters (1/l, 0/O, ×/x)"


def inside(inner: Sequence[float], outer: Sequence[float]) -> bool:
    return (
        outer[0] <= (inner[0] + inner[2]) / 2 <= outer[2]
        and outer[1] <= (inner[1] + inner[3]) / 2 <= outer[3]
    )


def block_style(page: dict[str, Any], block: dict[str, Any]) -> dict[str, Any] | None:
    """The region's dominant PDF text style, so the editor can render it like the source."""
    scale = page.get("render_scale") or 1
    weights: Counter[tuple[float, bool, bool, int, str]] = Counter()
    for native in page.get("native_blocks", []):
        if native.get("type") != "text" or not inside(native["bbox_px"], block["bbox_px"]):
            continue
        for span in native.get("spans", []):
            text = (span.get("text") or "").strip()
            if text:
                flags = int(span.get("flags", 0))
                key = (round(float(span.get("size", 0)) * scale, 1), bool(flags & 16), bool(flags & 2),
                       int(span.get("color", 0)), str(span.get("font", "")))
                weights[key] += len(text)
    if not weights:
        return None
    size, bold, italic, color, font = weights.most_common(1)[0][0]
    lines: dict[tuple[Any, ...], list[float]] = {}
    for word in page.get("native_words", []):
        if inside(word["bbox_px"], block["bbox_px"]):
            key = tuple(word.get("line") or ())
            x0, x1 = word["bbox_px"][0], word["bbox_px"][2]
            lines[key] = [min(lines[key][0], x0), max(lines[key][1], x1)] if key in lines else [x0, x1]
    align = "left"
    if len(lines) >= 1:
        left, right = block["bbox_px"][0], block["bbox_px"][2]
        width = max(1, right - left)
        starts = [s - left for s, _ in lines.values()]
        ends = [right - e for _, e in lines.values()]
        if all(abs(a - b) < 0.04 * width for a, b in zip(starts, ends, strict=True)) and min(starts) > 0.08 * width:
            align = "center"
        elif max(ends) - min(ends) < 0.02 * width and max(starts) - min(starts) > 0.05 * width:
            align = "right"
    return {"font_size_px": size, "bold": bold or "bold" in font.lower(), "italic": italic,
            "color": f"#{color:06x}", "font": font, "align": align}


def body_font_px(page: dict[str, Any]) -> float | None:
    """The page's most common text size (by characters): the baseline for spotting headings."""
    if "body_font_px" not in page:
        sizes: Counter[float] = Counter()
        scale = page.get("render_scale") or 1
        for native in page.get("native_blocks", []):
            for span in native.get("spans", []):
                sizes[round(float(span.get("size", 0)) * scale, 1)] += len((span.get("text") or "").strip())
        page["body_font_px"] = sizes.most_common(1)[0][0] if sizes else None
    value = page["body_font_px"]
    return float(value) if value is not None else None


def mark_heading(block: dict[str, Any], page: dict[str, Any]) -> None:
    """Short text that is clearly larger than body text, or a short bold line, is a heading."""
    style, body = block.get("style"), body_font_px(page)
    structure = block.get("proposed_structure")
    text = block.get("selected_text") or ""
    if not style or not body or not structure or block["type"] not in {"paragraph", "unknown"}:
        return
    words, lines = len(text.split()), text.count("\n") + 1
    larger = style["font_size_px"] >= 1.18 * body
    if words and words <= 16 and lines <= 2 and (larger or (style["bold"] and style["font_size_px"] >= body)):
        ratio = style["font_size_px"] / body
        level = 1 if ratio >= 1.7 else 2 if ratio >= 1.18 else 3
        block["type"] = structure["kind"] = "heading"
        block["heading_level"] = level


def needs_vision(page: dict[str, Any], box: list[int]) -> bool:
    """Whether a region still needs the vision model: not when the PDF text layer and OCR already
    agree (2 of 3 is met; a third reading adds cost and failure modes, not accuracy)."""
    words = [w for w in page.get("native_words", []) if inside(w["bbox_px"], box)]
    ocr_words = [w for w in page.get("ocr_words", []) if inside(w["bbox_px"], box)]
    if not words or not ocr_words:
        return True  # images, charts, scans: vision is one of only two readers
    grid = table_grid(words)
    if grid:
        for cell in grid["cells"]:
            if not cell["text"]:
                continue
            x0, y0, x1, y1 = cell["bbox_px"]
            pad = 0.35 * (y1 - y0)
            seen = lines_text([w for w in ocr_words if inside(w["bbox_px"], [x0 - pad, y0 - pad, x1 + pad, y1 + pad])])
            if not ocr_confirms(cell["text"], seen):
                return True
        return False
    return not ocr_confirms(" ".join(w["text"] for w in words), lines_text(ocr_words))


def _clean_cells(cells: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Grid cells in the review schema: explicit BLANK cells and header references."""
    headers = {c["column"]: c for c in cells if c.get("header")}

    def header_for(column: int) -> str | None:
        for start, cell in headers.items():
            if start <= column < start + cell.get("column_span", 1):
                return f"R{cell['row']}C{start}"
        return None

    result = []
    for cell in cells:
        text = cell.get("text") or ""
        ref = None if cell.get("header") or not text else header_for(cell["column"])
        result.append({
            "row": cell["row"], "column": cell["column"], "row_span": cell.get("row_span", 1),
            "column_span": cell.get("column_span", 1), "text": text, "state": "VALUE" if text else "BLANK",
            "header": bool(cell.get("header")), "header_refs": [ref] if ref else [],
        })
    return result


async def reconcile_block(
    block: dict[str, Any],
    page: dict[str, Any],
    image: bytes,
    settings: Settings,
    issue: Issue,
    region_ocr: Callable[[bytes, list[int], Settings], Awaitable[dict[str, Any] | None]] | None = None,
    *,
    trusted_text_layer: bool = False,
) -> bool:
    """Settle one leaf region. Returns True when the region no longer depends on a vision reading
    (so a failed vision call for it is not a release blocker)."""
    settled = await _reconcile(block, page, image, settings, issue, region_ocr, trusted_text_layer)
    mark_heading(block, page)
    if block.get("consensus") and block.get("selected_text") is not None:
        # The text two independent readers agreed on, kept as evidence next to what a reviewer saves.
        block["reader_text"] = block["selected_text"]
    return settled


async def _reconcile(
    block: dict[str, Any],
    page: dict[str, Any],
    image: bytes,
    settings: Settings,
    issue: Issue,
    region_ocr: Callable[[bytes, list[int], Settings], Awaitable[dict[str, Any] | None]] | None,
    trusted_text_layer: bool,
) -> bool:
    region_ocr = region_ocr or ocr_region  # looked up per call so it can be replaced in tests
    number = page["number"]
    words = [w for w in page.get("native_words", []) if inside(w["bbox_px"], block["bbox_px"])]
    ocr_words = [w for w in page.get("ocr_words", []) if inside(w["bbox_px"], block["bbox_px"])]
    block["native_text"] = " ".join(w["text"] for w in words)
    block["ocr_text"] = lines_text(ocr_words)
    block["ocr_min_confidence"] = min((w["confidence"] for w in ocr_words), default=None)
    if style := block_style(page, block):
        block["style"] = style
    reading = block.get("visual")
    block["readers"] = {"native_text_layer": bool(words), "ocr": bool(ocr_words), "vision": reading is not None}
    if reading:
        block["original_printed_label"] = reading.get("printed_label")
        for cell in reading.get("cells", []):
            cell["cell_id"] = f"{block['id']}-R{cell['row']}C{cell['column']}"
    ocr_ready = page.get("ocr", {}).get("status") == "complete"
    if not words and ocr_ready and not trusted_text_layer:
        # No text layer (a scan): OCR is the main reader, so also read the region on its own
        # (cropped, contrast-corrected, 2x) and keep whichever pass read it with more confidence.
        # Both passes are the same engine, so this improves the draft; it is never a second vote.
        recovered = await region_ocr(image, block["bbox_px"], settings)
        if recovered and recovered.get("words") and _confidence(recovered["words"]) > _confidence(ocr_words):
            block["ocr_page_text"] = block["ocr_text"]
            ocr_words = recovered["words"]
            block["ocr_text"] = lines_text(ocr_words)
            block["ocr_source"] = "region_pass"
            block["ocr_min_confidence"] = min((w["confidence"] for w in ocr_words), default=None)
            block["readers"]["ocr"] = True

    grid = table_grid(words) if words else table_grid(ocr_words) if ocr_words else None
    if trusted_text_layer and words:
        # A clean text layer (no vision or review needed for this page): its words are the text.
        if grid:
            block["type"] = "table"
            block["native_table"] = grid
            text = table_text(grid)
            structure = {"kind": "table", "text": text, "cells": _clean_cells(grid["cells"]), "complete": True}
        else:
            text = lines_text(words)
            structure = {"kind": block["type"], "text": text, "complete": True}
        block.update(status="candidate", selected_text=text, consensus="text_layer", proposed_structure=structure)
        return True
    if trusted_text_layer:
        is_figure = block["type"] == "figure"
        block.update(status="candidate", selected_text="", consensus="text_layer", proposed_structure={
            "kind": "figure" if is_figure else "unknown", "text": "", "complete": True, "blank": not is_figure})
        if not is_figure:
            block["type"] = "unknown"
        return True
    if grid:
        return await _reconcile_table(block, page, image, settings, issue, region_ocr, grid,
                                      from_text_layer=bool(words), ocr_words=ocr_words, ocr_ready=ocr_ready)

    native_text, ocr_text = block["native_text"], block["ocr_text"]
    vision_text = reading["text"] if reading else None
    native_ocr = bool(native_text and ocr_text) and ocr_confirms(native_text, ocr_text)
    vision_agrees = bool(native_text and vision_text) and same_text(native_text, vision_text or "")
    if native_text and not native_ocr and not vision_agrees and ocr_ready:
        # Page-level OCR misses light-on-dark bands and small print; retry the region alone.
        recovered = await region_ocr(image, block["bbox_px"], settings)
        if recovered and recovered.get("text"):
            block["ocr_region_text"] = recovered["text"]
            native_ocr = ocr_confirms(native_text, recovered["text"])
    block["agreement"] = vision_agrees

    if vision_text is not None and (vision_agrees or (not native_text and ocr_text and equivalent_text(ocr_text, vision_text))):
        block["selected_text"] = vision_text
        block["consensus"] = "native_vision" if vision_agrees else "ocr_vision"
        return True
    if native_ocr:
        # 2 of 3: text layer and OCR agree; the vision reading is the outlier or missing.
        text = lines_text(words)
        block.update(selected_text=text, consensus="native_ocr", status="candidate" if not reading else block["status"])
        block["proposed_structure"] = {"kind": (reading or {}).get("kind") or block["type"], "text": text, "complete": True}
        confirming = block.get("ocr_region_text") or ocr_text
        block["audit_notes"] = [
            ("A region-level OCR pass" if block.get("ocr_region_text") else "OCR") + " confirms the PDF text layer"
            + ("" if equivalent_text(native_text, confirming) else LOOKALIKE_NOTE) + "; the PDF text is kept. "
            + ("The vision reading differed and was not used." if reading else "No vision reading was needed.")
        ]
        return True
    if native_text and vision_text is not None:
        # No majority: the reviewer decides, drafting from the text layer (exact characters).
        block["proposed_structure"] = {"kind": reading["kind"] if reading else block["type"],
                                       "text": lines_text(words), "complete": True}
        issue(number, disagreement(native_text, vision_text),
              "PDF text, OCR and vision readings differ" if ocr_text else "Native and visual region candidates differ",
              block["id"])
        return True
    if reading is None and not native_text and not ocr_words and _blank_split_piece(block, page):
        block.update(status="candidate", selected_text="", consensus="native_ocr",
                     proposed_structure={"kind": "unknown", "text": "", "complete": True, "blank": True},
                     audit_notes=["Blank margin of a split region: no words in the PDF text layer or OCR."])
        return True
    if reading is None and (native_text or ocr_text):
        text = lines_text(words) if native_text else ocr_text
        block.update(status="candidate", proposed_structure={"kind": block["type"], "text": text, "complete": True})
        other = block.get("ocr_region_text") or ocr_text
        issue(
            number,
            disagreement(native_text, other) if native_text and other else "SINGLE_READER",
            ("Vision did not read this region and OCR does not confirm the PDF text" if native_text and other
             else "Only " + ("the PDF text layer" if native_text else "OCR") + " read this region")
            + "; check it against the original",
            block["id"],
        )
        return True
    if reading is None and block.get("status") == "unread":
        # Vision was not used and no reader found text: an image or empty area to confirm by eye.
        is_figure = block["type"] == "figure"
        block.update(status="candidate", proposed_structure={
            "kind": "figure" if is_figure else "unknown", "text": "", "complete": True, "blank": not is_figure})
        issue(number, "SINGLE_READER",
              "No reader found text here; confirm against the original that nothing is missing", block["id"])
        return True
    return False


def _confidence(words: list[dict[str, Any]]) -> float:
    """Confidently read characters. Rewards reading more of the region well: an average would
    favour a pass that skipped the hard parts (e.g. a white-on-dark header) entirely."""
    return float(sum(len(w["text"]) * w["confidence"] / 100 for w in words if w["confidence"] >= 60))


def _blank_split_piece(block: dict[str, Any], page: dict[str, Any]) -> bool:
    parent = next((b for b in page["blocks"] if b["id"] == block.get("parent_id")), None)
    if parent is None:
        return False
    return any(inside(w["bbox_px"], parent["bbox_px"]) for w in page.get("native_words", []))


async def _reconcile_table(
    block: dict[str, Any],
    page: dict[str, Any],
    image: bytes,
    settings: Settings,
    issue: Issue,
    region_ocr: Callable[[bytes, list[int], Settings], Awaitable[dict[str, Any] | None]],
    grid: dict[str, Any],
    *,
    from_text_layer: bool,
    ocr_words: list[dict[str, Any]],
    ocr_ready: bool,
) -> bool:
    number = page["number"]
    reading = block.get("visual")
    block["type"] = "table"
    block["native_table" if from_text_layer else "ocr_table"] = grid
    text = table_text(grid)
    structure = {"kind": "table", "text": text, "cells": _clean_cells(grid["cells"]), "complete": True}
    block["proposed_structure"] = structure
    block["status"] = "candidate" if not reading else block["status"]

    unconfirmed: list[dict[str, Any]] = []
    if from_text_layer and ocr_ready:
        pad = 0.35 * max(1.0, min(b - a for a, b in grid["row_bounds"]))
        columns = grid["column_bounds"]

        def cell_box(cell: dict[str, Any]) -> list[float]:
            # Column bounds come from data rows; a header can stick out past its (right-aligned)
            # column, so the cell's own words widen the box.
            span = columns[cell["column"]: cell["column"] + cell.get("column_span", 1)]
            y0, y1 = grid["row_bounds"][cell["row"]]
            own = cell.get("bbox_px") or [span[0][0], y0, span[-1][1], y1]
            return [min(own[0], *(c[0] for c in span)) - pad, y0 - pad,
                    max(own[2], *(c[1] for c in span)) + pad, y1 + pad]

        def check(pool: list[dict[str, Any]]) -> list[dict[str, Any]]:
            results = []
            for cell in grid["cells"]:
                if not cell["text"]:
                    continue
                seen = lines_text([w for w in pool if inside(w["bbox_px"], cell_box(cell))])
                results.append({"row": cell["row"], "column": cell["column"], "pdf": cell["text"], "ocr": seen,
                                "confirmed": ocr_confirms(cell["text"], seen)})
            return results

        checks = check(ocr_words)
        if any(not c["confirmed"] for c in checks):
            recovered = await region_ocr(image, block["bbox_px"], settings)
            if recovered and recovered.get("words"):
                again = {(c["row"], c["column"]): c for c in check(recovered["words"])}
                for c in checks:
                    retry = again.get((c["row"], c["column"]))
                    if not c["confirmed"] and retry and retry["confirmed"]:
                        c.update(ocr=retry["ocr"], confirmed=True, region_pass=True)
        block["cell_checks"] = checks
        unconfirmed = [c for c in checks if not c["confirmed"]]
        if not unconfirmed:
            block.update(selected_text=text, consensus="native_ocr")
            block["audit_notes"] = [f"OCR confirms all {len(checks)} table cells of the PDF text layer; the PDF values are kept."]
            return True
    if from_text_layer and reading and same_text(block["native_text"], reading["text"]):
        block.update(selected_text=text, consensus="native_vision")
        return True
    if unconfirmed:
        shown = "; ".join(f"R{c['row'] + 1}C{c['column'] + 1} PDF '{c['pdf']}' vs OCR '{c['ocr'] or 'nothing'}'"
                          for c in unconfirmed[:4])
        more = f" and {len(unconfirmed) - 4} more" if len(unconfirmed) > 4 else ""
        issue(number, disagreement(" ".join(c["pdf"] for c in unconfirmed), " ".join(c["ocr"] for c in unconfirmed)),
              f"{len(unconfirmed)} table cell{'s' if len(unconfirmed) != 1 else ''} differ: {shown}{more}", block["id"])
    else:
        issue(number, "SINGLE_READER",
              "Table read by " + ("the PDF text layer" if from_text_layer else "OCR") + " only; check the cells against the original",
              block["id"])
    return True
