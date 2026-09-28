"""Reading only the area of a page that a reviewer selects."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import HTTPException

from northstar_api.config import Settings
from northstar_api.routers import knowledge_extraction_area as route
from northstar_api.services import extraction_area as area


def _word(text, x0, y0, x1, y1, line):
    return {"text": text, "bbox_px": [x0, y0, x1, y1], "line": line, "confidence": 95.0, "order": x0}


PAGE = {
    "number": 1, "width_px": 1000, "height_px": 1400, "image": "pages/page_0001.png",
    "native_words": [
        _word("Site", 100, 100, 150, 130, [1, 0]), _word("AGR-01:", 160, 100, 260, 130, [1, 0]),
        _word("600", 270, 100, 320, 130, [1, 0]), _word("m²", 330, 100, 370, 130, [1, 0]),
        _word("Other", 100, 300, 180, 330, [2, 0]),
    ],
}


@pytest.fixture
def settings():
    return Settings(_env_file=None, extraction_ocr_enabled=True)


def _ocr(words):
    async def read(image, box, settings):
        return {"text": " ".join(w["text"] for w in words), "words": words}
    return read


async def test_reads_only_the_selected_area_and_confirms_it(monkeypatch, settings):
    monkeypatch.setattr(area, "ocr_region", _ocr([_word("Site", 100, 100, 150, 130, [1, 1, 1]),
                                                  _word("AGR-01:", 160, 100, 260, 130, [1, 1, 1]),
                                                  _word("600", 270, 100, 320, 130, [1, 1, 1]),
                                                  _word("m?", 330, 100, 370, 130, [1, 1, 1])]))
    result = await area.extract_area(PAGE, b"png", [90, 90, 400, 140], settings)
    assert result["readings"]["pdf_text"] == "Site AGR-01: 600 m²"
    assert "Other" not in result["readings"]["pdf_text"]  # outside the box
    assert result["suggestion"] == {"text": "Site AGR-01: 600 m²", "source": "pdf_text_confirmed_by_ocr", "confirmed": True}
    assert [w["text"] for w in result["words"]] == ["Site", "AGR-01:", "600", "m²"]


async def test_unconfirmed_pdf_text_is_offered_but_flagged(monkeypatch, settings):
    monkeypatch.setattr(area, "ocr_region", _ocr([_word("Site", 100, 100, 150, 130, [1, 1, 1]),
                                                  _word("AGR-01:", 160, 100, 260, 130, [1, 1, 1]),
                                                  _word("800", 270, 100, 320, 130, [1, 1, 1])]))
    result = await area.extract_area(PAGE, b"png", [90, 90, 400, 140], settings)
    assert result["suggestion"]["source"] == "pdf_text_unconfirmed" and not result["suggestion"]["confirmed"]


async def test_vision_is_only_called_on_request_and_can_confirm(monkeypatch, settings):
    monkeypatch.setattr(area, "ocr_region", _ocr([]))
    vision = AsyncMock(return_value={"raw": json.dumps({"kind": "paragraph", "text": "Site AGR-01: 600 m²", "complete": True}),
                                     "finish_reason": "stop"})
    monkeypatch.setattr(area, "read_evidence", vision)
    monkeypatch.setattr(area, "crop_image", lambda image, box: b"crop")
    without = await area.extract_area(PAGE, b"png", [90, 90, 400, 140], settings)
    vision.assert_not_awaited()
    assert without["readings"]["vision_status"] == "not_requested"
    with_vision = await area.extract_area(PAGE, b"png", [90, 90, 400, 140], settings, use_vision=True)
    assert with_vision["suggestion"]["source"] == "pdf_text_confirmed_by_vision"


async def test_scanned_area_uses_ocr_and_vision_agreement(monkeypatch, settings):
    scan = {**PAGE, "native_words": []}
    monkeypatch.setattr(area, "ocr_region", _ocr([_word("Tank", 100, 100, 160, 130, [1, 1, 1]), _word("T-01", 170, 100, 230, 130, [1, 1, 1])]))
    monkeypatch.setattr(area, "read_evidence", AsyncMock(return_value={
        "raw": json.dumps({"kind": "paragraph", "text": "Tank T-01", "complete": True}), "finish_reason": "stop"}))
    monkeypatch.setattr(area, "crop_image", lambda image, box: b"crop")
    result = await area.extract_area(scan, b"png", [90, 90, 400, 140], settings, use_vision=True)
    assert result["suggestion"] == {"text": "Tank T-01", "source": "ocr_confirmed_by_vision", "confirmed": True}


async def test_table_cells_in_the_area_are_read_one_by_one(monkeypatch, settings):
    ocr_words = [_word("240", 100, 100, 150, 130, [1, 1, 1]), _word("58", 300, 100, 340, 130, [1, 1, 1])]
    page = {**PAGE, "native_words": [_word("240", 100, 100, 150, 130, [1, 0]), _word("480", 300, 100, 350, 130, [1, 0])]}
    monkeypatch.setattr(area, "ocr_region", _ocr(ocr_words))
    result = await area.extract_area(page, b"png", [90, 90, 400, 140], settings, cells=[
        {"row": 1, "column": 2, "bbox_px": [95, 95, 160, 135]}, {"row": 1, "column": 3, "bbox_px": [295, 95, 360, 135]}])
    first, second = result["cells"]
    assert first["suggestion"]["confirmed"] and first["suggestion"]["text"] == "240"
    assert not second["suggestion"]["confirmed"] and second["pdf_text"] == "480" and second["ocr"] == "58"


async def test_tiny_or_outside_selections_are_rejected(settings):
    with pytest.raises(ValueError, match="larger area"):
        await area.extract_area(PAGE, b"png", [5000, 5000, 6000, 6000], settings)


async def test_route_reads_the_stored_page_and_rejects_bad_selections(monkeypatch, settings):
    source = SimpleNamespace(id=uuid4())
    package = SimpleNamespace(record={"pages": [PAGE]}, images={"pages/page_0001.png": b"png"})
    monkeypatch.setattr(route, "review_source", AsyncMock(return_value=source))
    monkeypatch.setattr(route, "load_extraction", AsyncMock(return_value=package))
    monkeypatch.setattr(route, "get_settings", lambda: settings)
    monkeypatch.setattr(area, "ocr_region", _ocr([]))
    payload = route.AreaRequest.model_validate({"bboxPx": [90, 90, 400, 140]})
    result = await route.extract_page_area(source.id, 1, payload, SimpleNamespace(), object())
    assert result["readings"]["pdf_text"] == "Site AGR-01: 600 m²"
    with pytest.raises(HTTPException) as missing:
        await route.extract_page_area(source.id, 9, payload, SimpleNamespace(), object())
    assert missing.value.status_code == 404
    tiny = route.AreaRequest.model_validate({"bboxPx": [10, 10, 12, 12]})
    with pytest.raises(HTTPException) as rejected:
        await route.extract_page_area(source.id, 1, tiny, SimpleNamespace(), object())
    assert rejected.value.status_code == 422


async def test_plain_text_vision_answer_is_kept_but_marked_unstructured(monkeypatch, settings):
    monkeypatch.setattr(area, "ocr_region", _ocr([]))
    monkeypatch.setattr(area, "read_evidence", AsyncMock(return_value={
        "raw": "Bar chart: Week 1 220, Week 2 245, Week 3 238, Week 4 270.", "finish_reason": "stop"}))
    monkeypatch.setattr(area, "crop_image", lambda image, box: b"crop")
    result = await area.extract_area({**PAGE, "native_words": []}, b"png", [90, 90, 400, 140], settings, use_vision=True)
    assert result["readings"]["vision_status"] == "complete_unstructured"
    assert result["suggestion"] == {"text": "Bar chart: Week 1 220, Week 2 245, Week 3 238, Week 4 270.",
                                    "source": "vision_only", "confirmed": False}
