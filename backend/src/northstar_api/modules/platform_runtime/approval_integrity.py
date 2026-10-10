"""Integrity boundary for persisted, approval-bound platform changes.

Reject tampered snapshots before accepting qualification tokens. This module
does not perform deployment or grant permissions.
"""
from __future__ import annotations

from .contracts import PlatformSpec
from .control_plane import build_change_plan, spec_digest


def persisted_change_integrity_blockers(
    *,
    current_json: dict,
    desired_json: dict,
    environment: str,
    source_revision: int,
    target_revision: int,
    source_digest: str,
    target_digest: str,
    action: str,
    classification: str,
) -> tuple[str, ...]:
    """Validate stored snapshots and the immutable plan against stored metadata."""
    try:
        current = PlatformSpec.model_validate(current_json)
        desired = PlatformSpec.model_validate(desired_json)
        plan = build_change_plan(current, desired)
    except (ValueError, TypeError):
        return ("persisted_spec_invalid",)

    blockers: list[str] = []
    if current.metadata.environment != environment or desired.metadata.environment != environment:
        blockers.append("persisted_environment_mismatch")
    if current.metadata.revision != source_revision or desired.metadata.revision != target_revision:
        blockers.append("persisted_revision_mismatch")
    if spec_digest(current) != source_digest or spec_digest(desired) != target_digest:
        blockers.append("persisted_digest_mismatch")
    if plan.action in {"noop", "reject"} or action != plan.action:
        blockers.append("persisted_action_mismatch")
    if classification != plan.classification:
        blockers.append("persisted_classification_mismatch")
    return tuple(blockers)
