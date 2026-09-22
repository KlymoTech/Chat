"""Durable desired-state versions and observed capability overlays."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from .contracts import PlatformSpec
from .control_plane import spec_digest
from .executor_contract import CapabilityObservationEvidence
from .persistence import PlatformCapabilityRecord, PlatformChangeRecord, PlatformConfigVersion
from .registry import CapabilityCatalog, build_capability_catalog

_VALID_HEALTH = {"healthy", "degraded", "unhealthy", "disabled", "unknown"}


async def effective_platform_spec(
    session: AsyncSession,
    fallback: PlatformSpec,
    *,
    environment: str | None = None,
) -> PlatformSpec:
    """Return the latest verified desired state for one environment.

    Active configuration versions are authoritative. For databases created
    before version activation was wired, the latest completed change is used as
    a compatibility fallback. A different environment is never fabricated from
    process settings.
    """
    selected_environment = environment or fallback.metadata.environment
    active = await session.scalar(
        select(PlatformConfigVersion)
        .where(
            PlatformConfigVersion.environment == selected_environment,
            PlatformConfigVersion.active.is_(True),
        )
        .order_by(desc(PlatformConfigVersion.revision))
        .limit(1)
    )
    if active is not None:
        spec = PlatformSpec.model_validate(active.configuration_json)
        if spec_digest(spec) != active.digest:
            raise ValueError("active platform configuration digest mismatch")
        return spec

    completed = await session.scalar(
        select(PlatformChangeRecord)
        .where(
            PlatformChangeRecord.environment == selected_environment,
            PlatformChangeRecord.status == "completed",
        )
        .order_by(desc(PlatformChangeRecord.completed_at), desc(PlatformChangeRecord.target_revision))
        .limit(1)
    )
    if completed is not None and completed.desired_spec_json:
        spec = PlatformSpec.model_validate(completed.desired_spec_json)
        if spec_digest(spec) != completed.target_digest:
            raise ValueError("completed platform change digest mismatch")
        return spec

    if selected_environment != fallback.metadata.environment:
        raise ValueError(f"no desired state has been recorded for environment {selected_environment}")
    return fallback


async def ensure_configuration_version(
    session: AsyncSession,
    change: PlatformChangeRecord,
) -> PlatformConfigVersion:
    """Persist the immutable target configuration for a change exactly once."""
    existing = await session.scalar(
        select(PlatformConfigVersion).where(
            PlatformConfigVersion.environment == change.environment,
            PlatformConfigVersion.revision == change.target_revision,
        )
    )
    if existing is not None:
        if existing.digest != change.target_digest:
            raise ValueError("configuration revision already exists with a different digest")
        return existing

    spec = PlatformSpec.model_validate(change.desired_spec_json)
    if spec_digest(spec) != change.target_digest:
        raise ValueError("change target configuration digest mismatch")
    version = PlatformConfigVersion(
        environment=change.environment,
        revision=change.target_revision,
        digest=change.target_digest,
        configuration_json=spec.model_dump(mode="json"),
        created_by=change.requested_by,
        active=False,
        created_at=change.requested_at,
    )
    session.add(version)
    return version


async def sync_desired_capabilities(session: AsyncSession, spec: PlatformSpec) -> None:
    """Persist the desired provider/state without overwriting runtime evidence."""
    catalog = build_capability_catalog(spec)
    existing_rows = (
        await session.scalars(
            select(PlatformCapabilityRecord).where(
                PlatformCapabilityRecord.environment == spec.metadata.environment
            )
        )
    ).all()
    existing = {row.capability_id: row for row in existing_rows}
    for state in catalog.capabilities:
        capability_id = state.definition.capability_id
        record = existing.get(capability_id)
        if record is None:
            record = PlatformCapabilityRecord(
                environment=spec.metadata.environment,
                capability_id=capability_id,
                provider=state.provider,
                fallback_provider=state.definition.fallback_provider,
                desired_state=state.desired_state,
                actual_state="unknown",
                health="unknown" if state.desired_state == "on" else "disabled",
                revision=spec.metadata.revision,
                metadata_json={},
            )
            session.add(record)
            continue
        provider_changed = record.provider != state.provider
        record.provider = state.provider
        record.fallback_provider = state.definition.fallback_provider
        record.desired_state = state.desired_state
        record.revision = spec.metadata.revision
        if provider_changed:
            record.actual_state = "unknown"
            record.health = "unknown" if state.desired_state == "on" else "disabled"
            metadata = dict(record.metadata_json or {})
            metadata.pop("observedProvider", None)
            metadata.pop("observedAt", None)
            metadata["fallbackActive"] = False
            metadata["healthMessage"] = "Observation invalidated because the desired provider changed."
            record.metadata_json = metadata


async def activate_configuration_version(
    session: AsyncSession,
    change: PlatformChangeRecord,
) -> PlatformConfigVersion:
    """Mark a verified deployment target active and synchronize desired state."""
    version = await ensure_configuration_version(session, change)
    active_rows = (
        await session.scalars(
            select(PlatformConfigVersion).where(
                PlatformConfigVersion.environment == change.environment,
                PlatformConfigVersion.active.is_(True),
            )
        )
    ).all()
    for active in active_rows:
        if active.id != version.id:
            active.active = False
    version.active = True
    spec = PlatformSpec.model_validate(version.configuration_json)
    await sync_desired_capabilities(session, spec)
    return version


async def apply_capability_observations(
    session: AsyncSession,
    spec: PlatformSpec,
    observations: tuple[CapabilityObservationEvidence, ...],
) -> None:
    """Apply executor-reported actual state only after contract validation."""
    if not observations:
        return
    catalog = build_capability_catalog(spec)
    desired_by_id = {state.definition.capability_id: state for state in catalog.capabilities}
    rows = (
        await session.scalars(
            select(PlatformCapabilityRecord).where(
                PlatformCapabilityRecord.environment == spec.metadata.environment
            )
        )
    ).all()
    existing = {row.capability_id: row for row in rows}
    observed_at = datetime.now(UTC).isoformat()

    seen: set[str] = set()
    for observation in observations:
        if observation.capability_id in seen:
            raise ValueError(f"duplicate capability observation: {observation.capability_id}")
        seen.add(observation.capability_id)
        desired = desired_by_id.get(observation.capability_id)
        if desired is None:
            raise ValueError(f"unknown capability observation: {observation.capability_id}")
        record = existing.get(observation.capability_id)
        if record is None:
            record = PlatformCapabilityRecord(
                environment=spec.metadata.environment,
                capability_id=observation.capability_id,
                provider=desired.provider,
                fallback_provider=desired.definition.fallback_provider,
                desired_state=desired.desired_state,
                actual_state=observation.actual_state,
                health=observation.health,
                revision=spec.metadata.revision,
                metadata_json={},
            )
            session.add(record)
            existing[observation.capability_id] = record
        else:
            record.provider = desired.provider
            record.fallback_provider = desired.definition.fallback_provider
            record.desired_state = desired.desired_state
            record.actual_state = observation.actual_state
            record.health = observation.health
            record.revision = spec.metadata.revision

        metadata = dict(record.metadata_json or {})
        metadata.update(
            {
                "observedProvider": observation.observed_provider,
                "fallbackActive": observation.fallback_active,
                "healthMessage": observation.health_message,
                "estimatedMonthlyCostUsd": observation.estimated_monthly_cost_usd,
                "observedAt": observed_at,
            }
        )
        record.metadata_json = metadata


def _cost_value(metadata: Mapping[str, Any]) -> float | None:
    value = metadata.get("estimatedMonthlyCostUsd")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if value < 0:
        return None
    return float(value)


async def catalog_with_observations(
    session: AsyncSession,
    spec: PlatformSpec,
) -> CapabilityCatalog:
    """Overlay persisted runtime observations onto the desired-state catalog."""
    catalog = build_capability_catalog(spec)
    rows = (
        await session.scalars(
            select(PlatformCapabilityRecord).where(
                PlatformCapabilityRecord.environment == spec.metadata.environment
            )
        )
    ).all()
    by_id = {row.capability_id: row for row in rows}
    states = []
    for state in catalog.capabilities:
        row = by_id.get(state.definition.capability_id)
        if row is None:
            states.append(state)
            continue
        metadata = row.metadata_json or {}
        observed_provider = metadata.get("observedProvider")
        health_message = metadata.get("healthMessage")
        states.append(
            state.model_copy(
                update={
                    "actual_state": row.actual_state,
                    "health": row.health if row.health in _VALID_HEALTH else "unknown",
                    "fallback_active": bool(metadata.get("fallbackActive", False)),
                    "health_message": health_message if isinstance(health_message, str) else None,
                    "observed_provider": observed_provider if isinstance(observed_provider, str) else None,
                    "estimated_monthly_cost_usd": _cost_value(metadata),
                }
            )
        )
    return catalog.model_copy(update={"capabilities": tuple(states)})


__all__ = [
    "apply_capability_observations",
    "activate_configuration_version",
    "catalog_with_observations",
    "effective_platform_spec",
    "ensure_configuration_version",
    "sync_desired_capabilities",
]
