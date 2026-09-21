"""Request-scoped Workspace invitation administrator and HTTP provenance.

Only protected invitation routes install this dependency. The principal comes
from verified authentication, never from user-provided headers or request JSON.
"""
from __future__ import annotations

from uuid import UUID

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from northstar_api.dependencies import CurrentPrincipal, DBSession

_ACTOR_KEY = "workspace_invitation_authenticated_actor"
_SCOPE_KEY = "workspace_invitation_authenticated_scope"
_REQUEST_KEY = "workspace_invitation_authenticated_request"


def _matches_scope(session: AsyncSession, tenant_id: UUID, workspace_id: UUID) -> bool:
    return getattr(session, "info", {}).get(_SCOPE_KEY) == (tenant_id, workspace_id)


def invitation_revoker_actor(
    session: AsyncSession, *, tenant_id: UUID, workspace_id: UUID,
) -> UUID | None:
    """Return the authenticated revoker only for the matching Workspace."""
    if not _matches_scope(session, tenant_id, workspace_id):
        return None
    actor = session.info.get(_ACTOR_KEY)
    return actor if isinstance(actor, UUID) else None


def invitation_audit_request(
    session: AsyncSession, *, tenant_id: UUID, workspace_id: UUID,
) -> Request | None:
    """Provide IP/user-agent provenance to audit, never to domain-event payloads."""
    if not _matches_scope(session, tenant_id, workspace_id):
        return None
    request = session.info.get(_REQUEST_KEY)
    return request if isinstance(request, Request) else None


async def capture_invitation_administrator(
    request: Request, principal: CurrentPrincipal, session: DBSession,
) -> None:
    """Attach a verified identity and request to this request's DB session.

    The router retains its existing operation-level permission dependencies.
    An organization-only principal clears any prior Workspace actor/context.
    """
    if principal.workspace_id is None:
        session.info.pop(_ACTOR_KEY, None)
        session.info.pop(_SCOPE_KEY, None)
        session.info.pop(_REQUEST_KEY, None)
        return
    session.info[_ACTOR_KEY] = principal.user_id
    session.info[_SCOPE_KEY] = (principal.tenant_id, principal.workspace_id)
    session.info[_REQUEST_KEY] = request
