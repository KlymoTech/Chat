from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from northstar_api.email_verification import EmailVerificationState
from northstar_api.models import (
    Role,
    Tenant,
    TenantMembership,
    User,
    Workspace,
    WorkspaceMembership,
    WorkspaceRole,
)
from northstar_api.security import hash_password
from northstar_api.services.subscriptions import create_subscription_for_tenant
from northstar_api.signup_schemas import SignupRequest
from northstar_api.workspace_invitations import (
    WorkspaceInvitationError,
    resolve_workspace_invitation,
)


class SignupConflict(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class ProvisionedSignup:
    user: User
    tenant: Tenant
    workspace: Workspace
    role: Role


def _base_slug(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return normalized[:70] or "workspace"


async def _available_tenant_slug(session: AsyncSession, organization_name: str) -> str:
    base = _base_slug(organization_name)
    existing = await session.scalar(select(Tenant.id).where(Tenant.slug == base))
    if existing is None:
        return base

    # Tenant slugs are an internal account selector and must remain globally
    # unique. A UUID fragment avoids organization-name collisions without
    # exposing email or other customer identifiers.
    for _ in range(8):
        suffix = uuid4().hex[:8]
        candidate = f"{base[:61]}-{suffix}"
        duplicate = await session.scalar(select(Tenant.id).where(Tenant.slug == candidate))
        if duplicate is None:
            return candidate
    raise SignupConflict("Unable to allocate an account identifier")


async def _provision_invited_signup(
    session: AsyncSession,
    *,
    payload: SignupRequest,
    normalized_email: str,
    password_hash: str,
    accepted_at: datetime,
) -> ProvisionedSignup:
    if payload.workspace_invitation_token is None:
        raise SignupConflict("Workspace invitation is required")
    try:
        invitation = await resolve_workspace_invitation(session, payload.workspace_invitation_token)
    except WorkspaceInvitationError as exc:
        raise SignupConflict(str(exc)) from None
    if invitation.email != normalized_email:
        raise SignupConflict("This workspace invitation was issued to a different email address")

    tenant = await session.get(Tenant, invitation.tenant_id)
    workspace = await session.get(Workspace, invitation.workspace_id)
    if tenant is None or workspace is None or workspace.tenant_id != tenant.id:
        raise SignupConflict("Workspace invitation is invalid or expired")

    user = User(
        email=normalized_email,
        name=payload.name,
        password_hash=password_hash,
        is_active=True,
        last_login_at=accepted_at,
    )
    session.add(user)
    await session.flush()
    session.add(EmailVerificationState(user_id=user.id, verified_at=None))
    session.add(
        TenantMembership(
            tenant_id=tenant.id,
            user_id=user.id,
            role=Role.MEMBER,
        )
    )
    session.add(
        WorkspaceMembership(
            tenant_id=tenant.id,
            workspace_id=workspace.id,
            user_id=user.id,
            role=invitation.role,
            all_agents_access=True,
        )
    )
    invitation.accepted_at = accepted_at
    invitation.updated_at = accepted_at
    await session.flush()
    return ProvisionedSignup(user=user, tenant=tenant, workspace=workspace, role=Role.MEMBER)


async def provision_signup(
    session: AsyncSession,
    *,
    payload: SignupRequest,
) -> ProvisionedSignup:
    normalized_email = str(payload.email).strip().lower()
    existing_user = await session.scalar(
        select(User.id).where(func.lower(User.email) == normalized_email)
    )
    if existing_user is not None:
        raise SignupConflict("An account with this email already exists")

    password_hash = await asyncio.to_thread(hash_password, payload.password)
    accepted_at = datetime.now(UTC)
    if payload.workspace_invitation_token is not None:
        return await _provision_invited_signup(
            session,
            payload=payload,
            normalized_email=normalized_email,
            password_hash=password_hash,
            accepted_at=accepted_at,
        )

    if payload.organization_name is None:
        raise SignupConflict("Organization name is required")
    tenant_slug = await _available_tenant_slug(session, payload.organization_name)
    tenant = Tenant(
        name=payload.organization_name,
        slug=tenant_slug,
        plan="starter",
        settings_json={
            "signup": {
                "source": "self_service",
                "termsAccepted": True,
                "privacyAccepted": True,
                "acceptedAt": accepted_at.isoformat(),
            }
        },
    )
    user = User(
        email=normalized_email,
        name=payload.name,
        password_hash=password_hash,
        is_active=True,
        last_login_at=accepted_at,
    )
    session.add_all([tenant, user])
    await session.flush()
    await create_subscription_for_tenant(session, tenant=tenant, plan="starter")
    session.add(EmailVerificationState(user_id=user.id, verified_at=None))

    workspace = Workspace(
        tenant_id=tenant.id,
        name=payload.organization_name,
        slug="default",
        created_by=user.id,
    )
    session.add(workspace)
    await session.flush()

    session.add(
        TenantMembership(
            tenant_id=tenant.id,
            user_id=user.id,
            role=Role.OWNER,
        )
    )
    session.add(
        WorkspaceMembership(
            tenant_id=tenant.id,
            workspace_id=workspace.id,
            user_id=user.id,
            role=WorkspaceRole.ADMIN,
            all_agents_access=True,
        )
    )
    await session.flush()
    return ProvisionedSignup(user=user, tenant=tenant, workspace=workspace, role=Role.OWNER)
