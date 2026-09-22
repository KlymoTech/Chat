from uuid import uuid4

import pytest
from pydantic import ValidationError

from northstar_api.modules.platform_runtime import (
    ChangeLifecycleError,
    PlatformSpec,
    PlatformSpecError,
    analyze_capability_change,
    apply_operation_policy,
    approver_is_distinct,
    build_capability_catalog,
    build_change_plan,
    build_dependency_graph,
    capability_control_policy,
    classify_provider_change,
    detect_drift,
    mutate_capability_spec,
    mutate_feature_spec,
    summarize_cost,
    summarize_health,
    transition_change,
    validate_platform_spec,
)


def test_local_profile_has_no_cloud_provider_requirement() -> None:
    spec = validate_platform_spec(PlatformSpec())
    graph = build_dependency_graph(spec)
    assert "postgres" in graph.nodes
    assert "s3" not in graph.nodes


def test_rag_requires_documents_and_generation() -> None:
    with pytest.raises(PlatformSpecError, match="features.documents"):
        validate_platform_spec(PlatformSpec(features={"rag": True}))


def test_optional_provider_requires_declared_resource() -> None:
    with pytest.raises(PlatformSpecError, match="redis_provisioned"):
        validate_platform_spec(PlatformSpec(providers={"cache": "redis"}))
    with pytest.raises(PlatformSpecError, match="opensearch_provisioned"):
        validate_platform_spec(PlatformSpec(providers={"search": "opensearch"}))


def test_profile_provider_contracts_are_explicit() -> None:
    with pytest.raises(PlatformSpecError, match="aws-standard"):
        validate_platform_spec(PlatformSpec(profile="aws-standard"))
    spec = PlatformSpec(
        profile="aws-standard",
        deployment={"orchestrator": "ecs", "region": "ap-south-1", "account_id": "123456789012"},
        providers={"storage": "s3"},
    )
    assert validate_platform_spec(spec).profile == "aws-standard"


def test_provider_change_classification() -> None:
    base = PlatformSpec()
    assert classify_provider_change(base, base) == "hot-safe"
    assert classify_provider_change(
        base,
        PlatformSpec(providers={"events": "kafka"}, resources={"kafka_provisioned": True}),
    ) == "migration"

    portable = PlatformSpec(profile="portable-production")
    assert classify_provider_change(
        portable,
        PlatformSpec(profile="portable-production", providers={"storage": "s3"}),
    ) == "migration"


def test_unknown_contract_keys_are_rejected() -> None:
    with pytest.raises(ValidationError):
        PlatformSpec.model_validate({"providers": {"unknown": "redis"}})


def test_mutable_image_tags_are_rejected() -> None:
    with pytest.raises(ValidationError, match="image_digest"):
        PlatformSpec(deployment={"image_digest": "latest"})


def test_change_plan_requires_migration_steps_for_storage_cutover() -> None:
    current = PlatformSpec(metadata={"revision": 1}, profile="portable-production")
    desired = PlatformSpec(
        metadata={"revision": 2},
        profile="portable-production",
        providers={"storage": "s3"},
    )
    plan = build_change_plan(current, desired)
    assert plan.action == "migrate"
    assert plan.requires_approval is True
    assert "copy_and_verify_authoritative_state" in plan.steps
    assert plan.destructive is False


def test_prohibited_profile_change_never_becomes_an_apply_plan() -> None:
    current = PlatformSpec()
    desired = PlatformSpec(
        metadata={"revision": 2},
        profile="aws-kubernetes",
        deployment={"orchestrator": "eks", "region": "ap-south-1", "account_id": "123456789012"},
    )
    plan = build_change_plan(current, desired)
    assert plan.action == "reject"
    assert plan.blockers == ("deployment_profile_change_requires_a_separate_cutover",)


def test_production_hot_safe_change_still_requires_approval() -> None:
    current = PlatformSpec(metadata={"environment": "production", "revision": 1}, profile="portable-production")
    desired = PlatformSpec(
        metadata={"environment": "production", "revision": 2},
        profile="portable-production",
        features={"analytics": False},
    )
    plan = build_change_plan(current, desired)
    assert plan.action == "apply"
    assert plan.classification == "hot-safe"
    assert plan.requires_approval is True


def test_change_plan_digest_is_stable() -> None:
    first = build_change_plan(PlatformSpec(), PlatformSpec(metadata={"revision": 2}))
    second = build_change_plan(PlatformSpec(), PlatformSpec(metadata={"revision": 2}))
    assert first.target_digest == second.target_digest


def test_change_plan_rejects_stale_revision() -> None:
    plan = build_change_plan(
        PlatformSpec(metadata={"revision": 2}),
        PlatformSpec(metadata={"revision": 1}, features={"analytics": False}),
    )
    assert plan.action == "reject"
    assert plan.blockers == ("target_revision_must_advance",)


def test_capability_catalog_exposes_locked_core_and_provider_state_without_inventing_health() -> None:
    catalog = build_capability_catalog(PlatformSpec())
    by_id = {item.definition.capability_id: item for item in catalog.capabilities}
    assert by_id["database"].definition.locked is True
    assert by_id["database"].desired_state == "on"
    assert by_id["database"].actual_state == "unknown"
    assert by_id["database"].health == "unknown"
    assert by_id["cache"].provider == "none"
    assert by_id["cache"].health == "disabled"
    assert ("jobs", "database") in catalog.dependencies.edges


