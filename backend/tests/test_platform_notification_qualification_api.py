"""Authenticated qualification decision API preserves isolation and audit boundaries."""
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from fastapi import HTTPException

from northstar_api.modules.super_admin.api import runtime


def request():
    return runtime.NotificationQualificationDecisionRequest(
        expected_revision=2, reason="Independent certification review completed",
    )


def session():
    return SimpleNamespace(commit=AsyncMock(), rollback=AsyncMock())


@pytest.mark.asyncio
async def test_missing_tenant_and_unknown_action_fail_before_mutation():
    db = session()
    with pytest.raises(HTTPException) as exc:
        await runtime.decide_notification_worker_qualification(
            "cert-123456", "approve", request(),
            SimpleNamespace(tenant_id=None, user_id=uuid4()), db,
        )
    assert exc.value.status_code == 403
    with pytest.raises(HTTPException) as exc:
        await runtime.decide_notification_worker_qualification(
            "cert-123456", "enable", request(),
            SimpleNamespace(tenant_id=uuid4(), user_id=uuid4()), db,
        )
    assert exc.value.status_code == 404
    db.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_approval_integrates_service_and_commits(monkeypatch):
    from northstar_api.modules.platform_runtime import queue_notification_qualification_governance as governance
    service = AsyncMock(return_value=3)
    monkeypatch.setattr(governance, "change_qualification_status", service)
    db = session()
    actor, tenant = uuid4(), uuid4()
    result = await runtime.decide_notification_worker_qualification(
        "cert-123456", "approve", request(),
        SimpleNamespace(tenant_id=tenant, user_id=actor), db,
    )
    assert result == {"qualification_id": "cert-123456", "revision": 3,
                      "approved": True, "revoked": False}
    assert service.await_args.kwargs["actor_id"] == str(actor)
    assert service.await_args.kwargs["expected_revision"] == 2
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_conflict_rolls_back_and_never_commits(monkeypatch):
    from northstar_api.modules.platform_runtime import queue_notification_qualification_governance as governance
    monkeypatch.setattr(
        governance, "change_qualification_status",
        AsyncMock(side_effect=governance.QualificationGovernanceConflict("stale")),
    )
    db = session()
    with pytest.raises(HTTPException) as exc:
        await runtime.decide_notification_worker_qualification(
            "cert-123456", "revoke", request(),
            SimpleNamespace(tenant_id=uuid4(), user_id=uuid4()), db,
        )
    assert exc.value.status_code == 409
    db.rollback.assert_awaited_once()
    db.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_audit_uses_existing_transaction(monkeypatch):
    from northstar_api.modules.platform_runtime import queue_notification_qualification_governance as governance
    audited = MagicMock()
    monkeypatch.setattr(runtime, "record_audit_event", audited)
    db = session()
    tenant, actor = uuid4(), uuid4()

    async def govern(sess, **kwargs):
        await kwargs["audit"](sess, {
            "action": "platform.notification_qualification.revoke",
            "qualification_id": "cert-123456",
            "revision": "4", "actor_id": str(actor),
        })
        return 4

    monkeypatch.setattr(governance, "change_qualification_status", govern)
    await runtime.decide_notification_worker_qualification(
        "cert-123456", "revoke", request(),
        SimpleNamespace(tenant_id=tenant, user_id=actor), db,
    )
    audited.assert_called_once()
    assert audited.call_args.args[0] is db
    assert audited.call_args.kwargs["tenant_id"] == tenant
    assert audited.call_args.kwargs["actor_user_id"] == actor
