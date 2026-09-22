"""Portable configuration contracts for the AWS-modular runtime profiles.

These models describe desired state only. They do not create AWS resources,
resolve secrets, or select an adapter; the composition root remains the only
place allowed to do that.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class _Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


ProviderChangeClass = Literal["hot-safe", "restart", "migration", "prohibited"]
Orchestrator = Literal["docker", "ecs", "eks"]
DeploymentProfile = Literal["local", "portable-production", "aws-standard", "aws-scale", "aws-kubernetes"]
CacheProvider = Literal["none", "redis"]
JobProvider = Literal["postgres", "rabbitmq", "sqs"]
EventProvider = Literal["postgres", "kafka"]
StorageProvider = Literal["s3", "minio"]
IdentityProvider = Literal["local", "oidc"]
SearchProvider = Literal["postgres", "opensearch"]
VectorProvider = Literal["disabled", "pgvector"]
NotificationProvider = Literal["none", "smtp", "ses"]
SecretProvider = Literal["env", "aws-secrets-manager"]
AIProvider = Literal["none", "nvidia", "openai-compatible"]


class DeploymentSpec(_Contract):
    orchestrator: Orchestrator = "docker"
    region: str = Field(default="local", min_length=1, max_length=64)
    account_id: str | None = Field(default=None, pattern=r"^\d{12}$")
    availability_zones: tuple[str, ...] = Field(default_factory=tuple, max_length=6)
    image_digest: str | None = Field(
        default=None,
        pattern=r"^sha256:[0-9a-f]{64}$",
        description="Immutable OCI image digest; mutable image tags are not accepted.",
    )


class ProviderSpec(_Contract):
    cache: CacheProvider = "none"
    jobs: JobProvider = "postgres"
    events: EventProvider = "postgres"
    storage: StorageProvider = "minio"
    identity: IdentityProvider = "local"
    search: SearchProvider = "postgres"
    vector: VectorProvider = "disabled"
    notifications: NotificationProvider = "none"
    secrets: SecretProvider = "env"
    ai: AIProvider = "none"


class FeatureSpec(_Contract):
    documents: bool = False
    ai: bool = False
    rag: bool = False
    analytics: bool = True
    whatsapp: bool = False


class ResourceSpec(_Contract):
    redis_provisioned: bool = False
    kafka_provisioned: bool = False


class ReliabilitySpec(_Contract):
    jobs_acceptance: Literal["postgres-ledger", "broker-ledger"] = "postgres-ledger"
    events_acceptance: Literal["transactional-outbox", "kafka"] = "transactional-outbox"
    automatic_stateful_provider_switch: bool = False
    cache_failure_mode: Literal["bypass", "fail-closed"] = "bypass"
    accepted_work_delivery: Literal["at-least-once"] = "at-least-once"
    require_idempotency: bool = True
    require_reconciliation: bool = True


class SecuritySpec(_Contract):
    authorization_required: bool = True
    tenant_isolation_required: bool = True
    audit_required: bool = True
    allow_external_ai_egress: bool = False


class PlatformMetadata(_Contract):
    environment: Literal["development", "test", "staging", "production"] = "development"
    revision: int = Field(default=1, ge=1)


class PlatformSpec(_Contract):
    """Validated desired platform state, independent of a cloud vendor."""

    api_version: Literal["platform.example/v1"] = "platform.example/v1"
    kind: Literal["PlatformSpec"] = "PlatformSpec"
    metadata: PlatformMetadata = Field(default_factory=PlatformMetadata)
    profile: DeploymentProfile = "local"
    deployment: DeploymentSpec = Field(default_factory=DeploymentSpec)
    providers: ProviderSpec = Field(default_factory=ProviderSpec)
    resources: ResourceSpec = Field(default_factory=ResourceSpec)
    reliability: ReliabilitySpec = Field(default_factory=ReliabilitySpec)
    security: SecuritySpec = Field(default_factory=SecuritySpec)
    features: FeatureSpec = Field(default_factory=FeatureSpec)
