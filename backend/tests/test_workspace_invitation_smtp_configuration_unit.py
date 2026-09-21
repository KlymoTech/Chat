"""Invitation creation must report an unavailable mail service, not a raw config error."""
from __future__ import annotations

import hashlib
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest
from cryptography.fernet import Fernet

from northstar_api.email_config import EmailSettings
from northstar_api.modules.workspace.services import invitation_email_delivery as delivery
from northstar_api.modules.workspace.services.invitation_email_config import InvitationEmailConfig
from northstar_api.workspace_invitations import WorkspaceInvitationStatus


def _invitation(token: str) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid4(),
        tenant_id=uuid4(),
        workspace_id=uuid4(),
        status=WorkspaceInvitationStatus.PENDING,
        token_hash=hashlib.sha256(token.encode()).hexdigest(),
        last_sent_at=None,
        last_delivery_error=None,
    )


def test_invalid_smtp_settings_fail_closed_without_staging_secrets(monkeypatch: pytest.MonkeyPatch) -> None:
    token = "sensitive-invite-" + uuid4().hex
    session = SimpleNamespace(add=Mock())
    monkeypatch.setattr(
        delivery,
        "get_settings",
        lambda: SimpleNamespace(app_env="production", background_dispatch_enabled=True),
    )
    monkeypatch.setattr(
        delivery,
        "get_invitation_email_config",
        lambda: InvitationEmailConfig(
            workspace_invitation_delivery_key=Fernet.generate_key().decode("ascii"),
        ),
    )
    monkeypatch.setattr(
        delivery,
        "get_email_settings",
        lambda: EmailSettings(email_delivery_mode="smtp", smtp_host=""),
    )
    with pytest.raises(delivery.WorkspaceInvitationEmailUnavailable) as raised:
        delivery.stage_invitation_email(session, invitation=_invitation(token), raw_token=token)
    assert raised.value.status_code == 503
    assert str(raised.value) == "Workspace invitation SMTP delivery is not configured"
    assert token not in str(raised.value)
    session.add.assert_not_called()


def test_legacy_development_fallback_does_not_require_smtp(monkeypatch: pytest.MonkeyPatch) -> None:
    session = SimpleNamespace(add=Mock())
    monkeypatch.setattr(
        delivery,
        "get_settings",
        lambda: SimpleNamespace(app_env="development", background_dispatch_enabled=False),
    )
    monkeypatch.setattr(
        delivery,
        "get_invitation_email_config",
        lambda: InvitationEmailConfig(workspace_invitation_delivery_key=None),
    )
    monkeypatch.setattr(
        delivery,
        "get_email_settings",
        Mock(side_effect=AssertionError("The original development sender owns its delivery settings")),
    )
    assert delivery.stage_invitation_email(session, invitation=_invitation("token"), raw_token="token") is False
    session.add.assert_not_called()
