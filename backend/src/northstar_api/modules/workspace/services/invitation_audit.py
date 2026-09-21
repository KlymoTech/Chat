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
from northstar_api.modules.workspace.services.invitation_actor import invitation_revoker_actor
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
    """Stage non-secret administrative metadata in the caller's transaction.

    The legacy revoke service does not take an actor argument. For that action
    alone, use a separately authenticated actor attached to this request's DB
    session, and only when tenant and workspace both match exactly. Public
    declines remain anonymous; the original inviter is never impersonated.
    """
    if action == "revoked" and actor_user_id is None:
        actor_user_id = invitation_revoker_actor(
            session, tenant_id=tenant_id, workspace_id=workspace_id,
        )
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
