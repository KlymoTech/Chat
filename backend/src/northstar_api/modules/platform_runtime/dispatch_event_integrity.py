"""Validate an approved outbox dispatch at the worker trust boundary.

This pure validator is intended for an external, authorized deployment worker.
It cannot authorize or execute AWS mutations; it must be combined with a fresh
transactional approved-state check, signed qualification and worker IAM policy.
"""
from __future__ import annotations

from .approval_integrity import persisted_change_integrity_blockers
from .contracts import PlatformSpec
from .control_plane import build_change_plan
from .executor_contract import DeploymentDispatchEvent


def validate_dispatch_event(
    event: DeploymentDispatchEvent,
    *,
    approved: bool,
    approved_change_id: str,
    approved_idempotency_key: str,
) -> tuple[str, ...]:
    """Fail closed on forged or stale events before worker side effects."""
    blockers = list(persisted_change_integrity_blockers(
        current_json=event.current_spec,
        desired_json=event.desired_spec,
        environment=event.environment,
        source_revision=event.source_revision,
        target_revision=event.target_revision,
        source_digest=event.source_digest,
        target_digest=event.target_digest,
        action=event.action,
        classification=event.classification,
    ))
    try:
        plan = build_change_plan(
            PlatformSpec.model_validate(event.current_spec),
            PlatformSpec.model_validate(event.desired_spec),
        )
    except (ValueError, TypeError):
        blockers.append("dispatch_plan_invalid")
    else:
        if tuple(event.plan_steps) != plan.steps:
            blockers.append("dispatch_steps_mismatch")
        if event.destructive != plan.destructive:
            blockers.append("dispatch_destructive_flag_mismatch")
    if not approved:
        blockers.append("change_not_approved")
    if str(event.change_id) != approved_change_id:
        blockers.append("approved_change_id_mismatch")
    if event.idempotency_key != approved_idempotency_key:
        blockers.append("idempotency_key_mismatch")
    if event.destructive and event.action == "hot_apply":
        blockers.append("destructive_hot_apply_rejected")
    if event.target_revision <= event.source_revision:
        blockers.append("nonadvancing_revision")
    return tuple(blockers)
