"""Native source candidates. These functions do not invoke or configure a model."""
from __future__ import annotations

import codecs
import hashlib
import json
import re
from typing import TYPE_CHECKING, Any

import fitz

if TYPE_CHECKING:
    from northstar_api.config import Settings


def configuration(settings: Settings) -> dict[str, Any]:
    values = {key: value for key, value in settings.model_dump().items() if key.startswith("extraction_")}
    for key in ("upload_max_bytes", "knowledge_max_pdf_pages", "knowledge_max_docx_uncompressed_bytes", "knowledge_max_extracted_characters"):
        values[key] = getattr(settings, key)
    return values


def text_unit(data: bytes) -> dict[str, Any]:
    encoding, bom = "utf-8", b""
    for marker, codec in ((codecs.BOM_UTF32_LE, "utf-32-le"), (codecs.BOM_UTF32_BE, "utf-32-be"),
                          (codecs.BOM_UTF8, "utf-8"), (codecs.BOM_UTF16_LE, "utf-16-le"), (codecs.BOM_UTF16_BE, "utf-16-be")):
        if data.startswith(marker):
            encoding, bom = codec, marker
            break
    text = data[len(bom):].decode(encoding, errors="strict")
    offset = len(bom)
    lines = []
    for number, line in enumerate(text.splitlines(keepends=True), 1):
        size = len(line.encode(encoding))
        lines.append({"number": number, "byte_start": offset, "byte_end": offset + size, "text": line})
        offset += size
    return {"number": 1, "source_page_index": None, "source_page_number": None, "rendered_page_number": None,
            "source_unit": "bytes", "native_text": text, "visual_text": None, "selected_text": text,
            "image": None, "requires_image": False, "encoding": encoding, "bom_hex": bom.hex(),
            "line_endings": sorted(set(re.findall(r"\r\n|\r|\n", text))), "lines": lines,
            "line_byte_offsets": [line["byte_start"] for line in lines], "blocks": [], "blank": not text,
            "inventory_complete": True}


def native_pdf(page: Any, scale: float) -> dict[str, Any]:
    blocks, words = [], []

    def box(value: Any) -> list[int]:
        rect = fitz.Rect(value) * page.rotation_matrix
        return [max(0, round(coordinate * scale)) for coordinate in rect]

    for index, value in enumerate(page.get_text("dict")["blocks"]):
        if value["type"] == 0:
            spans = [span for line in value["lines"] for span in line["spans"]]
            blocks.append({"id": f"N{index:04d}", "type": "text", "bbox_pt": list(value["bbox"]),
                           "bbox_px": box(value["bbox"]),
                           "text": "\n".join("".join(span["text"] for span in line["spans"]) for line in value["lines"]),
                           "spans": spans})
        else:
            blocks.append({"id": f"N{index:04d}", "type": "figure", "bbox_pt": list(value["bbox"]),
                           "bbox_px": box(value["bbox"]), "text": "",
                           "image_sha256": hashlib.sha256(value.get("image", b"")).hexdigest()})
    for word in page.get_text("words"):
        words.append({"bbox_px": box(word[:4]), "text": word[4], "line": [word[5], word[6]]})
    tables = []
    try:
        for table in page.find_tables().tables:
            tables.append({"bbox_px": box(table.bbox), "row_count": table.row_count, "column_count": table.col_count,
                           "rows": table.extract(), "cell_bboxes_pt": table.cells, "header": table.header.names})
        table_error = None
    except Exception as exc:
        table_error = type(exc).__name__
    annotations = [{"type": annotation.type, "rect": list(annotation.rect), "bbox_px": box(annotation.rect), "info": annotation.info}
                   for annotation in page.annots() or []]
    widgets = [{"name": widget.field_name, "value": widget.field_value, "rect": list(widget.rect), "bbox_px": box(widget.rect)}
               for widget in page.widgets() or []]
    result = {"native_blocks": blocks, "native_words": words, "native_tables": tables, "native_table_error": table_error,
            "annotations": annotations, "form_fields": widgets, "rotation": page.rotation,
            "source_width_pt": page.rect.width, "source_height_pt": page.rect.height,
            "media_box_pt": list(page.mediabox), "crop_box_pt": list(page.cropbox),
            "rotation_matrix": list(page.rotation_matrix), "render_scale": scale,
            "coordinate_spaces": {"native": "PDF_POINTS", "rendered": "IMAGE_PIXELS"}}
    # Normalize parser tuples at the adapter boundary, not during later exports.
    return json.loads(json.dumps(result, ensure_ascii=False, allow_nan=False))


def inside(inner: list[float], outer: list[float]) -> bool:
    return outer[0] <= (inner[0] + inner[2]) / 2 <= outer[2] and outer[1] <= (inner[1] + inner[3]) / 2 <= outer[3]
