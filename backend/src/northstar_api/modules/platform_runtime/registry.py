"""Capability catalog and dependency analysis for the platform control center.

The registry is deliberately provider-neutral.  It describes the selected
runtime and its dependencies; it never creates, deletes, or mutates an
infrastructure resource.  A deployment controller can consume the resulting
catalog and a separately approved :class:`ChangePlan`.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .contracts import PlatformSpec
from .control_plane import ChangePlan, build_change_plan
from .validation import validate_platform_spec

CapabilityId = Literal[
    "database",
    "authentication",
    "tenant-isolation",
    "encryption",
    "audit",
    "cache",
    "jobs",
    "events",
    "storage",
    "search",
    "vector",
    "notifications",
    "secrets",
    "ai",
    "orchestration",
    "metrics",
    "tracing",
    "websocket",
]
CapabilityCategory = Literal["core", "data", "messaging", "ai", "runtime", "observability"]
CapabilityHealth = Literal["healthy", "degraded", "unhealthy", "disabled", "unknown"]
CapabilityDesiredState = Literal["on", "off"]


class CapabilityDefinition(BaseModel):
    """Static policy for one capability exposed by the control center."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    capability_id: CapabilityId
    category: CapabilityCategory
    description: str = Field(min_length=1, max_length=300)
    required: bool
    locked: bool
    providers: tuple[str, ...] = Field(min_length=1)
    fallback_provider: str | None = None
    depends_on: tuple[CapabilityId, ...] = Field(default_factory=tuple)


class CapabilityState(BaseModel):
    """Desired and observed state for one capability."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    definition: CapabilityDefinition
    provider: str
    desired_state: CapabilityDesiredState
    actual_state: str
    health: CapabilityHealth
    fallback_active: bool = False
    health_message: str | None = None
    observed_provider: str | None = None
    estimated_monthly_cost_usd: float | None = Field(default=None, ge=0)


class CapabilityDependencyGraph(BaseModel):
    """Stable graph representation suitable for UI and policy checks."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    nodes: tuple[CapabilityId, ...]
    edges: tuple[tuple[CapabilityId, CapabilityId], ...]


class CapabilityCatalog(BaseModel):
    """Read-only control-center snapshot of the selected platform profile."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    generated_at: datetime
    environment: str
    revision: int = Field(ge=1)
    profile: str
    capabilities: tuple[CapabilityState, ...]
    dependencies: CapabilityDependencyGraph


class CapabilityChangeAnalysis(BaseModel):
    """Impact analysis returned alongside a safe change plan."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    plan: ChangePlan
    changed_capabilities: tuple[CapabilityId, ...] = Field(default_factory=tuple)
    impacted_capabilities: tuple[CapabilityId, ...] = Field(default_factory=tuple)
    blockers: tuple[str, ...] = Field(default_factory=tuple)


_DEFINITIONS: tuple[CapabilityDefinition, ...] = (
    CapabilityDefinition(
        capability_id="database", category="core", description="Authoritative relational database", required=True,
        locked=True, providers=("postgres",),
    ),
    CapabilityDefinition(
        capability_id="authentication", category="core", description="Identity and session authentication", required=True,
        locked=True, providers=("local", "oidc"), depends_on=("database",),
    ),
    CapabilityDefinition(
        capability_id="tenant-isolation", category="core", description="Tenant and workspace data isolation", required=True,
        locked=True, providers=("application",), depends_on=("database", "authentication"),
    ),
    CapabilityDefinition(
        capability_id="encryption", category="core", description="Encryption and secret protection", required=True,
        locked=True, providers=("env", "aws-secrets-manager"), depends_on=("secrets",),
    ),
    CapabilityDefinition(
        capability_id="audit", category="core", description="Security and administrative audit trail", required=True,
        locked=True, providers=("postgres", "transactional-outbox"), depends_on=("database",),
    ),
    CapabilityDefinition(
        capability_id="cache", category="data", description="Low-latency cache and temporary reads", required=False,
        locked=False, providers=("none", "redis"), fallback_provider="postgres", depends_on=("database",),
    ),
    CapabilityDefinition(
        capability_id="jobs", category="messaging", description="Durable background work execution", required=True,
        locked=False, providers=("postgres", "rabbitmq", "sqs"), depends_on=("database",),
    ),
    CapabilityDefinition(
        capability_id="events", category="messaging", description="Durable domain event delivery", required=True,
        locked=False, providers=("postgres", "kafka"), fallback_provider="postgres", depends_on=("database",),
    ),
    CapabilityDefinition(
        capability_id="storage", category="data", description="Object and document storage", required=True,
        locked=False, providers=("minio", "s3"), depends_on=("database",),
    ),
    CapabilityDefinition(
        capability_id="search", category="data", description="Full-text and structured search", required=False,
        locked=False, providers=("postgres", "opensearch"), fallback_provider="postgres", depends_on=("database",),
    ),
    CapabilityDefinition(
        capability_id="vector", category="ai", description="Vector retrieval index", required=False,
        locked=False, providers=("disabled", "pgvector"), fallback_provider="disabled", depends_on=("database",),
    ),
    CapabilityDefinition(
        capability_id="notifications", category="messaging", description="Email and notification delivery", required=False,
        locked=False, providers=("none", "smtp", "ses"), depends_on=("database",),
    ),
    CapabilityDefinition(
        capability_id="secrets", category="core", description="Secret material provider", required=True,
        locked=True, providers=("env", "aws-secrets-manager"),
    ),
    CapabilityDefinition(
        capability_id="ai", category="ai", description="Model inference gateway", required=False,
        locked=False, providers=("none", "nvidia", "openai-compatible"), fallback_provider="none", depends_on=("secrets",),
    ),
    CapabilityDefinition(
        capability_id="orchestration", category="runtime", description="Container and workload orchestration", required=True,
        locked=False, providers=("docker", "ecs", "eks"), depends_on=("database",),
    ),
    CapabilityDefinition(
        capability_id="metrics", category="observability", description="Metrics and service health signals", required=True,
        locked=True, providers=("opentelemetry",),
    ),
    CapabilityDefinition(
        capability_id="tracing", category="observability", description="Distributed request tracing", required=False,
        locked=False, providers=("opentelemetry", "disabled"), fallback_provider="disabled",
    ),
    CapabilityDefinition(
        capability_id="websocket", category="runtime", description="Realtime client connections", required=False,
        locked=False, providers=("application",), depends_on=("authentication",),
    ),
)

