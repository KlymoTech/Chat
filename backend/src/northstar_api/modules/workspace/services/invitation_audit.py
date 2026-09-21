"""Allowlisted audit/outbox staging for Workspace invitation transitions.

All writes use the caller's SQLAlchemy transaction; no tokens, token hashes,
recipient email addresses, passwords or invitation links enter event payloads.
The caller must commit or roll back its invitation and these records together.
"""
from __future__ import annotations

from typing import Literal
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from northstar_api.lead_crm.audit import record_audit_event
from northstar_api.services.outbox import enqueue_event

InvitationAction = Literal[
    "invited", "resent", "revoked", "accepted", "declined", "delivery_succeeded", "delivery_failed",
]


def stage_invitation_transition(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    workspace_id: UUID,
    invitation_id: UUID,
    actor_user_id: UUID | None,
    action: InvitationAction,
    role: str,
    all_agents_access: bool,
    agent_count: int | None = None,
) -> None:
    """Stage only non-secret administrative metadata in the current transaction.

    A public decline has no authenticated actor. A legacy revocation call also
    lacks an actor parameter; never claim that the original inviter revoked it.
    """
    metadata: dict[str, str | bool | int] = {
        "role": role,
        "allAgentsAccess": all_agents_access,
    }
    if agent_count is not None:
        metadata["agentCount"] = agent_count
    record_audit_event(
        session,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        actor_user_id=actor_user_id,
        action=f"workspace.invitation.{action}",
        entity_type="workspace_invitation",
        entity_id=str(invitation_id),
        category="access",
        metadata=metadata,
    )
    event = enqueue_event(
        session,
        tenant_id=tenant_id,
        aggregate_type="workspace_invitation",
        aggregate_id=invitation_id,
        event_type=f"workspace.invitation.{action}.v1",
        payload={"workspaceId": str(workspace_id), "invitationId": str(invitation_id), **metadata},
    )
    event.workspace_id = workspace_id
