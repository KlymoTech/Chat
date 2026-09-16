"""Ten deterministic, fail-closed checks; coverage is never called accuracy."""
from __future__ import annotations

import codecs
import io
import re
from typing import Any

from PIL import Image
from pydantic import ValidationError

from northstar_api.services.extraction_evidence import (
    MAX_GRID_POSITIONS, VALIDATOR_VERSION, crop_image, leaf_blocks, review_fingerprint,
    review_projection, safe_name, sha256, source_tokens, valid_box, verify_projection,
)
from northstar_api.services.extraction_schema import Cell, Reading, digest, strict_json


def same_text(left: str, right: str) -> bool:
    # Used only to compare candidates. Never replace source whitespace with this.
    return re.sub(r"\s+", " ", left).strip() == re.sub(r"\s+", " ", right).strip()


def disagreement(native: str, visual: str) -> str:
    numbers = r"[-+−]?\d+(?:[.,]\d+)*"
    if re.findall(numbers, native) != re.findall(numbers, visual):
        return "NUMERIC_CONFLICT"
    critical = r"\b(?:NOT|EXCEPT|least|most|incorrect)\b"
    if re.findall(critical, native, re.I) != re.findall(critical, visual, re.I):
        return "CRITICAL_WORD_CONFLICT"
    if re.findall(r"[≤≥≠²₂−]", native) != re.findall(r"[≤≥≠²₂−]", visual):
        return "CRITICAL_SYMBOL_CONFLICT"
    return "CANDIDATE_CONFLICT"


def critical_page(page: dict[str, Any]) -> bool:
    values = [page.get(key) or "" for key in ("native_text", "visual_text", "selected_text")]
    for block in leaf_blocks(page):
        structure = block.get("reviewed_structure") or block.get("visual") or {}
        if block.get("type") in {"table", "equation", "question", "answer_key"} or structure.get("kind") in {"table", "equation", "question", "answer_key"}:
            return True
        values += [str(value) for key, value in structure.items() if key not in {"derived_description", "complete", "blank", "uncertain"}]
    return bool(source_tokens("\n".join(values)))


def review_digest(page: dict[str, Any]) -> str:
    return review_fingerprint(page)


def table_errors(cells: list[dict[str, Any]]) -> list[str]:
    errors: list[str] = []
    if not cells:
        return ["Table has no structured cells"]
    try:
        parsed = [Cell.model_validate(cell).model_dump(mode="json") for cell in cells]
    except (ValidationError, ValueError, TypeError):
        return ["Invalid table-cell schema"]
    anchors = [c for c in parsed if c["state"] != "COVERED_BY_MERGE"]
    covered = [c for c in parsed if c["state"] == "COVERED_BY_MERGE"]
    coordinates = [(c["row"], c["column"]) for c in parsed]
    if len(coordinates) != len(set(coordinates)):
        errors.append("Duplicate cell coordinates")
    rows = max((c["row"] + c["row_span"] for c in anchors), default=0)
    columns = max((c["column"] + c["column_span"] for c in anchors), default=0)
    if rows * columns > MAX_GRID_POSITIONS or sum(c["row_span"] * c["column_span"] for c in anchors) > MAX_GRID_POSITIONS:
        return errors + ["Table grid exceeds safe occupancy budget"]
    occupancy: dict[tuple[int, int], str] = {}
    headers = {f"R{c['row']}C{c['column']}": c for c in anchors if c["header"]}
    for cell in anchors:
        identity = f"R{cell['row']}C{cell['column']}"
        if cell["state"] in {"UNREADABLE", "AMBIGUOUS", "STRUCTURE_UNKNOWN"}:
            errors.append(f"{identity}: unresolved cell state {cell['state']}")
        if cell["state"] == "VALUE" and not cell["text"]:
            errors.append(f"{identity}: empty VALUE must be explicitly BLANK")
        for row in range(cell["row"], cell["row"] + cell["row_span"]):
            for col in range(cell["column"], cell["column"] + cell["column_span"]):
                if (row, col) in occupancy:
                    errors.append(f"{identity}: overlapping cell spans")
                occupancy[(row, col)] = identity
        if headers and cell["state"] == "VALUE" and not cell["header"] and not cell["header_refs"]:
            errors.append(f"{identity}: header association required")
        for reference in cell["header_refs"]:
            header = headers.get(reference)
            if not header or reference == identity:
                errors.append(f"{identity}: unknown or self header {reference}")
                continue
            column_header = header["row"] < cell["row"] and header["column"] <= cell["column"] < header["column"] + header["column_span"]
            row_header = header["column"] < cell["column"] and header["row"] <= cell["row"] < header["row"] + header["row_span"]
            if not (column_header or row_header):
                errors.append(f"{identity}: header {reference} is outside the cell's row/column")
    if len(occupancy) != rows * columns:
        errors.append("Grid has unaccounted positions; record explicit blanks or merged coverage")
    for cell in covered:
        owner = occupancy.get((cell["row"], cell["column"]))
        if owner is None or owner == f"R{cell['row']}C{cell['column']}":
            errors.append("COVERED_BY_MERGE has no spanning anchor")
    return list(dict.fromkeys(errors))


