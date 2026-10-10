"""Private, opt-in worker HTTP facade must never bypass machine/audit guards."""
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from northstar_api.modules.platform_runtime.deployment_leases import DeploymentClaim
from northstar_api.modules.platform_runtime.deployment_step_journal import DeploymentStepClaim
from northstar_api.modules.platform_runtime.deployment_worker_audit import DeploymentAuditBlocked
from northstar_api.modules.platform_runtime.deployment_worker_http import (
    create_deployment_worker_app,
)
from northstar_api.modules.platform_runtime.deployment_worker_operations import (
    DeploymentWorkerOperations,
    DeploymentWorkerPolicy,
)

KEY = Ed25519PrivateKey.generate()
PUBLIC_KEY = KEY.public_key().public_bytes(
    encoding=serialization.Encoding.PEM,
    format=serialization.PublicFormat.SubjectPublicKeyInfo,
)
SUBJECT = "role/worker-qualification"
ENV = "qualification"
PATH = "/internal/deployment"


def access_token(*, subject=SUBJECT, scope=None, environment=ENV):
    now = datetime.now(UTC)
    if scope is None:
        scope = " ".join((
            "northstar.deploy.claim",
            "northstar.deploy.renew",
            "northstar.deploy.step.begin",
            "northstar.deploy.step.verify",
            "northstar.deploy.step.unknown",
            "northstar.deploy.close",
        ))
    return jwt.encode({
        "iss": "northstar-private-issuer",
        "aud": "northstar-private-worker",
        "sub": subject,
        "iat": int((now - timedelta(seconds=2)).timestamp()),
        "nbf": int((now - timedelta(seconds=2)).timestamp()),
        "exp": int((now + timedelta(seconds=100)).timestamp()),
        "jti": uuid4().hex,
        "environment": environment,
        "scope": scope,
    }, KEY, algorithm="EdDSA")


def bound(*, enabled):
    change_id, lease_token = uuid4(), uuid4()
    claim = DeploymentClaim(
        change_id, lease_token, SUBJECT,
        datetime.now(UTC) + timedelta(seconds=80), ENV,
    )
    leases = SimpleNamespace(
        claim=AsyncMock(return_value=claim),
        renew=AsyncMock(return_value=True),
        close=AsyncMock(return_value=True),
    )
    journal = SimpleNamespace(
        begin_step=AsyncMock(return_value=DeploymentStepClaim(
            change_id, 0, "validate_dependencies", lease_token,
        )),
        verify_step=AsyncMock(return_value=True),
        mark_unknown=AsyncMock(return_value=True),
    )
    audit = SimpleNamespace(
        begin=AsyncMock(return_value=SimpleNamespace(attempt_id=uuid4())),
        finish=AsyncMock(),
    )
    operations = DeploymentWorkerOperations(
        policy=DeploymentWorkerPolicy(
            PUBLIC_KEY, "northstar-private-issuer",
            "northstar-private-worker", ENV, SUBJECT,
        ),
        leases=leases, journal=journal, audit=audit,
    )
    app = create_deployment_worker_app(operations, private_ingress_enabled=enabled)
    return app, claim, leases, journal, audit


def serialized_claim(claim):
    return {
        "change_id": str(claim.change_id),
        "lease_token": str(claim.lease_token),
        "owner": claim.owner,
        "expires_at": claim.expires_at.isoformat(),
        "environment": claim.environment,
    }


def client(app):
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://private-worker.local",
    )


@pytest.mark.asyncio
async def test_http_contract_is_off_by_default_even_with_valid_machine_token():
    app, claim, leases, _, audit = bound(enabled=False)
    async with client(app) as http:
        response = await http.post(
            PATH + "/claims", json={"change_id": str(claim.change_id)},
            headers={"Authorization": "Bearer " + access_token()},
        )
        assert response.status_code == 503
        assert (await http.get("/openapi.json")).status_code == 404
        assert (await http.get("/docs")).status_code == 404
    leases.claim.assert_not_awaited()
    audit.begin.assert_not_awaited()


