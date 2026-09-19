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

from northstar_api.config import get_settings
from northstar_api.database import get_session, set_tenant_context
from northstar_api.models import (
    Role, TenantMembership, User, Workspace, WorkspaceMemberAgentAccess,
    WorkspaceMembership, WorkspaceRole, WorkspaceStatus,
)
from northstar_api.onboarding_models import OrganizationSetup
from northstar_api.security import TENANT_ROLE_PERMISSIONS, WORKSPACE_ROLE_PERMISSIONS, Principal, decode_token
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
        raise HTTPException(status_code=401, detail="Authentication required")
    token = credentials.credentials
    if token.startswith("nsk_live_"):
        principal = await authenticate_api_key(token, session, request=request)
    else:
        principal = await authenticate_access_token(token, session, request=request)
    request.state.principal = principal
    path = request.url.path.removeprefix(get_settings().app_api_prefix.rstrip("/"))
    if path.startswith("/v1/"):
        path = path[3:]
    setup_paths = {"/bootstrap", "/onboarding", "/workspaces", "/workspace"}
    setup = await session.scalar(select(OrganizationSetup).where(OrganizationSetup.tenant_id == principal.tenant_id))
    if setup is not None and setup.required and not setup.profile_complete:
        safe_read = request.method in {"GET", "HEAD"} and path in setup_paths
        if not safe_read and not path.startswith(("/auth/", "/organization/", "/billing/")):
            raise HTTPException(status_code=428, detail="Complete your organization profile before using workspace resources")
    return principal


async def _agent_scope(session: AsyncSession, membership: WorkspaceMembership, user_id: UUID) -> frozenset[UUID] | None:
    if membership.all_agents_access:
        return None
    return frozenset(await session.scalars(select(WorkspaceMemberAgentAccess.agent_id).where(
        WorkspaceMemberAgentAccess.workspace_id == membership.workspace_id,
        WorkspaceMemberAgentAccess.user_id == user_id,
    )))


async def authenticate_api_key(token: str, session: AsyncSession, *, request: Request | None = None) -> Principal:
    api_key = await find_active_workspace_api_key(session, token)
    if api_key is None or api_key.created_by_user_id is None:
        raise HTTPException(status_code=401, detail="Invalid or revoked API key")
    tenant_membership = await session.scalar(select(TenantMembership).join(User, User.id == TenantMembership.user_id).where(
        TenantMembership.user_id == api_key.created_by_user_id, TenantMembership.tenant_id == api_key.tenant_id,
        User.is_active.is_(True),
    ))
    workspace_membership = await session.scalar(select(WorkspaceMembership).join(Workspace, Workspace.id == WorkspaceMembership.workspace_id).where(
        WorkspaceMembership.user_id == api_key.created_by_user_id, WorkspaceMembership.tenant_id == api_key.tenant_id,
        WorkspaceMembership.workspace_id == api_key.workspace_id, Workspace.status == WorkspaceStatus.ACTIVE,
        Workspace.tenant_id == api_key.tenant_id,
    ))
    if tenant_membership is None or workspace_membership is None:
        raise HTTPException(status_code=401, detail="API key access is unavailable")
    if not await email_is_verified(session, api_key.created_by_user_id):
        raise HTTPException(status_code=403, detail="Email verification required")
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
    service_workspace_role = WorkspaceRole.MANAGER if workspace_membership.role == WorkspaceRole.ADMIN else workspace_membership.role
    return Principal(
        user_id=api_key.created_by_user_id, tenant_id=api_key.tenant_id, role=Role.MEMBER,
        token_id=f"api_key:{api_key.id}", workspace_id=api_key.workspace_id, workspace_role=service_workspace_role,
        permissions=WORKSPACE_ROLE_PERMISSIONS[service_workspace_role],
        agent_ids=await _agent_scope(session, workspace_membership, api_key.created_by_user_id),
    )


def _allows_organization_context(request: Request | None) -> bool:
    if request is None:
        return False
    path = request.url.path.removeprefix(get_settings().app_api_prefix.rstrip("/"))
    if path.startswith("/v1/"):
        path = path[3:]
    return path in {"/bootstrap", "/onboarding", "/workspaces", "/auth/logout", "/me/organizations", "/auth/select-organization"} or path.startswith(("/billing/", "/organization/"))


