"""Fail-closed qualification tests; no cloud credentials or AWS access needed."""
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from northstar_api.modules.platform_runtime.governed_switches import SwitchClass, TransitionGate
from northstar_api.modules.platform_runtime.qualification_gates import (
    ChangeGuards, QualificationEvidence, evaluate_change_qualification,
)


NOW = datetime(2026, 10, 8, tzinfo=timezone.utc)


def gate(kind=SwitchClass.C):
    return TransitionGate(kind, ("jobs",), ("backup_restore_proof", "dual_run_reconciliation"),
                          True, False, "stateful_migration")


def guards(**changes):
    base = ChangeGuards("production", "sha256:abc", NOW, "requester", "approver",
                        backups_healthy=True, within_maintenance_window=True,
                        approved_monthly_budget_delta_usd="100")
    return replace(base, **changes)


def evidence(kind, **changes):
    base = QualificationEvidence(kind + "-run", kind, "production", "sha256:abc",
                                 NOW - timedelta(minutes=30),
                                 NOW + timedelta(minutes=30), verified=True)
    return replace(base, **changes)


def test_valid_evidence_and_independent_approval_pass():
    result = evaluate_change_qualification(gate(),
        [evidence("backup_restore_proof"), evidence("dual_run_reconciliation")], guards())
    assert result.allowed
    assert not result.blockers


@pytest.mark.parametrize("override", [
    {"verified": False},
    {"target_digest": "different"},
    {"environment": "staging"},
    {"expires_at": NOW},
    {"recorded_at": NOW + timedelta(minutes=1)},
])
def test_untrusted_or_stale_evidence_does_not_pass(override):
    changed = evidence("backup_restore_proof", **override)
    result = evaluate_change_qualification(gate(),
        [changed, evidence("dual_run_reconciliation")], guards())
    assert not result.allowed
    assert "missing_valid_evidence:backup_restore_proof" in result.blockers


@pytest.mark.parametrize("override,blocker", [
    ({"approver_id": "requester"}, "independent_approval_required"),
    ({"approver_id": None}, "independent_approval_required"),
    ({"active_incident": True}, "active_incident"),
    ({"backups_healthy": False}, "healthy_backup_required"),
    ({"within_maintenance_window": False}, "maintenance_window_required"),
    ({"estimated_monthly_delta_usd": "101"}, "budget_exceeded"),
    ({"estimated_monthly_delta_usd": "NaN"}, "invalid_budget"),
])
def test_mutation_safety_guards_fail_closed(override, blocker):
    result = evaluate_change_qualification(gate(),
        [evidence("backup_restore_proof"), evidence("dual_run_reconciliation")],
        guards(**override))
    assert not result.allowed
    assert blocker in result.blockers


def test_locked_change_cannot_be_authorized_by_valid_evidence():
    result = evaluate_change_qualification(gate(SwitchClass.L),
        [evidence("backup_restore_proof"), evidence("dual_run_reconciliation")], guards())
    assert "locked_change_prohibited" in result.blockers


def test_experimental_change_requires_manual_qualification():
    result = evaluate_change_qualification(gate(SwitchClass.E),
        [evidence("backup_restore_proof"), evidence("dual_run_reconciliation")], guards())
    assert "manual_qualification_required" in result.blockers


def test_naive_timestamp_rejected():
    with pytest.raises(ValueError, match="timezone-aware"):
        guards(now=datetime(2026, 10, 8))


def test_evidence_must_have_valid_time_window():
    with pytest.raises(ValueError, match="expiry"):
        evidence("backup_restore_proof", expires_at=NOW - timedelta(hours=1))
