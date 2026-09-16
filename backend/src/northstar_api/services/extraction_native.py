"""Bounded parser subprocess protocol. No model credentials enter this process."""
from __future__ import annotations

import asyncio
import base64
import io
import json
import math
import os
import subprocess
import sys
from contextlib import redirect_stdout
from typing import TYPE_CHECKING, Any

from northstar_api.services.extraction_evidence import sha256

if TYPE_CHECKING:
    from northstar_api.config import Settings


def native_pdf(page: Any, scale: float) -> dict[str, Any]:
    import fitz
    blocks, words, tables = [], [], []
    width, height = math.ceil(page.rect.width * scale), math.ceil(page.rect.height * scale)
    def box(value: Any) -> list[int]:
        rect = fitz.Rect(value) * page.rotation_matrix
        return [max(0, min(width, math.floor(rect.x0 * scale))),
                max(0, min(height, math.floor(rect.y0 * scale))),
                max(0, min(width, math.ceil(rect.x1 * scale))),
                max(0, min(height, math.ceil(rect.y1 * scale)))]
    for index, value in enumerate(page.get_text("dict")["blocks"]):
        identity = f"N{index:04d}"
        if value["type"] == 0:
            blocks.append({"id": identity, "type": "text", "bbox_pt": list(value["bbox"]),
                "bbox_px": box(value["bbox"]), "text": "\n".join("".join(s["text"] for s in line["spans"]) for line in value["lines"]),
                "spans": [span for line in value["lines"] for span in line["spans"]]})
        else:
            blocks.append({"id": identity, "type": "figure", "bbox_pt": list(value["bbox"]),
                "bbox_px": box(value["bbox"]), "text": "", "image_sha256": sha256(value.get("image", b""))})
    for word in page.get_text("words"):
        words.append({"bbox_px": box(word[:4]), "text": word[4], "line": [word[5], word[6]],
                      "source_word_order": len(words)})
    try:
        for table in page.find_tables().tables:
            tables.append({"bbox_px": box(table.bbox), "row_count": table.row_count,
                           "column_count": table.col_count, "rows": table.extract(),
                           "cell_bboxes_pt": table.cells, "header": table.header.names})
        table_error = None
    except Exception as exc:
        table_error = type(exc).__name__
    return {"native_blocks": blocks, "native_words": words, "native_tables": tables,
            "native_table_error": table_error,
            "annotations": [{"type": a.type, "rect": list(a.rect), "info": a.info} for a in page.annots() or []],
            "form_fields": [{"name": w.field_name, "value": w.field_value, "rect": list(w.rect)} for w in page.widgets() or []],
            "links": page.get_links(), "rotation": page.rotation,
            "source_width_pt": page.rect.width, "source_height_pt": page.rect.height,
            "source_cropbox_pt": list(page.cropbox), "source_mediabox_pt": list(page.mediabox),
            "render_scale": scale, "coordinate_system": "top_left_pixels_after_pdf_rotation",
            "source_to_render": {"rotation_matrix": list(page.rotation_matrix), "scale": scale}}


def _execute(data: bytes, operation: str, settings: Settings, page: int | None) -> dict[str, Any]:
    config = {"operation": operation, "page": page, "dpi": settings.extraction_render_dpi,
              "pixels": settings.extraction_max_image_pixels, "input_limit": settings.upload_max_bytes,
              "characters": settings.knowledge_max_extracted_characters,
              "page_limit": settings.knowledge_max_pdf_pages}
    environment = {key: value for key, value in os.environ.items() if key in {
        "PATH", "PYTHONPATH", "SYSTEMROOT", "WINDIR", "VIRTUAL_ENV", "LD_LIBRARY_PATH"}}
    environment.update(LANG="C.UTF-8", LC_ALL="C.UTF-8", PYTHONIOENCODING="utf-8")
    result = subprocess.run([sys.executable, "-m", "northstar_api.services.extraction_native"],
        input=json.dumps(config).encode() + b"\n" + data, capture_output=True,
        timeout=90, check=False, env=environment)  # noqa: S603
    if result.returncode != 0:
        raise ValueError("NATIVE_PARSER_PROCESS_FAILED")
    if len(result.stdout) > settings.extraction_max_evidence_bytes:
        raise ValueError("NATIVE_PARSER_OUTPUT_LIMIT")
    value = json.loads(result.stdout)
    if value.get("error"):
        raise ValueError(value["error"])
    return value


async def pdf_info(data: bytes, settings: Settings) -> dict[str, Any]:
    return await asyncio.to_thread(_execute, data, "info", settings, None)


async def pdf_page(data: bytes, index: int, settings: Settings) -> tuple[bytes, str, dict[str, Any]]:
    result = await asyncio.to_thread(_execute, data, "page", settings, index)
    return base64.b64decode(result["image"], validate=True), result["text"], result["details"]


def _worker() -> None:
    # This is a resource-limited process boundary, not a claim of an OS security
    # sandbox. Deploy untrusted parsers in a network-isolated, read-only container.
    if os.name == "posix":
        import resource
        resource.setrlimit(resource.RLIMIT_CPU, (75, 80))
        resource.setrlimit(resource.RLIMIT_AS, (3 * 1024**3, 3 * 1024**3))
        resource.setrlimit(resource.RLIMIT_FSIZE, (0, 0))
    config = json.loads(sys.stdin.buffer.readline(4096))
    data = sys.stdin.buffer.read(min(int(config["input_limit"]), 512 * 1024**2) + 1)
    if len(data) > config["input_limit"]:
        raise ValueError("SOURCE_LIMIT")
    from pypdf import PdfReader
    reader = PdfReader(io.BytesIO(data))
    if config["operation"] == "info":
        if reader.is_encrypted:
            result = {"encrypted": True, "count": 0, "labels": []}
        else:
            count = len(reader.pages)
            if count > config["page_limit"]:
                raise ValueError("PAGE_LIMIT")
            result = {"encrypted": False, "count": count, "labels": reader.page_labels}
    elif config["operation"] == "page":
        import fitz
        index = int(config["page"])
        with fitz.open(stream=data, filetype="pdf") as document:
            if len(document) != len(reader.pages):
                raise ValueError("PAGE_COUNT_CONFLICT")
            page = document[index]
            scale = min(config["dpi"] / 72, math.sqrt(config["pixels"] / max(1, page.rect.width * page.rect.height)))
            bitmap = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
            text = reader.pages[index].extract_text() or ""
            if len(text) > config["characters"]:
                raise ValueError("TEXT_LIMIT")
            with redirect_stdout(sys.stderr):
                details = native_pdf(page, scale)
            result = {"image": base64.b64encode(bitmap.tobytes("png")).decode(), "text": text,
                      "details": details}
    else:
        raise ValueError("INVALID_PARSER_OPERATION")
    print(json.dumps(result, ensure_ascii=False, allow_nan=False))


if __name__ == "__main__":
    try:
        _worker()
    except Exception as error:
        print(json.dumps({"error": str(error) if isinstance(error, ValueError) and str(error).isupper() else type(error).__name__}))
