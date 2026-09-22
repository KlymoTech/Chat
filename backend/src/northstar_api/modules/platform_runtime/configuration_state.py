"""Durable desired-state versions and observed capability overlays."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from .contracts import PlatformSpec
from .control_plane import spec_digest
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
                actual_state=state.actual_state,
                health=state.health,
                revision=spec.metadata.revision,
                metadata_json={},
            )
            session.add(record)
            continue
        record.provider = state.provider
        record.fallback_provider = state.definition.fallback_provider
        record.desired_state = state.desired_state
        record.revision = spec.metadata.revision


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
    "activate_configuration_version",
    "catalog_with_observations",
    "effective_platform_spec",
    "ensure_configuration_version",
    "sync_desired_capabilities",
]
