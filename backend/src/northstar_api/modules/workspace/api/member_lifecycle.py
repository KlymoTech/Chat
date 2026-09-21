"""Additive Workspace member lifecycle endpoints.

Existing member/invitation routes stay in place while this capability migrates
under ``modules.workspace``.
"""
from __future__ import annotations

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import Field
from sqlalchemy import select

from northstar_api.dependencies import DBSession, require_permissions
from northstar_api.models import WorkspaceMembership
from northstar_api.modules.workspace.services.member_lifecycle import member_statuses, set_member_suspended
from northstar_api.schemas import APIModel
from northstar_api.security import Principal
from northstar_api.services.workspace_members import WorkspaceMemberError

router = APIRouter(prefix="/workspace/members", tags=["workspace members"])
MemberViewPrincipal = Annotated[Principal, Depends(require_permissions("members.view"))]
MemberManagePrincipal = Annotated[Principal, Depends(require_permissions("members.manage"))]


class WorkspaceMemberLifecycleOut(APIModel):
    user_id: UUID
    status: Literal["active", "suspended", "disabled"]


class WorkspaceMemberLifecycleChange(APIModel):
    reason: str = Field(min_length=3, max_length=500)
    confirmation: str = Field(min_length=1, max_length=16)


@router.get("/lifecycle", response_model=list[WorkspaceMemberLifecycleOut])
async def get_member_lifecycle(
    principal: MemberViewPrincipal, session: DBSession,
) -> list[WorkspaceMemberLifecycleOut]:
    assert principal.workspace_id is not None
    user_ids = list(await session.scalars(select(WorkspaceMembership.user_id).where(
        WorkspaceMembership.tenant_id == principal.tenant_id,
        WorkspaceMembership.workspace_id == principal.workspace_id,
    )))
    statuses = await member_statuses(
        session, tenant_id=principal.tenant_id,
        workspace_id=principal.workspace_id, user_ids=user_ids,
    )
    return [WorkspaceMemberLifecycleOut(user_id=user_id, status=statuses[user_id]) for user_id in user_ids]


async def _change(
    member_user_id: UUID,
    payload: WorkspaceMemberLifecycleChange,
    principal: Principal,
    session: DBSession,
    *,
    suspended: bool,
) -> WorkspaceMemberLifecycleOut:
    if principal.token_id.startswith("api_key:"):
        raise HTTPException(status_code=403, detail="An interactive session is required for member lifecycle changes")
    required = "SUSPEND" if suspended else "REACTIVATE"
    if payload.confirmation != required:
        raise HTTPException(status_code=422, detail=f"Type {required} to confirm this action")
    assert principal.workspace_id is not None
    try:
        await set_member_suspended(
            session,
            tenant_id=principal.tenant_id,
            workspace_id=principal.workspace_id,
            actor_user_id=principal.user_id,
            member_user_id=member_user_id,
            suspended=suspended,
            reason=payload.reason,
        )
        await session.commit()
    except WorkspaceMemberError as exc:
        await session.rollback()
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from None
    return WorkspaceMemberLifecycleOut(
        user_id=member_user_id,
        status="suspended" if suspended else "active",
    )


@router.post("/{member_user_id}/suspend", response_model=WorkspaceMemberLifecycleOut)
async def suspend_member(
    member_user_id: UUID,
    payload: WorkspaceMemberLifecycleChange,
    principal: MemberManagePrincipal,
    session: DBSession,
) -> WorkspaceMemberLifecycleOut:
    return await _change(member_user_id, payload, principal, session, suspended=True)


@router.post("/{member_user_id}/reactivate", response_model=WorkspaceMemberLifecycleOut)
async def reactivate_member(
    member_user_id: UUID,
    payload: WorkspaceMemberLifecycleChange,
    principal: MemberManagePrincipal,
    session: DBSession,
) -> WorkspaceMemberLifecycleOut:
    return await _change(member_user_id, payload, principal, session, suspended=False)
