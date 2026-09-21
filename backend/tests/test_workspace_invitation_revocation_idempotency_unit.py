"""A repeated Workspace invitation DELETE must not change credentials or audit history."""
from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest

from northstar_api.services import workspace_invitations as invitations
from northstar_api.workspace_invitations import WorkspaceInvitationStatus


class _Session:
    def __init__(self, invitation: SimpleNamespace | None) -> None:
        self.invitation = invitation
        self.flushes = 0
        self.query = None

    async def scalar(self, query):
        self.query = query
        return self.invitation

    async def flush(self) -> None:
        self.flushes += 1


def _invitation(status: WorkspaceInvitationStatus) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid4(), status=status, role=SimpleNamespace(value="viewer"),
        all_agents_access=True, token_hash="existing-hash",
        revoked_at=datetime(2026, 1, 1, tzinfo=UTC),
        updated_at=datetime(2026, 1, 1, tzinfo=UTC),
    )


def _revoke(session: _Session, *, tenant_id=None, workspace_id=None) -> None:
    asyncio.run(invitations.revoke_workspace_invitation(
        session, tenant_id=tenant_id or uuid4(), workspace_id=workspace_id or uuid4(),
        invitation_id=session.invitation.id if session.invitation else uuid4(),
    ))


def test_repeated_revoke_preserves_token_timestamps_and_emits_no_event(monkeypatch: pytest.MonkeyPatch) -> None:
    invitation = _invitation(WorkspaceInvitationStatus.REVOKED)
    session = _Session(invitation)
    staged: list[dict[str, object]] = []
    monkeypatch.setattr(invitations, "stage_invitation_transition", lambda *_args, **kwargs: staged.append(kwargs))
    before = (invitation.token_hash, invitation.revoked_at, invitation.updated_at)
    _revoke(session)
    _revoke(session)
    assert (invitation.token_hash, invitation.revoked_at, invitation.updated_at) == before
    assert session.flushes == 0
    assert staged == []
    assert session.query is not None  # existing scoped, locking lookup is retained


def test_first_revoke_rotates_token_and_emits_exactly_one_event(monkeypatch: pytest.MonkeyPatch) -> None:
    invitation = _invitation(WorkspaceInvitationStatus.PENDING)
    session = _Session(invitation)
    staged: list[dict[str, object]] = []
    monkeypatch.setattr(invitations, "stage_invitation_transition", lambda *_args, **kwargs: staged.append(kwargs))
    tenant_id, workspace_id = uuid4(), uuid4()
    _revoke(session, tenant_id=tenant_id, workspace_id=workspace_id)
    assert invitation.status == WorkspaceInvitationStatus.REVOKED
    assert invitation.token_hash != "existing-hash"
    assert invitation.updated_at > datetime(2026, 1, 1, tzinfo=UTC)
    assert session.flushes == 1
    assert len(staged) == 1
    assert staged[0]["action"] == "revoked"
    assert staged[0]["tenant_id"] == tenant_id
    assert staged[0]["workspace_id"] == workspace_id
    snapshot = (invitation.token_hash, invitation.revoked_at, invitation.updated_at)
    _revoke(session, tenant_id=tenant_id, workspace_id=workspace_id)
    assert (invitation.token_hash, invitation.revoked_at, invitation.updated_at) == snapshot
    assert session.flushes == 1 and len(staged) == 1


def test_accepted_invitation_remains_protected(monkeypatch: pytest.MonkeyPatch) -> None:
    session = _Session(_invitation(WorkspaceInvitationStatus.ACCEPTED))
    staged: list[dict[str, object]] = []
    monkeypatch.setattr(invitations, "stage_invitation_transition", lambda *_args, **kwargs: staged.append(kwargs))
    with pytest.raises(invitations.WorkspaceInvitationError) as exc:
        _revoke(session)
    assert exc.value.status_code == 409
    assert session.flushes == 0 and not staged
    assert session.invitation.status == WorkspaceInvitationStatus.ACCEPTED


def test_missing_invitation_still_returns_not_found() -> None:
    session = _Session(None)
    with pytest.raises(invitations.WorkspaceInvitationError) as exc:
        _revoke(session)
    assert exc.value.status_code == 404
    assert session.flushes == 0
