from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status

from northstar_api.dependencies import DBSession, require_permissions
from northstar_api.schemas import APIModel
from northstar_api.security import Principal
from northstar_api.services.workspace_api_keys import (
    WorkspaceAPIKeyError,
    issue_workspace_api_key,
    list_workspace_api_keys,
    revoke_workspace_api_key,
)
from northstar_api.workspace_api_key_schemas import (
    WorkspaceAPIKeyCreate,
    WorkspaceAPIKeyCreated,
    WorkspaceAPIKeyOut,
)
from northstar_api.workspace_api_keys import WorkspaceAPIKey

router = APIRouter(prefix="/workspace/api-keys", tags=["workspace API keys"])
APIKeyViewPrincipal = Annotated[Principal, Depends(require_permissions("api_keys.view"))]
APIKeyManagePrincipal = Annotated[Principal, Depends(require_permissions("api_keys.manage"))]


def _out(record: WorkspaceAPIKey) -> WorkspaceAPIKeyOut:
    return WorkspaceAPIKeyOut(
        id=record.id,
        name=record.name,
        prefix=record.prefix,
        created_at=record.created_at,
        last_used_at=record.last_used_at,
    )


@router.get("", response_model=list[WorkspaceAPIKeyOut])
async def get_workspace_api_keys(
    principal: APIKeyViewPrincipal,
    session: DBSession,
) -> list[WorkspaceAPIKeyOut]:
    assert principal.workspace_id is not None
    values = await list_workspace_api_keys(
        session,
        tenant_id=principal.tenant_id,
        workspace_id=principal.workspace_id,
    )
    return [_out(item) for item in values]


@router.post("", response_model=WorkspaceAPIKeyCreated, status_code=status.HTTP_201_CREATED)
async def create_workspace_api_key(
    payload: WorkspaceAPIKeyCreate,
    principal: APIKeyManagePrincipal,
    session: DBSession,
) -> WorkspaceAPIKeyCreated:
    assert principal.workspace_id is not None
    issued = await issue_workspace_api_key(
        session,
        tenant_id=principal.tenant_id,
        workspace_id=principal.workspace_id,
        created_by_user_id=principal.user_id,
        name=payload.name,
    )
    await session.commit()
    await session.refresh(issued.record)
    return WorkspaceAPIKeyCreated(
        **_out(issued.record).model_dump(),
        secret=issued.secret,
    )


@router.delete("/{api_key_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_workspace_api_key(
    api_key_id: UUID,
    principal: APIKeyManagePrincipal,
    session: DBSession,
) -> Response:
    assert principal.workspace_id is not None
    try:
        await revoke_workspace_api_key(
            session,
            tenant_id=principal.tenant_id,
            workspace_id=principal.workspace_id,
            api_key_id=api_key_id,
        )
        await session.commit()
    except WorkspaceAPIKeyError as exc:
        await session.rollback()
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from None
    return Response(status_code=status.HTTP_204_NO_CONTENT)