_DEFINITIONS_BY_ID = {item.capability_id: item for item in _DEFINITIONS}


def capability_definitions() -> tuple[CapabilityDefinition, ...]:
    """Return the immutable catalog definitions in stable order."""
    return _DEFINITIONS


def _selected_providers(spec: PlatformSpec) -> dict[CapabilityId, str]:
    return {
        "database": "postgres",
        "authentication": spec.providers.identity,
        "tenant-isolation": "application",
        "encryption": spec.providers.secrets,
        "audit": "postgres" if spec.providers.events == "postgres" else "transactional-outbox",
        "cache": spec.providers.cache,
        "jobs": spec.providers.jobs,
        "events": spec.providers.events,
        "storage": spec.providers.storage,
        "search": spec.providers.search,
        "vector": spec.providers.vector,
        "notifications": spec.providers.notifications,
        "secrets": spec.providers.secrets,
        "ai": spec.providers.ai,
        "orchestration": spec.deployment.orchestrator,
        "metrics": "opentelemetry" if spec.observability.metrics else "disabled",
        "tracing": "opentelemetry" if spec.observability.tracing else "disabled",
        "websocket": "application",
    }


def _state_health(provider: str, health: Mapping[str, CapabilityHealth] | None, capability_id: CapabilityId) -> CapabilityHealth:
    if provider in {"none", "disabled"}:
        return "disabled"
    return (health or {}).get(capability_id, "unknown")


def build_capability_catalog(
    spec: PlatformSpec,
    *,
    health: Mapping[str, CapabilityHealth] | None = None,
) -> CapabilityCatalog:
    """Build a deterministic capability snapshot for a validated platform spec."""
    validate_platform_spec(spec)
    selected = _selected_providers(spec)
    states: list[CapabilityState] = []
    for definition in _DEFINITIONS:
        provider = selected[definition.capability_id]
        enabled = provider not in {"none", "disabled"}
        states.append(
            CapabilityState(
                definition=definition,
                provider=provider,
                desired_state="on" if enabled or definition.required else "off",
                actual_state="disabled" if not enabled else "unknown",
                health=_state_health(provider, health, definition.capability_id),
                fallback_active=False,
            )
        )
    edges = tuple(
        (definition.capability_id, dependency)
        for definition in _DEFINITIONS
        for dependency in definition.depends_on
    )
    graph = CapabilityDependencyGraph(
        nodes=tuple(definition.capability_id for definition in _DEFINITIONS),
        edges=edges,
    )
    return CapabilityCatalog(
        generated_at=datetime.now(UTC),
        environment=spec.metadata.environment,
        revision=spec.metadata.revision,
        profile=spec.profile,
        capabilities=tuple(states),
        dependencies=graph,
    )


def _changed_capabilities(current: PlatformSpec, desired: PlatformSpec) -> set[CapabilityId]:
    old = _selected_providers(current)
    new = _selected_providers(desired)
    changed = {capability_id for capability_id in old if old[capability_id] != new[capability_id]}
    if current.profile != desired.profile or current.deployment.orchestrator != desired.deployment.orchestrator:
        changed.add("orchestration")
    if current.resources.redis_provisioned != desired.resources.redis_provisioned:
        changed.add("cache")
    if current.resources.kafka_provisioned != desired.resources.kafka_provisioned:
        changed.add("events")
    if current.resources.opensearch_provisioned != desired.resources.opensearch_provisioned:
        changed.add("search")
    if current.observability.tracing != desired.observability.tracing:
        changed.add("tracing")
    return changed


def _impacted_capabilities(changed: set[CapabilityId]) -> set[CapabilityId]:
    impacted = set(changed)
    changed_again = True
    while changed_again:
        changed_again = False
        for definition in _DEFINITIONS:
            if set(definition.depends_on) & impacted and definition.capability_id not in impacted:
                impacted.add(definition.capability_id)
                changed_again = True
    return impacted


def analyze_capability_change(current: PlatformSpec, desired: PlatformSpec) -> CapabilityChangeAnalysis:
    """Return a safe plan plus dependency-aware impact information."""
    plan = build_change_plan(current, desired)
    changed = _changed_capabilities(current, desired)
    impacted = _impacted_capabilities(changed)
    return CapabilityChangeAnalysis(
        plan=plan,
        changed_capabilities=tuple(sorted(changed)),
        impacted_capabilities=tuple(sorted(impacted)),
        blockers=plan.blockers,
    )


__all__ = [
    "CapabilityCategory",
    "CapabilityChangeAnalysis",
    "CapabilityDefinition",
    "CapabilityDependencyGraph",
    "CapabilityDesiredState",
    "CapabilityHealth",
    "CapabilityId",
    "CapabilityCatalog",
    "CapabilityState",
    "analyze_capability_change",
    "build_capability_catalog",
    "capability_definitions",
]
