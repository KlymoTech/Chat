"""CMS editorial lifecycle validation and no-implicit-publish tests."""
import pytest
from pydantic import ValidationError
from northstar_api.services.website_cms_lifecycle import (
    EditorialAction, EditorialState, EditorialTransition, next_editorial_state,
)


def test_review_to_publication_requires_approval():
    assert next_editorial_state(EditorialState.DRAFT, EditorialAction.SUBMIT) == EditorialState.IN_REVIEW
    assert next_editorial_state(EditorialState.IN_REVIEW, EditorialAction.APPROVE) == EditorialState.APPROVED
    assert next_editorial_state(EditorialState.APPROVED, EditorialAction.PUBLISH) == EditorialState.PUBLISHED


@pytest.mark.parametrize("before,action", [
    (EditorialState.DRAFT, EditorialAction.PUBLISH),
    (EditorialState.IN_REVIEW, EditorialAction.PUBLISH),
    (EditorialState.ARCHIVED, EditorialAction.PUBLISH),
    (EditorialState.PUBLISHED, EditorialAction.RESTORE_DRAFT),
])
def test_illegal_transitions_fail(before, action):
    with pytest.raises(ValueError, match="Invalid"):
        next_editorial_state(before, action)


def test_approved_content_may_be_scheduled():
    assert next_editorial_state(EditorialState.APPROVED, EditorialAction.SCHEDULE) == EditorialState.SCHEDULED
    assert next_editorial_state(EditorialState.SCHEDULED, EditorialAction.PUBLISH) == EditorialState.PUBLISHED


def test_archived_content_restores_only_to_draft():
    assert next_editorial_state(EditorialState.PUBLISHED, EditorialAction.ARCHIVE) == EditorialState.ARCHIVED
    assert next_editorial_state(EditorialState.ARCHIVED, EditorialAction.RESTORE_DRAFT) == EditorialState.DRAFT


def test_auditable_transition_contract_rejects_forged_state():
    with pytest.raises(ValidationError):
        EditorialTransition(
            before="draft", action="publish", after="published",
            actor_id="owner-1", revision_id="rev-1",
        )


def test_transition_requires_actor_and_revision():
    with pytest.raises(ValidationError):
        EditorialTransition(
            before="approved", action="publish", after="published",
            actor_id="", revision_id="",
        )
