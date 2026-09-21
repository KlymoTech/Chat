"""Secret-safe, transactional Workspace invitation email delivery contract."""
from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest
from cryptography.fernet import Fernet
from pydantic import SecretStr

from northstar_api.modules.workspace.services import invitation_email_delivery as delivery
from northstar_api.modules.workspace.services.invitation_email_config import InvitationEmailConfig
from northstar_api.workspace_invitations import WorkspaceInvitationStatus
from northstar_api.workers import workspace_invitation_email_tasks


def _invite(token: str):
    return SimpleNamespace(
        id=uuid4(), tenant_id=uuid4(), workspace_id=uuid4(),
        status=WorkspaceInvitationStatus.PENDING,
        token_hash=hashlib.sha256(token.encode()).hexdigest(),
        last_sent_at=datetime.now(UTC), last_delivery_error="old error",
    )


def _configure(monkeypatch, *, key: str | None, env: str = "test", dispatch: bool = False, smtp: bool = True):
    monkeypatch.setattr(delivery, "get_settings", lambda: SimpleNamespace(
        app_env=env, background_dispatch_enabled=dispatch,
    ))
    monkeypatch.setattr(delivery, "get_email_settings", lambda: SimpleNamespace(
        email_delivery_mode="smtp" if smtp else "log",
    ))
    monkeypatch.setattr(delivery, "get_invitation_email_config", lambda: InvitationEmailConfig(
        workspace_invitation_delivery_key=SecretStr(key) if key else None,
    ))


def test_staged_credentials_are_encrypted_and_never_sent_to_an_ordinary_event(monkeypatch):
    key = Fernet.generate_key().decode()
    token = "test-raw-invitation-secret-" + uuid4().hex
    invitation = _invite(token)
    session = SimpleNamespace(add=Mock())
    _configure(monkeypatch, key=key)
    assert delivery.stage_invitation_email(session, invitation=invitation, raw_token=token)
    session.add.assert_called_once()
    job = session.add.call_args.args[0]
    assert job.tenant_id == invitation.tenant_id
    assert job.workspace_id == invitation.workspace_id
    assert job.invitation_id == invitation.id
    assert token not in job.ciphertext
    assert Fernet(key.encode()).decrypt(job.ciphertext.encode()).decode() == token
    assert job.token_hash == invitation.token_hash
    assert invitation.last_sent_at is None
    assert invitation.last_delivery_error is None
    assert not hasattr(job, "recipient_email")


@pytest.mark.parametrize("env, dispatch, expected", [
    ("production", True, "encryption"),
    ("staging", True, "encryption"),
])
def test_missing_key_fails_closed_and_does_not_stage(monkeypatch, env, dispatch, expected):
    _configure(monkeypatch, key=None, env=env, dispatch=dispatch)
    session = SimpleNamespace(add=Mock())
    with pytest.raises(delivery.WorkspaceInvitationEmailUnavailable, match=expected):
        delivery.stage_invitation_email(session, invitation=_invite("token"), raw_token="token")
    session.add.assert_not_called()


def test_missing_key_keeps_only_original_development_fallback(monkeypatch):
    _configure(monkeypatch, key=None, env="test")
    session = SimpleNamespace(add=Mock())
    assert delivery.stage_invitation_email(session, invitation=_invite("token"), raw_token="token") is False
    session.add.assert_not_called()


@pytest.mark.parametrize("env, dispatch, smtp, expected", [
    ("production", False, True, "dispatcher"),
    ("production", True, False, "SMTP"),
])
def test_missing_dispatcher_or_smtp_fails_before_staging(monkeypatch, env, dispatch, smtp, expected):
    _configure(monkeypatch, key=Fernet.generate_key().decode(), env=env, dispatch=dispatch, smtp=smtp)
    session = SimpleNamespace(add=Mock())
    with pytest.raises(delivery.WorkspaceInvitationEmailUnavailable, match=expected):
        delivery.stage_invitation_email(session, invitation=_invite("token"), raw_token="token")
    session.add.assert_not_called()


def test_changed_token_is_not_queued(monkeypatch):
    _configure(monkeypatch, key=Fernet.generate_key().decode())
    session = SimpleNamespace(add=Mock())
    with pytest.raises(delivery.WorkspaceInvitationEmailUnavailable, match="changed"):
        delivery.stage_invitation_email(session, invitation=_invite("original"), raw_token="rotated")
    session.add.assert_not_called()


class _Session:
    def __init__(self, jobs):
        self.jobs = jobs

    async def scalars(self, _statement):
        return SimpleNamespace(all=lambda: self.jobs)


@pytest.mark.asyncio
async def test_dispatch_retries_failed_job_with_only_identifiers(monkeypatch):
    job = SimpleNamespace(
        id=uuid4(), tenant_id=uuid4(), status="failed", dispatch_attempts=0,
        ciphertext="encrypted-only", next_dispatch_at=None,
        dispatched_at=None, last_error="SMTPException",
    )
    apply = Mock()
    monkeypatch.setattr(workspace_invitation_email_tasks.send_workspace_invitation_email_task, "apply_async", apply)
    now = datetime.now(UTC)
    assert await delivery.dispatch_invitation_email_jobs(_Session([job]), now=now) == 1
    assert apply.call_args.kwargs["args"] == [str(job.tenant_id), str(job.id)]
    assert apply.call_args.kwargs["queue"] == "workspace.email"
    assert "encrypted-only" not in str(apply.call_args)
    assert job.status == "queued"
    assert job.dispatch_attempts == 1
    assert job.next_dispatch_at == now + timedelta(minutes=5)


@pytest.mark.asyncio
async def test_broker_failure_keeps_ciphertext_for_bounded_retry(monkeypatch):
    job = SimpleNamespace(
        id=uuid4(), tenant_id=uuid4(), status="queued", dispatch_attempts=0,
        ciphertext="encrypted-only", next_dispatch_at=None, last_error=None,
    )
    monkeypatch.setattr(
        workspace_invitation_email_tasks.send_workspace_invitation_email_task,
        "apply_async", Mock(side_effect=RuntimeError("broker secret must not be logged")),
    )
    assert await delivery.dispatch_invitation_email_jobs(_Session([job])) == 0
    assert job.status == "queued"
    assert job.dispatch_attempts == 1
    assert job.ciphertext == "encrypted-only"
    assert job.last_error == "RuntimeError"
    assert job.next_dispatch_at is not None
