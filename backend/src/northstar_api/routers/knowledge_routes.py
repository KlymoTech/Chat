"""Shared FastAPI route registry and dependencies for the knowledge capability."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from northstar_api.database import get_session
from northstar_api.dependencies import require_permissions
from northstar_api.security import Principal

__all__ = ["DB", "KnowledgeManagePrincipal", "KnowledgeViewPrincipal", "router"]

router = APIRouter(tags=["knowledge"])
DB = Annotated[AsyncSession, Depends(get_session)]
KnowledgeViewPrincipal = Annotated[Principal, Depends(require_permissions("knowledge.view"))]
KnowledgeManagePrincipal = Annotated[Principal, Depends(require_permissions("knowledge.manage"))]
