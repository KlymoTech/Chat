"""Deterministic checks; agreement and coverage are never reported as accuracy."""

from __future__ import annotations

import hashlib
import re
from collections import Counter
from typing import Any

from northstar_api.services.extraction_schema import Cell, digest

CRITICAL = re.compile(r"\d|\b(?:NOT|EXCEPT|least|most|incorrect)\b|[=<>\u2264\u2265\u00b2\u2082]", re.I)


def same_text(left: str, right: str) -> bool:
    return re.sub(r"\s+", " ", left).strip() == re.sub(r"\s+", " ", right).strip()


def disagreement(native: str, visual: str) -> str:
    if re.findall(r"[-+\u2212]?\d+(?:[.,]\d+)*", native) != re.findall(r"[-+\u2212]?\d+(?:[.,]\d+)*", visual):
        return "NUMERIC_CONFLICT"
    if re.findall(r"\b(?:NOT|EXCEPT|least|most|incorrect)\b", native, re.I) != re.findall(r"\b(?:NOT|EXCEPT|least|most|incorrect)\b", visual, re.I):
        return "CRITICAL_WORD_CONFLICT"
    return "CANDIDATE_CONFLICT"


def critical_page(page: dict[str, Any]) -> bool:
    return bool(CRITICAL.search(page.get("native_text", "") + (page.get("visual_text") or ""))) or any(
        block["type"] in {"table", "equation", "question", "answer_key"} for block in page.get("blocks", [])
    )


def review_digest(page: dict[str, Any]) -> str:
    return digest({"number": page["number"], "image": page.get("image_sha256"),
                   "selected_text": page.get("selected_text"),
                   "blocks": [{"id": b["id"], "selected_text": b.get("selected_text"),
                               "reviewed_structure": b.get("reviewed_structure")} for b in page.get("blocks", [])]})


def table_errors(cells: list[dict[str, Any]]) -> list[str]:
    errors: list[str] = []
    occupied: dict[tuple[int, int], str] = {}
    headers = {f"R{c['row']}C{c['column']}" for c in cells if c.get("header")}
    if not cells:
        return ["Table has no cells"]
    if any(c.get("row_span", 1) * c.get("column_span", 1) > 10000 for c in cells):
        return ["Table spans exceed safe grid limits"]
    for value in cells:
        try:
            cell = Cell.model_validate(value)
        except ValueError:
            errors.append("Invalid cell schema")
            continue
        key = f"R{cell.row}C{cell.column}"
        if cell.state in {"UNREADABLE", "AMBIGUOUS", "STRUCTURE_UNKNOWN"}:
            errors.append(f"{key}: unresolved cell")
        if cell.state == "BLANK" and cell.text:
            errors.append(f"{key}: blank cell contains text")
        if cell.state == "COVERED_BY_MERGE":
            continue
        for row in range(cell.row, cell.row + cell.row_span):
            for column in range(cell.column, cell.column + cell.column_span):
                if (row, column) in occupied:
                    errors.append(f"{key}: overlapping span")
                occupied[row, column] = key
        if any(ref not in headers for ref in cell.header_refs):
            errors.append(f"{key}: unknown header reference")
    if occupied:
        rows = max(r for r, _ in occupied) + 1
        cols = max(c for _, c in occupied) + 1
        if rows * cols != len(occupied):
            errors.append("Table grid has unaccounted positions")
    for cell in cells:
        if cell.get("state") == "COVERED_BY_MERGE" and (cell["row"], cell["column"]) not in occupied:
            errors.append("Covered position has no spanning cell")
    return errors


