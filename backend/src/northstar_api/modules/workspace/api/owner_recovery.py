"""Separate, interactive and independently authorized Workspace owner recovery."""
from __future__ import annotations

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response

from northstar_api.dependencies import DBSession, require_permissions
from northstar_api.models import Role
from northstar_api.modules.workspace.services.owner_recovery import (
    WorkspaceRecoveryResult, recover_workspace_ownership,
)
from northstar_api.modules.workspace.services.ownership import WorkspaceOwnershipError
from northstar_api.schemas import APIModel
from northstar_api.security import Principal

router = APIRouter(tags=["workspace ownership"])
RecoveryPrincipal = Annotated[Principal, Depends(require_permissions("members.manage"))]


class WorkspaceOwnerRecovery(APIModel):
    target_user_id: UUID
    confirmation: Literal["RECOVER"]
    reason: Literal["recorded_owner_unavailable", "legacy_owner_unavailable"]


class WorkspaceOwnerRecoveryOut(APIModel):
    owner_user_id: UUID
    owner_name: str
    creator_user_id: UUID | None


@router.post("/recover", response_model=WorkspaceOwnerRecoveryOut)
async def recover_owner(
    payload: WorkspaceOwnerRecovery, principal: RecoveryPrincipal,
    session: DBSession, response: Response,
) -> WorkspaceOwnerRecoveryOut:
    if principal.token_id.startswith("api_key:"):
        raise HTTPException(status_code=403, detail="An interactive session is required for ownership recovery")
    if principal.role is not Role.OWNER:
        raise HTTPException(status_code=403, detail="Only an organization owner can recover workspace ownership")
    if principal.workspace_id is None:
        raise HTTPException(status_code=403, detail="Select an authorized workspace")
    try:
        result: WorkspaceRecoveryResult = await recover_workspace_ownership(
            session,
            tenant_id=principal.tenant_id,
            workspace_id=principal.workspace_id,
            actor_user_id=principal.user_id,
            target_user_id=payload.target_user_id,
            reason=payload.reason,
        )
        await session.commit()
    except WorkspaceOwnershipError as exc:
        await session.rollback()
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from None
    response.headers["Cache-Control"] = "private, no-store"
    return WorkspaceOwnerRecoveryOut(
        owner_user_id=result.owner.user_id,
        owner_name=result.owner.name,
        creator_user_id=result.creator_user_id,
    )