def test_capability_change_analysis_includes_dependents() -> None:
    current = PlatformSpec(metadata={"revision": 1})
    desired = PlatformSpec(
        metadata={"revision": 2},
        features={"rag": True, "documents": True, "ai": True},
        providers={"ai": "nvidia", "vector": "pgvector"},
    )
    analysis = analyze_capability_change(current, desired)
    assert analysis.plan.action == "restart"
    assert "ai" in analysis.changed_capabilities
    assert "vector" in analysis.changed_capabilities
    assert "ai" in analysis.impacted_capabilities


def test_disable_is_separate_from_stop_and_destroy() -> None:
    current = PlatformSpec(
        metadata={"revision": 4},
        providers={"cache": "redis"},
        resources={"redis_provisioned": True},
    )
    disabled = mutate_capability_spec(current, "cache", operation="disable")
    assert disabled.providers.cache == "none"
    assert disabled.resources.redis_provisioned is True
    assert disabled.metadata.revision == 5

    stopped = mutate_capability_spec(disabled, "cache", operation="stop")
    assert stopped.providers.cache == "none"
    assert stopped.resources.redis_provisioned is True
    assert stopped.metadata.revision == 6

    destroyed = mutate_capability_spec(stopped, "cache", operation="destroy")
    assert destroyed.providers.cache == "none"
    assert destroyed.resources.redis_provisioned is False
    assert destroyed.metadata.revision == 7


def test_stop_and_destroy_plans_are_elevated_even_when_provider_config_is_already_detached() -> None:
    current = PlatformSpec(metadata={"revision": 5}, resources={"redis_provisioned": True})
    stopped = mutate_capability_spec(current, "cache", operation="stop")
    stop_analysis = apply_operation_policy(analyze_capability_change(current, stopped), "stop")
    assert stop_analysis.plan.action == "migrate"
    assert stop_analysis.plan.classification == "migration"
    assert stop_analysis.plan.requires_approval is True
    assert stop_analysis.plan.destructive is False
    assert "stop_infrastructure" in stop_analysis.plan.steps

    destroyed = mutate_capability_spec(stopped, "cache", operation="destroy")
    destroy_analysis = apply_operation_policy(analyze_capability_change(stopped, destroyed), "destroy")
    assert destroy_analysis.plan.action == "migrate"
    assert destroy_analysis.plan.destructive is True
    assert "generate_gitops_or_terraform_plan" in destroy_analysis.plan.steps
    assert "destroy_infrastructure" in destroy_analysis.plan.steps


def test_stateful_resource_cannot_be_stopped_while_still_in_request_path() -> None:
    current = PlatformSpec(
        providers={"cache": "redis", "events": "kafka"},
        resources={"redis_provisioned": True, "kafka_provisioned": True},
    )
    with pytest.raises(ValueError, match="disable cache dependency"):
        mutate_capability_spec(current, "cache", operation="stop")
    with pytest.raises(ValueError, match="transactional outbox"):
        mutate_capability_spec(current, "events", operation="destroy")


def test_locked_capability_policy_has_no_mutation_operations() -> None:
    policy = capability_control_policy("database")
    assert policy.risk_class == "locked"
    assert policy.mutable is False
    assert policy.allowed_operations == ()


def test_disabling_ai_cascades_to_rag_and_vector_without_deleting_other_state() -> None:
    current = PlatformSpec(
        metadata={"revision": 9},
        features={"documents": True, "ai": True, "rag": True, "analytics": True},
        providers={"ai": "nvidia", "vector": "pgvector"},
    )
    desired = mutate_capability_spec(current, "ai", operation="disable")
    assert desired.features.ai is False
    assert desired.features.rag is False
    assert desired.features.analytics is True
    assert desired.providers.ai == "none"
    assert desired.providers.vector == "disabled"
    assert desired.metadata.revision == 10


def test_feature_toggle_preserves_dependency_invariants() -> None:
    current = PlatformSpec(
        metadata={"revision": 2},
        features={"documents": True, "ai": True, "rag": True},
        providers={"ai": "nvidia", "vector": "pgvector"},
    )
    desired = mutate_feature_spec(current, "documents", False)
    assert desired.features.documents is False
    assert desired.features.rag is False
    assert desired.metadata.revision == 3


def test_drift_and_health_do_not_treat_missing_observation_as_success() -> None:
    catalog = build_capability_catalog(PlatformSpec())
    drift = detect_drift(catalog)
    health = summarize_health(catalog)
    assert drift.drift_count == 0
    assert drift.unobserved_count > 0
    assert health.overall == "unknown"
    assert health.unknown > 0


def test_cost_summary_only_totals_reported_evidence() -> None:
    catalog = build_capability_catalog(PlatformSpec())
    states = list(catalog.capabilities)
    database_index = next(index for index, item in enumerate(states) if item.definition.capability_id == "database")
    states[database_index] = states[database_index].model_copy(update={"estimated_monthly_cost_usd": 125.50})
    cost = summarize_cost(catalog.model_copy(update={"capabilities": tuple(states)}))
    assert cost.reported_monthly_usd == 125.50
    assert cost.reported_capabilities == ("database",)
    assert "cache" in cost.unreported_capabilities


def test_change_lifecycle_requires_approval_separation_and_safe_transitions() -> None:
    assert transition_change("waiting_approval", "approved") == "approved"
    assert approver_is_distinct(uuid4(), uuid4()) is True
    with pytest.raises(ChangeLifecycleError, match="cannot transition"):
        transition_change("waiting_approval", "deploying")
