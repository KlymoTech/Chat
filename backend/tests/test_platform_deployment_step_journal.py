"""Fenced journal tests: no out-of-order, duplicate, forged or unknown progress."""
import base64
import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from northstar_api.modules.platform_runtime.contracts import PlatformSpec
from northstar_api.modules.platform_runtime.control_plane import build_change_plan
from northstar_api.modules.platform_runtime.deployment_leases import DeploymentClaim
from northstar_api.modules.platform_runtime.deployment_step_journal import DeploymentStepJournal
from northstar_api.modules.platform_runtime.deployment_step_persistence import PlatformDeploymentStep
from northstar_api.modules.platform_runtime.persistence import PlatformChangeRecord


class FakeSession:
    def __init__(self, lease, change):
        self.lease, self.change = lease, change
        self.steps = {}
        self.scalar = AsyncMock(return_value=lease)
        self.add = MagicMock(side_effect=self._add)

    def _add(self, obj):
        self.steps[obj.change_id, obj.step_index] = obj

    def begin(self):
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_value, traceback):
        return False

    async def get(self, model, key):
        if model is PlatformChangeRecord:
            return self.change
        if model is PlatformDeploymentStep:
            return self.steps.get(key)
        raise AssertionError("Unexpected ORM model")


def fixture():
    current = PlatformSpec()
    desired = PlatformSpec(metadata={"revision": 2}, features={"analytics": False})
    plan = build_change_plan(current, desired)
    change_id, token = uuid4(), uuid4()
    change = SimpleNamespace(
        id=change_id, status="approved", requested_by=uuid4(), approved_by=uuid4(),
        environment=current.metadata.environment,
        source_revision=plan.source_revision, target_revision=plan.target_revision,
        source_digest=plan.source_digest, target_digest=plan.target_digest,
        action=plan.action, classification=plan.classification, plan_steps=list(plan.steps),
        current_spec_json=current.model_dump(mode="json"),
        desired_spec_json=desired.model_dump(mode="json"),
    )
    lease = SimpleNamespace(
        status="leased", owner="trusted-worker", lease_token=token,
        environment=change.environment, source_digest=plan.source_digest,
        target_digest=plan.target_digest,
        lease_expires_at=datetime.now(UTC) + timedelta(minutes=5),
    )
    claim = DeploymentClaim(change_id, token, lease.owner, lease.lease_expires_at)
    session = FakeSession(lease, change)
    return DeploymentStepJournal(lambda: session), session, claim


def signed_attestation(session, claim, step, private):
    now = datetime.now(UTC)
    payload = {
        "change_id": str(claim.change_id),
        "lease_token": str(claim.lease_token),
        "environment": session.change.environment,
        "step_index": step.step_index,
        "step_name": step.step_name,
        "source_digest": session.change.source_digest,
        "target_digest": session.change.target_digest,
        "evidence_digest": "b" * 64,
        "verifier_run_id": "independent-run-123",
        "issued_at": int((now - timedelta(seconds=5)).timestamp()),
        "expires_at": int((now + timedelta(minutes=2)).timestamp()),
    }
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()

    def encode(value):
        return base64.urlsafe_b64encode(value).decode().rstrip("=")

    public = private.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    return encode(raw) + "." + encode(private.sign(raw)), public


@pytest.mark.asyncio
async def test_order_and_duplicate_execution_are_blocked():
    journal, session, claim = fixture()
    assert await journal.begin_step(claim, 1) is None
    first = await journal.begin_step(claim, 0)
    assert first is not None
    assert first.step_name == session.change.plan_steps[0]
    assert await journal.begin_step(claim, 0) is None
    assert await journal.begin_step(claim, 1) is None


@pytest.mark.asyncio
async def test_independent_signature_unlocks_only_next_step():
    journal, session, claim = fixture()
    step = await journal.begin_step(claim, 0)
    private = Ed25519PrivateKey.generate()
    token, public = signed_attestation(session, claim, step, private)
    assert not await journal.verify_step(claim, 0, signed_attestation=token, verifier_public_key_pem=b"invalid")
    assert await journal.verify_step(claim, 0, signed_attestation=token, verifier_public_key_pem=public)
    assert session.steps[claim.change_id, 0].status == "verified"
    assert session.steps[claim.change_id, 0].evidence_digest == "b" * 64
    assert await journal.begin_step(claim, 1) is not None
    assert not await journal.verify_step(claim, 0, signed_attestation=token, verifier_public_key_pem=public)


@pytest.mark.asyncio
async def test_unknown_effect_freezes_execution():
    journal, session, claim = fixture()
    assert await journal.begin_step(claim, 0) is not None
    assert await journal.mark_unknown(claim, 0, reason="unknown provider timeout")
    assert session.steps[claim.change_id, 0].status == "unknown"
    assert await journal.begin_step(claim, 0) is None
    assert await journal.begin_step(claim, 1) is None
    assert not await journal.mark_unknown(claim, 0, reason="second attempt")


@pytest.mark.asyncio
async def test_stale_or_unauthorized_lease_never_advances_journal():
    journal, session, claim = fixture()
    session.lease.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
    assert await journal.begin_step(claim, 0) is None
    session.lease.lease_expires_at = datetime.now(UTC) + timedelta(minutes=5)
    wrong = DeploymentClaim(claim.change_id, uuid4(), claim.owner, claim.expires_at)
    assert await journal.begin_step(wrong, 0) is None
    session.change.approved_by = session.change.requested_by
    assert await journal.begin_step(claim, 0) is None
    session.add.assert_not_called()


@pytest.mark.asyncio
async def test_changed_approved_steps_are_not_executable():
    journal, session, claim = fixture()
    session.change.plan_steps = ["skip_health_checks"]
    assert await journal.begin_step(claim, 0) is None


@pytest.mark.asyncio
async def test_unknown_reason_requires_useful_detail():
    journal, _, claim = fixture()
    with pytest.raises(ValueError, match="reconciliation reason"):
        await journal.mark_unknown(claim, 0, reason="no")
