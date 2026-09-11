from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Literal
from uuid import UUID

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from jwt import InvalidTokenError

from northstar_api.config import Settings, get_settings
from northstar_api.models import Role, WorkspaceRole

WORKSPACE_ROLE_PERMISSIONS: dict[WorkspaceRole, frozenset[str]] = {
    WorkspaceRole.ADMIN: frozenset({"*"}),
    WorkspaceRole.MANAGER: frozenset(
        {
            "workspace.view",
            "members.view",
            "agents.view",
            "agents.create",
            "agents.update",
            "agents.deploy",
            "knowledge.view",
            "knowledge.manage",
            "conversations.view",
            "conversations.reply",
            "conversations.resolve",
            "conversations.assign",
            "leads.view",
            "leads.update",
            "leads.export",
            "integrations.view",
            "crm.view",
            "analytics.view",
            "education.view",
            "education.manage",
            "settings.view",
        }
    ),
    WorkspaceRole.OPERATOR: frozenset(
        {
            "workspace.view",
            "agents.view",
            "knowledge.view",
            "conversations.view",
            "conversations.reply",
            "conversations.resolve",
            "conversations.assign",
            "leads.view",
            "leads.update",
            "education.view",
        }
    ),
    WorkspaceRole.ANALYST: frozenset(
        {
            "workspace.view",
            "agents.view",
            "knowledge.view",
            "conversations.view",
            "leads.view",
            "leads.export",
            "analytics.view",
            "integrations.view",
            "crm.view",
            "education.view",
        }
    ),
    WorkspaceRole.VIEWER: frozenset(
        {
            "workspace.view",
            "agents.view",
            "knowledge.view",
            "conversations.view",
            "leads.view",
            "analytics.view",
            "education.view",
        }
    ),
}

TENANT_ROLE_PERMISSIONS: dict[Role, frozenset[str]] = {
    Role.OWNER: frozenset({"*"}),
    Role.ADMIN: frozenset({"*"}),
    Role.BILLING_ADMIN: frozenset({"workspace.view", "billing.view", "billing.manage", "usage.view"}),
    Role.SECURITY_ADMIN: frozenset(
        {
            "workspace.view",
            "members.view",
            "security.view",
            "security.manage",
            "audit.view",
        }
    ),
    Role.MEMBER: frozenset(),
    Role.ANALYST: frozenset(),
}

password_hasher = PasswordHasher(time_cost=3, memory_cost=65_536, parallelism=4, hash_len=32, salt_len=16)
_DUMMY_HASH = password_hasher.hash("not-a-real-password-for-timing-equalization")


@dataclass(frozen=True, slots=True)
class Principal:
    user_id: UUID
    tenant_id: UUID
    role: Role
    token_id: str
    workspace_id: UUID | None = None
    workspace_role: WorkspaceRole | None = None
    permissions: frozenset[str] = field(default_factory=frozenset)
    agent_ids: frozenset[UUID] | None = None

    def can(self, permission: str) -> bool:
        return "*" in self.permissions or permission in self.permissions


@dataclass(frozen=True, slots=True)
class WidgetPrincipal:
    tenant_id: UUID
    agent_id: UUID
    conversation_id: UUID
    origin: str
    token_id: str


def hash_password(password: str) -> str:
    return password_hasher.hash(password)


def verify_password(password: str, password_hash: str | None) -> bool:
    candidate = password_hash or _DUMMY_HASH
    try:
        valid = password_hasher.verify(candidate, password)
        return bool(valid and password_hash)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def _token(
    subject: str,
    token_type: Literal["access", "refresh", "widget", "whatsapp_signup", "mfa_challenge"],
    expires_delta: timedelta,
    claims: dict[str, Any],
    settings: Settings,
) -> tuple[str, datetime]:
    now = datetime.now(UTC)
    expires_at = now + expires_delta
    payload = {
        "sub": subject,
        "type": token_type,
        "iat": now,
        "nbf": now,
        "exp": expires_at,
        "iss": settings.jwt_issuer,
        "aud": settings.jwt_audience,
        "jti": secrets.token_urlsafe(18),
        **claims,
    }
    encoded = jwt.encode(payload, settings.jwt_secret.get_secret_value(), algorithm=settings.jwt_algorithm)
    return encoded, expires_at


def create_access_token(
    user_id: UUID,
    tenant_id: UUID,
    role: Role,
    settings: Settings | None = None,
    *,
    credential_version: int = 0,
) -> tuple[str, datetime]:
    config = settings or get_settings()
    return _token(
        str(user_id),
        "access",
        timedelta(minutes=config.jwt_access_ttl_minutes),
        {"tid": str(tenant_id), "role": role.value, "cv": credential_version},
        config,
    )


def create_refresh_token(
    user_id: UUID,
    tenant_id: UUID,
    role: Role,
    settings: Settings | None = None,
    *,
    family_id: str | None = None,
    credential_version: int = 0,
) -> tuple[str, datetime]:
    config = settings or get_settings()
    return _token(
        str(user_id),
        "refresh",
        timedelta(days=config.jwt_refresh_ttl_days),
        {
            "tid": str(tenant_id),
            "role": role.value,
            "fid": family_id or secrets.token_urlsafe(18),
            "cv": credential_version,
        },
        config,
    )


def create_mfa_challenge_token(
    user_id: UUID,
    tenant_id: UUID,
    role: Role,
    settings: Settings | None = None,
    *,
    credential_version: int = 0,
) -> tuple[str, datetime]:
    config = settings or get_settings()
    return _token(
        str(user_id),
        "mfa_challenge",
        timedelta(minutes=5),
        {"tid": str(tenant_id), "role": role.value, "cv": credential_version},
        config,
    )


def create_widget_token(
    tenant_id: UUID,
    agent_id: UUID,
    conversation_id: UUID,
    origin: str,
    settings: Settings | None = None,
) -> tuple[str, datetime]:
    config = settings or get_settings()
    return _token(
        str(conversation_id),
        "widget",
        timedelta(hours=12),
        {"tid": str(tenant_id), "aid": str(agent_id), "origin": origin},
        config,
    )


def create_whatsapp_signup_token(
    user_id: UUID,
    tenant_id: UUID,
    settings: Settings | None = None,
) -> tuple[str, datetime]:
    config = settings or get_settings()
    return _token(
        str(user_id),
        "whatsapp_signup",
        timedelta(seconds=config.meta_signup_session_ttl_seconds),
        {"tid": str(tenant_id)},
        config,
    )


def decode_token(token: str, expected_type: str, settings: Settings | None = None) -> dict[str, Any]:
    config = settings or get_settings()
    try:
        payload = jwt.decode(
            token,
            config.jwt_secret.get_secret_value(),
            algorithms=[config.jwt_algorithm],
            issuer=config.jwt_issuer,
            audience=config.jwt_audience,
            options={"require": ["exp", "iat", "nbf", "iss", "aud", "sub", "jti", "type"]},
        )
    except InvalidTokenError as exc:
        raise ValueError("invalid or expired token") from exc
    if payload.get("type") != expected_type:
        raise ValueError("unexpected token type")
    return payload


def token_fingerprint(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def generate_api_key() -> tuple[str, str, str]:
    plaintext = "nsk_live_" + secrets.token_urlsafe(32)
    return plaintext, plaintext[:16], token_fingerprint(plaintext)
