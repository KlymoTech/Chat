from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from redis.exceptions import RedisError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from northstar_api.database import get_session, set_tenant_context
from northstar_api.models import (
    Role,
    TenantMembership,
    User,
    Workspace,
    WorkspaceMemberAgentAccess,
    WorkspaceMembership,
    WorkspaceRole,
    WorkspaceStatus,
)
from northstar_api.security import (
    TENANT_ROLE_PERMISSIONS,
    WORKSPACE_ROLE_PERMISSIONS,
    Principal,
    decode_token,
)
from northstar_api.services.email_verification import email_is_verified
from northstar_api.services.password_reset import credential_version
from northstar_api.services.rate_limit import redis_services
from northstar_api.services.workspace_api_keys import find_active_workspace_api_key

bearer = HTTPBearer(auto_error=False)
DBSession = Annotated[AsyncSession, Depends(get_session)]


async def get_current_principal(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
    session: DBSession,
) -> Principal:
    if not credentials or credentials.scheme.lower() != "bearer":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")
    token = credentials.credentials
    if token.startswith("nsk_live_"):
        return await authenticate_api_key(token, session, request=request)
    return await authenticate_access_token(token, session, request=request)


async def _agent_scope(
    session: AsyncSession,
    membership: WorkspaceMembership,
    user_id: UUID,
) -> frozenset[UUID] | None:
    if membership.all_agents_access:
        return None
    return frozenset(
        await session.scalars(
            select(WorkspaceMemberAgentAccess.agent_id).where(
                WorkspaceMemberAgentAccess.workspace_id == membership.workspace_id,
                WorkspaceMemberAgentAccess.user_id == user_id,
            )
        )
    )


