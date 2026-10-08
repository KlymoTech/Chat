"""Pre-dispatch fail-closed bridge between legacy plans and governed switches.

Verifies signed qualification pipeline evidence using the existing verifier.
This pure preflight does not grant permissions to the executor and does not
replace authorization, transactional state checks or execution audit logging.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from .contracts import PlatformSpec
from .control_plane import build_change_plan
from .governed_switches import SwitchClass, classify_transition
from .qualification import verify_qualification_proofs


@dataclass(frozen=True)
class DispatchPreflight:
    allowed: bool
    classification: SwitchClass
    blockers: tuple[str, ...]
    target_digest: str


def preflight_governed_dispatch(
    current: PlatformSpec,
    desired: PlatformSpec,
    *,
    tokens: tuple[str, ...],
    signing_key: bytes,
    now: datetime,
    requester_id: str,
    approver_id: str | None,
    active_incident: bool,
    backup_healthy: bool,
    within_maintenance_window: bool,
    budget_approved: bool,
) -> DispatchPreflight:
    """Reject unqualified execution, including legacy planner underclassification."""
    plan = build_change_plan(current, desired)
    gate = classify_transition(current, desired)
    blockers = list(plan.blockers)
    if plan.action == "reject":
        blockers.append("legacy_plan_rejected")
    if plan.action == "noop":
        blockers.append("no_mutation_requested")
    if gate.change_class is SwitchClass.L:
        blockers.append("locked_change_prohibited")
    if gate.change_class is SwitchClass.E:
        blockers.append("manual_qualification_required")
    if active_incident:
        blockers.append("active_incident")
    if not budget_approved:
        blockers.append("budget_approval_missing")
    if gate.requires_approval and (
        not requester_id or not approver_id or requester_id == approver_id
    ):
        blockers.append("independent_approval_required")
    if gate.requires_approval and not within_maintenance_window:
        blockers.append("maintenance_window_required")
    if gate.change_class in {SwitchClass.C, SwitchClass.D} and not backup_healthy:
        blockers.append("healthy_backup_required")

    evidence_blockers = verify_qualification_proofs(
        tokens,
        required=gate.required_evidence,
        environment=desired.metadata.environment,
        source_digest=plan.source_digest,
        target_digest=plan.target_digest,
        signing_key=signing_key,
        now=now,
    )
    blockers.extend(evidence_blockers)
    return DispatchPreflight(
        allowed=not blockers,
        classification=gate.change_class,
        blockers=tuple(dict.fromkeys(blockers)),
        target_digest=plan.target_digest,
    )
