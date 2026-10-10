"""Evidence-gated classification for adaptive infrastructure transitions.

This module is advisory and has no infrastructure mutation permissions.
It deliberately supplements the legacy change planner without changing it.
"""
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from enum import Enum

from .contracts import PlatformSpec
from .validation import validate_platform_spec


class SwitchClass(str, Enum):
    A = "A"  # Reversible runtime preference
    B = "B"  # Restart or deployment
    C = "C"  # Stateful provider migration
    D = "D"  # Topology or placement migration
    L = "L"  # Locked safety invariant
    E = "E"  # Experimental or unqualified change


@dataclass(frozen=True)
class TransitionGate:
    change_class: SwitchClass
    changes: tuple[str, ...]
    required_evidence: tuple[str, ...]
    requires_approval: bool
    eligible_for_automatic_execution: bool
    reason: str


_MIGRATION = frozenset({"jobs", "events", "storage", "search", "vector"})
_TOPOLOGY = frozenset({"profile", "orchestrator", "region", "account_id", "availability_zones"})
_LOCKED = frozenset({"authorization_required", "tenant_isolation_required", "audit_required"})
_RESTART = frozenset({"identity", "secrets", "image_digest", "ai", "allow_external_ai_egress"})
_EVIDENCE = {
    SwitchClass.A: ("health_snapshot", "rollback_configuration"),
    SwitchClass.B: ("deployment_plan", "canary_result", "rollback_configuration"),
    SwitchClass.C: ("backup_restore_proof", "dual_run_reconciliation", "cutover_plan", "rollback_or_forward_repair"),
    SwitchClass.D: ("capacity_qualification", "backup_restore_proof", "routing_epoch_plan",
                    "canary_result", "rollback_or_forward_repair"),
    SwitchClass.L: (),
    SwitchClass.E: ("architecture_review", "explicit_risk_acceptance"),
}


def _diff(current: PlatformSpec, desired: PlatformSpec) -> set[str]:
    changed: set[str] = set()
    for section in ("providers", "security", "features", "deployment", "reliability", "resources", "metadata"):
        a, b = getattr(current, section), getattr(desired, section)
        for field in type(a).model_fields:
            if getattr(a, field) != getattr(b, field):
                if field != "revision":
                    changed.add(field)
    if current.profile != desired.profile:
        changed.add("profile")
    return changed


def classify_transition(current: PlatformSpec, desired: PlatformSpec) -> TransitionGate:
    """Plan the strongest required change class; never execute a transition."""
    validate_platform_spec(current)
    # Validate proposed state separately: fail closed on invalid production configs.
    validate_platform_spec(desired)
    changed = _diff(current, desired)
    if not changed:
        return TransitionGate(SwitchClass.A, (), (), False, False, "no_change")
    if "environment" in changed:
        kind, reason = SwitchClass.L, "cross_environment_change_prohibited"
    elif changed & _LOCKED:
        kind, reason = SwitchClass.L, "locked_security_configuration_requires_review"
    elif changed & _TOPOLOGY:
        kind, reason = SwitchClass.D, "topology_or_placement_migration"
    elif changed & _MIGRATION:
        kind, reason = SwitchClass.C, "stateful_provider_migration"
    elif changed & _RESTART:
        kind, reason = SwitchClass.B, "deployment_or_restart_required"
    elif changed & {"automatic_stateful_provider_switch"}:
        kind, reason = SwitchClass.E, "unqualified_automation_policy"
    else:
        kind, reason = SwitchClass.A, "reversible_configuration"
    return TransitionGate(
        change_class=kind,
        changes=tuple(sorted(changed)),
        required_evidence=_EVIDENCE[kind],
        requires_approval=kind is not SwitchClass.A,
        # Even Class A changes require the existing change executor; the
        # planner itself never has permissions to apply state.
        eligible_for_automatic_execution=kind is SwitchClass.A,
        reason=reason,
    )


def verify_evidence(gate: TransitionGate, evidence: Iterable[str], *, approved: bool = False) -> tuple[str, ...]:
    """Return fail-closed blockers, not a claim of production certification."""
    supplied = set(evidence)
    blockers = [f"missing:{item}" for item in gate.required_evidence if item not in supplied]
    if gate.requires_approval and not approved:
        blockers.append("independent_approval_required")
    if gate.change_class is SwitchClass.L:
        blockers.append("locked_change_prohibited")
    if gate.change_class is SwitchClass.E:
        blockers.append("manual_qualification_required")
    return tuple(blockers)