async def authenticate_access_token(token: str, session: AsyncSession, *, request: Request | None = None) -> Principal:
    try:
        payload = decode_token(token, "access")
        user_id, tenant_id, token_role = UUID(payload["sub"]), UUID(payload["tid"]), Role(payload["role"])
    except (ValueError, KeyError, TypeError):
        raise HTTPException(status_code=401, detail="Invalid or expired access token") from None
    try:
        if await redis_services.client.exists(f"northstar:revoked:{payload['jti']}"):
            raise HTTPException(status_code=401, detail="Access token was revoked")
    except RedisError:
        if not redis_services.settings.rate_limit_fail_open:
            raise HTTPException(status_code=503, detail="Session service unavailable") from None
    membership = await session.scalar(select(TenantMembership).join(User, User.id == TenantMembership.user_id).where(
        TenantMembership.user_id == user_id, TenantMembership.tenant_id == tenant_id, User.is_active.is_(True),
    ))
    if not membership:
        raise HTTPException(status_code=401, detail="Account or workspace is unavailable")
    if membership.role != token_role:
        raise HTTPException(status_code=401, detail="Session role is stale; sign in again")
    if int(payload.get("cv", 0)) != await credential_version(session, user_id):
        raise HTTPException(status_code=401, detail="Session credentials changed; sign in again")
    allow_unverified_logout = bool(request and request.url.path.endswith("/auth/logout"))
    if not allow_unverified_logout and not await email_is_verified(session, user_id):
        raise HTTPException(status_code=403, detail="Email verification required")
    await set_tenant_context(session, tenant_id)
    requested_workspace = request.headers.get("x-workspace-id", "").strip() if request else ""
    workspace_id: UUID | None = None
    if requested_workspace:
        try:
            workspace_id = UUID(requested_workspace)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid workspace identifier") from None
    query = select(WorkspaceMembership).join(Workspace, Workspace.id == WorkspaceMembership.workspace_id).where(
        WorkspaceMembership.user_id == user_id, WorkspaceMembership.tenant_id == tenant_id,
        Workspace.tenant_id == tenant_id, Workspace.status == WorkspaceStatus.ACTIVE,
    ).order_by(WorkspaceMembership.created_at, WorkspaceMembership.workspace_id)
    if workspace_id:
        query = query.where(WorkspaceMembership.workspace_id == workspace_id)
    workspace_membership = await session.scalar(query)
    if not workspace_membership:
        if workspace_id is not None or not _allows_organization_context(request):
            raise HTTPException(status_code=403, detail="Workspace access is unavailable")
        return Principal(user_id=user_id, tenant_id=tenant_id, role=membership.role, token_id=payload["jti"],
                         permissions=TENANT_ROLE_PERMISSIONS[membership.role])
    permissions = TENANT_ROLE_PERMISSIONS[membership.role] | WORKSPACE_ROLE_PERMISSIONS[workspace_membership.role]
    return Principal(
        user_id=user_id, tenant_id=tenant_id, role=membership.role, token_id=payload["jti"],
        workspace_id=workspace_membership.workspace_id, workspace_role=workspace_membership.role,
        permissions=permissions, agent_ids=await _agent_scope(session, workspace_membership, user_id),
    )


CurrentPrincipal = Annotated[Principal, Depends(get_current_principal)]


def require_roles(*roles: Role) -> Callable[..., Awaitable[Principal]]:
    """Compatibility guard for workspace routes; organization roles cannot override a viewer grant."""
    async def dependency(principal: CurrentPrincipal) -> Principal:
        allowed: set[WorkspaceRole] = set()
        if Role.OWNER in roles or Role.ADMIN in roles:
            allowed.add(WorkspaceRole.ADMIN)
        if Role.MEMBER in roles:
            allowed.update({WorkspaceRole.MANAGER, WorkspaceRole.OPERATOR})
        if Role.ANALYST in roles:
            allowed.add(WorkspaceRole.ANALYST)
        if principal.workspace_id is None or principal.workspace_role not in allowed:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient workspace role")
        return principal
    return dependency


AdminPrincipal = Annotated[Principal, Depends(require_roles(Role.OWNER, Role.ADMIN))]
WorkspaceWritePrincipal = Annotated[Principal, Depends(require_roles(Role.OWNER, Role.ADMIN, Role.MEMBER))]


def require_permissions(*permissions: str) -> Callable[..., Awaitable[Principal]]:
    async def dependency(principal: CurrentPrincipal) -> Principal:
        if not all(principal.can(permission) for permission in permissions):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permission")
        return principal
    return dependency


def request_origin(request: Request) -> str:
    return request.headers.get("origin", "").strip().lower()
