"""External deployment worker must refuse stale or forged dispatch envelopes."""
from uuid import uuid4

from northstar_api.modules.platform_runtime.contracts import PlatformSpec
from northstar_api.modules.platform_runtime.control_plane import build_change_plan
from northstar_api.modules.platform_runtime.dispatch_event_integrity import validate_dispatch_event
from northstar_api.modules.platform_runtime.executor_contract import DeploymentDispatchEvent


def approved_event():
    source = PlatformSpec()
    target = PlatformSpec(metadata={"revision": 2}, features={"analytics": False})
    plan = build_change_plan(source, target)
    change_id = uuid4()
    event = DeploymentDispatchEvent(
        changeId=change_id,
        environment=source.metadata.environment,
        action=plan.action,
        classification=plan.classification,
        destructive=False,
        sourceRevision=plan.source_revision,
        targetRevision=plan.target_revision,
        sourceDigest=plan.source_digest,
        targetDigest=plan.target_digest,
        idempotencyKey="change-key-123",
        reason="reviewed and approved",
        planSteps=tuple(plan.steps),
        currentSpec=source.model_dump(mode="json"),
        desiredSpec=target.model_dump(mode="json"),
    )
    return event


def evaluate(event, **overrides):
    values = dict(
        approved=True,
        approved_change_id=str(event.change_id),
        approved_idempotency_key=event.idempotency_key,
    )
    values.update(overrides)
    return validate_dispatch_event(event, **values)


def test_exact_approved_dispatch_passes():
    assert evaluate(approved_event()) == ()


def test_unapproved_message_rejected():
    assert "change_not_approved" in evaluate(approved_event(), approved=False)


def test_wrong_change_and_idempotency_rejected():
    event = approved_event()
    blocked = evaluate(event, approved_change_id=str(uuid4()), approved_idempotency_key="other-key")
    assert "approved_change_id_mismatch" in blocked
    assert "idempotency_key_mismatch" in blocked


def test_mutated_target_digest_rejected():
    event = approved_event().model_copy(update={"target_digest": "a" * 64})
    assert "persisted_digest_mismatch" in evaluate(event)


def test_cross_environment_event_rejected():
    event = approved_event().model_copy(update={"environment": "another-environment"})
    assert "persisted_environment_mismatch" in evaluate(event)


def test_destructive_hot_apply_rejected():
    event = approved_event().model_copy(update={"action": "hot_apply", "destructive": True})
    assert "destructive_hot_apply_rejected" in evaluate(event)
