"""Ten deterministic/source-review gates; processing coverage is not accuracy."""
from __future__ import annotations

import hashlib
import io
import re
from collections import Counter
from pathlib import PurePosixPath
from typing import Any

from PIL import Image

from northstar_api.services.extraction_schema import POLICY_VERSION, digest
from northstar_api.services.extraction_structure import relationship_errors, structure_errors, word_mapping_errors
from northstar_api.services.extraction_structure import table_errors as table_errors

CRITICAL = re.compile(r"\d|\b(?:NOT|EXCEPT|least|most|incorrect)\b|[=<>≤≥²₂⁻₋]", re.I)


def same_text(left: str, right: str) -> bool:
    # Agreement uses whitespace normalization; stored source strings are never normalized.
    return re.sub(r"\s+", " ", left).strip() == re.sub(r"\s+", " ", right).strip()


def disagreement(native: str, visual: str) -> str:
    if re.findall(r"[-+−]?\d+(?:[.,]\d+)*", native) != re.findall(r"[-+−]?\d+(?:[.,]\d+)*", visual):
        return "NUMERIC_CONFLICT"
    if re.findall(r"\b(?:NOT|EXCEPT|least|most|incorrect)\b", native, re.I) != re.findall(r"\b(?:NOT|EXCEPT|least|most|incorrect)\b", visual, re.I):
        return "CRITICAL_WORD_CONFLICT"
    if re.findall(r"[=<>≤≥²₂⁻₋]", native) != re.findall(r"[=<>≤≥²₂⁻₋]", visual):
        return "SYMBOL_CONFLICT"
    return "CANDIDATE_CONFLICT"


def critical_page(page: dict[str, Any]) -> bool:
    text = " ".join(str(page.get(key) or "") for key in ("native_text", "visual_text", "selected_text"))
    return bool(CRITICAL.search(text)) or any(
        block.get("type") in {"table", "equation", "question", "answer_key"}
        or block.get("inventory_kind") in {"table", "equation", "question", "answer_key"}
        for block in page.get("blocks", [])
    )


def review_context(record: dict[str, Any], number: int) -> str:
    pairs = [(page, block) for page in record.get("pages", []) for block in page.get("blocks", [])]
    refs = {ref for page, block in pairs if page.get("number") == number for ref in block.get("related_block_ids", [])}
    targets = [{"id": block.get("id"), "unit": page.get("number"), "type": block.get("type"),
                "selected_text": block.get("selected_text"), "structure": block.get("reviewed_structure") or block.get("visual"),
                "related_block_ids": block.get("related_block_ids", []), "image_sha256": page.get("image_sha256")}
               for page, block in pairs if block.get("id") in refs]
    return digest({
        "policy": POLICY_VERSION, "related_source_fragments": targets, "source_sha256": record.get("source_sha256"),
        "config_sha256": record.get("config_sha256"), "word": record.get("word"),
        "issues": [{key: issue.get(key) for key in ("id", "code", "status", "disposition", "resolution_reason")}
                   for issue in record.get("issues", []) if issue.get("page") in {0, number}],
    })


def review_digest(page: dict[str, Any]) -> str:
    # Bind ALL page evidence, geometry, candidates, reading order, links and reviewed cells.
    # Approval metadata itself is excluded to allow an independent second signature.
    excluded = {"primary_review", "second_review", "requires_second_review"}
    return digest({"policy": POLICY_VERSION, "page": {k: v for k, v in page.items() if k not in excluded}})


def current_review(record: dict[str, Any], page: dict[str, Any], review: Any) -> bool:
    if not isinstance(review, dict):
        return False
    return bool(
        isinstance(review.get("reviewer"), str) and review["reviewer"].strip()
        and isinstance(review.get("reason"), str) and review["reason"].strip()
        and review.get("policy_version") == POLICY_VERSION
        and review.get("structure_confirmed") is True
        and review.get("source_sha256") == record.get("source_sha256")
        and review.get("image_sha256") == page.get("image_sha256")
        and page.get("review_context_sha256") == review_context(record, page["number"])
        and review.get("content_sha256") == review_digest(page)
    )


def safe_name(name: Any) -> bool:
    if not isinstance(name, str) or not name or "\\" in name or "\x00" in name:
        return False
    path = PurePosixPath(name)
    return not path.is_absolute() and all(part not in {".", "..", ""} for part in name.split("/")) and ":" not in name


def valid_box(box: Any, width: int, height: int) -> bool:
    return bool(isinstance(box, (list, tuple)) and len(box) == 4 and all(type(n) is int for n in box)
                and 0 <= box[0] < box[2] <= width and 0 <= box[1] < box[3] <= height)


