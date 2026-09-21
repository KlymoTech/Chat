from __future__ import annotations

from contextvars import ContextVar
from uuid import UUID

from sqlalchemy import event, select
from sqlalchemy.orm import Session, with_loader_criteria

from northstar_api.models import Conversation

from .conversation_assignments import WorkspaceConversationAssignment

_assigned_user_context: ContextVar[UUID | None] = ContextVar(
    "workspace_assigned_conversation_user",
    default=None,
)


def set_assigned_conversation_scope(user_id: UUID | None) -> None:
    """Restrict Conversation ORM reads to rows assigned to ``user_id``.

    A ``None`` value means no assignment-level restriction. Tenant/workspace and
    agent scopes remain enforced by the existing principal/query pipeline.
    """
    _assigned_user_context.set(user_id)


@event.listens_for(Session, "do_orm_execute")
def apply_assigned_conversation_scope(execute_state: object) -> None:
    if not getattr(execute_state, "is_select", False):
        return
    user_id = _assigned_user_context.get()
    if user_id is None:
        return
    assignment_ids = select(WorkspaceConversationAssignment.conversation_id).where(
        WorkspaceConversationAssignment.assigned_user_id == user_id
    )
    execute_state.statement = execute_state.statement.options(  # type: ignore[attr-defined]
        with_loader_criteria(
            Conversation,
            Conversation.id.in_(assignment_ids),
            include_aliases=True,
        )
    )
