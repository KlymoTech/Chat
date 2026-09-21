"""Workspace general settings change detection and transactional side effects.

Only field names, never customer-provided values, enter audit or outbox payloads.
The caller commits these records in the same transaction as workspace changes.
"""
from __future__ import annotations

from collections.abc import Mapping
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from northstar_api.lead_crm.audit import record_audit_event
from northstar_api.services.outbox import enqueue_event

GENERAL_SETTING_FIELDS = frozenset({
    "name", "slug", "timezone", "default_language", "date_format",
})
GENERAL_PREFERENCE_FIELDS: Mapping[str, str] = {
    "industry": "industry",
    "country": "country",
    "description": "description",
    "time_format": "timeFormat",
    "currency": "currency",
    "week_start": "weekStart",
    "workspace_icon": "workspaceIcon",
    "business_hours": "businessHours",
}
_AUDITABLE_FIELDS = GENERAL_SETTING_FIELDS | frozenset(GENERAL_PREFERENCE_FIELDS)


def normalize_workspace_name(value: str | None) -> str | None:
    """Validate the persisted form, not just the untrimmed request length.

    Both workspace creation and profile updates trim names before saving. A
    whitespace-only or single-visible-character name must not become an empty
    or invalid database value after Pydantic's length check has already passed.
    Preserve optional ``None`` in PATCH for backwards compatibility.
    """
    if value is None:
        return None
    normalized = value.strip()
    if len(normalized) < 2:
        raise ValueError("Workspace name must contain at least two visible characters")
    return normalized


def changed_general_fields(
    before: Mapping[str, object], after: Mapping[str, object],
) -> tuple[str, ...]:
    """Return only changed, allowlisted top-level fields in deterministic order."""
    return tuple(sorted(
        field for field in GENERAL_SETTING_FIELDS if before.get(field) != after.get(field)
    ))


def changed_preference_fields(
    before: Mapping[str, object], after: Mapping[str, object],
) -> tuple[str, ...]:
    """Compare validated camelCase preference snapshots and return field names only."""
    return tuple(sorted(
        field for field, alias in GENERAL_PREFERENCE_FIELDS.items()
        if before.get(alias) != after.get(alias)
    ))


def record_general_settings_update(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    workspace_id: UUID,
    actor_user_id: UUID,
    changed_fields: tuple[str, ...],
) -> bool:
    """Stage an audit record and outbox event; the workspace route owns commit.

    A no-op PATCH does not produce misleading administrative activity. Reject
    unexpected field names instead of accidentally recording sensitive values.
    """
    fields = tuple(sorted(set(changed_fields)))
    if not fields:
        return False
    if not set(fields) <= _AUDITABLE_FIELDS:
        raise ValueError("Only general workspace setting fields may be audited here")

    record_audit_event(
        session,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        actor_user_id=actor_user_id,
        action="workspace.settings.updated",
        entity_type="workspace",
        entity_id=str(workspace_id),
        category="workspace",
        metadata={"fields": list(fields)},
    )
    event = enqueue_event(
        session,
        tenant_id=tenant_id,
        aggregate_type="workspace",
        aggregate_id=workspace_id,
        event_type="workspace.settings.updated.v1",
        payload={"workspaceId": str(workspace_id), "fields": list(fields)},
    )
    event.workspace_id = workspace_id
    return True
