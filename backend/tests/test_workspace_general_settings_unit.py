"""Focused regression tests for the additive workspace settings service."""
from __future__ import annotations

from unittest.mock import Mock
from uuid import uuid4

import pytest

from northstar_api.modules.workspace.services import general_settings


def test_change_detection_is_allowlisted_and_deterministic() -> None:
    before = {
        "name": "Before", "slug": "before", "timezone": "UTC",
        "default_language": "English", "date_format": "DD/MM/YYYY",
        "api_key": "old-secret",
    }
    after = {**before, "name": "After", "timezone": "Asia/Calcutta", "api_key": "new-secret"}
    assert general_settings.changed_general_fields(before, after) == ("name", "timezone")
    assert general_settings.changed_general_fields(after, after) == ()


def test_record_general_change_is_tenant_scoped_and_never_contains_values(monkeypatch: pytest.MonkeyPatch) -> None:
    audit = Mock()
    outbox = Mock()
    monkeypatch.setattr(general_settings, "record_audit_event", audit)
    monkeypatch.setattr(general_settings, "enqueue_event", outbox)
    session = Mock()
    tenant_id, workspace_id, actor_id = uuid4(), uuid4(), uuid4()

    assert general_settings.record_general_settings_update(
        session, tenant_id=tenant_id, workspace_id=workspace_id,
        actor_user_id=actor_id, changed_fields=("timezone", "name", "name"),
    ) is True
    audit.assert_called_once()
    outbox.assert_called_once()
    assert audit.call_args.kwargs["tenant_id"] == tenant_id
    assert audit.call_args.kwargs["workspace_id"] == workspace_id
    assert audit.call_args.kwargs["actor_user_id"] == actor_id
    assert audit.call_args.kwargs["action"] == "workspace.settings.updated"
    assert audit.call_args.kwargs["metadata"] == {"fields": ["name", "timezone"]}
    assert outbox.call_args.kwargs == {
        "tenant_id": tenant_id,
        "aggregate_type": "workspace",
        "aggregate_id": workspace_id,
        "event_type": "workspace.settings.updated.v1",
        "payload": {"workspaceId": str(workspace_id), "fields": ["name", "timezone"]},
    }
    assert outbox.return_value.workspace_id == workspace_id


def test_noop_creates_no_audit_or_event(monkeypatch: pytest.MonkeyPatch) -> None:
    audit = Mock()
    outbox = Mock()
    monkeypatch.setattr(general_settings, "record_audit_event", audit)
    monkeypatch.setattr(general_settings, "enqueue_event", outbox)
    assert general_settings.record_general_settings_update(
        Mock(), tenant_id=uuid4(), workspace_id=uuid4(),
        actor_user_id=uuid4(), changed_fields=(),
    ) is False
    audit.assert_not_called()
    outbox.assert_not_called()


def test_unknown_audit_fields_are_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    audit = Mock()
    monkeypatch.setattr(general_settings, "record_audit_event", audit)
    with pytest.raises(ValueError, match="Only general workspace"):
        general_settings.record_general_settings_update(
            Mock(), tenant_id=uuid4(), workspace_id=uuid4(),
            actor_user_id=uuid4(), changed_fields=("api_key",),
        )
    audit.assert_not_called()
