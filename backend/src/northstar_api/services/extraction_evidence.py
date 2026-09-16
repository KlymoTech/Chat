"""Evidence integrity, safe containers and deterministic review projections."""
from __future__ import annotations

import hashlib
import io
import json
import re
import stat
import zipfile
from pathlib import PurePosixPath
from typing import Any

from PIL import Image

from northstar_api.services.extraction_schema import digest, strict_json

VALIDATOR_VERSION = "source-verification-v4"
MAX_GRID_POSITIONS = 100_000


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def safe_name(name: str) -> bool:
    path = PurePosixPath(name)
    return bool(name) and not path.is_absolute() and "\\" not in name and ":" not in name and "\x00" not in name and all(
        part not in {"", ".", ".."} for part in name.split("/")
    )


def read_zip(data: bytes, *, max_bytes: int, max_members: int = 5000) -> dict[str, bytes]:
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        members = archive.infolist()
        if len(members) > max_members or sum(item.file_size for item in members) > max_bytes:
            raise ValueError("Archive exceeds expanded-size or member limit")
        if len({item.filename for item in members}) != len(members):
            raise ValueError("Archive contains duplicate members")
        result: dict[str, bytes] = {}
        for item in members:
            name = item.filename.rstrip("/") if item.is_dir() else item.filename
            if not safe_name(name) or item.flag_bits & 1 or stat.S_ISLNK(item.external_attr >> 16):
                raise ValueError("Archive has unsafe, encrypted or symbolic-link members")
            if not item.is_dir():
                result[item.filename] = archive.read(item)
        return result


def deterministic_zip(artifacts: dict[str, bytes]) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, data in sorted(artifacts.items()):
            if not safe_name(name):
                raise ValueError("Unsafe evidence artifact path")
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100600 << 16
            archive.writestr(info, data)
    return output.getvalue()


def valid_box(box: Any, width: int | float, height: int | float) -> bool:
    return isinstance(box, (list, tuple)) and len(box) == 4 and all(
        isinstance(v, (int, float)) and not isinstance(v, bool) for v in box
    ) and 0 <= box[0] < box[2] <= width and 0 <= box[1] < box[3] <= height


def crop_image(image: bytes, box: list[int] | tuple[int, ...]) -> bytes:
    with Image.open(io.BytesIO(image)) as original:
        if not valid_box(box, *original.size) or any(not isinstance(v, int) for v in box):
            raise ValueError("Crop must use integer coordinates inside the source image")
        output = io.BytesIO()
        original.crop(tuple(box)).save(output, format="PNG")
        return output.getvalue()


def leaf_blocks(page: dict[str, Any]) -> list[dict[str, Any]]:
    return [block for block in page.get("blocks", []) if block.get("status") != "split"]


def review_fingerprint(page: dict[str, Any]) -> str:
    # Hash every source-bearing field, including links, geometry, native candidates,
    # raw call provenance and labels. Exclude only derived metrics and signatures.
    ignored = {"primary_review", "second_review", "requires_second_review", "validation_status"}
    return digest({key: value for key, value in page.items() if key not in ignored})


def projection_records(record: dict[str, Any]) -> list[dict[str, Any]]:
    """Independently enumerable source-bearing records for TXT/JSON round trips."""
    result: list[dict[str, Any]] = []
    for page in record.get("pages", []):
        result.append({"record_type": "SOURCE_UNIT", "value": {k: v for k, v in page.items() if k != "blocks"}})
        for block in page.get("blocks", []):
            result.append({"record_type": "BLOCK", "page": page["number"], "value": block})
            structure = block.get("reviewed_structure") or block.get("visual") or {}
            for cell in structure.get("cells", []):
                result.append({"record_type": "CELL", "block_id": block["id"], "value": cell})
    if "word" in record:
        result.append({"record_type": "WORD_LOGICAL_SOURCE", "value": record["word"]})
    result.extend({"record_type": "ISSUE", "value": issue} for issue in record.get("issues", []))
    return result


def review_projection(record: dict[str, Any]) -> str:
    quoted = lambda value: json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False)
    lines = [f"SOURCE SHA-256: {record['source_sha256']}",
             f"EXTRACTION REVISION: {record.get('extraction_revision')}",
             f"STATUS: {record.get('review_status', 'needs_review').upper()}",
             "Draft candidates are not approved content. Source strings below are JSON-escaped."]
    for page in record.get("pages", []):
        lines += ["", f"SOURCE UNIT: {page['number']} ({page.get('source_unit', 'page')})",
                  "PAGE IDENTITY: " + quoted({key: page.get(key) for key in (
                      "source_page_index", "source_page_number", "rendered_page_number", "pdf_page_label", "printed_page_label")}),
                  f"IMAGE: {page.get('image') or 'NONE'}"]
        for key in ("native_text", "visual_text", "selected_text"):
            lines.append(key.upper() + ": " + quoted(page.get(key)))
        for block in page.get("blocks", []):
            lines.append(f"[{block['type'].upper()} {block['id']} | {block.get('status', 'unknown')}]")
            lines.append("SELECTED TEXT: " + quoted(block.get("selected_text")))
            lines.append("SOURCE CROP: " + quoted(block.get("crop")))
            structure = block.get("reviewed_structure") or block.get("visual") or {}
            for cell in structure.get("cells", []):
                lines.append(f"CELL R{cell['row']}C{cell['column']}: " + quoted(cell))
            for key in ("latex", "printed_label", "printed_caption", "figure_labels", "handwritten_annotation",
                        "options", "subparts", "option_labels", "printed_answer", "instructions", "marks", "units"):
                if key in structure:
                    lines.append(key.upper() + ": " + quoted(structure[key]))
            if structure.get("derived_description"):
                lines.append("DERIVED DESCRIPTION — NOT SOURCE TEXT: " + quoted(structure["derived_description"]))
    # Tags are redundant by design; missing a visible source-bearing record is
    # detected independently of the final canonical envelope.
    lines.extend("SOURCE_RECORD\t" + quoted(item) for item in projection_records(record))
    lines.append("CANONICAL_RECORD\t" + quoted(record))
    return "\n".join(lines) + "\n"


def verify_projection(text: str, record: dict[str, Any]) -> None:
    tags = [strict_json(line.split("\t", 1)[1], max_bytes=100_000_000)
            for line in text.split("\n") if line.startswith("SOURCE_RECORD\t")]
    envelopes = [strict_json(line.split("\t", 1)[1], max_bytes=100_000_000)
                 for line in text.split("\n") if line.startswith("CANONICAL_RECORD\t")]
    if tags != projection_records(record) or envelopes != [record] or text != review_projection(record):
        raise ValueError("TXT projection differs from canonical source records")


def source_tokens(value: str) -> list[str]:
    return re.findall(r"[-+−]?\d+(?:[.,]\d+)*|\b(?:NOT|EXCEPT|least|most|incorrect)\b|[≤≥≠²₂]", value, re.I)
