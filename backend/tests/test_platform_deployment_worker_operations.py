"""Machine credentials cannot bypass lease ownership or per-action boundaries."""
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from northstar_api.modules.platform_runtime.deployment_leases import DeploymentClaim
from northstar_api.modules.platform_runtime.deployment_machine_identity import MachineAuthenticationError
from northstar_api.modules.platform_runtime.deployment_worker_operations import (
    DeploymentWorkerOperations,
    DeploymentWorkerPolicy,
)

KEY = Ed25519PrivateKey.generate()
PUBLIC = KEY.public_key().public_bytes(
    serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
)
SUBJECT = "role/northstar-deployment"
ENVIRONMENT = "qualification"
SCOPES = " ".join((
    "northstar.deploy.claim",
    "northstar.deploy.renew",
    "northstar.deploy.step.begin",
    "northstar.deploy.step.verify",
    "northstar.deploy.step.unknown",
    "northstar.deploy.close",
))


def credential(*, scope=SCOPES, environment=ENVIRONMENT, subject=SUBJECT):
    now = datetime.now(UTC)
    return jwt.encode({
        "iss": "northstar-issuer",
        "aud": "northstar-worker",
        "sub": subject,
        "iat": int((now - timedelta(seconds=2)).timestamp()),
        "nbf": int((now - timedelta(seconds=2)).timestamp()),
        "exp": int((now + timedelta(seconds=100)).timestamp()),
        "jti": uuid4().hex,
        "environment": environment,
        "scope": scope,
    }, KEY, algorithm="EdDSA")


def bound():
    change_id = uuid4()
    claim = DeploymentClaim(
        change_id, uuid4(), SUBJECT, datetime.now(UTC) + timedelta(minutes=2), ENVIRONMENT
    )
    leases = SimpleNamespace(
        claim=AsyncMock(return_value=claim),
        renew=AsyncMock(return_value=True),
        close=AsyncMock(return_value=True),
    )
    journal = SimpleNamespace(
        begin_step=AsyncMock(return_value="step"),
        verify_step=AsyncMock(return_value=True),
        mark_unknown=AsyncMock(return_value=True),
    )
    operations = DeploymentWorkerOperations(
        policy=DeploymentWorkerPolicy(
            PUBLIC, "northstar-issuer", "northstar-worker", ENVIRONMENT, SUBJECT
        ),
        leases=leases, journal=journal,
    )
    return operations, leases, journal, claim


@pytest.mark.asyncio
async def test_machine_credentials_are_required_for_every_action():
    operations, leases, journal, claim = bound()
    token = credential()
    assert await operations.claim(token, claim.change_id) == claim
    leases.claim.assert_awaited_once_with(
        claim.change_id, owner=SUBJECT, expected_environment=ENVIRONMENT,
    )
    assert await operations.renew(token, claim)
    leases.renew.assert_awaited_once_with(claim, expected_environment=ENVIRONMENT)
    assert await operations.begin_step(token, claim, 0) == "step"
    assert await operations.verify_step(token, claim, 0, signed_attestation="signed")
    assert await operations.mark_unknown(token, claim, 0, reason="ambiguous AWS call")
    assert await operations.close(token, claim)
    leases.close.assert_awaited_once_with(claim, expected_environment=ENVIRONMENT)
    journal.verify_step.assert_awaited_once_with(claim, 0, signed_attestation="signed")


@pytest.mark.asyncio
async def test_wrong_environment_and_actor_are_rejected_before_database_access():
    operations, leases, journal, claim = bound()
    for token in (
        credential(environment="production"),
        credential(subject="role/other"),
        "",
    ):
        with pytest.raises(MachineAuthenticationError):
            await operations.claim(token, claim.change_id)
    leases.claim.assert_not_awaited()
    journal.begin_step.assert_not_awaited()


@pytest.mark.asyncio
async def test_missing_action_scope_does_not_advance_steps():
    operations, _, journal, claim = bound()
    limited_token = credential(scope="northstar.deploy.claim")
    with pytest.raises(MachineAuthenticationError):
        await operations.begin_step(limited_token, claim, 0)
    with pytest.raises(MachineAuthenticationError):
        await operations.verify_step(limited_token, claim, 0, signed_attestation="signed")
    journal.begin_step.assert_not_awaited()
    journal.verify_step.assert_not_awaited()


@pytest.mark.asyncio
async def test_unscoped_legacy_claim_not_accepted_by_authenticated_facade():
    operations, leases, journal, claim = bound()
    legacy = DeploymentClaim(
        claim.change_id, claim.lease_token, claim.owner, claim.expires_at
    )
    with pytest.raises(MachineAuthenticationError):
        await operations.renew(credential(), legacy)
    with pytest.raises(MachineAuthenticationError):
        await operations.close(credential(), legacy)
    leases.renew.assert_not_awaited()
    leases.close.assert_not_awaited()
    journal.begin_step.assert_not_awaited()


@pytest.mark.asyncio
async def test_stolen_lease_token_with_wrong_owner_rejected():
    operations, leases, _, claim = bound()
    forged = DeploymentClaim(
        claim.change_id, claim.lease_token, "role/untrusted",
        claim.expires_at, claim.environment,
    )
    with pytest.raises(MachineAuthenticationError):
        await operations.close(credential(), forged)
    leases.close.assert_not_awaited()


def test_unconfigured_worker_policy_is_invalid():
    with pytest.raises(ValueError, match="fully configured"):
        DeploymentWorkerPolicy(b"", "issuer", "audience", "qualification", SUBJECT)
