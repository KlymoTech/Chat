"""Accuracy gate: the offline gold-set benchmark must not regress.

Runs without a vision model or OCR (as in CI), so it pins the deterministic core: layout,
reading order, table cells, text-layer drafts, and that nothing wrong is ever auto-accepted.
"""

import json

import fitz
import pytest

from northstar_api.config import Settings
from northstar_api.evaluation import benchmark
from northstar_api.evaluation.gold import gold_documents
from northstar_api.evaluation.scoring import cer, reading_order, table_cell_accuracy, wer
from northstar_api.services import extraction_reconcile as reconcile
from northstar_api.services import hybrid_extraction as hybrid
from northstar_api.services.extraction_regions import reading_order as order_regions
from northstar_api.services.extraction_tables import find_table_zones, table_grid, table_text


@pytest.fixture
def settings():
    return Settings(_env_file=None, extraction_render_dpi=150, extraction_ocr_enabled=False)


async def test_offline_gold_benchmark_meets_the_accuracy_gate(settings):
    report = await benchmark.run(settings, include_scanned=False)
    summary = report["summary"]
    pages = [p for d in report["documents"] for p in d["pages"]]
    assert summary["false_accepts"] == 0, json.dumps([p["false_accepts"] for p in pages if p["false_accepts"]])
    assert all(p["cer"] == 0 for p in pages), [(d["name"], p["cer"]) for d in report["documents"] for p in d["pages"]]
    assert all(p["reading_order"] == 1 for p in pages)
    assert summary["mean_table_cell_accuracy"] == 1
    assert summary["technical_issues"] == 0


def test_scoring_metrics():
    assert cer("Value -12.50", "Value -12.50") == 0
    assert cer("Value -12.50", "Value 12.50") == pytest.approx(1 / 12)
    assert wer("a b c d", "a x c d") == 0.25
    assert table_cell_accuracy([["A", "B"], ["1", "2"]], [
        {"row": 0, "column": 0, "text": "A"}, {"row": 0, "column": 1, "text": "B"},
        {"row": 1, "column": 0, "text": "1"}, {"row": 1, "column": 1, "text": "3"}]) == 0.75
    assert reading_order(["first", "second", "third"], "first third second") == pytest.approx(2 / 3)


def _words(pdf: bytes) -> list[dict]:
    with fitz.open(stream=pdf, filetype="pdf") as doc:
        return [{"text": w[4], "bbox_px": list(w[:4]), "line": [w[5], w[6]]} for w in doc[0].get_text("words")]


@pytest.mark.parametrize("name", ["table-ruled", "table-striped", "table-whitespace"])
def test_table_grid_recovers_every_cell(name):
    document = next(d for d in gold_documents(include_scanned=False) if d.name == name)
    truth = next(b for b in document.pages[0].blocks if "rows" in b)
    x0, y0, x1, y1 = truth["bbox_pt"]
    inside = [w for w in _words(document.pdf) if x0 <= (w["bbox_px"][0] + w["bbox_px"][2]) / 2 <= x1
              and y0 <= (w["bbox_px"][1] + w["bbox_px"][3]) / 2 <= y1]
    grid = table_grid(inside)
    assert grid and table_cell_accuracy(truth["rows"], grid["cells"]) == 1
    assert table_text(grid).splitlines()[0] == " | ".join(truth["rows"][0])


def test_two_column_body_text_is_not_mistaken_for_a_table():
    document = next(d for d in gold_documents(include_scanned=False) if d.name == "two-column")
    assert find_table_zones(_words(document.pdf)) == []


def test_reading_order_reads_columns_before_moving_across():
    regions = [("h", [0, 0, 900, 50]), ("p", [0, 60, 420, 200]), ("p", [480, 60, 900, 200]),
               ("p", [0, 210, 420, 300]), ("p", [480, 210, 900, 300]), ("f", [0, 400, 900, 440])]
    assert [r[1][:2] for r in order_regions(regions)] == [
        [0, 0], [0, 60], [0, 210], [480, 60], [480, 210], [0, 400]]


