import pytest
from pydantic import ValidationError

from northstar_api.modules.platform_runtime import (
    PlatformSpec,
    PlatformSpecError,
    build_dependency_graph,
    classify_provider_change,
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
        deployment={"orchestrator": "ecs", "region": "ap-south-1"},
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
        PlatformSpec(providers={"storage": "s3"}, profile="aws-standard", deployment={"orchestrator": "ecs"}),
    ) == "migration"


def test_unknown_contract_keys_are_rejected() -> None:
    with pytest.raises(ValidationError):
        PlatformSpec.model_validate({"providers": {"unknown": "redis"}})

