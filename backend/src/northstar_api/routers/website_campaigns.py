"""Authenticated campaign URL generator for the owner CMS marketing console.

The frontend never constructs attribution URLs independently; the validated
backend contract is the authoritative implementation for first-party campaigns.
"""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel, ConfigDict

from northstar_api.dependencies import require_roles
from northstar_api.models import Role
from northstar_api.security import Principal
from northstar_api.services.website_campaign_links import CampaignLink, build_campaign_url

router = APIRouter(prefix="/site-campaigns", tags=["site-campaigns"])
OwnerOrAdmin = Annotated[Principal, Depends(require_roles(Role.OWNER, Role.ADMIN))]


class CampaignLinkResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    url: str
    source: str
    medium: str
    campaign: str


@router.post("/url", response_model=CampaignLinkResult)
async def generate_campaign_url(
    payload: CampaignLink, principal: OwnerOrAdmin, response: Response,
) -> CampaignLinkResult:
    """Generate a validated URL without contacting external attribution providers."""
    # The role dependency handles tenant- and workspace-scoped authorization.
    _ = principal
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return CampaignLinkResult(
        url=build_campaign_url(payload),
        source=payload.source,
        medium=payload.medium,
        campaign=payload.campaign,
    )