async def test_clean_pdf_gets_structured_regions_and_still_auto_releases(settings):
    with fitz.open() as pdf:
        page = pdf.new_page()
        page.insert_text((50, 60), "Staff travel policy", fontsize=20, fontname="hebo")
        body = ("Employees may book standard class rail tickets for journeys longer than two hours. Receipts "
                "must be submitted within thirty days of travel through the expenses portal. ")
        page.insert_textbox(fitz.Rect(50, 90, 545, 400), body * 3, fontsize=11)
        raw = pdf.tobytes()
    package = await hybrid.extract_document(raw, "clean.pdf", settings)
    blocks = package.record["pages"][0]["blocks"]
    assert package.record["review_status"] == "verified_release" and package.record["release_eligible"]
    assert blocks[0]["type"] == "heading" and blocks[0]["heading_level"] == 1
    assert blocks[0]["style"]["bold"] and blocks[0]["style"]["font_size_px"] > blocks[1]["style"]["font_size_px"]
    assert all(b["consensus"] == "text_layer" for b in blocks)


async def test_table_cells_are_checked_against_ocr_one_by_one(monkeypatch, settings):
    document = next(d for d in gold_documents(include_scanned=False) if d.name == "table-striped")
    scale = settings.extraction_render_dpi / 72

    async def ocr(image, _settings):
        words = []
        for index, word in enumerate(_words(document.pdf)):
            text = "58" if word["text"] == "480" and index % 2 else word["text"]  # OCR misreads one cell
            words.append({"text": text, "bbox_px": [round(v * scale) for v in word["bbox_px"]],
                          "confidence": 95.0, "line": [*word["line"], 0], "order": index})
        return {"engine": "tesseract", "version": "test", "status": "complete", "words": words}

    async def no_region(image, box, _settings):
        return None

    async def failed(_):
        return {"status": "FAILED"}, b""

    monkeypatch.setattr(hybrid, "ocr_page", ocr)
    monkeypatch.setattr(reconcile, "ocr_region", no_region)
    monkeypatch.setattr(hybrid, "verify_image_capability", failed)
    monkeypatch.setattr(hybrid, "native_page_quality", lambda native, details: {
        "score": 0.5, "reasons": ["forced"], "vision_required": True, "review_required": True,
        "method": "native_text_then_visual", "native_character_count": 1, "native_word_count": 1,
        "native_figure_count": 0, "native_table_count": 0, "formula_detected": False})
    package = await hybrid.extract_document(document.pdf, "striped.pdf", settings.model_copy(update={"extraction_ocr_enabled": True}))
    table = next(b for b in package.record["pages"][0]["blocks"] if b["type"] == "table")
    differing = [c for c in table["cell_checks"] if not c["confirmed"]]
    assert len(differing) == 1 and differing[0]["pdf"] == "480" and differing[0]["ocr"] == "58"
    issue = next(i for i in package.issues if i.get("block_id") == table["id"])
    assert "1 table cell differs" in issue["message"] or "1 table cell" in issue["message"]
    assert not issue["technical"]
    assert table["proposed_structure"]["cells"][0]["header"]  # draft keeps the grid for the editor


def test_ocr_confirmation_tolerates_only_superscript_misreads():
    from northstar_api.services.extraction_validation import ocr_confirms

    assert ocr_confirms("Area (m\u00b2) Plants", "Area (m7?) Plants")
    assert ocr_confirms("600 m\u00b2 of growing area", "600 m? of growing area")
    assert not ocr_confirms("600 m\u00b2 of growing area", "800 m? of growing area")
    assert not ocr_confirms("x\u00b2", "x123")


def test_running_header_parts_on_one_line_become_separate_regions():
    from northstar_api.services.extraction_regions import _side_by_side

    words = [{"text": "AGRICULTURE", "bbox_px": [300, 140, 520, 180]},
             {"text": "AGR-101", "bbox_px": [1900, 140, 2010, 180]}, {"text": "|", "bbox_px": [2020, 140, 2030, 180]},
             {"text": "KNOWLEDGE", "bbox_px": [2040, 140, 2200, 180]}]
    assert _side_by_side([300, 140, 2200, 180], words) == [[300, 140, 520, 180], [1900, 140, 2200, 180]]
    paragraph = [{"text": t, "bbox_px": [100 + i * 90, 100, 170 + i * 90, 130]} for i, t in enumerate("a normal line of text".split())]
    assert _side_by_side([100, 100, 600, 130], paragraph) == [[100, 100, 600, 130]]
