"""Pure, fail-closed evidence gates for Northstar governed infrastructure changes.

This module never executes AWS mutations. An evidence reference is not proof by
itself: the issuer, expiry, environment, scope and bound configuration digest
must match the proposed change. Callers must verify the underlying signed or
immutable evidence artifact separately before recording it as trusted.
"""
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation

from .governed_switches import SwitchClass, TransitionGate


@dataclass(frozen=True)
class QualificationEvidence:
    evidence_id: str
    kind: str
    environment: str
    target_digest: str
    recorded_at: datetime
    expires_at: datetime
    verified: bool = False

    def __post_init__(self) -> None:
        if not self.evidence_id or not self.kind or not self.target_digest:
            raise ValueError("evidence requires nonempty id, kind and target digest")
        if self.recorded_at.tzinfo is None or self.expires_at.tzinfo is None:
            raise ValueError("evidence timestamps must be timezone-aware")
        if self.expires_at <= self.recorded_at:
            raise ValueError("evidence expiry must be after recording")


@dataclass(frozen=True)
class ChangeGuards:
    environment: str
    target_digest: str
    now: datetime
    requester_id: str
    approver_id: str | None = None
    active_incident: bool = False
    backups_healthy: bool = False
    within_maintenance_window: bool = False
    estimated_monthly_delta_usd: str = "0"
    approved_monthly_budget_delta_usd: str = "0"

    def __post_init__(self) -> None:
        if not self.environment or not self.target_digest or not self.requester_id:
            raise ValueError("environment, target digest and requester are required")
        if self.now.tzinfo is None:
            raise ValueError("now must be timezone-aware")


@dataclass(frozen=True)
class QualificationDecision:
    allowed: bool
    blockers: tuple[str, ...]
    satisfied_evidence: tuple[str, ...]


def evaluate_change_qualification(
    gate: TransitionGate,
    evidence: Iterable[QualificationEvidence],
    guards: ChangeGuards,
) -> QualificationDecision:
    """Assess an immutable proposal, without granting execution rights.

    Unknown/expired/unverified/wrong-environment evidence never satisfies a
    gate. The same evidence ID cannot satisfy multiple different requirements.
    Class L and E are blocked from automated execution regardless of evidence.
    """
    now = guards.now.astimezone(UTC)
    blockers: list[str] = []
    if gate.change_class is SwitchClass.L:
        blockers.append("locked_change_prohibited")
    if gate.change_class is SwitchClass.E:
        blockers.append("manual_qualification_required")
    if guards.active_incident:
        blockers.append("active_incident")
    if gate.requires_approval:
        if not guards.approver_id or guards.approver_id == guards.requester_id:
            blockers.append("independent_approval_required")
        if not guards.within_maintenance_window:
            blockers.append("maintenance_window_required")
    if gate.change_class in {SwitchClass.C, SwitchClass.D} and not guards.backups_healthy:
        blockers.append("healthy_backup_required")

    try:
        projected = Decimal(guards.estimated_monthly_delta_usd)
        budget = Decimal(guards.approved_monthly_budget_delta_usd)
        if not projected.is_finite() or not budget.is_finite() or budget < 0:
            raise InvalidOperation()
    except (InvalidOperation, ValueError):
        blockers.append("invalid_budget")
    else:
        if projected > budget:
            blockers.append("budget_exceeded")

    valid_by_kind: dict[str, set[str]] = {}
    for item in evidence:
        if (item.verified and item.environment == guards.environment
                and item.target_digest == guards.target_digest
                and item.recorded_at.astimezone(UTC) <= now
                < item.expires_at.astimezone(UTC)):
            valid_by_kind.setdefault(item.kind, set()).add(item.evidence_id)
    satisfied = tuple(sorted(set(gate.required_evidence) & valid_by_kind.keys()))
    for requirement in gate.required_evidence:
        if requirement not in valid_by_kind:
            blockers.append(f"missing_valid_evidence:{requirement}")
    return QualificationDecision(not blockers, tuple(blockers), satisfied)
