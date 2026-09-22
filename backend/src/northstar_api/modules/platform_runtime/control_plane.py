"""Safe, provider-neutral planning for platform configuration changes.

The control plane produces an immutable, reviewable plan. It deliberately does
not call AWS, mutate infrastructure, delete resources, or claim that a change
has been applied. A deployment controller may consume a plan only after its
approval and profile-specific evidence gates have passed.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field

from .contracts import PlatformSpec, ProviderChangeClass
from .validation import classify_provider_change, validate_platform_spec

PlanAction = Literal["noop", "apply", "restart", "migrate", "reject"]


class ChangePlan(BaseModel):
    """An immutable desired-state transition for review and deployment."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    plan_id: UUID
    action: PlanAction
    classification: ProviderChangeClass
    source_revision: int = Field(ge=1)
    target_revision: int = Field(ge=1)
    source_digest: str = Field(min_length=64, max_length=64)
    target_digest: str = Field(min_length=64, max_length=64)
    requires_approval: bool
    destructive: bool = False
    steps: tuple[str, ...] = Field(default_factory=tuple)
    blockers: tuple[str, ...] = Field(default_factory=tuple)
    created_at: datetime


def spec_digest(spec: PlatformSpec) -> str:
    """Return a stable digest for the exact desired platform state."""
    payload = json.dumps(spec.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def build_change_plan(
    current: PlatformSpec,
    desired: PlatformSpec,
    *,
    plan_id: UUID | None = None,
) -> ChangePlan:
    """Build a safe change plan without applying infrastructure mutations."""
    validate_platform_spec(current)
    validate_platform_spec(desired)
    classification = classify_provider_change(current, desired)
    source_digest = spec_digest(current)
    target_digest = spec_digest(desired)

    if current == desired:
        return ChangePlan(
            plan_id=plan_id or uuid4(),
            action="noop",
            classification="hot-safe",
            source_revision=current.metadata.revision,
            target_revision=desired.metadata.revision,
            source_digest=source_digest,
            target_digest=target_digest,
            requires_approval=False,
            steps=("verify_observed_state",),
            created_at=datetime.now(UTC),
        )

    if desired.metadata.revision <= current.metadata.revision:
        return ChangePlan(
            plan_id=plan_id or uuid4(),
            action="reject",
            classification=classification,
            source_revision=current.metadata.revision,
            target_revision=desired.metadata.revision,
            source_digest=source_digest,
            target_digest=target_digest,
            requires_approval=True,
            blockers=("target_revision_must_advance",),
            created_at=datetime.now(UTC),
        )

    if classification == "prohibited":
        return ChangePlan(
            plan_id=plan_id or uuid4(),
            action="reject",
            classification=classification,
            source_revision=current.metadata.revision,
            target_revision=desired.metadata.revision,
            source_digest=source_digest,
            target_digest=target_digest,
            requires_approval=True,
            blockers=("deployment_profile_change_requires_a_separate_cutover",),
            created_at=datetime.now(UTC),
        )

    if classification == "migration":
        steps = (
            "freeze_new_writes_at_boundary",
            "copy_and_verify_authoritative_state",
            "advance_provider_generation",
            "switch_reads_and_writes",
            "reconcile_pending_work_and_indeterminate_effects",
            "observe_before_retiring_previous_provider",
        )
        action: PlanAction = "migrate"
        requires_approval = True
    elif classification == "restart":
        steps = ("validate_dependencies", "drain_or_fence_workers", "roll_out_new_revision", "verify_observed_state")
        action = "restart"
        requires_approval = True
    else:
        steps = ("validate_dependencies", "apply_runtime_configuration", "verify_observed_state")
        action = "apply"
        requires_approval = False

    return ChangePlan(
        plan_id=plan_id or uuid4(),
        action=action,
        classification=classification,
        source_revision=current.metadata.revision,
        target_revision=desired.metadata.revision,
        source_digest=source_digest,
        target_digest=target_digest,
        requires_approval=requires_approval,
        steps=steps,
        created_at=datetime.now(UTC),
    )


__all__ = ["ChangePlan", "PlanAction", "build_change_plan", "spec_digest"]
