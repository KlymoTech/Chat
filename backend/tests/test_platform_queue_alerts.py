"""Pure queue alert classifier and endpoint boundary tests."""
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from fastapi import HTTPException

from northstar_api.modules.platform_runtime.queue_alerts import (
    QueueAlertThresholds,
    classify_queue_alerts,
)
from northstar_api.modules.super_admin.api import runtime


def overview():
    tenant = str(uuid4())
    return {
        "tenant_id": tenant,
        "status": "unknown",
        "durable_jobs": {
            "tenant_id": tenant,
            "counts": {"dead_letter": 0},
            "overdue": 0,
            "stale_leases": 0,
            "oldest_pending_seconds": None,
        },
        "brokers": {
            "sqs": {"status": "unconfigured"},
            "rabbitmq": {"status": "unconfigured"},
        },
    }


def test_unconfigured_brokers_do_not_emit_incident_alerts():
    assert classify_queue_alerts(overview()) == ()


def test_boundaries_and_scope_are_explicit():
    value = overview()
    value["durable_jobs"].update(
        overdue=50, stale_leases=1, oldest_pending_seconds=300,
        counts={"dead_letter": 2},
    )
    alerts = classify_queue_alerts(value)
    severities = {a.code: a.severity for a in alerts}
    assert severities == {
        "queue_overdue": "critical", "queue_dead_letters": "warning",
        "queue_stale_leases": "warning", "queue_pending_age": "warning",
    }
    assert all(a.scope == "tenant" for a in alerts)


def test_unknown_and_unavailable_probe_do_not_become_healthy():
    value = overview()
    value["brokers"]["sqs"] = {"status": "unavailable"}
    value["brokers"]["rabbitmq"] = {"status": "unexpected"}
    alerts = classify_queue_alerts(value)
    assert {a.code: a.severity for a in alerts} == {
        "sqs_probe_failed": "warning", "rabbitmq_probe_unknown": "unknown",
    }
    assert all(a.scope == "shared_queue" for a in alerts)


def test_cross_tenant_data_rejected():
    value = overview()
    value["durable_jobs"]["tenant_id"] = str(uuid4())
    with pytest.raises(ValueError, match="tenant"):
        classify_queue_alerts(value)


def test_invalid_threshold_configuration_rejected():
    with pytest.raises(ValueError):
        QueueAlertThresholds(warning_overdue=20, critical_overdue=5)


@pytest.mark.asyncio
async def test_admin_alert_endpoint_never_sends_notifications(monkeypatch):
    data = overview()
    monkeypatch.setattr(runtime, "read_platform_queue_overview", AsyncMock(return_value=data))
    result = await runtime.read_platform_queue_alerts(
        SimpleNamespace(tenant_id=data["tenant_id"]), MagicMock()
    )
    assert result["alerts"] == []
    assert result["delivery_configured"] is False


@pytest.mark.asyncio
async def test_admin_alert_endpoint_propagates_tenant_denial(monkeypatch):
    monkeypatch.setattr(
        runtime, "read_platform_queue_overview",
        AsyncMock(side_effect=HTTPException(status_code=403, detail="tenant scope required")),
    )
    with pytest.raises(HTTPException) as error:
        await runtime.read_platform_queue_alerts(SimpleNamespace(tenant_id=None), MagicMock())
    assert error.value.status_code == 403
