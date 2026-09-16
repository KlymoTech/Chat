"""Exact-match benchmark against explicitly human-adjudicated source annotations."""
from __future__ import annotations

from typing import Any

from northstar_api.services.extraction_schema import digest
from northstar_api.services.extraction_validation import disagreement


def benchmark(record: dict[str, Any], truth: dict[str, Any]) -> dict[str, Any]:
    if truth.get("adjudicated") is not True or not truth.get("reviewer"):
        raise ValueError("Benchmark truth must be explicitly human-adjudicated")
    if truth.get("source_sha256") != record.get("source_sha256"):
        raise ValueError("Benchmark truth belongs to a different source")
    expected = truth.get("blocks")
    if not isinstance(expected, list) or not expected or len(expected) > 100000:
        raise ValueError("Provide bounded source block annotations")
    if any(not isinstance(block, dict) or not isinstance(block.get("id"), str) for block in expected):
        raise ValueError("Every truth block needs a stable source block ID")
    if len({block["id"] for block in expected}) != len(expected):
        raise ValueError("Duplicate ground-truth block IDs")
    actual = {block["id"]: block for page in record["pages"] for block in page.get("blocks", []) if block.get("status") != "split"}
    counts = {name: {"matched": 0, "expected": 0} for name in (
        "block_recall", "text_exact_match", "critical_token_fidelity", "table_cell_exact_match",
        "header_associations", "equation_exact_match", "question_answer_linkage", "reading_order",
    )}
    failures = []

    def score(metric: str, matched: bool, source_id: str) -> None:
        counts[metric]["expected"] += 1
        counts[metric]["matched"] += int(matched)
        if not matched:
            failures.append({"metric": metric, "block_id": source_id})

    actual_order = list(actual)
    expected_order = [block["id"] for block in expected]
    for annotated in expected:
        identifier = annotated["id"]
        found = actual.get(identifier)
        score("block_recall", found is not None, identifier)
        structure = (found or {}).get("reviewed_structure") or (found or {}).get("visual") or {}
        if "text" in annotated:
            if not isinstance(annotated["text"], str):
                raise ValueError("Truth text must be a string")
            selected = (found or {}).get("selected_text")
            score("text_exact_match", selected == annotated["text"], identifier)
            score("critical_token_fidelity", found is not None and disagreement(annotated["text"], selected or "") not in
                  {"NUMERIC_CONFLICT", "CRITICAL_WORD_CONFLICT", "SYMBOL_CONFLICT"}, identifier)
        score("reading_order", identifier in actual_order and [key for key in actual_order if key in expected_order].index(identifier) == expected_order.index(identifier), identifier)
        for cell in annotated.get("cells", []):
            matches = [candidate for candidate in structure.get("cells", []) if (candidate["row"], candidate["column"]) == (cell["row"], cell["column"])]
            candidate = matches[0] if len(matches) == 1 else {}
            score("table_cell_exact_match", bool(candidate) and all(candidate.get(key, 1 if key.endswith("span") else None) == cell[key]
                  for key in ("text", "state", "row_span", "column_span", "unit") if key in cell), identifier)
            if "header_refs" in cell:
                score("header_associations", candidate.get("header_refs") == cell["header_refs"], identifier)
        for key, metric in (("latex", "equation_exact_match"), ("related_block_ids", "question_answer_linkage")):
            if key in annotated:
                value = (found or {}).get(key) if key == "related_block_ids" else structure.get(key)
                score(metric, value == annotated[key], identifier)
    return {"source_sha256": record["source_sha256"], "ground_truth_sha256": digest(truth),
            "reviewer": truth["reviewer"], "scope": "ANNOTATED_BLOCKS_ONLY", "failures": failures,
            "metrics": {name: {**value, "rate": value["matched"] / value["expected"] if value["expected"] else None,
                                "status": "MEASURED" if value["expected"] else "NOT_MEASURED"} for name, value in counts.items()},
            "unannotated_extracted_blocks": sorted(set(actual) - set(expected_order)),
            "universal_accuracy_claim": False}
