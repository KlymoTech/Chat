"""Source-fidelity contract tests. Synthetic fixtures are not accuracy benchmarks."""
from __future__ import annotations

import hashlib
import io
import json
from copy import deepcopy

import pytest
from PIL import Image

from northstar_api.services.extraction_package import ExtractionPackage, verify_review_projection
from northstar_api.services.extraction_review import apply_review
from northstar_api.services.extraction_schema import Inventory, Reading, digest, parse_response
from northstar_api.services.extraction_structure import assemble_logical, relationship_errors, table_errors
from northstar_api.services.extraction_validation import disagreement, review_digest


def text_package(text: str = "Exact source spelling.\r\n") -> ExtractionPackage:
    data = text.encode()
    offset = 0
    lines = []
    for number, line in enumerate(text.splitlines(keepends=True), 1):
        size = len(line.encode())
        lines.append({"number": number, "byte_start": offset, "byte_end": offset + size, "text": line})
        offset += size
    page = {"number": 1, "source_unit": "bytes", "native_text": text, "visual_text": None,
            "selected_text": text, "source_page_index": None, "source_page_number": None,
            "rendered_page_number": None, "requires_image": False, "image": None,
            "encoding": "utf-8", "bom_hex": "", "lines": lines, "blocks": [], "blank": not text}
    return ExtractionPackage({"schema_version": 2, "source_name": "fixture.txt", "source_sha256": hashlib.sha256(data).hexdigest(),
                              "config": {}, "config_sha256": digest({}), "expected_units": 1, "pages": [page],
                              "issues": [], "review_status": "needs_review", "correction_history": []}, {"source/original.txt": data})


def image_package(count: int = 1) -> ExtractionPackage:
    output = io.BytesIO()
    Image.new("RGB", (80, 80), "white").save(output, format="PNG")
    image = output.getvalue()
    record = text_package().record
    record.update({"source_name": "synthetic.png", "source_sha256": hashlib.sha256(image).hexdigest(), "expected_units": count, "pages": []})
    artifacts = {"source/original.png": image}
    for number in range(1, count + 1):
        reading = Reading(kind="paragraph", text="Source fragment", complete=True).model_dump()
        block = {"id": f"P{number}-R1", "type": "paragraph", "inventory_kind": "paragraph", "source_page_number": number,
                 "bbox_px": [0, 0, 80, 80], "reading_order": 0, "status": "candidate", "native_text": "",
                 "visual": reading, "selected_text": "Source fragment", "crop": f"crops/P{number}-R1.png",
                 "crop_sha256": hashlib.sha256(image).hexdigest()}
        page = {"number": number, "source_unit": "image_frame", "native_text": "", "visual_text": reading["text"],
                "selected_text": reading["text"], "image": f"pages/page_{number:04d}.png", "image_sha256": hashlib.sha256(image).hexdigest(),
                "width_px": 80, "height_px": 80, "requires_image": True, "inventory_complete": True, "blocks": [block], "blank": False}
        record["pages"].append(page)
        artifacts[page["image"]] = image
        artifacts[block["crop"]] = image
    return ExtractionPackage(record, artifacts)


def submission(page: dict) -> dict:
    return {"number": page["number"], "selected_text": page["selected_text"], "reason": "Compared against the retained source evidence.",
            "structure_confirmed": True, "blank_confirmed": not page["selected_text"],
            "blocks": [{"id": block["id"], "selected_text": block["selected_text"],
                        "structure": deepcopy(block.get("reviewed_structure") or block["visual"]),
                        "related_block_ids": list(block.get("related_block_ids", []))}
                       for block in page.get("blocks", []) if block.get("status") != "split"]}


def approve(package: ExtractionPackage, reviewer: str = "reviewer-a") -> None:
    apply_review(package.record, [submission(page) for page in package.record["pages"]], [], reviewer)
    package.refresh()


@pytest.mark.parametrize("payload", [
    '{"regions":[],"blank":true,"complete":true,"complete":false}',
    '{"regions":[],"blank":true,"complete":"true"}',
    '{"regions":[{"kind":"paragraph","bbox":[0,0,NaN,10]}],"complete":true}',
    '{"regions":[],"blank":true,"complete":true} trailing text',
])
def test_invalid_or_ambiguous_model_json_rejected(payload: str) -> None:
    with pytest.raises(ValueError):
        parse_response(payload, Inventory)


def test_valid_json_geometry_remains_supported() -> None:
    result = parse_response('{"regions":[{"kind":"paragraph","bbox":[0,0,1000,1000]}],"complete":true}', Inventory)
    assert result.regions[0].bbox == (0, 0, 1000, 1000)


