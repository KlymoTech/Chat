"""Safety tests for the governed dispatch boundary."""
import base64
import hashlib
import hmac
import json
from datetime import UTC, datetime, timedelta

from northstar_api.modules.platform_runtime.contracts import PlatformSpec
from northstar_api.modules.platform_runtime.control_plane import spec_digest
from northstar_api.modules.platform_runtime.dispatch_preflight import preflight_governed_dispatch

KEY = b"northstar-isolated-qualification-signing-secret"
NOW = datetime(2026, 10, 8, tzinfo=UTC)


def specs():
    before = PlatformSpec()
    after = PlatformSpec(metadata={"revision": 2}, features={"analytics": False})
    return before, after


def signed_token(before, after, kind):
    payload = json.dumps({
        "kind": kind,
        "environment": after.metadata.environment,
        "source_digest": spec_digest(before),
        "target_digest": spec_digest(after),
        "run_id": "qualification-123",
        "issued_at": int((NOW - timedelta(minutes=1)).timestamp()),
        "expires_at": int((NOW + timedelta(minutes=10)).timestamp()),
    }, sort_keys=True).encode()
    signature = hmac.new(KEY, payload, hashlib.sha256).digest()
    def encode(value):
        return base64.urlsafe_b64encode(value).decode().rstrip("=")

    return encode(payload) + "." + encode(signature)


def run(before, after, **kwargs):
    overrides = {
        "tokens": tuple(signed_token(before, after, kind) for kind in (
            "health_snapshot", "rollback_configuration",
        )),
        "signing_key": KEY,
        "now": NOW,
        "requester_id": "requester",
        "approver_id": None,
        "active_incident": False,
        "backup_healthy": False,
        "within_maintenance_window": False,
        "budget_approved": True,
    }
    overrides.update(kwargs)
    return preflight_governed_dispatch(before, after, **overrides)


def test_valid_class_a_runtime_change_passes():
    before, after = specs()
    result = run(before, after)
    assert result.allowed
    assert result.classification.value == "A"


def test_unsigned_proofs_and_no_qualification_fail_closed():
    before, after = specs()
    assert not run(before, after, tokens=()).allowed
    assert not run(before, after, signing_key=b"short").allowed


def test_wrong_digest_proof_fails():
    before, after = specs()
    other = PlatformSpec(metadata={"revision": 3}, features={"analytics": False})
    result = run(before, after, tokens=(
        signed_token(before, other, "health_snapshot"),
        signed_token(before, other, "rollback_configuration"),
    ))
    assert not result.allowed


def test_incident_and_budget_block_even_valid_proofs():
    before, after = specs()
    assert "active_incident" in run(before, after, active_incident=True).blockers
    assert "budget_approval_missing" in run(before, after, budget_approved=False).blockers


def test_revision_rollback_cannot_dispatch():
    before, after = specs()
    result = run(after, before)
    assert "legacy_plan_rejected" in result.blockers


def test_noop_never_dispatches():
    before, _ = specs()
    assert "no_mutation_requested" in run(before, before).blockers


def test_stateful_migration_needs_backup_and_independent_approval():
    before, after = specs()
    after = after.model_copy(update={
        "providers": after.providers.model_copy(update={"search": "opensearch"}),
    })
    result = run(before, after)
    assert result.classification.value == "C"
    assert "healthy_backup_required" in result.blockers
    assert "independent_approval_required" in result.blockers
    assert "maintenance_window_required" in result.blockers


def test_cross_environment_proposal_is_never_dispatchable():
    before, after = specs()
    after = after.model_copy(update={
        "metadata": after.metadata.model_copy(update={"environment": "production"}),
    })
    result = run(before, after)
    assert not result.allowed
    assert "cross_environment_change_prohibited" in result.blockers
