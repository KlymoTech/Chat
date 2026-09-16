"""Bounded table occupancy and explicit, source-linked document assembly."""
from __future__ import annotations

from typing import Any

from northstar_api.services.extraction_schema import Cell, Reading, digest

MAX_GRID_POSITIONS = 100_000


def table_errors(cells: list[dict[str, Any]], rows: int | None = None, columns: int | None = None) -> list[str]:
    errors: list[str] = []
    if not isinstance(cells, list) or not cells or len(cells) > 1000:
        return ["Table must contain between 1 and 1000 cells"]
    parsed: list[Cell] = []
    for value in cells:
        try:
            parsed.append(Cell.model_validate(value))
        except (ValueError, TypeError):
            errors.append("Invalid cell schema")
    if errors:
        return errors
    work = sum(c.row_span * c.column_span for c in parsed)
    if work > MAX_GRID_POSITIONS or any(c.row_span * c.column_span > 10000 for c in parsed):
        return ["Table spans exceed safe grid limits"]
    coordinates = [(c.row, c.column) for c in parsed]
    if len(coordinates) != len(set(coordinates)):
        errors.append("Duplicate cell coordinates")
    occupied: dict[tuple[int, int], str] = {}
    headers = {f"R{c.row}C{c.column}": c for c in parsed if c.header and c.state != "COVERED_BY_MERGE"}
    for cell in parsed:
        key = f"R{cell.row}C{cell.column}"
        if cell.state in {"UNREADABLE", "AMBIGUOUS", "STRUCTURE_UNKNOWN"}:
            errors.append(f"{key}: unresolved cell")
        if cell.state == "COVERED_BY_MERGE":
            continue
        for row in range(cell.row, cell.row + cell.row_span):
            for column in range(cell.column, cell.column + cell.column_span):
                if (row, column) in occupied:
                    errors.append(f"{key}: overlapping span")
                occupied[row, column] = key
        if len(cell.header_refs) != len(set(cell.header_refs)):
            errors.append(f"{key}: duplicate header reference")
        if headers and not cell.header and cell.state == "VALUE" and not cell.header_refs:
            errors.append(f"{key}: header associations are missing")
        for reference in cell.header_refs:
            header = headers.get(reference)
            if header is None or reference == key:
                errors.append(f"{key}: invalid header reference {reference}")
                continue
            col_overlap = cell.column < header.column + header.column_span and header.column < cell.column + cell.column_span
            row_overlap = cell.row < header.row + header.row_span and header.row < cell.row + cell.row_span
            if not (col_overlap or row_overlap):
                errors.append(f"{key}: header {reference} is outside this row and column")
    if occupied:
        inferred_rows = max(r for r, _ in occupied) + 1
        inferred_columns = max(c for _, c in occupied) + 1
        height = inferred_rows if rows is None else rows
        width = inferred_columns if columns is None else columns
        if type(height) is not int or type(width) is not int or height <= 0 or width <= 0:
            errors.append("Invalid declared table dimensions")
        elif height * width > MAX_GRID_POSITIONS:
            errors.append("Table dimensions exceed safe grid limits")
        elif height != inferred_rows or width != inferred_columns or height * width != len(occupied):
            errors.append("Table grid has unaccounted positions or incorrect declared dimensions")
    for cell in parsed:
        if cell.state == "COVERED_BY_MERGE":
            owner = occupied.get((cell.row, cell.column))
            if owner is None or owner == f"R{cell.row}C{cell.column}":
                errors.append("Covered position has no distinct spanning owner")
    return list(dict.fromkeys(errors))


def leaf_blocks(record: dict[str, Any]) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    return [(page, block) for page in record.get("pages", []) for block in page.get("blocks", [])
            if block.get("status") != "split"]


def structure_errors(block: dict[str, Any]) -> list[str]:
    raw = block.get("reviewed_structure") or block.get("visual")
    if not raw:
        return ["Visual reading is missing"]
    try:
        reading = Reading.model_validate(raw)
    except (ValueError, TypeError):
        return ["Invalid structured reading"]
    errors = []
    if not reading.complete:
        errors.append("Structured reading is incomplete")
    if reading.uncertain or "[[UNREADABLE]]" in reading.text:
        errors.append("Source uncertainty remains")
    if reading.kind != block.get("type"):
        errors.append("Region kind differs from its structured reading")
    if block.get("selected_text") is not None and reading.text != block["selected_text"]:
        errors.append("Structured text differs from selected text")
    if reading.kind == "table":
        errors.extend(table_errors([c.model_dump() for c in reading.cells], reading.table_row_count, reading.table_column_count))
    return errors


