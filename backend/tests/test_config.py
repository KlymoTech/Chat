from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from northstar_api.config import Settings


def _production_settings(**overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "app_env": "production",
        "app_auto_create_schema": False,
        "app_cors_origins": ["https://console.example.org"],
        "database_url": "postgresql+asyncpg://app:db-runtime-credential@postgres/northstar",
        "redis_url": "redis://:redis-runtime-credential@redis/0",
        "rabbitmq_url": "amqp://app:rabbit-runtime-credential@rabbitmq/northstar",
        "jwt_secret": "a-production-jwt-secret-with-more-than-32-characters",
        "mfa_encryption_key": "a-distinct-production-mfa-secret-with-more-than-32-characters",
        "require_nvidia": True,
        "nvidia_api_key": "provider-key-used-only-by-config-validation",
        "allow_deterministic_embeddings": False,
        "rate_limit_fail_open": False,
        "s3_access_key_id": "object-store-runtime-user",
        "s3_secret_access_key": "object-store-runtime-credential",
        "seed_admin_email": None,
        "seed_admin_password": None,
        "seed_demo_agent": False,
    }
    values.update(overrides)
    return Settings(**values)


def test_hardened_production_configuration_is_accepted() -> None:
    settings = _production_settings()

    assert settings.is_production
    assert settings.require_nvidia
    assert settings.mfa_encryption_key is not None
    assert not settings.allow_deterministic_embeddings
    assert not settings.rate_limit_fail_open


def test_production_accepts_explicit_aws_default_storage_credentials() -> None:
    settings = _production_settings(
        s3_auth_mode="aws-default",
        s3_access_key_id=None,
        s3_secret_access_key=None,
    )
    assert settings.s3_configured
    assert settings.s3_auth_mode == "aws-default"


@pytest.mark.parametrize(
    "override",
    [
        {"s3_access_key_id": "old-key", "s3_secret_access_key": "old-secret"},
        {"s3_endpoint_url": "http://minio:9000"},
        {"s3_public_endpoint_url": "https://objects.example.org"},
    ],
)
def test_aws_default_storage_rejects_static_keys_or_custom_endpoints(
    override: dict[str, Any],
) -> None:
    with pytest.raises(ValidationError, match="S3_AUTH_MODE=aws-default"):
        _production_settings(**{
            "s3_auth_mode": "aws-default",
            "s3_access_key_id": None,
            "s3_secret_access_key": None,
            **override,
        })


@pytest.mark.parametrize(
    ("override", "message"),
    [
        ({"jwt_secret": "replace-with-at-least-32-random-characters"}, "JWT_SECRET"),
        ({"mfa_encryption_key": None}, "MFA_ENCRYPTION_KEY"),
        ({"mfa_encryption_key": "too-short"}, "MFA_ENCRYPTION_KEY"),
        (
            {"mfa_encryption_key": "a-production-jwt-secret-with-more-than-32-characters"},
            "distinct from JWT_SECRET",
        ),
        (
            {"database_url": ("postgresql+asyncpg://app:replace-local-runtime-password@postgres/northstar")},
            "connection credentials",
        ),
        ({"app_cors_origins": ["*"]}, "Wildcard"),
        ({"allow_deterministic_embeddings": True}, "DETERMINISTIC_EMBEDDINGS"),
        ({"rate_limit_fail_open": True}, "RATE_LIMIT_FAIL_OPEN"),
    ],
)
def test_unsafe_production_configuration_is_rejected(override: dict[str, Any], message: str) -> None:
    with pytest.raises(ValidationError, match=message):
        _production_settings(**override)


def test_production_seed_requires_explicit_opt_in() -> None:
    with pytest.raises(ValidationError, match="ALLOW_PRODUCTION_SEED"):
        _production_settings(
            seed_admin_email="bootstrap@example.org",
            seed_admin_password="A-strong-bootstrap-password-42!",  # noqa: S106
        )


def test_blank_optional_seed_credentials_are_disabled() -> None:
    settings = Settings(seed_admin_email=" ", seed_admin_password="")

    assert settings.seed_admin_email is None
    assert settings.seed_admin_password is None


def test_blank_optional_whatsapp_configuration_is_disabled() -> None:
    settings = Settings(
        meta_app_id=" ",
        meta_app_secret="",
        meta_whatsapp_configuration_id="",
        meta_whatsapp_webhook_verify_token=" ",  # noqa: S106
        meta_whatsapp_token_encryption_key="",
    )

    assert not settings.whatsapp_configured


def test_partial_whatsapp_configuration_is_rejected() -> None:
    with pytest.raises(ValidationError, match="WhatsApp requires"):
        Settings(meta_app_id="123456789")


def test_production_rejects_non_meta_graph_base_url() -> None:
    with pytest.raises(ValidationError, match="META_GRAPH_BASE_URL"):
        _production_settings(meta_graph_base_url="https://example.invalid")