def _source_text(data: bytes) -> str:
    for bom, codec in ((codecs.BOM_UTF32_LE, "utf-32-le"), (codecs.BOM_UTF32_BE, "utf-32-be"),
                       (codecs.BOM_UTF8, "utf-8"), (codecs.BOM_UTF16_LE, "utf-16-le"), (codecs.BOM_UTF16_BE, "utf-16-be")):
        if data.startswith(bom):
            return data[len(bom):].decode(codec, errors="strict")
    return data.decode("utf-8", errors="strict")


def _current_review(review: Any, page: dict[str, Any], record: dict[str, Any]) -> bool:
    return isinstance(review, dict) and bool(review.get("reviewer")) and bool(review.get("reason", "").strip()) and (
        review.get("content_sha256") == review_digest(page)
        and review.get("source_sha256") == record.get("source_sha256")
        and review.get("config_sha256") == record.get("config_sha256")
        and review.get("image_sha256") == page.get("image_sha256")
        and review.get("validator_version") == VALIDATOR_VERSION
        and review.get("structure_confirmed") is True
    )


def validate(record: dict[str, Any], artifacts: dict[str, bytes]) -> list[dict[str, Any]]:
    names = ["source_render_integrity", "schema_identity", "coverage_reconciliation", "text_comparison",
             "tables_numbers", "educational_structure", "visual_audit", "document_continuity",
             "export_consistency", "human_acceptance"]
    failures: dict[str, list[str]] = {name: [] for name in names}
    def fail(layer: str, message: str) -> None:
        # Bound report growth while retaining the count of affected checks.
        if len(failures[layer]) < 1000 and message not in failures[layer]:
            failures[layer].append(message)
    pages = record.get("pages", [])
    issues = record.get("issues", [])
    expected = record.get("expected_units")
    numbers = [page.get("number") for page in pages]
    if not isinstance(expected, int) or expected < 1 or numbers != list(range(1, expected + 1)):
        fail("source_render_integrity", "Every expected source unit must occur exactly once, in order")
    originals = [key for key in artifacts if key.startswith("source/original.")]
    original = artifacts[originals[0]] if len(originals) == 1 else None
    if original is None or sha256(original) != record.get("source_sha256"):
        fail("source_render_integrity", "Original source bytes are absent or their checksum differs")
    if any(not safe_name(name) for name in artifacts):
        fail("source_render_integrity", "Unsafe evidence artifact path")
    try:
        if digest(record.get("config")) != record.get("config_sha256"):
            fail("source_render_integrity", "Configuration checksum differs")
    except (ValueError, TypeError):
        fail("source_render_integrity", "Configuration is not canonical JSON")
    if record.get("schema_version") != 2:
        fail("schema_identity", "Re-extract with the current evidence schema")
    ids = [block.get("id") for page in pages for block in page.get("blocks", [])]
    if any(not isinstance(value, str) or not value for value in ids) or len(ids) != len(set(ids)):
        fail("schema_identity", "Source block IDs must be nonempty and unique")
    issue_ids = [i.get("id") for i in issues]
    if len(issue_ids) != len(set(issue_ids)) or any(not value for value in issue_ids):
        fail("schema_identity", "Issue IDs must be nonempty and unique")
    blocks_by_id = {b.get("id"): (p, b) for p in pages for b in p.get("blocks", [])}
    for issue in issues:
        if issue.get("page") not in {0, *numbers} or (issue.get("block_id") and issue["block_id"] not in blocks_by_id):
            fail("schema_identity", "Issue points to unknown source evidence")
        if issue.get("status") != "resolved":
            fail("human_acceptance", f"Unresolved issue {issue.get('id')}: {issue.get('code')}")
        elif issue.get("technical"):
            fail("source_render_integrity", "Technical failures cannot be waived by a reviewer")
        elif issue.get("disposition") not in {"source_verified", "source_anomaly"} or not issue.get("resolution_reason") or not issue.get("resolved_by"):
            fail("human_acceptance", "Issue resolution lacks a source-based disposition")
    for page in pages:
        label = f"Unit {page.get('number')}"
        required_image = bool(page.get("requires_image"))
        image = artifacts.get(page.get("image", ""))
        width, height = page.get("width_px", 0), page.get("height_px", 0)
        if required_image:
            if image is None or sha256(image) != page.get("image_sha256"):
                fail("source_render_integrity", f"{label}: source image missing or changed")
            else:
                try:
                    with Image.open(io.BytesIO(image)) as bitmap:
                        if bitmap.size != (width, height):
                            fail("source_render_integrity", f"{label}: recorded image dimensions differ")
                except (ValueError, OSError):
                    fail("source_render_integrity", f"{label}: invalid image artifact")
            if not page.get("inventory_complete"):
                fail("coverage_reconciliation", f"{label}: independent visual inventory incomplete")
        leaves = leaf_blocks(page)
        if required_image and not leaves and not page.get("blank"):
            fail("coverage_reconciliation", f"{label}: nonblank source has no visible regions")
        if required_image and not leaves and page.get("selected_text") not in {None, ""}:
            fail("text_comparison", f"{label}: blank inventory contains unrepresented text")
        if page.get("source_unit") == "bytes" and original is not None:
            try:
                exact_text = _source_text(original)
                if page.get("native_text") != exact_text or page.get("selected_text") != exact_text:
                    fail("text_comparison", f"{label}: original text bytes differ from transcription")
                lines = page.get("lines", [])
                if "".join(line.get("text", "") for line in lines) != exact_text:
                    fail("coverage_reconciliation", f"{label}: source line inventory is incomplete")
                for line in lines:
                    start, end = line.get("byte_start"), line.get("byte_end")
                    if not isinstance(start, int) or not isinstance(end, int) or not 0 <= start <= end <= len(original) or original[start:end].decode(page.get("encoding", "utf-8")) != line.get("text"):
                        fail("schema_identity", f"{label}: invalid byte/line mapping")
            except (UnicodeError, ValueError, LookupError):
                fail("source_render_integrity", f"{label}: undecodable source needs explicit encoding")
        if leaves and (any(b.get("selected_text") is None for b in leaves) or page.get("selected_text") != "\n".join(b.get("selected_text") or "" for b in leaves)):
            fail("export_consistency", f"{label}: page text is not the exact ordered region projection")
        primary_valid = _current_review(page.get("primary_review"), page, record)
        if not primary_valid:
            fail("human_acceptance", f"{label}: current source-based primary review required")
            if required_image:
                fail("visual_audit", f"{label}: source image audit pending")
        if critical_page(page):
            second = page.get("second_review")
            if not _current_review(second, page, record) or not primary_valid or second.get("reviewer") == page["primary_review"].get("reviewer"):
                fail("human_acceptance", f"{label}: independent second review required for critical content")
        if page.get("selected_text") is None:
            fail("text_comparison", f"{label}: selected source transcription is unresolved")
        if page.get("native_text") and page.get("visual_text") is not None and not same_text(page["native_text"], page["visual_text"]) and not primary_valid:
            fail("text_comparison", f"{label}: {disagreement(page['native_text'], page['visual_text'])}")
        for attempt in page.get("vision_attempts", []):
            key = f"attempts/{attempt.get('id')}.json"
            try:
                if key not in artifacts or strict_json(artifacts[key]) != attempt:
                    fail("source_render_integrity", f"{label}: raw model-call evidence differs")
                if image is not None and sha256(crop_image(image, attempt["bbox_px"])) != attempt.get("image_sha256"):
                    fail("source_render_integrity", f"{label}: model-input crop checksum differs")
            except (ValueError, KeyError, TypeError, OSError):
                fail("source_render_integrity", f"{label}: invalid model-call provenance")
        for block in page.get("blocks", []):
            block_label = f"{label}/{block.get('id')}"
            if block.get("source_page_number") != page.get("number") or not valid_box(block.get("bbox_px"), width, height):
                fail("schema_identity", f"{block_label}: invalid page coordinates")
            crop = artifacts.get(block.get("crop", ""))
            if required_image:
                try:
                    if crop is None or image is None or crop != crop_image(image, block["bbox_px"]):
                        fail("source_render_integrity", f"{block_label}: region crop does not match source coordinates")
                except (ValueError, OSError, TypeError, KeyError):
                    fail("source_render_integrity", f"{block_label}: region crop mapping failed")
            if block.get("parent_id") and block["parent_id"] not in blocks_by_id:
                fail("schema_identity", f"{block_label}: split parent is unknown")
            if block.get("status") == "split":
                if not any(b.get("parent_id") == block.get("id") for b in page.get("blocks", [])):
                    fail("coverage_reconciliation", f"{block_label}: split has no represented children")
                continue
            visual = block.get("visual")
            if not isinstance(visual, dict) or not visual.get("complete") or block.get("status") == "failed":
                fail("visual_audit", f"{block_label}: successful independent visual reading missing")
            structure = block.get("reviewed_structure") or visual
            try:
                parsed = Reading.model_validate(structure).model_dump(mode="json")
            except (ValidationError, ValueError, TypeError):
                fail("schema_identity", f"{block_label}: invalid structured reading")
                continue
            if parsed["kind"] != block.get("type"):
                fail("schema_identity", f"{block_label}: selected kind differs from block classification")
            if not parsed["complete"] or parsed["uncertain"] or "[[UNREADABLE]]" in parsed["text"]:
                fail("educational_structure", f"{block_label}: incomplete or unreadable source remains")
            if block.get("reviewed_structure") and parsed["text"] != block.get("selected_text"):
                fail("export_consistency", f"{block_label}: reviewed structure text differs")
            if parsed["kind"] == "table":
                for error in table_errors(parsed["cells"]):
                    fail("tables_numbers", f"{block_label}: {error}")
            if parsed["kind"] == "equation" and not parsed.get("latex"):
                fail("educational_structure", f"{block_label}: equation representation is missing")
            links = block.get("related_block_ids", [])
            if len(set(links)) != len(links):
                fail("document_continuity", f"{block_label}: duplicate relationship")
            linked = []
            for link in links:
                if link not in blocks_by_id or link == block.get("id"):
                    fail("document_continuity", f"{block_label}: relationship target unknown or self")
                else:
                    linked.append(blocks_by_id[link])
            for flag, direction in (("continues_from_previous", -1), ("continues_on_next", 1)):
                if parsed.get(flag):
                    matches = [(p, b) for p, b in linked if b.get("type") == block.get("type") and direction * (p["number"] - page["number"]) > 0]
                    if not matches or not any(block["id"] in b.get("related_block_ids", []) for _, b in matches):
                        fail("document_continuity", f"{block_label}: {flag} needs a reciprocal source-fragment link")
            if parsed["kind"] == "answer_key" and not any(b.get("type") == "question" for _, b in linked):
                fail("educational_structure", f"{block_label}: printed answer key needs source question links")
            if parsed["kind"] == "caption" and not any(b.get("type") in {"table", "figure", "equation"} for _, b in linked):
                fail("educational_structure", f"{block_label}: caption needs a source object link")
        native_dispositions = {b.get("native_object_id") for b in page.get("blocks", [])}
        for native in page.get("native_blocks", []):
            if native.get("id") in native_dispositions:
                continue
            box = native.get("bbox_px")
            if box and not any(valid_box(b.get("bbox_px"), width, height) and b["bbox_px"][0] <= (box[0] + box[2]) / 2 <= b["bbox_px"][2] and b["bbox_px"][1] <= (box[1] + box[3]) / 2 <= b["bbox_px"][3] for b in leaves):
                fail("coverage_reconciliation", f"{label}: native object {native.get('id')} has no disposition")
    for logical in record.get("word", {}).get("blocks", []):
        if logical.get("part") != "word/document.xml" or logical.get("type") != "paragraph" or logical.get("channel") != "visible_candidate" or not logical.get("text", "").strip():
            continue
        mapped = logical.get("rendered_pages", [])
        if not mapped or any(number not in numbers for number in mapped) or logical.get("mapping_status") not in {"matched", "source_reviewed"}:
            fail("document_continuity", f"Word logical block {logical['id']}: source-to-page mapping remains unresolved")
        if logical.get("mapping_status") == "source_reviewed":
            linked_pages = sorted({p["number"] for p in pages for b in leaf_blocks(p) if logical['id'] in (b.get('reviewed_structure') or {}).get('source_logical_ids', [])})
            if mapped != linked_pages:
                fail("document_continuity", f"Word logical block {logical['id']}: reviewed mappings disagree")
    for issue in issues:
        if issue.get("status") == "resolved":
            continue
        code = issue.get("code", "")
        layer = "tables_numbers" if any(token in code for token in ("TABLE", "NUMERIC")) else "text_comparison" if "CONFLICT" in code else "document_continuity" if "CONTINUITY" in code else "visual_audit" if "VISION" in code or "VISUAL" in code else "coverage_reconciliation"
        fail(layer, f"{issue.get('id')}: {code}")
    try:
        verify_projection(review_projection(record), record)
    except (ValueError, KeyError, TypeError):
        fail("export_consistency", "Source-record projection failed its round-trip check")
    return [{"name": name, "status": "FAILED" if failures[name] else "PASSED", "details": failures[name],
             "validator_version": VALIDATOR_VERSION} for name in names]


def metrics(record: dict[str, Any]) -> dict[str, Any]:
    pages = record.get("pages", [])
    expected = record.get("expected_units", 0)
    leaves = [b for page in pages for b in leaf_blocks(page)]
    visual_required = [p for p in pages if p.get("requires_image")]
    successful = sum(bool(p.get("inventory_complete")) and all((b.get("visual") or {}).get("complete") for b in leaf_blocks(p)) for p in visual_required)
    return {
        "expected_units": expected, "processed_units": len(pages),
        "page_processing_coverage": len(pages) / expected if expected else 0,
        "visual_units_required": len(visual_required), "visual_units_completed": successful,
        "detected_regions": len(leaves), "candidate_agreement_count": sum(bool(b.get("agreement")) for b in leaves),
        "primary_reviews_current": sum(_current_review(p.get("primary_review"), p, record) for p in pages),
        "critical_units": sum(critical_page(p) for p in pages),
        "open_issues": sum(i.get("status") != "resolved" for i in record.get("issues", [])),
        "measured_transcription_accuracy": "NOT_MEASURED",
    }
