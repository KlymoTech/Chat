from northstar_api.modules.platform_runtime import (
    DeploymentDispatchEvent,
    DeploymentExecutionReport,
    build_capacity_budget,
)
from northstar_api.modules.super_admin.api.runtime import (
    _declared_platform_spec,
    _deployment_dispatch_payload,
    router,
)


def test_runtime_control_plane_exposes_only_read_and_plan_operations() -> None:
    routes = {(route.path, tuple(sorted(route.methods or ()))) for route in router.routes}
    assert ("/platform-admin/runtime/capabilities", ("GET",)) in routes
    assert ("/platform-admin/runtime/dependencies", ("GET",)) in routes
    assert ("/platform-admin/runtime/capacity", ("GET",)) in routes
    assert ("/platform-admin/runtime/changes/plan", ("POST",)) in routes
    assert ("/platform-admin/runtime/changes", ("POST",)) in routes
    assert ("/platform-admin/runtime/changes", ("GET",)) in routes
    assert ("/platform-admin/runtime/changes/{change_id}", ("GET",)) in routes
    assert ("/platform-admin/runtime/changes/{change_id}/executions", ("GET",)) in routes
    assert ("/platform-admin/runtime/changes/{change_id}/executions", ("POST",)) in routes
    assert ("/platform-admin/runtime/changes/{change_id}/approve", ("POST",)) in routes
    assert ("/platform-admin/runtime/changes/{change_id}/reject", ("POST",)) in routes
    assert not any("destroy" in path or path.endswith("/apply") for path, _ in routes)


def test_declared_runtime_spec_is_valid_without_exposing_secrets() -> None:
    spec = _declared_platform_spec()
    assert spec.metadata.environment in {"development", "test", "staging", "production"}
    assert spec.providers.ai in {"none", "nvidia"}
    assert spec.deployment.account_id is None


def test_capacity_budget_is_explicitly_not_a_user_guarantee() -> None:
    budget = build_capacity_budget(api_replicas=3, database_pool_size=10, database_max_overflow=20)
    assert budget.database_connection_budget == 90
    assert budget.model_concurrency_budget == 48
    assert budget.active_user_guarantee is None
    assert budget.measured is False


def test_approved_dispatch_payload_carries_immutable_plan_inputs() -> None:
    from datetime import UTC, datetime
    from uuid import uuid4

    from northstar_api.modules.platform_runtime.persistence import PlatformChangeRecord

    change = PlatformChangeRecord(
        id=uuid4(),
        environment="staging",
        requested_by=uuid4(),
        status="approved",
        action="migrate",
        classification="migration",
        requires_approval=True,
        destructive=False,
        source_revision=4,
        target_revision=5,
        source_digest="a" * 64,
        target_digest="b" * 64,
        idempotency_key="change-2026-09-22-001",
        reason="Move the event provider after verification",
        plan_steps=["validate_dependencies", "switch_reads_and_writes"],
        blockers=[],
        impact_json={},
        requested_at=datetime.now(UTC),
        current_spec_json={"metadata": {"revision": 4}},
        desired_spec_json={"metadata": {"revision": 5}},
    )

    payload = _deployment_dispatch_payload(change)

    assert payload["changeId"] == str(change.id)
    assert payload["sourceDigest"] == "a" * 64
    assert payload["targetDigest"] == "b" * 64
    assert payload["desiredSpec"] == {"metadata": {"revision": 5}}
    assert payload["planSteps"] == ["validate_dependencies", "switch_reads_and_writes"]


def test_deployment_dispatch_contract_validates_the_outbox_shape() -> None:
    from uuid import uuid4

    from pydantic import ValidationError

    payload = {
        "changeId": str(uuid4()),
        "environment": "staging",
        "action": "migrate",
        "classification": "migration",
        "destructive": False,
        "sourceRevision": 4,
        "targetRevision": 5,
        "sourceDigest": "a" * 64,
        "targetDigest": "b" * 64,
        "idempotencyKey": "change-2026-09-22-001",
        "reason": "Move the event provider after verification",
        "planSteps": ["validate_dependencies"],
        "currentSpec": {"metadata": {"revision": 4}},
        "desiredSpec": {"metadata": {"revision": 5}},
    }
    event = DeploymentDispatchEvent.model_validate(payload)

    assert event.target_revision == 5
    payload["unexpected"] = True
    try:
        DeploymentDispatchEvent.model_validate(payload)
    except ValidationError:
        pass
    else:
        raise AssertionError("deployment dispatch contract accepted an unknown field")


def test_execution_report_requires_plan_digests_and_supports_staged_phases() -> None:
    report = DeploymentExecutionReport.model_validate(
        {
            "reportKey": "deploy-2026-09-22-001",
            "pipeline": "gitops/staging",
            "phase": "verifying",
            "sourceDigest": "a" * 64,
            "targetDigest": "b" * 64,
            "healthResult": {"api": "healthy", "workers": "healthy"},
        }
    )

    assert report.phase == "verifying"
    assert report.health_result["api"] == "healthy"
