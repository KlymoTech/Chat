"""Northstar tier ladder and safe, non-executing transition plans.

Tier metadata is architectural intent, not measured system capacity. Existing
application runtime and platform profiles remain backward compatible.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class PlatformTier(str, Enum):
    T0 = "T0"
    T1 = "T1"
    T2 = "T2"
    T3 = "T3"
    T4 = "T4"


@dataclass(frozen=True)
class TierDefinition:
    tier: PlatformTier
    name: str
    topology: str
    capabilities: tuple[str, ...]


TIERS: tuple[TierDefinition, ...] = (
    TierDefinition(PlatformTier.T0, "Starter", "single deployment",
                   ("durable-data", "tenant-isolation", "audit", "minimum-telemetry")),
    TierDefinition(PlatformTier.T1, "Standard", "multi-availability-zone",
                   ("multi-az", "durable-data", "tenant-isolation", "audit", "minimum-telemetry")),
    TierDefinition(PlatformTier.T2, "Growth", "split workload roles",
                   ("role-splitting", "horizontal-replicas", "cache-adapter", "multi-az")),
    TierDefinition(PlatformTier.T3, "Scale", "tenant-cell partitioning",
                   ("cell-directory", "routing-epochs", "cell-failover", "multi-az")),
    TierDefinition(PlatformTier.T4, "Global", "multi-region topology",
                   ("regional-routing", "data-residency", "region-recovery", "tenant-cells")),
)


@dataclass(frozen=True)
class TierTransition:
    source: PlatformTier
    target: PlatformTier
    direction: str
    steps: tuple[str, ...]
    required_evidence: tuple[str, ...]
    blockers: tuple[str, ...]
    automatic: bool = False


def tier_definition(tier: PlatformTier) -> TierDefinition:
    return TIERS[list(PlatformTier).index(tier)]


def plan_tier_transition(
    source: PlatformTier,
    target: PlatformTier,
    *,
    approved: bool = False,
    evidence: frozenset[str] = frozenset(),
) -> TierTransition:
    """Return a reviewable plan; never provision or destroy infrastructure.

    Adjacent tier transitions only. Downgrades require explicit consolidation
    evidence and are not implicitly the reverse of an upgrade.
    """
    source_index, target_index = list(PlatformTier).index(source), list(PlatformTier).index(target)
    if source == target:
        return TierTransition(source, target, "none", (), (), (), False)
    if abs(source_index - target_index) != 1:
        return TierTransition(source, target, "nonadjacent", (), (),
                              ("tier_changes_must_be_adjacent",), False)
    downgrade = target_index < source_index
    requirements = (
        "current_load_evidence",
        "capacity_headroom_qualification",
        "backup_restore_proof",
        "change_canary_result",
        "rollback_or_forward_repair",
        "cost_budget_approval",
    )
    if downgrade:
        requirements += ("data_consolidation_reconciliation", "residency_and_retention_review")
    steps = (
        "capture_desired_and_observed_state",
        "check_incidents_budget_quotas_and_backups",
        "approve_governed_child_migrations",
        "provision_or_consolidate_resources",
        "canary_and_verify_data_plane",
        "reconcile_and_stabilize",
        "update_observed_tier_and_audit",
    )
    blockers = tuple(f"missing:{item}" for item in requirements if item not in evidence)
    if not approved:
        blockers += ("independent_approval_required",)
    return TierTransition(source, target, "downgrade" if downgrade else "upgrade",
                          steps, requirements, blockers, False)
