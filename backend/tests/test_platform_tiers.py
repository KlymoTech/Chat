"""Pure tier-planner tests: no cloud credentials or infrastructure required."""
from northstar_api.modules.platform_runtime.tiers import (
    PlatformTier, TIERS, plan_tier_transition, tier_definition,
)


def test_five_tiers_have_distinct_definitions() -> None:
    assert tuple(item.tier for item in TIERS) == tuple(PlatformTier)
    assert tier_definition(PlatformTier.T3).name == "Scale"


def test_noop_does_not_mutate() -> None:
    plan = plan_tier_transition(PlatformTier.T0, PlatformTier.T0)
    assert plan.direction == "none"
    assert not plan.automatic


def test_nonadjacent_change_fails_closed() -> None:
    plan = plan_tier_transition(PlatformTier.T0, PlatformTier.T3, approved=True)
    assert plan.blockers == ("tier_changes_must_be_adjacent",)


def test_upgrade_requires_approval_and_evidence() -> None:
    plan = plan_tier_transition(PlatformTier.T1, PlatformTier.T2)
    assert plan.direction == "upgrade"
    assert "independent_approval_required" in plan.blockers
    assert "missing:backup_restore_proof" in plan.blockers
    qualified = plan_tier_transition(PlatformTier.T1, PlatformTier.T2, approved=True,
                                     evidence=frozenset(plan.required_evidence))
    assert qualified.blockers == ()
    assert not qualified.automatic


def test_downgrade_requires_consolidation_and_residency() -> None:
    plan = plan_tier_transition(PlatformTier.T4, PlatformTier.T3)
    assert plan.direction == "downgrade"
    assert "missing:data_consolidation_reconciliation" in plan.blockers
    assert "missing:residency_and_retention_review" in plan.blockers