@pytest.mark.parametrize(("native", "visual", "code"), [
    ("Value −12.50", "Value 12.50", "NUMERIC_CONFLICT"),
    ("Which is NOT correct?", "Which is correct?", "CRITICAL_WORD_CONFLICT"),
    ("x² ≤ y", "x₂ < y", "SYMBOL_CONFLICT"),
    ("paragraph present", "paragraph omitted", "CANDIDATE_CONFLICT"),
])
def test_critical_mutations_classified(native: str, visual: str, code: str) -> None:
    assert disagreement(native, visual) == code


def test_noncritical_text_requires_source_review() -> None:
    package = text_package()
    package.refresh()
    assert not package.record["release_eligible"]
    approve(package)
    assert package.record["release_eligible"]
    assert package.record["metrics"]["measured_transcription_accuracy"] == "NOT_MEASURED"


def test_critical_text_requires_a_distinct_second_reviewer() -> None:
    package = text_package("Do NOT omit −12.50.\n")
    approve(package)
    assert not package.record["release_eligible"]
    approve(package)
    assert not package.record["release_eligible"]
    approve(package, "reviewer-b")
    assert package.record["release_eligible"]


def test_atomic_review_rolls_back_all_pages_and_issue_decisions() -> None:
    package = image_package(2)
    package.record["issues"] = [{"id": "I1", "page": 1, "code": "CANDIDATE_CONFLICT", "status": "open", "technical": False}]
    before = deepcopy(package.record)
    edits = [submission(page) for page in package.record["pages"]]
    edits[1]["blocks"][0]["structure"]["complete"] = False
    with pytest.raises(ValueError, match="Incomplete"):
        apply_review(package.record, edits, [{"id": "I1", "action": "source_verified", "reason": "Checked image"}], "reviewer-a")
    assert package.record == before


def test_review_preserves_api_page_list_alias() -> None:
    package = text_package()
    original_pages = package.record["pages"]
    original_page = original_pages[0]
    approve(package)
    assert package.record["pages"] is original_pages
    assert package.record["pages"][0] is original_page
    assert "primary_review" in original_page


def test_partial_review_cannot_release_unreviewed_pages() -> None:
    package = image_package(2)
    apply_review(package.record, [submission(package.record["pages"][0])], [], "reviewer-a")
    package.refresh()
    assert package.record["approved_pages"] == [1]
    assert not package.record["release_eligible"]


@pytest.mark.parametrize("field", ["related_block_ids", "bbox_px", "source_fragments", "native_text", "reading_order", "type"])
def test_review_hash_binds_geometry_candidates_and_links(field: str) -> None:
    page = image_package().record["pages"][0]
    original = review_digest(page)
    page["blocks"][0][field] = "mutated"
    assert review_digest(page) != original


def test_selected_text_tampering_invalidates_release() -> None:
    package = text_package("Value −12.50\n")
    approve(package)
    approve(package, "reviewer-b")
    package.record["pages"][0]["selected_text"] = "Value 12.50\n"
    package.refresh()
    assert not package.record["release_eligible"]
    assert {"export_consistency", "human_acceptance"} <= set(package.record["release_blockers"])


def test_original_bytes_tampering_invalidates_release() -> None:
    package = text_package()
    approve(package)
    package.images["source/original.txt"] = b"different original"
    package.refresh()
    assert "source_render_integrity" in package.record["release_blockers"]


def test_line_offset_tampering_is_detected() -> None:
    package = text_package("One\r\nTwo\n")
    package.record["pages"][0]["lines"][1]["byte_start"] += 1
    package.refresh()
    assert "export_consistency" in package.record["release_blockers"]


def test_merged_grid_and_explicit_covered_cell() -> None:
    cells = [{"row": 0, "column": 0, "text": "Heading", "column_span": 2, "header": True},
             {"row": 0, "column": 1, "text": "", "state": "COVERED_BY_MERGE"},
             {"row": 1, "column": 0, "text": "left", "header_refs": ["R0C0"]},
             {"row": 1, "column": 1, "text": "right", "header_refs": ["R0C0"]}]
    assert table_errors(cells, 2, 2) == []


@pytest.mark.parametrize("cells", [
    [{"text": "missing coordinates"}],
    [{"row": True, "column": 0, "text": "boolean row"}],
    [{"row": 0, "column": 0, "text": "", "state": "COVERED_BY_MERGE"}],
    [{"row": 0, "column": 0, "text": ""}],
    [{"row": 0, "column": 0, "text": "a", "column_span": 2}, {"row": 0, "column": 1, "text": "b"}],
    [{"row": 0, "column": 0, "text": "a"}, {"row": 1, "column": 1, "text": "b"}],
    [{"row": 0, "column": 0, "text": "a", "row_span": 1000, "column_span": 1000}],
])
def test_malformed_or_unaccounted_tables_fail_without_crashing(cells: list[dict]) -> None:
    assert table_errors(cells)


