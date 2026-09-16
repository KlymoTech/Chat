"""Deterministic, source-bearing TXT/JSON projections and evidence archives."""
from __future__ import annotations

import hashlib
import io
import json
import zipfile
from dataclasses import dataclass
from typing import Any

from northstar_api.services.extraction_schema import POLICY_VERSION, strict_json
from northstar_api.services.extraction_structure import assemble_logical
from northstar_api.services.extraction_validation import metrics, safe_name, validate


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False)


def source_records(record: dict[str, Any]) -> list[tuple[str, Any]]:
    """An auditable projection independent of the full canonical backup record."""
    result: list[tuple[str, Any]] = []
    for page in record.get("pages", []):
        prefix = f"unit/{page['number']}"
        for key in ("native_text", "visual_text", "selected_text", "printed_page_label", "pdf_page_label", "lines",
                    "annotations", "form_fields", "native_blocks", "native_tables"):
            if key in page:
                result.append((f"{prefix}/{key}", page[key]))
        for block in page.get("blocks", []):
            for key in ("native_text", "selected_text", "visual", "reviewed_structure", "source_fragments", "related_block_ids"):
                if key in block:
                    result.append((f"{prefix}/block/{block['id']}/{key}", block[key]))
    for key in ("word", "logical_blocks", "issues", "correction_history"):
        if key in record:
            result.append((key, record[key]))
    return result


def render_review(record: dict[str, Any]) -> str:
    lines = [f"SOURCE: {_json(record.get('source_name'))}", f"SOURCE SHA-256: {record['source_sha256']}",
             f"EXTRACTION REVISION: {record.get('extraction_revision')}",
             f"STATUS: {record.get('review_status', 'needs_review').upper()}",
             "Source strings are JSON-escaped; original newlines, delimiters and exact characters are preserved.",
             "Derived descriptions are NOT source transcriptions. Measured extraction accuracy: NOT_MEASURED."]
    for page in record.get("pages", []):
        lines.extend(["", f"SOURCE UNIT: {page['number']} ({page.get('source_unit', 'page')})",
                      f"SOURCE PAGE INDEX: {_json(page.get('source_page_index'))}",
                      f"SOURCE PAGE NUMBER: {_json(page.get('source_page_number'))}",
                      f"RENDERED PAGE NUMBER: {_json(page.get('rendered_page_number'))}",
                      f"PRINTED PAGE LABEL: {_json(page.get('printed_page_label'))}",
                      f"PDF PAGE LABEL: {_json(page.get('pdf_page_label'))}",
                      f"IMAGE: {page.get('image') or 'NONE'}"])
        for key in ("native_text", "visual_text", "selected_text"):
            lines.append(f"{key.upper()}: {_json(page.get(key))}")
        for block in page.get("blocks", []):
            lines.append(f"[{block['type'].upper()} {block['id']} | {block.get('status', 'unresolved')}]")
            lines.append(f"SOURCE CROP: {block.get('crop')} | BBOX PX: {_json(block.get('bbox_px'))}")
            lines.append("SELECTED TEXT: " + _json(block.get("selected_text")))
            structure = block.get("reviewed_structure") or block.get("visual") or {}
            for cell in structure.get("cells", []):
                lines.append(f"CELL R{cell['row'] + 1}C{cell['column'] + 1} | state={cell.get('state', 'VALUE')} "
                             f"| span={cell.get('row_span', 1)}x{cell.get('column_span', 1)} "
                             f"| headers={_json(cell.get('header_refs', []))} | unit={_json(cell.get('unit'))} "
                             f"| text={_json(cell['text'])}")
            for key in ("latex", "printed_label", "printed_caption", "figure_labels", "handwritten_annotation", "observed_relationships", "option_labels", "options", "printed_answer"):
                if structure.get(key) not in (None, [], ""):
                    lines.append(f"{key.upper()}: {_json(structure[key])}")
            if block["type"] in {"question", "answer_key"} and structure.get("printed_answer") is None:
                lines.append("PRINTED ANSWER: NOT PRESENT | GENERATED ANSWER: NOT ALLOWED IN EXTRACTION")
            if structure.get("derived_description"):
                lines.append("[DERIVED DESCRIPTION - NOT SOURCE TEXT] " + _json(structure["derived_description"]))
            lines.append("BLOCK_RECORD\t" + _json(block))
    for issue in record.get("issues", []):
        lines.append("[ISSUE - NOT SOURCE TEXT] " + _json(issue))
    # Every cell/label/markup channel is independently checked, not just the backup blob.
    for key, value in source_records(record):
        lines.append("SOURCE_RECORD\t" + _json(key) + "\t" + _json(value))
    lines.append("CANONICAL_RECORD\t" + _json(record))
    return "\n".join(lines) + "\n"


