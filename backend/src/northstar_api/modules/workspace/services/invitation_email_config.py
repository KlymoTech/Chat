"""Separate envelope-encryption configuration for durable Workspace invite mail.

Do not reuse JWT, MFA, CRM or WhatsApp encryption keys for invitation tokens.
New jobs use the current key; configured previous keys decrypt outstanding jobs.
"""
from __future__ import annotations

from functools import lru_cache

from cryptography.fernet import Fernet, MultiFernet
from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class InvitationEmailConfigurationError(RuntimeError):
    """Fail closed without leaking the configured key or invitation token."""


class InvitationEmailConfig(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")
    workspace_invitation_delivery_key: SecretStr | None = None
    workspace_invitation_delivery_previous_keys: SecretStr | None = None

    @field_validator(
        "workspace_invitation_delivery_key",
        "workspace_invitation_delivery_previous_keys",
        mode="before",
    )
    @classmethod
    def empty_key_is_missing(cls, value: object) -> object | None:
        return None if value is None or isinstance(value, str) and not value.strip() else value


def invitation_cipher(config: InvitationEmailConfig) -> Fernet | MultiFernet | None:
    """Encrypt with the current key; decrypt with it or approved older keys.

    Previous keys are a comma-separated environment secret. An invalid, empty,
    repeated or current-key duplicate entry is a configuration error, never a
    reason to silently discard the entry and risk losing queued invitations.
    """
    current = config.workspace_invitation_delivery_key
    previous = config.workspace_invitation_delivery_previous_keys
    if current is None:
        if previous is not None:
            raise InvitationEmailConfigurationError(
                "WORKSPACE_INVITATION_DELIVERY_KEY is required when previous keys are configured"
            )
        return None
    try:
        current_value = current.get_secret_value().strip()
        values = [current_value]
        if previous is not None:
            values.extend(part.strip() for part in previous.get_secret_value().split(","))
        if any(not value for value in values) or len(values) != len(set(values)):
            raise ValueError("Invalid or duplicate invitation delivery keys")
        ciphers = [Fernet(value.encode("ascii")) for value in values]
        return ciphers[0] if len(ciphers) == 1 else MultiFernet(ciphers)
    except (ValueError, TypeError, UnicodeError):
        raise InvitationEmailConfigurationError(
            "WORKSPACE_INVITATION_DELIVERY_KEY and previous keys must be distinct valid Fernet keys"
        ) from None


@lru_cache(maxsize=1)
def get_invitation_email_config() -> InvitationEmailConfig:
    return InvitationEmailConfig()
