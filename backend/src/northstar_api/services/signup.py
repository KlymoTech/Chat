from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

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
from northstar_api.signup_schemas import SignupRequest


class SignupConflict(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class ProvisionedSignup:
    user: User
    tenant: Tenant
    workspace: Workspace


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


async def provision_signup(
    session: AsyncSession,
    *,
    payload: SignupRequest,
) -> ProvisionedSignup:
    normalized_email = str(payload.email).strip().lower()
    existing_user = await session.scalar(select(User.id).where(User.email == normalized_email))
    if existing_user is not None:
        raise SignupConflict("An account with this email already exists")

    tenant_slug = await _available_tenant_slug(session, payload.organization_name)
    password_hash = await asyncio.to_thread(hash_password, payload.password)
    accepted_at = datetime.now(UTC)

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
    return ProvisionedSignup(user=user, tenant=tenant, workspace=workspace)
