import json
import re
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest

from northstar_api.handlers import domain_events

TOPIC_ARN = "arn:aws:sns:ap-south-1:123456789012:events.fifo"
QUEUE_ARN = "arn:aws:sqs:ap-south-1:123456789012:events.fifo"


def sqs_event(event_type: str = "feedback.recorded.v1", *, topic_arn: str = TOPIC_ARN) -> dict:
    envelope = {
        "eventId": str(uuid4()),
        "eventType": event_type,
        "schemaVersion": 1,
        "tenantId": str(uuid4()),
        "aggregateType": "feedback",
        "aggregateId": str(uuid4()),
        "occurredAt": datetime.now(UTC).isoformat(),
        "payload": {"agentId": str(uuid4()), "value": 1},
    }
    return {
        "Records": [
            {
                "eventSource": "aws:sqs",
                "eventSourceARN": QUEUE_ARN,
                "messageId": "sqs-message-1",
                "body": json.dumps({
                    "Type": "Notification",
                    "TopicArn": topic_arn,
                    "Message": json.dumps(envelope),
                    "MessageAttributes": {"eventType": {"Type": "String", "Value": event_type}},
                }),
            }
        ]
    }


def configure(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PLATFORM_DOMAIN_EVENTS_TOPIC_ARN", TOPIC_ARN)
    monkeypatch.setenv("PLATFORM_DOMAIN_EVENTS_QUEUE_ARN", QUEUE_ARN)


@pytest.mark.asyncio
async def test_valid_sns_sqs_record_dispatches_once_and_closes_engine(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configure(monkeypatch)
    engine = Mock(dispose=AsyncMock())
    build = Mock(return_value=engine)
    dispatch = AsyncMock()
    monkeypatch.setattr(domain_events, "build_engine", build)
    monkeypatch.setattr(domain_events, "async_sessionmaker", Mock(return_value=Mock()))
    monkeypatch.setattr(domain_events, "dispatch_event", dispatch)

    assert await domain_events.run(sqs_event()) == {"batchItemFailures": []}
    build.assert_called_once()
    assert build.call_args.args[0].database_pool_size == 1
    dispatch.assert_awaited_once()
    engine.dispose.assert_awaited_once()


@pytest.mark.asyncio
async def test_wrong_topic_or_unsupported_event_never_opens_database(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configure(monkeypatch)
    build = Mock()
    monkeypatch.setattr(domain_events, "build_engine", build)
    wrong = sqs_event(topic_arn="arn:aws:sns:ap-south-1:123456789012:other.fifo")
    unsupported = sqs_event("unknown.v1")

    assert await domain_events.run(wrong) == {
        "batchItemFailures": [{"itemIdentifier": "sqs-message-1"}]
    }
    assert await domain_events.run(unsupported) == {
        "batchItemFailures": [{"itemIdentifier": "sqs-message-1"}]
    }
    build.assert_not_called()


@pytest.mark.asyncio
async def test_dispatch_error_returns_partial_batch_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    configure(monkeypatch)
    engine = Mock(dispose=AsyncMock())
    monkeypatch.setattr(domain_events, "build_engine", Mock(return_value=engine))
    monkeypatch.setattr(domain_events, "async_sessionmaker", Mock(return_value=Mock()))
    monkeypatch.setattr(
        domain_events, "dispatch_event", AsyncMock(side_effect=RuntimeError("database unavailable"))
    )

    assert await domain_events.run(sqs_event()) == {
        "batchItemFailures": [{"itemIdentifier": "sqs-message-1"}]
    }
    engine.dispose.assert_awaited_once()


def test_sns_attribute_mismatch_is_rejected() -> None:
    record = sqs_event()["Records"][0]
    wrapper = json.loads(record["body"])
    wrapper["MessageAttributes"]["eventType"]["Value"] = "other.v1"
    record["body"] = json.dumps(wrapper)
    with pytest.raises(ValueError, match="attribute"):
        domain_events.parse_sns_sqs_record(record, topic_arn=TOPIC_ARN, queue_arn=QUEUE_ARN)


def test_one_shot_registry_covers_every_legacy_kafka_consumer_topic() -> None:
    from northstar_api.workers import (
        analytics_consumer,
        channel_event_consumer,
        crm_router_consumer,
        crm_webhook_consumer,
        notification_consumer,
        object_cleaner,
        zoho_flow_lead_delivery,
    )

    legacy_topics = (
        set(analytics_consumer.TOPICS)
        | set(channel_event_consumer.TOPICS)
        | set(crm_router_consumer.TOPICS)
        | set(crm_webhook_consumer.TOPICS)
        | set(notification_consumer.TOPICS)
        | {object_cleaner.TOPIC}
        | set(zoho_flow_lead_delivery.TOPICS)
    )
    assert domain_events.ROUTED_TYPES == legacy_topics


def test_terraform_subscription_filter_matches_dispatch_registry() -> None:
    terraform = (
        Path(__file__).resolve().parents[2]
        / "infrastructure/terraform/modules/scale_to_zero_outbox/main.tf"
    ).read_text(encoding="utf-8")
    match = re.search(r"domain_event_types\s*=\s*\[(.*?)\]", terraform, re.DOTALL)
    assert match is not None
    assert set(re.findall(r'"([a-z][a-z0-9_.]+\.v1)"', match.group(1))) == domain_events.ROUTED_TYPES
    assert re.search(
        r"filter_policy\s*=\s*jsonencode\(\{ eventType = local\.domain_event_types \}\)",
        terraform,
    )


def test_planned_manifest_uses_one_shot_event_handler() -> None:
    manifest = (Path(__file__).resolve().parents[2] / "platform.yaml").read_text(encoding="utf-8")
    event_process = re.search(r"(?m)^  - name: events\n(.*?)(?=^  - name:|\Z)", manifest, re.DOTALL)
    assert event_process is not None
    assert "runtime: lambda" in event_process.group(1)
    assert "handler: northstar_api.handlers.domain_events:lambda_handler" in event_process.group(1)
    assert "timeout_s: 900" in event_process.group(1)
    assert "deployment_status: planned" in manifest


@pytest.mark.asyncio
async def test_notification_projection_uses_existing_consumer_inbox(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    record = sqs_event("lead.crm.delivery.failed.v1")["Records"][0]
    envelope = domain_events.parse_sns_sqs_record(record, topic_arn=TOPIC_ARN, queue_arn=QUEUE_ARN)
    session = Mock()
    session.scalar = AsyncMock(return_value=envelope.event_id)
    session.commit = AsyncMock()
    context = AsyncMock()
    context.__aenter__.return_value = session
    factory = Mock(return_value=context)
    tenant = AsyncMock()
    project = AsyncMock()
    monkeypatch.setattr(domain_events, "set_tenant_context", tenant)
    monkeypatch.setattr(domain_events, "project_notification_event", project)

    await domain_events.dispatch_event(factory, envelope)
    tenant.assert_awaited_once_with(session, envelope.tenant_id)
    project.assert_awaited_once()
    session.commit.assert_awaited_once()

    session.scalar.return_value = None
    project.reset_mock()
    await domain_events.dispatch_event(factory, envelope)
    project.assert_not_awaited()
    assert session.commit.await_count == 2


@pytest.mark.asyncio
async def test_lead_created_fans_out_to_notification_and_zoho_flow(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    record = sqs_event("lead.created.v1")["Records"][0]
    envelope = domain_events.parse_sns_sqs_record(record, topic_arn=TOPIC_ARN, queue_arn=QUEUE_ARN)
    session = Mock(scalar=AsyncMock(return_value=envelope.event_id), commit=AsyncMock())
    context = AsyncMock()
    context.__aenter__.return_value = session
    factory = Mock(return_value=context)
    monkeypatch.setattr(domain_events, "set_tenant_context", AsyncMock())
    notify = AsyncMock()
    zoho = AsyncMock()
    monkeypatch.setattr(domain_events, "project_notification_event", notify)
    monkeypatch.setattr(domain_events, "_deliver_zoho_flow_event", zoho)

    await domain_events.dispatch_event(factory, envelope)
    notify.assert_awaited_once()
    zoho.assert_awaited_once_with(factory, envelope)
    session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_zoho_http_failure_leaves_event_unprocessed_for_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from northstar_api.workers import zoho_flow_lead_delivery as zoho

    envelope = domain_events.parse_sns_sqs_record(
        sqs_event("lead.updated.v1")["Records"][0], topic_arn=TOPIC_ARN, queue_arn=QUEUE_ARN
    )
    settings = Mock(zoho_flow_lead_workspace_id=uuid4(), zoho_flow_webhook_timeout_seconds=5)
    settings.zoho_flow_lead_webhook_url.get_secret_value.return_value = "https://example.invalid/hook"
    monkeypatch.setattr(domain_events, "get_settings", Mock(return_value=settings))
    monkeypatch.setattr(zoho, "_lead_id", Mock(return_value=uuid4()))
    monkeypatch.setattr(zoho, "_was_processed", AsyncMock(return_value=False))
    monkeypatch.setattr(zoho, "_lead_payload", AsyncMock(return_value={"lead_id": "123"}))
    marked = AsyncMock()
    monkeypatch.setattr(zoho, "_mark_processed", marked)
    response = Mock(raise_for_status=Mock(side_effect=RuntimeError("remote failure")))
    client = Mock(post=AsyncMock(return_value=response))
    context = AsyncMock()
    context.__aenter__.return_value = client
    monkeypatch.setattr(domain_events.httpx, "AsyncClient", Mock(return_value=context))

    with pytest.raises(RuntimeError, match="remote failure"):
        await domain_events._deliver_zoho_flow_event(Mock(), envelope)
    marked.assert_not_awaited()
    assert client.post.await_args.kwargs["headers"] == {"Idempotency-Key": str(envelope.event_id)}