def verify_review_projection(text: str, record: dict[str, Any]) -> None:
    canonical, actual = [], []
    for line in text.splitlines():
        if line.startswith("CANONICAL_RECORD\t"):
            canonical.append(strict_json(line.split("\t", 1)[1]))
        elif line.startswith("SOURCE_RECORD\t"):
            _, key, value = line.split("\t", 2)
            actual.append((strict_json(key), strict_json(value)))
    if canonical != [record] or actual != source_records(record):
        raise ValueError("TXT projection differs from canonical source-bearing records")
    if text != render_review(record):
        raise ValueError("Readable TXT projection was changed or truncated")


def render_validation(record: dict[str, Any]) -> str:
    lines = [f"Source SHA-256: {record['source_sha256']}",
             f"Extraction revision: {record.get('extraction_revision')}",
             f"Review revision: {record.get('review_revision', 0)}",
             f"Configuration SHA-256: {record.get('config_sha256')}",
             f"Validation policy: {POLICY_VERSION}", f"Parsers: {_json(record.get('parsers'))}",
             f"Expected units: {record.get('expected_units')}", f"Processed units: {len(record.get('pages', []))}",
             f"Vision model: {record.get('vision_model') or 'NOT_RUN'}", "Measured accuracy: NOT_MEASURED",
             f"Verified release: {'APPROVED' if record.get('review_status') == 'verified_release' and record.get('release_eligible') else 'BLOCKED'}",
             "Draft review export: AVAILABLE"]
    for stage in record.get("stages", []):
        lines.append("STAGE " + _json(stage))
    for check in record.get("checks", []):
        lines.append(f"{check['name']}: {check['status']} " + _json(check.get("details", [])))
    for issue in record.get("issues", []):
        lines.append("ISSUE " + _json(issue))
    lines.append("METRICS " + _json(record.get("metrics")))
    return "\n".join(lines) + "\n"


@dataclass
class ExtractionPackage:
    record: dict[str, Any]
    images: dict[str, bytes]

    def __post_init__(self) -> None:
        self.refresh()

    @property
    def issues(self) -> list[dict[str, Any]]:
        return self.record["issues"]

    def refresh(self) -> None:
        self.record["logical_blocks"] = assemble_logical(self.record)
        self.record["checks"] = validate(self.record, self.images)
        self.record["metrics"] = metrics(self.record)
        self.record["validation_policy_version"] = POLICY_VERSION
        passed = all(check["status"] == "PASSED" for check in self.record["checks"])
        self.record["release_eligible"] = passed
        if self.record.get("review_status") == "verified_release" and not passed:
            self.record["review_status"] = "needs_review"
        self.record["release_blockers"] = [check["name"] for check in self.record["checks"] if check["status"] != "PASSED"]

    def review_text(self) -> str:
        self.refresh()
        return render_review(self.record)

    def validation_text(self) -> str:
        self.refresh()
        return render_validation(self.record)

    def archive(self) -> bytes:
        reserved = {"manifest.json", "extracted.json", "extracted_review.txt", "validation_report.txt", "correction_history.json"}
        if reserved.intersection(self.images):
            raise ValueError("Evidence must not replace reserved export artifacts")
        self.refresh()
        report = render_review(self.record)
        verify_review_projection(report, self.record)
        artifacts = {"extracted.json": json.dumps(self.record, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False).encode(),
                     "extracted_review.txt": report.encode(), "validation_report.txt": render_validation(self.record).encode(),
                     "correction_history.json": _json(self.record.get("correction_history", [])).encode(), **self.images}
        if any(not safe_name(name) for name in artifacts):
            raise ValueError("Unsafe evidence artifact name")
        manifest = {"schema_version": 2, "validation_policy_version": POLICY_VERSION,
                    "extraction_revision": self.record.get("extraction_revision"),
                    "source_sha256": self.record["source_sha256"], "config_sha256": self.record.get("config_sha256"),
                    "parsers": self.record.get("parsers"), "vision_model": self.record.get("vision_model"),
                    "vision_provider": self.record.get("vision_provider"), "expected_units": self.record.get("expected_units"),
                    "source_units": [{k: page.get(k) for k in ("number", "source_unit", "source_page_index", "source_page_number", "rendered_page_number", "image", "image_sha256")}
                                     for page in self.record.get("pages", [])],
                    "artifacts": {name: hashlib.sha256(data).hexdigest() for name, data in artifacts.items()}}
        artifacts["manifest.json"] = json.dumps(manifest, sort_keys=True, indent=2).encode()
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for name, data in sorted(artifacts.items()):
                info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = 0o600 << 16
                archive.writestr(info, data)
        return output.getvalue()
