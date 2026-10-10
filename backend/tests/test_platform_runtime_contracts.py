from uuid import uuid4

import pytest
from pydantic import ValidationError

from northstar_api.modules.platform_runtime import registry as capability_registry

from northstar_api.modules.platform_runtime import (
    ChangeLifecycleError,
    DependencyGraph,
    PlatformSpec,
    PlatformSpecError,
    analyze_capability_change,
    approver_is_distinct,
    build_capability_catalog,
    build_change_plan,
    build_dependency_graph,
    classify_provider_change,
    transition_change,
    validate_dependency_graph,
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
    ) == "restart"
    assert classify_provider_change(
        base,
        PlatformSpec(
            providers={"storage": "s3"},
            profile="aws-standard",
            deployment={"orchestrator": "ecs", "region": "ap-south-1", "account_id": "123456789012"},
        ),
    ) == "migration"


def test_unknown_contract_keys_are_rejected() -> None:
    with pytest.raises(ValidationError):
        PlatformSpec.model_validate({"providers": {"unknown": "redis"}})


def test_mutable_image_tags_are_rejected() -> None:
    with pytest.raises(ValidationError, match="image_digest"):
        PlatformSpec(deployment={"image_digest": "latest"})


def test_change_plan_requires_migration_steps_for_storage_cutover() -> None:
    current = PlatformSpec(metadata={"revision": 1})
    desired = PlatformSpec(
        metadata={"revision": 2},
        profile="aws-standard",
        deployment={"orchestrator": "ecs", "region": "ap-south-1", "account_id": "123456789012"},
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


def test_capability_catalog_exposes_locked_core_and_provider_state() -> None:
    catalog = build_capability_catalog(PlatformSpec())
    by_id = {item.definition.capability_id: item for item in catalog.capabilities}
    assert by_id["database"].definition.locked is True
    assert by_id["database"].desired_state == "on"
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


def test_change_lifecycle_requires_approval_separation_and_safe_transitions() -> None:
    assert transition_change("waiting_approval", "approved") == "approved"
    assert approver_is_distinct(uuid4(), uuid4()) is True
    with pytest.raises(ChangeLifecycleError, match="cannot transition"):
        transition_change("waiting_approval", "deploying")



def test_dependency_graph_declares_all_consumers_and_providers() -> None:
    graph = build_dependency_graph(
        PlatformSpec(
            providers={"cache": "redis", "events": "kafka", "storage": "minio"},
            resources={"redis_provisioned": True, "kafka_provisioned": True},
        )
    )
    assert graph == validate_dependency_graph(graph)
    assert {"application", "cache", "events", "storage"} <= set(graph.nodes)
    assert all(set(edge) <= set(graph.nodes) for edge in graph.edges)
    assert ("cache", "redis") in graph.edges
    assert ("events", "kafka") in graph.edges


@pytest.mark.parametrize(
    "graph",
    [
        DependencyGraph(("a", "b"), (("a", "missing"),)),
        DependencyGraph(("a", "b"), (("a", "b"), ("b", "a"))),
        DependencyGraph(("a",), (("a", "a"),)),
        DependencyGraph(("a", "a"), ()),
        DependencyGraph(("",), ()),
    ],
)
def test_dependency_graph_fitness_fails_closed(graph: DependencyGraph) -> None:
    with pytest.raises(PlatformSpecError, match="dependency graph"):
        validate_dependency_graph(graph)



def test_capability_catalog_rejects_cycle_before_exposing_state(monkeypatch) -> None:
    definitions = capability_registry.capability_definitions()
    cyclic = tuple(
        definition.model_copy(update={"depends_on": ("authentication",)})
        if definition.capability_id == "database"
        else definition
        for definition in definitions
    )
    monkeypatch.setattr(capability_registry, "_DEFINITIONS", cyclic)
    with pytest.raises(PlatformSpecError, match="cycle"):
        capability_registry.build_capability_catalog(PlatformSpec())


def test_capability_catalog_declares_every_dependency_node() -> None:
    catalog = build_capability_catalog(PlatformSpec())
    assert catalog.dependencies.nodes
    assert all(
        source in catalog.dependencies.nodes and target in catalog.dependencies.nodes
        for source, target in catalog.dependencies.edges
    )