def test_swapped_header_association_is_detected() -> None:
    cells = [{"row": 0, "column": 0, "text": "2025", "header": True},
             {"row": 0, "column": 1, "text": "2026", "header": True},
             {"row": 1, "column": 0, "text": "12.50", "header_refs": ["R0C1"]},
             {"row": 1, "column": 1, "text": "13.50", "header_refs": ["R0C1"]}]
    assert any("outside" in error for error in table_errors(cells))


def test_missing_header_association_is_not_silently_accepted() -> None:
    cells = [{"row": 0, "column": 0, "text": "Year", "header": True}, {"row": 1, "column": 0, "text": "2026"}]
    assert any("missing" in error for error in table_errors(cells))


def test_continuation_needs_reciprocal_adjacent_fragment() -> None:
    package = image_package(2)
    first, second = [page["blocks"][0] for page in package.record["pages"]]
    first["visual"]["continues_on_next"] = True
    first["related_block_ids"] = [second["id"]]
    assert relationship_errors(package.record)
    second["visual"]["continues_from_previous"] = True
    second["related_block_ids"] = [first["id"]]
    assert relationship_errors(package.record) == []
    first["reviewed_structure"] = first["visual"]
    second["reviewed_structure"] = second["visual"]
    logical = assemble_logical(package.record)
    assert len(logical) == 1
    assert logical[0]["block_ids"] == [first["id"], second["id"]]
    assert len(logical[0]["source_fragments"]) == 2


def test_txt_projection_detects_loss_even_when_backup_json_is_intact() -> None:
    package = text_package()
    text = package.review_text()
    verify_review_projection(text, package.record)
    damaged = "\n".join(line for line in text.splitlines() if not line.startswith("SOURCE_RECORD\t")) + "\n"
    with pytest.raises(ValueError, match="projection"):
        verify_review_projection(damaged, package.record)
    damaged = text.replace("SELECTED_TEXT:", "MISSING_TEXT:")
    with pytest.raises(ValueError, match="projection"):
        verify_review_projection(damaged, package.record)


def test_archive_is_deterministic_and_complete() -> None:
    import zipfile

    package = text_package("Delimiter | tab\t [[ISSUE]]\nCANONICAL_RECORD\tmalicious-looking-source\n")
    first, second = package.archive(), package.archive()
    assert first == second
    with zipfile.ZipFile(io.BytesIO(first)) as archive:
        manifest = json.loads(archive.read("manifest.json"))
        assert set(archive.namelist()) == set(manifest["artifacts"]) | {"manifest.json"}
        for name, checksum in manifest["artifacts"].items():
            assert hashlib.sha256(archive.read(name)).hexdigest() == checksum
        assert b"NOT_MEASURED" in archive.read("validation_report.txt")


def test_technical_failure_cannot_be_waived_by_a_reviewer() -> None:
    package = text_package()
    package.record["issues"] = [{"id": "I1", "page": 1, "code": "RENDER_FAILED", "status": "open", "technical": True}]
    before = deepcopy(package.record)
    with pytest.raises(ValueError, match="reprocessing"):
        apply_review(package.record, [submission(package.record["pages"][0])], [{"id": "I1", "action": "source_verified", "reason": "Trust me"}], "reviewer-a")
    assert package.record == before


def test_word_mapping_cannot_be_resolved_by_waiving_an_issue() -> None:
    package = image_package()
    package.record["word"] = {"blocks": [{"id": "W000001", "part": "word/document.xml", "channel": "current", "type": "paragraph",
                                         "text": "Source fragment", "mapping_status": "ambiguous", "rendered_pages": []}]}
    package.record["issues"] = [{"id": "Iword", "page": 0, "code": "WORD_MAPPING_AMBIGUOUS", "status": "open", "technical": False}]
    apply_review(package.record, [submission(package.record["pages"][0])],
                 [{"id": "Iword", "action": "source_verified", "reason": "Confirmed against source"}], "reviewer-a")
    package.refresh()
    assert "document_continuity" in package.record["release_blockers"]
    edit = submission(package.record["pages"][0])
    edit["blocks"][0]["related_block_ids"] = ["W000001"]
    apply_review(package.record, [edit], [], "reviewer-a")
    package.refresh()
    logical = package.record["word"]["blocks"][0]
    assert logical["mapping_status"] == "source_reviewed"
    assert logical["rendered_pages"] == [1]
    assert package.record["release_eligible"]


def test_evidence_cannot_override_reserved_export_names() -> None:
    package = text_package()
    package.images["extracted.json"] = b"{}"
    with pytest.raises(ValueError, match="reserved"):
        package.archive()
