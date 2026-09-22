"""Dependency and change validation for portable platform profiles."""

from __future__ import annotations

from dataclasses import dataclass

from .contracts import PlatformSpec, ProviderChangeClass


class PlatformSpecError(ValueError):
    """The desired platform state cannot satisfy a declared contract."""


@dataclass(frozen=True)
class DependencyGraph:
    nodes: tuple[str, ...]
    edges: tuple[tuple[str, str], ...]


def validate_platform_spec(spec: PlatformSpec) -> PlatformSpec:
    """Validate semantic dependencies after Pydantic schema validation."""
    providers = spec.providers
    features = spec.features

    if features.rag and (not features.documents or not features.ai):
        raise PlatformSpecError("features.rag requires features.documents and features.ai")
    if features.ai and providers.ai == "none":
        raise PlatformSpecError("features.ai requires an enabled providers.ai adapter")
    if providers.ai != "none" and not features.ai:
        raise PlatformSpecError("providers.ai cannot be enabled while features.ai is disabled")
    if providers.vector == "pgvector" and not features.rag:
        raise PlatformSpecError("providers.vector requires features.rag")
    if providers.cache == "redis" and not spec.resources.redis_provisioned:
        raise PlatformSpecError("providers.cache=redis requires resources.redis_provisioned")
    if providers.events == "kafka" and not spec.resources.kafka_provisioned:
        raise PlatformSpecError("providers.events=kafka requires resources.kafka_provisioned")
    if providers.jobs == "sqs" and spec.profile == "local":
        raise PlatformSpecError("providers.jobs=sqs is only supported by an AWS profile")
    if providers.storage == "s3" and spec.profile == "local":
        raise PlatformSpecError("providers.storage=s3 is not valid for the local profile; use minio")
    if spec.profile in {"aws-standard", "aws-scale"} and spec.deployment.orchestrator != "ecs":
        raise PlatformSpecError(f"{spec.profile} requires deployment.orchestrator=ecs")
    if spec.profile == "aws-kubernetes" and spec.deployment.orchestrator != "eks":
        raise PlatformSpecError("aws-kubernetes requires deployment.orchestrator=eks")
    if spec.security.allow_external_ai_egress and providers.ai == "none":
        raise PlatformSpecError("external AI egress cannot be enabled without an AI provider")
    if spec.profile in {"aws-standard", "aws-scale", "aws-kubernetes"}:
        if spec.deployment.region == "local":
            raise PlatformSpecError("AWS profiles require an explicit region")
        if not spec.deployment.account_id:
            raise PlatformSpecError("AWS profiles require a 12-digit account_id")
    if spec.profile == "portable-production" and spec.deployment.orchestrator != "docker":
        raise PlatformSpecError("portable-production requires deployment.orchestrator=docker")
    if spec.reliability.accepted_work_delivery != "at-least-once":
        raise PlatformSpecError("production work delivery must be at-least-once")
    if not spec.reliability.require_idempotency or not spec.reliability.require_reconciliation:
        raise PlatformSpecError("durable work requires idempotency and reconciliation")
    if not spec.security.authorization_required or not spec.security.tenant_isolation_required:
        raise PlatformSpecError("authorization and tenant isolation are mandatory platform invariants")
    if not spec.security.audit_required:
        raise PlatformSpecError("audit is a mandatory platform invariant")
    return spec


def build_dependency_graph(spec: PlatformSpec) -> DependencyGraph:
    """Return a deterministic capability/provider dependency graph."""
    validate_platform_spec(spec)
    nodes = {"postgres", "authorization", "tenant-isolation", "audit"}
    edges: set[tuple[str, str]] = {
        ("application", "postgres"),
        ("application", "authorization"),
        ("application", "tenant-isolation"),
        ("application", "audit"),
    }
    providers = spec.providers
    if providers.cache != "none":
        nodes.add(providers.cache)
        edges.add(("cache", providers.cache))
    if providers.jobs != "postgres":
        nodes.add(providers.jobs)
        edges.add(("jobs", providers.jobs))
    if providers.events != "postgres":
        nodes.add(providers.events)
        edges.add(("events", providers.events))
    nodes.add(providers.storage)
    edges.add(("storage", providers.storage))
    if providers.ai != "none":
        nodes.add(providers.ai)
        edges.add(("ai", providers.ai))
    if providers.vector != "disabled":
        nodes.add(providers.vector)
        edges.add(("vector", providers.vector))
    return DependencyGraph(tuple(sorted(nodes)), tuple(sorted(edges)))


def classify_provider_change(old: PlatformSpec, new: PlatformSpec) -> ProviderChangeClass:
    """Classify a desired provider change before a control-plane plan is created."""
    validate_platform_spec(old)
    validate_platform_spec(new)
    if old == new:
        return "hot-safe"
    if old.providers.storage != new.providers.storage or old.providers.jobs != new.providers.jobs:
        return "migration"
    if old.providers.events != new.providers.events or old.providers.vector != new.providers.vector:
        return "restart"
    if old.profile != new.profile or old.deployment.orchestrator != new.deployment.orchestrator:
        return "prohibited"
    return "hot-safe"