async def authenticate_api_key(
    token: str,
    session: AsyncSession,
    *,
    request: Request | None = None,
) -> Principal:
    api_key = await find_active_workspace_api_key(session, token)
    if api_key is None or api_key.created_by_user_id is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or revoked API key")

    tenant_membership = await session.scalar(
        select(TenantMembership)
        .join(User, User.id == TenantMembership.user_id)
        .where(
            TenantMembership.user_id == api_key.created_by_user_id,
            TenantMembership.tenant_id == api_key.tenant_id,
            User.is_active.is_(True),
        )
    )
    workspace_membership = await session.scalar(
        select(WorkspaceMembership)
        .join(Workspace, Workspace.id == WorkspaceMembership.workspace_id)
        .where(
            WorkspaceMembership.user_id == api_key.created_by_user_id,
            WorkspaceMembership.tenant_id == api_key.tenant_id,
            WorkspaceMembership.workspace_id == api_key.workspace_id,
            Workspace.status == WorkspaceStatus.ACTIVE,
        )
    )
    if tenant_membership is None or workspace_membership is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="API key access is unavailable")
    if not await email_is_verified(session, api_key.created_by_user_id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Email verification required")

    requested_workspace = request.headers.get("x-workspace-id", "").strip() if request else ""
    if requested_workspace:
        try:
            requested_workspace_id = UUID(requested_workspace)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid workspace identifier") from None
        if requested_workspace_id != api_key.workspace_id:
            raise HTTPException(status_code=403, detail="API key is scoped to a different workspace")

    api_key.last_used_at = datetime.now(UTC)
    await session.commit()
    await set_tenant_context(session, api_key.tenant_id)

    # API keys are workspace service credentials, not tenant administrator sessions.
    # They are capped to the creator's workspace role, with workspace_admin reduced
    # to manager-level capabilities so a leaked server credential cannot mutate
    # tenant membership, billing, security policy, workspace settings, or other keys.
    service_workspace_role = (
        WorkspaceRole.MANAGER
        if workspace_membership.role == WorkspaceRole.ADMIN
        else workspace_membership.role
    )
    permissions = WORKSPACE_ROLE_PERMISSIONS[service_workspace_role]
    return Principal(
        user_id=api_key.created_by_user_id,
        tenant_id=api_key.tenant_id,
        role=Role.MEMBER,
        token_id=f"api_key:{api_key.id}",
        workspace_id=api_key.workspace_id,
        workspace_role=service_workspace_role,
        permissions=permissions,
        agent_ids=await _agent_scope(session, workspace_membership, api_key.created_by_user_id),
    )


async def authenticate_access_token(
    token: str,
    session: AsyncSession,
    *,
    request: Request | None = None,
) -> Principal:
    try:
        payload = decode_token(token, "access")
        user_id = UUID(payload["sub"])
        tenant_id = UUID(payload["tid"])
        token_role = Role(payload["role"])
    except (ValueError, KeyError, TypeError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired access token"
        ) from None
    try:
        if await redis_services.client.exists(f"northstar:revoked:{payload['jti']}"):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Access token was revoked")
    except RedisError:
        if not redis_services.settings.rate_limit_fail_open:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Session service unavailable"
            ) from None

    membership = await session.scalar(
        select(TenantMembership)
        .join(User, User.id == TenantMembership.user_id)
        .where(
            TenantMembership.user_id == user_id,
            TenantMembership.tenant_id == tenant_id,
            User.is_active.is_(True),
        )
    )
    if not membership:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Account or workspace is unavailable"
        )
    if membership.role != token_role:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Session role is stale; sign in again"
        )
    if int(payload.get("cv", 0)) != await credential_version(session, user_id):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session credentials changed; sign in again",
        )

    # Legacy users have no verification-state row and remain verified. New
    # self-service users receive an explicit unverified row during Signup.
    allow_unverified_logout = bool(request and request.url.path.endswith("/auth/logout"))
    if not allow_unverified_logout and not await email_is_verified(session, user_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Email verification required",
        )

    await set_tenant_context(session, tenant_id)
    requested_workspace = request.headers.get("x-workspace-id", "").strip() if request else ""
    workspace_id: UUID | None = None
    if requested_workspace:
        try:
            workspace_id = UUID(requested_workspace)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid workspace identifier") from None
    workspace_query = (
        select(WorkspaceMembership)
        .join(Workspace, Workspace.id == WorkspaceMembership.workspace_id)
        .where(
            WorkspaceMembership.user_id == user_id,
            WorkspaceMembership.tenant_id == tenant_id,
            Workspace.status == WorkspaceStatus.ACTIVE,
        )
        .order_by(WorkspaceMembership.created_at, WorkspaceMembership.workspace_id)
    )
    if workspace_id:
        workspace_query = workspace_query.where(WorkspaceMembership.workspace_id == workspace_id)
    workspace_membership = await session.scalar(workspace_query)
    if not workspace_membership:
        raise HTTPException(status_code=403, detail="Workspace access is unavailable")
    permissions = TENANT_ROLE_PERMISSIONS[membership.role] | WORKSPACE_ROLE_PERMISSIONS[workspace_membership.role]
    return Principal(
        user_id=user_id,
        tenant_id=tenant_id,
        role=membership.role,
        token_id=payload["jti"],
        workspace_id=workspace_membership.workspace_id,
        workspace_role=workspace_membership.role,
        permissions=permissions,
        agent_ids=await _agent_scope(session, workspace_membership, user_id),
    )


CurrentPrincipal = Annotated[Principal, Depends(get_current_principal)]


def require_roles(*roles: Role) -> Callable[..., Awaitable[Principal]]:
    async def dependency(principal: CurrentPrincipal) -> Principal:
        workspace_admin = principal.workspace_role == WorkspaceRole.ADMIN
        if principal.role not in roles and not (Role.ADMIN in roles and workspace_admin):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient workspace role")
        return principal

    return dependency


AdminPrincipal = Annotated[Principal, Depends(require_roles(Role.OWNER, Role.ADMIN))]
WorkspaceWritePrincipal = Annotated[
    Principal,
    Depends(require_roles(Role.OWNER, Role.ADMIN, Role.MEMBER)),
]


def require_permissions(*permissions: str) -> Callable[..., Awaitable[Principal]]:
    async def dependency(principal: CurrentPrincipal) -> Principal:
        if not all(principal.can(permission) for permission in permissions):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permission")
        return principal

    return dependency


def request_origin(request: Request) -> str:
    return request.headers.get("origin", "").strip().lower()
