"""Control-center policy, provider catalog, and safe desired-state mutations.

The browser never calls infrastructure APIs directly.  This module converts an
operator intent into a new immutable :class:`PlatformSpec`, while preserving
the distinction between disabling an application dependency and stopping or
destroying the underlying infrastructure.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .contracts import PlatformSpec
from .registry import CapabilityId, capability_definitions

RiskClass = Literal["green", "blue", "amber", "red", "locked"]
SwitchClass = Literal["runtime", "application-provider", "infrastructure", "migration", "locked"]
CapabilityOperation = Literal["enable", "disable", "switch", "stop", "destroy"]


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ProviderDescriptor(_FrozenModel):
    capability_id: CapabilityId
    provider: str
    label: str
    implemented: bool = True
    external_resource: bool = False
    fallback: bool = False


class CapabilityControlPolicy(_FrozenModel):
    capability_id: CapabilityId
    risk_class: RiskClass
    switch_class: SwitchClass
    mutable: bool
    allowed_operations: tuple[CapabilityOperation, ...] = Field(default_factory=tuple)
    production_approval_required: bool = True
    destructive_requires_gitops: bool = True


class EnvironmentControlPolicy(_FrozenModel):
    environment: str
    distinct_approver_required: bool
    destructive_requires_gitops: bool
    allow_direct_runtime_flags: bool
    stabilization_seconds: int = Field(ge=0)


class FeatureDefinition(_FrozenModel):
    feature_id: str
    label: str
    risk_class: RiskClass = "green"
    depends_on: tuple[str, ...] = Field(default_factory=tuple)


_PROVIDER_LABELS: dict[str, str] = {
    "none": "Disabled",
    "redis": "Redis",
    "postgres": "PostgreSQL",
    "rabbitmq": "RabbitMQ",
    "sqs": "Amazon SQS",
    "kafka": "Kafka / MSK",
    "minio": "MinIO",
    "s3": "Amazon S3",
    "opensearch": "OpenSearch",
    "disabled": "Disabled",
    "pgvector": "pgvector",
    "smtp": "SMTP",
    "ses": "Amazon SES",
    "local": "Local identity",
    "oidc": "OIDC",
    "env": "Environment",
    "aws-secrets-manager": "AWS Secrets Manager",
    "nvidia": "NVIDIA",
    "openai-compatible": "OpenAI-compatible",
    "docker": "Docker",
    "ecs": "Amazon ECS",
    "eks": "Amazon EKS",
    "opentelemetry": "OpenTelemetry",
    "application": "Application",
    "transactional-outbox": "Transactional outbox",
}

_EXTERNAL_RESOURCE_PROVIDERS = {"redis", "rabbitmq", "sqs", "kafka", "s3", "opensearch", "ses", "ecs", "eks"}

_POLICY_OVERRIDES: dict[CapabilityId, tuple[RiskClass, SwitchClass, tuple[CapabilityOperation, ...]]] = {
    "cache": ("blue", "application-provider", ("enable", "disable", "switch", "stop", "destroy")),
    "jobs": ("amber", "application-provider", ("switch",)),
    "events": ("amber", "application-provider", ("disable", "switch", "stop", "destroy")),
    "storage": ("amber", "migration", ("switch",)),
    "search": ("amber", "application-provider", ("disable", "switch", "stop", "destroy")),
    "vector": ("blue", "application-provider", ("enable", "disable", "switch")),
    "notifications": ("green", "runtime", ("enable", "disable", "switch")),
    "ai": ("blue", "application-provider", ("enable", "disable", "switch")),
    "orchestration": ("red", "migration", ("switch",)),
    "tracing": ("green", "runtime", ("enable", "disable")),
}

_FEATURES: tuple[FeatureDefinition, ...] = (
    FeatureDefinition(feature_id="documents", label="Documents"),
    FeatureDefinition(feature_id="ai", label="AI chat", risk_class="blue"),
    FeatureDefinition(feature_id="rag", label="RAG", risk_class="blue", depends_on=("documents", "ai")),
    FeatureDefinition(feature_id="analytics", label="Analytics"),
    FeatureDefinition(feature_id="whatsapp", label="WhatsApp"),
    FeatureDefinition(feature_id="workflow", label="Workflow builder"),
    FeatureDefinition(feature_id="email", label="Email"),
    FeatureDefinition(feature_id="sms", label="SMS"),
    FeatureDefinition(feature_id="voice", label="Voice"),
    FeatureDefinition(feature_id="export", label="Export"),
)


def provider_catalog() -> tuple[ProviderDescriptor, ...]:
    """Return providers exposed by the control center.

    The list is derived from the runtime capability registry, so the UI cannot
    invent a provider that the backend contract does not understand.
    """
    values: list[ProviderDescriptor] = []
    for definition in capability_definitions():
        for provider in definition.providers:
            values.append(
                ProviderDescriptor(
                    capability_id=definition.capability_id,
                    provider=provider,
                    label=_PROVIDER_LABELS.get(provider, provider.replace("-", " ").title()),
                    external_resource=provider in _EXTERNAL_RESOURCE_PROVIDERS,
                    fallback=provider == definition.fallback_provider,
                )
            )
    return tuple(values)


def capability_control_policies() -> tuple[CapabilityControlPolicy, ...]:
    """Return immutable switch semantics for every capability."""
    values: list[CapabilityControlPolicy] = []
    for definition in capability_definitions():
        if definition.locked:
            values.append(
                CapabilityControlPolicy(
                    capability_id=definition.capability_id,
                    risk_class="locked",
                    switch_class="locked",
                    mutable=False,
                )
            )
            continue
        override = _POLICY_OVERRIDES.get(definition.capability_id)
        if override is None:
            values.append(
                CapabilityControlPolicy(
                    capability_id=definition.capability_id,
                    risk_class="blue",
                    switch_class="application-provider",
                    mutable=False,
                )
            )
            continue
        risk_class, switch_class, operations = override
        values.append(
            CapabilityControlPolicy(
                capability_id=definition.capability_id,
                risk_class=risk_class,
                switch_class=switch_class,
                mutable=True,
                allowed_operations=operations,
            )
        )
    return tuple(values)


def capability_control_policy(capability_id: CapabilityId) -> CapabilityControlPolicy:
    for policy in capability_control_policies():
        if policy.capability_id == capability_id:
            return policy
    raise ValueError(f"unknown capability: {capability_id}")


def environment_control_policy(environment: str) -> EnvironmentControlPolicy:
    if environment == "production":
        return EnvironmentControlPolicy(
            environment=environment,
            distinct_approver_required=True,
            destructive_requires_gitops=True,
            allow_direct_runtime_flags=False,
            stabilization_seconds=300,
        )
    if environment == "staging":
        return EnvironmentControlPolicy(
            environment=environment,
            distinct_approver_required=False,
            destructive_requires_gitops=True,
            allow_direct_runtime_flags=True,
            stabilization_seconds=60,
        )
    return EnvironmentControlPolicy(
        environment=environment,
        distinct_approver_required=False,
        destructive_requires_gitops=False,
        allow_direct_runtime_flags=True,
        stabilization_seconds=15,
    )


def feature_definitions() -> tuple[FeatureDefinition, ...]:
    return _FEATURES


def _advance_revision(spec: PlatformSpec) -> dict[str, object]:
    return {
        "metadata": spec.metadata.model_copy(update={"revision": spec.metadata.revision + 1}),
    }


def mutate_feature_spec(spec: PlatformSpec, feature_id: str, enabled: bool) -> PlatformSpec:
    """Return a new desired specification for one application feature."""
    if feature_id not in {item.feature_id for item in _FEATURES}:
        raise ValueError(f"unknown feature: {feature_id}")
    feature_values = spec.features.model_dump()
    feature_values[feature_id] = enabled

    # Turning off a prerequisite must never leave an impossible RAG state.
    provider_updates: dict[str, object] = {}
    if not enabled and feature_id in {"documents", "ai"}:
        feature_values["rag"] = False
    if not enabled and feature_id == "ai":
        provider_updates["ai"] = "none"
        provider_updates["vector"] = "disabled"

    updates = _advance_revision(spec)
    updates["features"] = spec.features.model_copy(update=feature_values)
    if provider_updates:
        updates["providers"] = spec.providers.model_copy(update=provider_updates)
    return spec.model_copy(update=updates)


def mutate_capability_spec(
    spec: PlatformSpec,
    capability_id: CapabilityId,
    *,
    operation: CapabilityOperation,
    provider: str | None = None,
) -> PlatformSpec:
    """Translate an operator intent into a new desired state.

    Disable keeps provisioned infrastructure intact. Stop only changes the
    desired revision and is meaningful after the application has moved to a
    fallback. Destroy removes the resource declaration where the portable
    contract owns one; the external GitOps executor remains responsible for the
    actual infrastructure action.
    """
    definition = next((item for item in capability_definitions() if item.capability_id == capability_id), None)
    if definition is None:
        raise ValueError(f"unknown capability: {capability_id}")
    policy = capability_control_policy(capability_id)
    if not policy.mutable or operation not in policy.allowed_operations:
        raise ValueError(f"{capability_id} does not allow operation {operation}")

    if provider is not None and provider not in definition.providers:
        raise ValueError(f"provider {provider} is not supported by {capability_id}")

    provider_updates: dict[str, object] = {}
    resource_updates: dict[str, object] = {}
    feature_updates: dict[str, object] = {}
    observability_updates: dict[str, object] = {}
    deployment_updates: dict[str, object] = {}

    selected_provider = provider
    if operation == "enable" and selected_provider is None:
        selected_provider = next(
            (item for item in definition.providers if item not in {"none", "disabled"}),
            None,
        )
    if operation == "switch" and selected_provider is None:
        raise ValueError("switch requires an explicit provider")

    if capability_id == "cache":
        if operation == "disable":
            provider_updates["cache"] = "none"
        elif operation in {"enable", "switch"}:
            provider_updates["cache"] = selected_provider
            if selected_provider == "redis":
                resource_updates["redis_provisioned"] = True
        elif operation == "stop":
            if spec.providers.cache == "redis":
                raise ValueError("disable cache dependency before stopping Redis")
        elif operation == "destroy":
            if spec.providers.cache == "redis":
                raise ValueError("disable cache dependency before destroying Redis")
            resource_updates["redis_provisioned"] = False
    elif capability_id == "events":
        if operation == "disable":
            provider_updates["events"] = "postgres"
        elif operation == "switch":
            provider_updates["events"] = selected_provider
            if selected_provider == "kafka":
                resource_updates["kafka_provisioned"] = True
        elif operation == "stop":
            if spec.providers.events == "kafka":
                raise ValueError("switch events to the transactional outbox before stopping Kafka")
        elif operation == "destroy":
            if spec.providers.events == "kafka":
                raise ValueError("switch events to the transactional outbox before destroying Kafka")
            resource_updates["kafka_provisioned"] = False
    elif capability_id == "jobs":
        provider_updates["jobs"] = selected_provider
    elif capability_id == "storage":
        provider_updates["storage"] = selected_provider
    elif capability_id == "search":
        if operation == "disable":
            provider_updates["search"] = "postgres"
        elif operation == "switch":
            provider_updates["search"] = selected_provider
            if selected_provider == "opensearch":
                resource_updates["opensearch_provisioned"] = True
        elif operation == "stop":
            if spec.providers.search == "opensearch":
                raise ValueError("switch search to PostgreSQL before stopping OpenSearch")
        elif operation == "destroy":
            if spec.providers.search == "opensearch":
                raise ValueError("switch search to PostgreSQL before destroying OpenSearch")
            resource_updates["opensearch_provisioned"] = False
    elif capability_id == "vector":
        provider_updates["vector"] = "disabled" if operation == "disable" else selected_provider
    elif capability_id == "notifications":
        provider_updates["notifications"] = "none" if operation == "disable" else selected_provider
    elif capability_id == "ai":
        if operation == "disable":
            provider_updates["ai"] = "none"
            provider_updates["vector"] = "disabled"
            feature_updates["ai"] = False
            feature_updates["rag"] = False
        else:
            provider_updates["ai"] = selected_provider
            feature_updates["ai"] = True
    elif capability_id == "orchestration":
        deployment_updates["orchestrator"] = selected_provider
    elif capability_id == "tracing":
        observability_updates["tracing"] = operation != "disable"
    else:
        raise ValueError(f"{capability_id} does not have a portable mutation adapter")

    updates = _advance_revision(spec)
    if provider_updates:
        updates["providers"] = spec.providers.model_copy(update=provider_updates)
    if resource_updates:
        updates["resources"] = spec.resources.model_copy(update=resource_updates)
    if feature_updates:
        updates["features"] = spec.features.model_copy(update=feature_updates)
    if observability_updates:
        updates["observability"] = spec.observability.model_copy(update=observability_updates)
    if deployment_updates:
        updates["deployment"] = spec.deployment.model_copy(update=deployment_updates)
    return spec.model_copy(update=updates)


__all__ = [
    "CapabilityControlPolicy",
    "CapabilityOperation",
    "EnvironmentControlPolicy",
    "FeatureDefinition",
    "ProviderDescriptor",
    "RiskClass",
    "SwitchClass",
    "capability_control_policies",
    "capability_control_policy",
    "environment_control_policy",
    "feature_definitions",
    "mutate_capability_spec",
    "mutate_feature_spec",
    "provider_catalog",
]