def validate(record: dict[str, Any], artifacts: dict[str, bytes]) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    pages = record.get("pages", [])
    issues = record.get("issues", [])
    open_issues = [i for i in issues if i.get("status") != "resolved"]

    def check(name: str, errors: list[str], pending: bool = False) -> None:
        checks.append({"name": name, "status": "FAILED" if errors else "NOT_RUN" if pending else "PASSED",
                       "details": errors, "method": "deterministic" if name != "human_acceptance" else "source_review"})

    integrity = []
    if not pages or len(pages) != record.get("expected_units"):
        integrity.append("Expected source unit count does not match processed units")
    if [p["number"] for p in pages] != list(range(1, record.get("expected_units", 0) + 1)):
        integrity.append("Source units are missing, duplicated or out of order")
    for page in pages:
        if page.get("requires_image") and not page.get("image"):
            integrity.append(f"Page {page['number']}: rendering missing")
        if page.get("image") and hashlib.sha256(artifacts.get(page["image"], b"")).hexdigest() != page.get("image_sha256"):
            integrity.append(f"Page {page['number']}: image missing or checksum mismatch")
    check("source_render_integrity", integrity)

    identities = []
    ids = [b["id"] for p in pages for b in p.get("blocks", [])]
    if len(ids) != len(set(ids)):
        identities.append("Duplicate block IDs")
    for page in pages:
        for block in page.get("blocks", []):
            if block.get("source_page_number") != page["number"]:
                identities.append(f"{block['id']}: incorrect source page")
            box = block.get("bbox_px")
            if box and not (0 <= box[0] < box[2] <= page["width_px"] and 0 <= box[1] < box[3] <= page["height_px"]):
                identities.append(f"{block['id']}: invalid coordinates")
            if block.get("crop") and block["crop"] not in artifacts:
                identities.append(f"{block['id']}: crop missing")
    check("schema_identity", identities)
    coverage = [f"Page {p['number']}: visual inventory incomplete" for p in pages if p.get("requires_image") and not p.get("inventory_complete")]
    coverage += [i["id"] for i in open_issues if i["code"] in {"NATIVE_REGION_UNACCOUNTED", "VISUAL_INVENTORY_FAILED", "REGION_OVERLAP"}]
    check("coverage_reconciliation", coverage)
    check("text_comparison", [i["id"] for i in open_issues if "CONFLICT" in i["code"] or i["code"] == "UNREADABLE_SOURCE"])

    tables, educational = [], []
    for page in pages:
        for block in page.get("blocks", []):
            structure = block.get("reviewed_structure") or block.get("visual") or {}
            if block["type"] == "table" and block.get("status") != "split":
                tables.extend(f"{block['id']}: {e}" for e in table_errors(structure.get("cells", [])))
            if structure.get("uncertain") or "[[UNREADABLE]]" in (block.get("selected_text") or ""):
                educational.append(f"{block['id']}: uncertainty remains")
            if block["type"] in {"equation", "question", "answer_key", "figure"} and not block.get("structure_reviewed"):
                educational.append(f"{block['id']}: source structure needs review")
    check("tables_numbers", tables + [i["id"] for i in open_issues if i["code"] == "NUMERIC_CONFLICT"])
    check("educational_structure", educational)
    check("visual_audit", [i["id"] for i in open_issues if i.get("technical")],
          pending=any(p.get("requires_image") and not p.get("primary_review") for p in pages))
    check("document_continuity", [i["id"] for i in open_issues if i["code"] in {"CONTINUITY_REVIEW", "SPLIT_BOUNDARY_REVIEW", "WORD_MAPPING_AMBIGUOUS"}])

    projections = []
    for page in pages:
        if page.get("selected_text") is not None and page.get("blocks"):
            values = [b.get("selected_text") for b in page["blocks"] if b.get("status") != "split"]
            if any(v is None for v in values) or "\n".join(v or "" for v in values) != page["selected_text"]:
                projections.append(f"Page {page['number']}: selected blocks differ from page text")
    check("export_consistency", projections)
    reviews = []
    for page in pages:
        primary, second = page.get("primary_review"), page.get("second_review")
        expected = review_digest(page)
        if not primary or primary.get("content_sha256") != expected:
            reviews.append(f"Page {page['number']}: primary source review missing or stale")
        if critical_page(page) and (not second or second.get("content_sha256") != expected or not primary or second.get("reviewer") == primary.get("reviewer")):
            reviews.append(f"Page {page['number']}: independent second review missing or stale")
    reviews.extend(f"{i['id']}: unresolved {i['code']}" for i in open_issues)
    check("human_acceptance", reviews)
    return checks


def metrics(record: dict[str, Any]) -> dict[str, Any]:
    pages = record["pages"]
    blocks = [b for p in pages for b in p.get("blocks", []) if b.get("status") != "split"]
    return {"expected_units": record["expected_units"], "processed_units": len(pages),
            "detected_regions": len(blocks), "regions_read": sum(bool(b.get("visual")) for b in blocks),
            "candidate_agreements": sum(b.get("agreement", False) for b in blocks),
            "primary_reviews": sum(bool(p.get("primary_review")) for p in pages),
            "second_reviews": sum(bool(p.get("second_review")) for p in pages),
            "measured_transcription_accuracy": "NOT_MEASURED",
            "issue_counts": dict(Counter(i["code"] for i in record["issues"] if i.get("status") != "resolved"))}
