"""Request-scoped invitation administrator provenance for legacy service compatibility.

Only authenticated Workspace invitation routes set these values on their request's
SQLAlchemy AsyncSession. Public invitation routes do not install this dependency.
No request headers or client-controlled identity values are trusted here.
"""
from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from northstar_api.dependencies import CurrentPrincipal, DBSession

_ACTOR_KEY = "workspace_invitation_authenticated_actor"
_SCOPE_KEY = "workspace_invitation_authenticated_scope"


def invitation_revoker_actor(
    session: AsyncSession, *, tenant_id: UUID, workspace_id: UUID,
) -> UUID | None:
    """Return the authenticated actor only for an exact matching Workspace scope."""
    if session.info.get(_SCOPE_KEY) != (tenant_id, workspace_id):
        return None
    actor = session.info.get(_ACTOR_KEY)
    return actor if isinstance(actor, UUID) else None


async def capture_invitation_administrator(
    principal: CurrentPrincipal, session: DBSession,
) -> None:
    """Bind the already-authenticated principal to this request's DB session.

    The router retains its existing per-operation permission dependencies.
    A missing workspace is not given a reusable actor context.
    """
    if principal.workspace_id is None:
        session.info.pop(_ACTOR_KEY, None)
        session.info.pop(_SCOPE_KEY, None)
        return
    session.info[_ACTOR_KEY] = principal.user_id
    session.info[_SCOPE_KEY] = (principal.tenant_id, principal.workspace_id)
