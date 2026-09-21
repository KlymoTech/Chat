"""Separate envelope-encryption configuration for durable Workspace invite mail.

Do not reuse JWT, MFA, CRM or WhatsApp encryption keys for invitation tokens.
"""
from __future__ import annotations

from functools import lru_cache

from cryptography.fernet import Fernet
from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class InvitationEmailConfigurationError(RuntimeError):
    """Fail closed without leaking the configured key or invitation token."""


class InvitationEmailConfig(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")
    workspace_invitation_delivery_key: SecretStr | None = None

    @field_validator("workspace_invitation_delivery_key", mode="before")
    @classmethod
    def empty_key_is_missing(cls, value: object) -> object | None:
        return None if value is None or isinstance(value, str) and not value.strip() else value


def invitation_cipher(config: InvitationEmailConfig) -> Fernet | None:
    secret = config.workspace_invitation_delivery_key
    if secret is None:
        return None
    try:
        return Fernet(secret.get_secret_value().encode("ascii"))
    except (ValueError, TypeError, UnicodeError):
        raise InvitationEmailConfigurationError(
            "WORKSPACE_INVITATION_DELIVERY_KEY must be a valid independent Fernet key"
        ) from None


@lru_cache(maxsize=1)
def get_invitation_email_config() -> InvitationEmailConfig:
    return InvitationEmailConfig()
