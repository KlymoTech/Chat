"""Safety contract tests for advisory governed provider switching."""

from northstar_api.modules.platform_runtime.contracts import (
    DeploymentSpec,
    FeatureSpec,
    PlatformMetadata,
    PlatformSpec,
    ProviderSpec,
    SecuritySpec,
)
from northstar_api.modules.platform_runtime.governed_switches import (
    SwitchClass,
    classify_transition,
    verify_evidence,
)


def advanced(spec: PlatformSpec, **changes: object) -> PlatformSpec:
    return spec.model_copy(
        update={"metadata": PlatformMetadata(revision=spec.metadata.revision + 1), **changes}
    )


def test_noop_is_not_executable() -> None:
    result = classify_transition(PlatformSpec(), PlatformSpec())
    assert result.changes == ()
    assert not result.eligible_for_automatic_execution


def test_runtime_feature_is_class_a() -> None:
    current = PlatformSpec()
    desired = advanced(current, features=current.features.model_copy(update={"analytics": False}))
    result = classify_transition(current, desired)
    assert result.change_class is SwitchClass.A
    assert verify_evidence(result, ()) == ("missing:health_snapshot", "missing:rollback_configuration")


def test_job_migration_is_class_c_and_evidence_gated() -> None:
    current = PlatformSpec()
    desired = advanced(current, providers=ProviderSpec(jobs="rabbitmq"))
    result = classify_transition(current, desired)
    assert result.change_class is SwitchClass.C
    assert not result.eligible_for_automatic_execution
    assert "independent_approval_required" in verify_evidence(result, ())
    assert verify_evidence(result, result.required_evidence, approved=True) == ()


def test_topology_migration_is_class_d() -> None:
    current = PlatformSpec()
    desired = advanced(current, deployment=DeploymentSpec(region="another-local-region"))
    assert classify_transition(current, desired).change_class is SwitchClass.D


def test_secrets_switch_is_class_b() -> None:
    current = PlatformSpec()
    desired = advanced(current, providers=ProviderSpec(secrets="aws-secrets-manager"))
    assert classify_transition(current, desired).change_class is SwitchClass.B


def test_cross_environment_change_is_locked_even_when_only_metadata_changes() -> None:
    current = PlatformSpec()
    desired = advanced(current, metadata=PlatformMetadata(environment="staging", revision=2))
    gate = classify_transition(current, desired)
    assert gate.change_class is SwitchClass.L
    assert gate.reason == "cross_environment_change_prohibited"
    assert not gate.eligible_for_automatic_execution
    assert "locked_change_prohibited" in verify_evidence(gate, (), approved=True)


def test_ai_provider_and_external_egress_changes_require_deployment_review() -> None:
    current = PlatformSpec(features=FeatureSpec(ai=True), providers=ProviderSpec(ai="nvidia"))
    provider_change = advanced(current, providers=ProviderSpec(ai="openai-compatible"))
    egress_change = advanced(
        current,
        security=SecuritySpec(allow_external_ai_egress=True),
    )

    for desired in (provider_change, egress_change):
        gate = classify_transition(current, desired)
        assert gate.change_class is SwitchClass.B
        assert gate.requires_approval
        assert not gate.eligible_for_automatic_execution
