"""Persisted change approval must bind to the exact approved plan."""
from northstar_api.modules.platform_runtime.approval_integrity import (
    persisted_change_integrity_blockers,
)
from northstar_api.modules.platform_runtime.contracts import PlatformSpec
from northstar_api.modules.platform_runtime.control_plane import build_change_plan


def proposal():
    current = PlatformSpec()
    desired = PlatformSpec(metadata={"revision": 2}, features={"analytics": False})
    plan = build_change_plan(current, desired)
    values = dict(
        current_json=current.model_dump(mode="json"),
        desired_json=desired.model_dump(mode="json"),
        environment=current.metadata.environment,
        source_revision=plan.source_revision,
        target_revision=plan.target_revision,
        source_digest=plan.source_digest,
        target_digest=plan.target_digest,
        action=plan.action,
        classification=plan.classification,
    )
    return values


def test_exact_persisted_plan_is_accepted():
    assert persisted_change_integrity_blockers(**proposal()) == ()


def test_tampered_target_digest_is_rejected():
    values = proposal()
    values["target_digest"] = "f" * 64
    assert "persisted_digest_mismatch" in persisted_change_integrity_blockers(**values)


def test_cross_environment_snapshot_is_rejected():
    values = proposal()
    values["environment"] = "other-environment"
    assert "persisted_environment_mismatch" in persisted_change_integrity_blockers(**values)


def test_stale_revision_and_action_are_rejected():
    values = proposal()
    values["target_revision"] = 999
    values["action"] = "apply" if values["action"] != "apply" else "migrate"
    blockers = persisted_change_integrity_blockers(**values)
    assert "persisted_revision_mismatch" in blockers
    assert "persisted_action_mismatch" in blockers


def test_invalid_snapshot_is_rejected_before_approval():
    values = proposal()
    values["desired_json"] = {"unexpected": "invalid"}
    assert persisted_change_integrity_blockers(**values)


def test_bad_stored_classification_is_rejected():
    values = proposal()
    values["classification"] = "migration"
    assert "persisted_classification_mismatch" in persisted_change_integrity_blockers(**values)