@pytest.mark.asyncio
async def test_missing_wrong_and_unscoped_auth_never_reaches_worker_database():
    app, claim, leases, _, audit = bound(enabled=True)
    async with client(app) as http:
        request = {"change_id": str(claim.change_id)}
        requests = (
            {},
            {"Authorization": "Basic something"},
            {"Authorization": "Bearer untrusted"},
            {"Authorization": "Bearer " + access_token(environment="production")},
            {"Authorization": "Bearer " + access_token(subject="role/attacker")},
            {"Authorization": "Bearer " + access_token(scope="northstar.deploy.close")},
        )
        for headers in requests:
            response = await http.post(PATH + "/claims", json=request, headers=headers)
            assert response.status_code in (401, 403), response.text
    leases.claim.assert_not_awaited()
    audit.begin.assert_not_awaited()


@pytest.mark.asyncio
async def test_signed_machine_can_use_all_bounded_operations():
    app, claim, leases, journal, audit = bound(enabled=True)
    headers = {"Authorization": "Bearer " + access_token()}
    body = {"claim": serialized_claim(claim)}
    async with client(app) as http:
        created = await http.post(PATH + "/claims", headers=headers,
                                  json={"change_id": str(claim.change_id)})
        assert created.status_code == 200
        assert created.json()["claim"]["lease_token"] == str(claim.lease_token)
        renewed = await http.post(PATH + "/leases/renew", json=body, headers=headers)
        assert renewed.json() == {"accepted": True}
        begin = await http.post(
            PATH + "/steps/begin", headers=headers, json={**body, "index": 0},
        )
        assert begin.json()["step_name"] == "validate_dependencies"
        verified = await http.post(PATH + "/steps/verify", headers=headers, json={
            **body, "index": 0, "signed_attestation": "independent-proof-123",
        })
        assert verified.json() == {"verified": True}
        unknown = await http.post(PATH + "/steps/unknown", headers=headers, json={
            **body, "index": 0, "reason": "external provider acknowledgement missing",
        })
        assert unknown.json() == {"requires_reconciliation": True}
        closed = await http.post(PATH + "/leases/close", json=body, headers=headers)
        assert closed.json() == {"closed": True}
    assert leases.claim.await_count == 1
    assert journal.begin_step.await_count == 1
    assert audit.begin.await_count == 6
    assert audit.finish.await_count == 6


@pytest.mark.asyncio
async def test_unexpected_database_errors_are_sanitized():
    app, claim, leases, _, audit = bound(enabled=True)
    leases.claim.side_effect = RuntimeError("secret-database-connection-info")
    async with client(app) as http:
        response = await http.post(PATH + "/claims",
            headers={"Authorization": "Bearer " + access_token()},
            json={"change_id": str(claim.change_id)})
    assert response.status_code == 503
    assert "secret-database-connection-info" not in response.text
    assert audit.finish.await_args.kwargs["outcome"] == "unknown"


@pytest.mark.asyncio
async def test_unresolved_audit_intent_returns_conflict_and_prevents_mutation():
    app, claim, leases, _, audit = bound(enabled=True)
    audit.begin.side_effect = DeploymentAuditBlocked("confidential reconciliation details")
    async with client(app) as http:
        response = await http.post(PATH + "/claims",
            headers={"Authorization": "Bearer " + access_token()},
            json={"change_id": str(claim.change_id)})
    assert response.status_code == 409
    assert "confidential" not in response.text
    leases.claim.assert_not_awaited()


@pytest.mark.asyncio
async def test_invalid_extra_fields_are_rejected_before_leases():
    app, claim, leases, _, audit = bound(enabled=True)
    async with client(app) as http:
        response = await http.post(PATH + "/leases/renew",
            headers={"Authorization": "Bearer " + access_token()},
            json={"claim": {**serialized_claim(claim), "untrusted": True}})
    assert response.status_code == 422
    leases.renew.assert_not_awaited()
    audit.begin.assert_not_awaited()


@pytest.mark.asyncio
async def test_claims_reject_legacy_unscoped_environment():
    app, claim, leases, _, audit = bound(enabled=True)
    raw = serialized_claim(claim)
    del raw["environment"]
    async with client(app) as http:
        response = await http.post(PATH + "/leases/close",
            headers={"Authorization": "Bearer " + access_token()},
            json={"claim": raw})
    assert response.status_code == 422
    leases.close.assert_not_awaited()
    audit.begin.assert_not_awaited()
