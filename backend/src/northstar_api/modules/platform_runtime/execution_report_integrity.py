"""Conflict detection for immutable deployment execution reports.

Report IDs are idempotency keys, not permission to overwrite health evidence.
An exact replay is safe; conflicting reports must fail closed.
"""
from __future__ import annotations

from typing import Any

from .executor_contract import DeploymentExecutionReport


def execution_report_matches(
    *,
    stored_source_digest: str | None,
    stored_target_digest: str | None,
    stored_pipeline: str,
    stored_phase: str,
    stored_health: dict[str, Any],
    stored_error: str | None,
    incoming: DeploymentExecutionReport,
) -> bool:
    """Compare every durable report field, not only its idempotency key."""
    return (
        stored_source_digest == incoming.source_digest
        and stored_target_digest == incoming.target_digest
        and stored_pipeline == incoming.pipeline
        and stored_phase == incoming.phase
        and stored_health == incoming.health_result
        and stored_error == incoming.error
    )
