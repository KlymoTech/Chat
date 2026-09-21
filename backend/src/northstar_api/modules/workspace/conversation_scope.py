from __future__ import annotations

from uuid import UUID

from sqlalchemy import event, select
from sqlalchemy.orm import Session, with_loader_criteria

from northstar_api.models import Conversation

from .conversation_assignment_model import WorkspaceConversationAssignment

_SESSION_KEY = "workspace_assigned_conversation_user_id"


def set_assigned_conversation_scope(session: object, user_id: UUID | None) -> None:
    """Attach assigned-conversation scope to the current database session only.

    ``None`` removes the assignment-level restriction. Tenant/workspace and
    agent scopes continue to be enforced by the existing principal/query
    pipeline. Keeping this state on the request-scoped SQLAlchemy session avoids
    cross-request leakage while allowing all Conversation ORM queries to share
    the same enforcement point.
    """
    sync_session = getattr(session, "sync_session", session)
    info = getattr(sync_session, "info", None)
    if info is None:
        return
    if user_id is None:
        info.pop(_SESSION_KEY, None)
    else:
        info[_SESSION_KEY] = user_id


@event.listens_for(Session, "do_orm_execute")
def apply_assigned_conversation_scope(execute_state: object) -> None:
    if not getattr(execute_state, "is_select", False):
        return
    session = getattr(execute_state, "session", None)
    info = getattr(session, "info", {}) if session is not None else {}
    user_id = info.get(_SESSION_KEY)
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
