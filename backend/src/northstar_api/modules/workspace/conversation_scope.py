from __future__ import annotations

from uuid import UUID

from sqlalchemy import event, or_, select
from sqlalchemy.orm import Session, with_loader_criteria

from northstar_api.models import Conversation

from .conversation_assignment_model import WorkspaceConversationAssignment

_SESSION_KEY = "workspace_conversation_assignment_scope"


def set_conversation_assignment_scope(
    session: object,
    *,
    user_id: UUID | None = None,
    team_ids: frozenset[str] | None = None,
) -> None:
    """Attach conversation-assignment scope to the current database session.

    With no user/team scope the assignment restriction is removed. Assigned
    scope filters by ``assigned_user_id``; team scope filters by one of the
    caller's workspace team IDs. Existing tenant/workspace/agent constraints
    remain additional boundaries in the normal query pipeline.
    """
    sync_session = getattr(session, "sync_session", session)
    info = getattr(sync_session, "info", None)
    if info is None:
        return
    normalized_team_ids = frozenset(value for value in (team_ids or frozenset()) if value)
    if user_id is None and not normalized_team_ids:
        info.pop(_SESSION_KEY, None)
    else:
        info[_SESSION_KEY] = (user_id, normalized_team_ids)


@event.listens_for(Session, "do_orm_execute")
def apply_conversation_assignment_scope(execute_state: object) -> None:
    if not getattr(execute_state, "is_select", False):
        return
    session = getattr(execute_state, "session", None)
    info = getattr(session, "info", {}) if session is not None else {}
    scope = info.get(_SESSION_KEY)
    if scope is None:
        return
    user_id, team_ids = scope
    predicates: list[object] = []
    if user_id is not None:
        predicates.append(WorkspaceConversationAssignment.assigned_user_id == user_id)
    if team_ids:
        predicates.append(WorkspaceConversationAssignment.assigned_team_id.in_(team_ids))
    if not predicates:
        return
    assignment_ids = select(WorkspaceConversationAssignment.conversation_id).where(
        or_(*predicates)
    )
    execute_state.statement = execute_state.statement.options(  # type: ignore[attr-defined]
        with_loader_criteria(
            Conversation,
            Conversation.id.in_(assignment_ids),
            include_aliases=True,
        )
    )
