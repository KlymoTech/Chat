"""Admin notification route draft/approve API guards and transactional auditing."""
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from fastapi import HTTPException

from northstar_api.modules.super_admin.api import runtime
from northstar_api.modules.super_admin.api.runtime import (
    NotificationRouteApprovalRequest,
    NotificationRouteDraftRequest,
    approve_platform_notification_route,
    draft_platform_notification_route,
)


def session():
    return SimpleNamespace(commit=AsyncMock(), rollback=AsyncMock())


@pytest.mark.asyncio
async def test_draft_commits_only_after_audit(monkeypatch):
    db = session()
    principal = SimpleNamespace(tenant_id=uuid4(), user_id=uuid4())
    audit = MagicMock()
    monkeypatch.setattr(runtime, "record_audit_event", audit)
    from northstar_api.modules.platform_runtime import queue_notification_governance as governance
    service = AsyncMock(return_value=4)
    monkeypatch.setattr(governance, "draft_notification_route", service)
    result = await draft_platform_notification_route(
        "email", NotificationRouteDraftRequest(
            destination_reference="approved:ops", expected_revision=3,
            reason="Documented operational destination",
        ), principal, db,
    )
    assert result == {"channel": "email", "revision": 4, "approved": False, "enabled": False}
    callback = service.await_args.kwargs["audit"]
    await callback(db, {
        "action": "platform.notification_route.drafted",
        "tenant_id": str(principal.tenant_id), "actor_id": str(principal.user_id),
        "channel": "email", "revision": "4",
    })
    audit.assert_called_once()
    assert audit.call_args.kwargs["actor_user_id"] == principal.user_id
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_approve_stays_disabled(monkeypatch):
    db = session()
    principal = SimpleNamespace(tenant_id=uuid4(), user_id=uuid4())
    from northstar_api.modules.platform_runtime import queue_notification_governance as governance
    service = AsyncMock()
    monkeypatch.setattr(governance, "approve_notification_route", service)
    result = await approve_platform_notification_route(
        "webhook", NotificationRouteApprovalRequest(
            revision=3, reason="Approved after independent review",
        ), principal, db,
    )
    assert result["approved"] is True
    assert result["enabled"] is False
    assert service.await_args.kwargs["actor_id"] == principal.user_id
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_missing_tenant_and_invalid_channel_fail_before_mutation():
    db = session()
    principal = SimpleNamespace(tenant_id=None, user_id=uuid4())
    with pytest.raises(HTTPException) as exc:
        await draft_platform_notification_route(
            "email", NotificationRouteDraftRequest(
                destination_reference="approved:ops", expected_revision=0,
                reason="Documented new route proposal",
            ), principal, db,
        )
    assert exc.value.status_code == 403
    db.commit.assert_not_awaited()
    principal.tenant_id = uuid4()
    with pytest.raises(HTTPException) as exc:
        await approve_platform_notification_route(
            "sms", NotificationRouteApprovalRequest(
                revision=1, reason="Approval requested for routing",
            ), principal, db,
        )
    assert exc.value.status_code == 422
    db.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_approval_conflict_rolls_back(monkeypatch):
    from northstar_api.modules.platform_runtime import queue_notification_governance as governance
    db = session()
    monkeypatch.setattr(governance, "approve_notification_route",
                        AsyncMock(side_effect=governance.RouteConflict("same actor")))
    with pytest.raises(HTTPException) as exc:
        await approve_platform_notification_route(
            "email", NotificationRouteApprovalRequest(
                revision=1, reason="Independent authorization review",
            ), SimpleNamespace(tenant_id=uuid4(), user_id=uuid4()), db,
        )
    assert exc.value.status_code == 409
    db.rollback.assert_awaited_once()
    db.commit.assert_not_awaited()
