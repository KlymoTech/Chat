"""Additive workspace-owner endpoints under the existing /workspace scope."""
from __future__ import annotations

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import select

from northstar_api.dependencies import DBSession, require_permissions
from northstar_api.models import Workspace, WorkspaceStatus
from northstar_api.modules.workspace.services.ownership import (
    WorkspaceOwnershipError,
    resolve_workspace_owner,
    transfer_workspace_ownership,
)
from northstar_api.schemas import APIModel
from northstar_api.security import Principal

router = APIRouter(prefix="/workspace/owner", tags=["workspace ownership"])
OwnerViewPrincipal = Annotated[Principal, Depends(require_permissions("workspace.view"))]
OwnerManagePrincipal = Annotated[Principal, Depends(require_permissions("members.manage"))]


class WorkspaceOwnerOut(APIModel):
    owner_user_id: UUID | None
    owner_name: str | None
    creator_user_id: UUID | None


class WorkspaceOwnerTransfer(APIModel):
    expected_owner_user_id: UUID
    target_user_id: UUID
    confirmation: Literal["TRANSFER"]
    reason: Literal[
        "administrative_handover", "responsibility_change", "account_recovery",
    ]


@router.get("", response_model=WorkspaceOwnerOut)
async def get_workspace_owner(
    principal: OwnerViewPrincipal, session: DBSession, response: Response,
) -> WorkspaceOwnerOut:
    assert principal.workspace_id is not None
    workspace = await session.scalar(
        select(Workspace).where(
            Workspace.tenant_id == principal.tenant_id,
            Workspace.id == principal.workspace_id,
            Workspace.status == WorkspaceStatus.ACTIVE,
        )
    )
    if workspace is None:
        raise HTTPException(status_code=404, detail="Workspace not found")
    owner = await resolve_workspace_owner(
        session, tenant_id=principal.tenant_id, workspace=workspace,
    )
    response.headers["Cache-Control"] = "private, no-store"
    return WorkspaceOwnerOut(
        owner_user_id=owner.user_id if owner is not None else None,
        owner_name=owner.name if owner is not None else None,
        creator_user_id=workspace.created_by,
    )


@router.post("/transfer", response_model=WorkspaceOwnerOut)
async def transfer_owner(
    payload: WorkspaceOwnerTransfer, principal: OwnerManagePrincipal, session: DBSession,
    response: Response,
) -> WorkspaceOwnerOut:
    if principal.token_id.startswith("api_key:"):
        raise HTTPException(status_code=403, detail="An interactive session is required for ownership transfer")
    assert principal.workspace_id is not None
    try:
        owner = await transfer_workspace_ownership(
            session,
            tenant_id=principal.tenant_id,
            workspace_id=principal.workspace_id,
            actor_user_id=principal.user_id,
            expected_owner_user_id=payload.expected_owner_user_id,
            target_user_id=payload.target_user_id,
            reason=payload.reason,
        )
        await session.commit()
    except WorkspaceOwnershipError as exc:
        await session.rollback()
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from None
    workspace = await session.scalar(
        select(Workspace).where(
            Workspace.id == principal.workspace_id,
            Workspace.tenant_id == principal.tenant_id,
        )
    )
    response.headers["Cache-Control"] = "private, no-store"
    return WorkspaceOwnerOut(
        owner_user_id=owner.user_id,
        owner_name=owner.name,
        creator_user_id=workspace.created_by if workspace is not None else None,
    )


# Recovery uses its own organization-level authorization and is only reachable
# inside the same existing /workspace/owner router and workspace context.
from northstar_api.modules.workspace.api import owner_recovery  # noqa: E402

router.include_router(owner_recovery.router)
