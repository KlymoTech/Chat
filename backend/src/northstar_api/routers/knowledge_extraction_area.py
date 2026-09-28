"""Area extraction: read only the part of a page that a reviewer selects."""

from __future__ import annotations

from uuid import UUID

import structlog
from fastapi import HTTPException
from pydantic import Field

from northstar_api.config import get_settings
from northstar_api.routers.knowledge_routes import DB, KnowledgeManagePrincipal, router
from northstar_api.routers.knowledge_support import load_extraction, review_source
from northstar_api.schemas import APIModel
from northstar_api.services.extraction_area import extract_area

logger = structlog.get_logger()


class AreaCell(APIModel):
    row: int = Field(ge=0, le=1000)
    column: int = Field(ge=0, le=1000)
    bbox_px: list[float] = Field(min_length=4, max_length=4)


class AreaRequest(APIModel):
    bbox_px: list[float] = Field(min_length=4, max_length=4, description="x0, y0, x1, y1 in page-image pixels")
    vision: bool = False
    cells: list[AreaCell] = Field(default_factory=list, max_length=400)


@router.post("/knowledge/{source_id}/extraction/pages/{page_number}/area")
async def extract_page_area(
    source_id: UUID, page_number: int, payload: AreaRequest, principal: KnowledgeManagePrincipal, session: DB
) -> dict[str, object]:
    """Read one selected area of a page. Nothing is stored: the reviewer places the result in the
    editor and it is saved, with its audit trail, through the normal page review."""
    source = await review_source(source_id, principal, session)
    package = await load_extraction(source)
    page = next((p for p in package.record["pages"] if p["number"] == page_number), None)
    if not page or page.get("image") not in package.images:
        raise HTTPException(status_code=404, detail="Page image not found")
    try:
        result = await extract_area(
            page, package.images[page["image"]], payload.bbox_px, get_settings(),
            cells=[c.model_dump() for c in payload.cells], use_vision=payload.vision,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    logger.info("extraction_area_read", source_id=str(source.id), page=page_number, vision=payload.vision,
                confirmed=result["suggestion"]["confirmed"])
    return result
