"""Current-key encryption and bounded previous-key decryption for queued invites."""
from __future__ import annotations

import pytest
from cryptography.fernet import Fernet, InvalidToken, MultiFernet
from pydantic import SecretStr

from northstar_api.modules.workspace.services.invitation_email_config import (
    InvitationEmailConfig,
    InvitationEmailConfigurationError,
    invitation_cipher,
)


def _config(current: str | None, previous: str | None = None) -> InvitationEmailConfig:
    return InvitationEmailConfig(
        workspace_invitation_delivery_key=SecretStr(current) if current is not None else None,
        workspace_invitation_delivery_previous_keys=SecretStr(previous) if previous is not None else None,
    )


def test_single_key_keeps_existing_encryption_contract() -> None:
    key = Fernet.generate_key().decode("ascii")
    cipher = invitation_cipher(_config(key))
    assert isinstance(cipher, Fernet)
    assert cipher.decrypt(cipher.encrypt(b"secret")) == b"secret"


def test_rotation_decrypts_outstanding_job_and_encrypts_only_with_new_key() -> None:
    old_key = Fernet.generate_key()
    new_key = Fernet.generate_key()
    old_job = Fernet(old_key).encrypt(b"pending-invitation")
    cipher = invitation_cipher(_config(new_key.decode(), old_key.decode()))
    assert isinstance(cipher, MultiFernet)
    assert cipher.decrypt(old_job) == b"pending-invitation"
    new_job = cipher.encrypt(b"new-invitation")
    assert Fernet(new_key).decrypt(new_job) == b"new-invitation"
    with pytest.raises(InvalidToken):
        Fernet(old_key).decrypt(new_job)


def test_multiple_previous_keys_are_accepted_without_changing_encryption_key() -> None:
    keys = [Fernet.generate_key() for _ in range(3)]
    cipher = invitation_cipher(_config(keys[0].decode(), ", ".join(key.decode() for key in keys[1:])))
    assert cipher is not None
    assert cipher.decrypt(Fernet(keys[1]).encrypt(b"one")) == b"one"
    assert cipher.decrypt(Fernet(keys[2]).encrypt(b"two")) == b"two"
    assert Fernet(keys[0]).decrypt(cipher.encrypt(b"new")) == b"new"


@pytest.mark.parametrize("previous", [",", "not-a-fernet-key", "valid-key,"])
def test_malformed_previous_keys_fail_closed(previous: str) -> None:
    with pytest.raises(InvitationEmailConfigurationError, match="distinct valid Fernet keys"):
        invitation_cipher(_config(Fernet.generate_key().decode(), previous))


def test_duplicate_previous_or_current_key_fails_closed() -> None:
    key = Fernet.generate_key().decode()
    with pytest.raises(InvitationEmailConfigurationError):
        invitation_cipher(_config(key, key))
    old = Fernet.generate_key().decode()
    with pytest.raises(InvitationEmailConfigurationError):
        invitation_cipher(_config(key, f"{old},{old}"))


def test_previous_key_without_primary_fails_closed() -> None:
    with pytest.raises(InvitationEmailConfigurationError, match="required"):
        invitation_cipher(_config(None, Fernet.generate_key().decode()))


def test_unconfigured_key_ring_preserves_existing_development_fallback() -> None:
    assert invitation_cipher(_config(None)) is None