def relationship_errors(record: dict[str, Any]) -> list[str]:
    """Never invent a continuation or an answer-key match from semantic similarity."""
    pairs = leaf_blocks(record)
    by_id = {block["id"]: (page, block) for page, block in pairs}
    word_ids = {block["id"] for block in record.get("word", {}).get("blocks", [])}
    errors: list[str] = []
    for page, block in pairs:
        references = block.get("related_block_ids", [])
        if not isinstance(references, list) or any(not isinstance(ref, str) for ref in references):
            errors.append(f"{block['id']}: invalid source relationships")
            continue
        if len(references) != len(set(references)):
            errors.append(f"{block['id']}: duplicate source relationship")
        if any((ref not in by_id and ref not in word_ids) or ref == block["id"] for ref in references):
            errors.append(f"{block['id']}: unknown, split, or identical related block")
        structure = block.get("reviewed_structure") or block.get("visual") or {}
        for flag, offset, reciprocal in (
            ("continues_from_previous", -1, "continues_on_next"),
            ("continues_on_next", 1, "continues_from_previous"),
        ):
            if not structure.get(flag):
                continue
            matches = []
            for ref in references:
                if ref not in by_id:
                    continue
                other_page, other = by_id[ref]
                other_structure = other.get("reviewed_structure") or other.get("visual") or {}
                if (other_page["number"] == page["number"] + offset and other["type"] == block["type"]
                        and other_structure.get(reciprocal) and block["id"] in other.get("related_block_ids", [])):
                    matches.append(ref)
            if len(matches) != 1:
                errors.append(f"{block['id']}: {flag} requires one reciprocal adjacent-page fragment of the same type")
    return errors


def assemble_logical(record: dict[str, Any]) -> list[dict[str, Any]]:
    """Keep physical fragments intact; join only explicitly reviewed continuations."""
    pairs = leaf_blocks(record)
    by_id = {b["id"]: (p, b) for p, b in pairs}
    parents = {key: key for key in by_id}

    def root(key: str) -> str:
        while parents[key] != key:
            parents[key] = parents[parents[key]]
            key = parents[key]
        return key

    for page, block in pairs:
        structure = block.get("reviewed_structure") or {}
        if not structure.get("continues_on_next"):
            continue
        for ref in block.get("related_block_ids", []):
            if ref not in by_id:
                continue
            other_page, other = by_id[ref]
            if (other_page["number"] == page["number"] + 1 and other["type"] == block["type"]
                    and (other.get("reviewed_structure") or {}).get("continues_from_previous")
                    and block["id"] in other.get("related_block_ids", [])):
                parents[root(ref)] = root(block["id"])
    groups: dict[str, list[tuple[dict[str, Any], dict[str, Any]]]] = {}
    for page, block in pairs:
        groups.setdefault(root(block["id"]), []).append((page, block))
    result = []
    for fragments in groups.values():
        ids = [block["id"] for _, block in fragments]
        result.append({
            "id": "L-" + digest(ids)[:20], "type": fragments[0][1]["type"], "block_ids": ids,
            "source_fragments": [{"unit": p["number"], "block_id": b["id"],
                                  "bbox_px": b.get("bbox_px"), "crop": b.get("crop")} for p, b in fragments],
            "selected_fragments": [b.get("selected_text") for _, b in fragments],
            "assembly_basis": "reviewed_reciprocal_continuation" if len(ids) > 1 else "physical_fragment",
        })
    return result


def word_mapping_errors(record: dict[str, Any]) -> list[str]:
    pairs = leaf_blocks(record)
    by_id = {block["id"]: (page, block) for page, block in pairs}
    errors = []
    for block in record.get("word", {}).get("blocks", []):
        if block.get("part") != "word/document.xml" or block.get("channel") != "current" or not block.get("text", "").strip():
            continue
        status = block.get("mapping_status")
        if status == "source_reviewed":
            refs = block.get("mapping_evidence_block_ids", [])
            if (not refs or any(ref not in by_id or block["id"] not in by_id[ref][1].get("related_block_ids", []) for ref in refs)
                    or not block.get("mapping_review_reason")):
                errors.append(f"{block['id']}: logical Word mapping has no current source evidence")
            elif sorted({by_id[ref][0]["number"] for ref in refs}) != block.get("rendered_pages"):
                errors.append(f"{block['id']}: logical Word mapping refers to incorrect rendered pages")
        elif status != "matched" or len(block.get("rendered_pages", [])) != 1:
            errors.append(f"{block['id']}: logical Word source requires an explicit rendered-page mapping")
    return errors