def validate(record: dict[str, Any], artifacts: dict[str, bytes]) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    raw_pages = record.get("pages", [])
    pages = raw_pages if isinstance(raw_pages, list) and all(isinstance(p, dict) for p in raw_pages) else []
    issues = record.get("issues", [])
    issues = issues if isinstance(issues, list) and all(isinstance(i, dict) for i in issues) else []
    open_issues = [i for i in issues if i.get("status") != "resolved"]

    def check(name: str, errors: list[str], pending: bool = False) -> None:
        checks.append({"name": name, "status": "FAILED" if errors else "NOT_RUN" if pending else "PASSED",
                       "details": list(dict.fromkeys(errors)), "policy_version": POLICY_VERSION,
                       "method": "source_review" if name in {"human_acceptance", "visual_audit"} else "deterministic"})

    integrity: list[str] = []
    expected = record.get("expected_units")
    if type(expected) is not int or not 1 <= expected <= 5000 or len(pages) != expected:
        integrity.append("Expected source unit count does not match processed units")
    if isinstance(expected, int) and 0 <= expected <= 5000 and [p.get("number") for p in pages] != list(range(1, expected + 1)):
        integrity.append("Source units are missing, duplicated or out of order")
    originals = [name for name in artifacts if name.startswith("source/original.")]
    if len(originals) != 1 or hashlib.sha256(artifacts[originals[0]]).hexdigest() != record.get("source_sha256"):
        integrity.append("Original source is missing or its checksum differs")
    if any(not safe_name(name) for name in artifacts):
        integrity.append("Unsafe evidence artifact name")
    try:
        if not isinstance(record.get("config"), dict) or digest(record["config"]) != record.get("config_sha256"):
            integrity.append("Extraction configuration checksum differs")
    except (ValueError, TypeError):
        integrity.append("Invalid extraction configuration")
    images: dict[int, tuple[int, int]] = {}
    for page in pages:
        number = page.get("number")
        path = page.get("image")
        if page.get("requires_image") and (not path or path not in artifacts):
            integrity.append(f"Page {number}: rendering missing")
        if path:
            data = artifacts.get(path)
            if data is None or hashlib.sha256(data).hexdigest() != page.get("image_sha256"):
                integrity.append(f"Page {number}: image missing or checksum mismatch")
                continue
            try:
                with Image.open(io.BytesIO(data)) as bitmap:
                    if (bitmap.width, bitmap.height) != (page.get("width_px"), page.get("height_px")) or bitmap.width * bitmap.height > 40_000_000:
                        raise ValueError("Invalid image dimensions")
                    images[number] = bitmap.size
            except (OSError, ValueError, Image.DecompressionBombError):
                integrity.append(f"Page {number}: invalid image or dimensions")
    check("source_render_integrity", integrity)

    identities: list[str] = []
    if record.get("schema_version") != 2:
        identities.append("Unsupported canonical schema")
    ids = [b.get("id") for p in pages for b in p.get("blocks", [])]
    if any(not isinstance(key, str) or not key for key in ids) or len(ids) != len(set(str(key) for key in ids)):
        identities.append("Invalid or duplicate block IDs")
    issue_ids = [i.get("id") for i in issues]
    if len(issue_ids) != len(set(str(key) for key in issue_ids)):
        identities.append("Duplicate issue IDs")
    for page in pages:
        order: list[int] = []
        for block in page.get("blocks", []):
            block_id = block.get("id", "UNKNOWN")
            order.append(block.get("reading_order", -1))
            # Existing schema-v2 blocks identify the rendered source unit with this field.
            if block.get("source_page_number") != page.get("number"):
                identities.append(f"{block_id}: incorrect source unit")
            dimensions = images.get(page.get("number"))
            if dimensions and not valid_box(block.get("bbox_px"), *dimensions):
                identities.append(f"{block_id}: invalid coordinates")
            crop = block.get("crop")
            if not crop or crop not in artifacts:
                identities.append(f"{block_id}: crop missing")
            elif block.get("crop_sha256") and hashlib.sha256(artifacts[crop]).hexdigest() != block["crop_sha256"]:
                identities.append(f"{block_id}: crop checksum mismatch")
            parent = block.get("parent_id")
            if parent and parent not in ids:
                identities.append(f"{block_id}: unknown parent region")
        if order and (any(type(n) is not int or n < 0 for n in order) or order != sorted(set(order))):
            identities.append(f"Page {page.get('number')}: invalid or duplicate reading order")
    check("schema_identity", identities)

    coverage = [f"Page {p.get('number')}: visual inventory incomplete" for p in pages if p.get("requires_image") and not p.get("inventory_complete")]
    coverage += [str(i.get("id")) for i in open_issues if i.get("code") in {"NATIVE_REGION_UNACCOUNTED", "VISUAL_INVENTORY_FAILED", "REGION_OVERLAP"}]
    for page in pages:
        if page.get("requires_image") and not page.get("blank") and not page.get("blocks"):
            coverage.append(f"Page {page.get('number')}: nonblank page has no regions")
        for block in page.get("blocks", []):
            if block.get("status") not in {"split", "candidate", "reviewed"}:
                coverage.append(f"{block.get('id')}: region reading did not complete")
    check("coverage_reconciliation", coverage)

    conflicts = [str(i.get("id")) for i in open_issues if "CONFLICT" in str(i.get("code")) or i.get("code") == "UNREADABLE_SOURCE"]
    for page in pages:
        for block in page.get("blocks", []):
            visual = block.get("visual") or {}
            native = block.get("native_text") or ""
            if block.get("status") != "split" and native and not same_text(native, visual.get("text", "")):
                if not block.get("structure_reviewed") or not current_review(record, page, page.get("primary_review")):
                    conflicts.append(f"{block.get('id')}: native/visual disagreement lacks a current source review")
    check("text_comparison", conflicts)

    tables: list[str] = []
    educational: list[str] = []
    for page in pages:
        for block in page.get("blocks", []):
            if block.get("status") == "split":
                continue
            errors = structure_errors(block)
            destination = tables if block.get("type") == "table" else educational
            destination.extend(f"{block.get('id')}: {error}" for error in errors)
            if block.get("type") in {"table", "equation", "question", "answer_key", "figure"} and not block.get("structure_reviewed"):
                educational.append(f"{block.get('id')}: source structure needs review")
    check("tables_numbers", tables + [str(i.get("id")) for i in open_issues if i.get("code") == "NUMERIC_CONFLICT"])
    check("educational_structure", educational)
    check("visual_audit", [str(i.get("id")) for i in open_issues if i.get("technical")],
          pending=any(p.get("requires_image") and not current_review(record, p, p.get("primary_review")) for p in pages))
    continuity = relationship_errors(record) + word_mapping_errors(record)
    continuity += [str(i.get("id")) for i in open_issues if i.get("code") in {"CONTINUITY_REVIEW", "SPLIT_BOUNDARY_REVIEW", "WORD_MAPPING_AMBIGUOUS"}]
    check("document_continuity", continuity)

    projections: list[str] = []
    for page in pages:
        text = page.get("selected_text")
        if not isinstance(text, str):
            projections.append(f"Page {page.get('number')}: selected source transcription is unresolved")
            continue
        if "[[UNREADABLE]]" in text:
            projections.append(f"Page {page.get('number')}: unreadable marker remains")
        blocks = [b for b in page.get("blocks", []) if b.get("status") != "split"]
        if blocks and (any(not isinstance(b.get("selected_text"), str) for b in blocks)
                       or "\n".join(b.get("selected_text") or "" for b in blocks) != text):
            projections.append(f"Page {page.get('number')}: selected blocks differ from page text")
        if page.get("source_unit") == "bytes":
            try:
                source = bytes.fromhex(page.get("bom_hex", "")) + text.encode(page["encoding"], errors="strict")
                if hashlib.sha256(source).hexdigest() != record.get("source_sha256"):
                    raise ValueError("Source differs")
                lines = page.get("lines", [])
                if "".join(line["text"] for line in lines) != text:
                    raise ValueError("Line projection differs")
                offset = len(bytes.fromhex(page.get("bom_hex", "")))
                for index, line in enumerate(lines, 1):
                    end = offset + len(line["text"].encode(page["encoding"], errors="strict"))
                    if (line.get("number"), line.get("byte_start"), line.get("byte_end")) != (index, offset, end):
                        raise ValueError("Byte offsets differ")
                    offset = end
            except (ValueError, KeyError, UnicodeError, LookupError):
                projections.append(f"Page {page.get('number')}: text/line/byte evidence differs from the original")
    check("export_consistency", projections)

    reviews: list[str] = []
    for page in pages:
        primary, second = page.get("primary_review"), page.get("second_review")
        if not current_review(record, page, primary):
            reviews.append(f"Page {page.get('number')}: primary source review missing or stale")
        if critical_page(page) and (not current_review(record, page, second) or not primary or second.get("reviewer") == primary.get("reviewer")):
            reviews.append(f"Page {page.get('number')}: independent second review missing or stale")
        if page.get("selected_text") == "" and not page.get("blank_confirmed") and not page.get("blocks"):
            reviews.append(f"Page {page.get('number')}: blank source has not been explicitly confirmed")
    reviews.extend(f"{i.get('id')}: unresolved {i.get('code')}" for i in open_issues)
    check("human_acceptance", reviews)
    return checks


def metrics(record: dict[str, Any]) -> dict[str, Any]:
    pages = record.get("pages", [])
    blocks = [b for p in pages for b in p.get("blocks", []) if b.get("status") != "split"]
    return {"expected_units": record.get("expected_units"), "processed_units": len(pages),
            "detected_regions": len(blocks), "regions_read": sum(bool(b.get("visual")) for b in blocks),
            "candidate_agreements": sum(b.get("agreement", False) for b in blocks),
            "primary_reviews": sum(current_review(record, p, p.get("primary_review")) for p in pages),
            "second_reviews": sum(current_review(record, p, p.get("second_review")) for p in pages),
            "measured_transcription_accuracy": "NOT_MEASURED",
            "issue_counts": dict(Counter(i.get("code", "UNKNOWN") for i in record.get("issues", []) if i.get("status") != "resolved"))}
