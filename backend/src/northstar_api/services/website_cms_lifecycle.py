"""CMS publication state machine; a pure domain guard for future persistence endpoints.

Publishing APIs must still perform role authorization, transactional revision writes,
audit/outbox creation and cache invalidation before claiming publication success.
"""
from __future__ import annotations

from enum import StrEnum
from pydantic import BaseModel, ConfigDict, Field, model_validator


class EditorialState(StrEnum):
    DRAFT = "draft"
    IN_REVIEW = "in_review"
    APPROVED = "approved"
    SCHEDULED = "scheduled"
    PUBLISHED = "published"
    ARCHIVED = "archived"


class EditorialAction(StrEnum):
    SUBMIT = "submit"
    APPROVE = "approve"
    REQUEST_CHANGES = "request_changes"
    SCHEDULE = "schedule"
    PUBLISH = "publish"
    ARCHIVE = "archive"
    RESTORE_DRAFT = "restore_draft"


_TRANSITIONS = {
    (EditorialState.DRAFT, EditorialAction.SUBMIT): EditorialState.IN_REVIEW,
    (EditorialState.IN_REVIEW, EditorialAction.APPROVE): EditorialState.APPROVED,
    (EditorialState.IN_REVIEW, EditorialAction.REQUEST_CHANGES): EditorialState.DRAFT,
    (EditorialState.APPROVED, EditorialAction.SCHEDULE): EditorialState.SCHEDULED,
    (EditorialState.APPROVED, EditorialAction.PUBLISH): EditorialState.PUBLISHED,
    (EditorialState.SCHEDULED, EditorialAction.PUBLISH): EditorialState.PUBLISHED,
    (EditorialState.SCHEDULED, EditorialAction.REQUEST_CHANGES): EditorialState.DRAFT,
    (EditorialState.PUBLISHED, EditorialAction.ARCHIVE): EditorialState.ARCHIVED,
    (EditorialState.ARCHIVED, EditorialAction.RESTORE_DRAFT): EditorialState.DRAFT,
}


class EditorialTransition(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    before: EditorialState
    action: EditorialAction
    after: EditorialState
    actor_id: str = Field(min_length=1, max_length=128)
    revision_id: str = Field(min_length=1, max_length=128)

    @model_validator(mode="after")
    def check_transition(self) -> "EditorialTransition":
        if _TRANSITIONS.get((self.before, self.action)) != self.after:
            raise ValueError("Invalid CMS editorial state transition")
        return self


def next_editorial_state(before: EditorialState, action: EditorialAction) -> EditorialState:
    try:
        return _TRANSITIONS[(before, action)]
    except KeyError as exc:
        raise ValueError("Invalid CMS editorial state transition") from exc
