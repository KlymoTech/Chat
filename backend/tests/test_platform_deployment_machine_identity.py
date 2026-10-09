"""Worker-only authorization rejects forged user, scope and environment tokens."""
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from northstar_api.modules.platform_runtime.deployment_machine_identity import (
    MachineAuthenticationError,
    authenticate_deployment_worker,
)

ISSUER = "northstar-qualification-issuer"
AUDIENCE = "northstar-platform-worker"
SUBJECT = "role/deployment-executor"
ENVIRONMENT = "qualification"

SIGNER = Ed25519PrivateKey.generate()
PUBLIC = SIGNER.public_key().public_bytes(
    serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
)


def signed(**overrides):
    now = datetime.now(UTC)
    claims = {
        "iss": ISSUER,
        "aud": AUDIENCE,
        "sub": SUBJECT,
        "iat": int((now - timedelta(seconds=5)).timestamp()),
        "nbf": int((now - timedelta(seconds=5)).timestamp()),
        "exp": int((now + timedelta(minutes=2)).timestamp()),
        "jti": uuid4().hex,
        "environment": ENVIRONMENT,
        "scope": "northstar.deploy.claim northstar.deploy.renew northstar.deploy.step.verify",
    }
    claims.update(overrides)
    return jwt.encode(claims, SIGNER, algorithm="EdDSA")


def check(token, **kwargs):
    options = {
        "public_key_pem": PUBLIC,
        "issuer": ISSUER,
        "audience": AUDIENCE,
        "environment": ENVIRONMENT,
        "allowed_subject": SUBJECT,
        "action": "claim",
    }
    options.update(kwargs)
    return authenticate_deployment_worker(token, **options)


def test_pinned_machine_identity_is_scoped_to_subject_and_environment():
    principal = check(signed())
    assert principal.subject == SUBJECT
    assert principal.environment == ENVIRONMENT
    assert "northstar.deploy.claim" in principal.scopes


@pytest.mark.parametrize("claims", [
    {"iss": "untrusted"},
    {"aud": "another-service"},
    {"sub": "role/compromised"},
    {"environment": "production"},
    {"scope": "northstar.deploy.step.verify"},
    {"scope": ""},
    {"jti": "short"},
    {"exp": 1},
    {"iat": int((datetime.now(UTC) + timedelta(hours=1)).timestamp())},
    {"nbf": int((datetime.now(UTC) + timedelta(hours=1)).timestamp())},
    {"exp": int((datetime.now(UTC) + timedelta(hours=2)).timestamp())},
])
def test_untrusted_or_broad_credentials_fail_closed(claims):
    with pytest.raises(MachineAuthenticationError):
        check(signed(**claims))


def test_other_signer_cannot_issue_worker_authorization():
    outsider = Ed25519PrivateKey.generate()
    token = jwt.encode(
        jwt.decode(signed(), PUBLIC, algorithms=["EdDSA"], audience=AUDIENCE, issuer=ISSUER),
        outsider, algorithm="EdDSA",
    )
    with pytest.raises(MachineAuthenticationError):
        check(token)


@pytest.mark.parametrize("token", ["", "not-a-jwt", "bad.header.payload", "x" * 8193])
def test_invalid_machine_tokens_rejected(token):
    with pytest.raises(MachineAuthenticationError):
        check(token)


def test_unconfigured_trust_anchor_rejected():
    with pytest.raises(MachineAuthenticationError):
        check(signed(), public_key_pem=b"")


def test_worker_must_have_specific_action_scope():
    with pytest.raises(MachineAuthenticationError):
        check(signed(), action="mark_unknown")
    assert check(signed(), action="verify").subject == SUBJECT


def test_jwt_none_algorithm_rejected_even_with_valid_claims():
    payload = jwt.decode(signed(), PUBLIC, algorithms=["EdDSA"], audience=AUDIENCE, issuer=ISSUER)
    token = jwt.encode(payload, key="", algorithm="none")
    with pytest.raises(MachineAuthenticationError):
        check(token)
