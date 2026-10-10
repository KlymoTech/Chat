"""Fail-closed signing key access for independent Jenkins test and release roles."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.asymmetric.rsa import generate_private_key

from northstar_api.modules.platform_runtime.aws_protected_qualification_signer import (
    AwsProtectedQualificationEd25519Signer,
)

ACCOUNT = "123456789012"
REGION = "us-east-1"
BRANCH = "feature/northstar-adaptive-architecture-20261008"
RUN = "jenkins-build-123"
PREFIX = "northstarqa"


def private_bytes(key):
    return key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )


def pub_pem(key):
    return key.public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )


def setup(*, purpose="test", region=REGION):
    key = Ed25519PrivateKey.generate()
    sts = MagicMock()
    secrets = MagicMock()
    role = (
        f"{PREFIX}-test-certification-signer"
        if purpose == "test"
        else f"{PREFIX}-release-manifest-signer"
    )
    session_prefix = "northstar-test-jenkins-" if purpose == "test" else "northstar-release-jenkins-"
    session = session_prefix + RUN
    part = "aws-us-gov" if region.startswith("us-gov-") else "aws"
    secret = f"arn:{part}:secretsmanager:{region}:{ACCOUNT}:secret:northstar-{purpose}-Signer123"
    sts.get_caller_identity.return_value = {
        "Arn": f"arn:{part}:sts::{ACCOUNT}:assumed-role/{role}/{session}",
        "UserId": "AROAEXAMPLE123:" + session,
        "Account": ACCOUNT,
    }
    secrets.get_secret_value.return_value = {
        "ARN": secret,
        "VersionStages": ["AWSCURRENT"],
        "SecretBinary": private_bytes(key),
    }
    args = dict(
        purpose=purpose,
        account_id=ACCOUNT,
        region=region,
        role_name=role,
        secret_arn=secret,
        trusted_public_key_pem=pub_pem(key),
        allowed_branch=BRANCH,
        sts_client=sts,
        secrets_client=secrets,
    )
    return key, sts, secrets, args


@pytest.mark.asyncio
@pytest.mark.parametrize("purpose", ["test", "release"])
async def test_only_correct_aws_role_and_public_key_returns_signing_key(purpose):
    original, sts, secrets, args = setup(purpose=purpose)
    gate = AwsProtectedQualificationEd25519Signer(**args)
    result = await gate.retrieve_for_isolated_service(run_id=RUN, branch=BRANCH)
    assert result is not None
    signature = result.sign(b"trusted local test payload")
    original.public_key().verify(signature, b"trusted local test payload")
    sts.get_caller_identity.assert_called_once_with()
    secrets.get_secret_value.assert_called_once_with(
        SecretId=args["secret_arn"], VersionStage="AWSCURRENT"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("kind,bad", [
    ("Account", "999999999999"),
    ("Arn", "arn:aws:sts::123456789012:assumed-role/untrusted/northstar-test-jenkins-jenkins-build-123"),
    ("UserId", "AROAEXAMPLE123:other-run"),
])
async def test_wrong_aws_identity_never_reads_secret(kind, bad):
    _, sts, secrets, args = setup()
    sts.get_caller_identity.return_value[kind] = bad
    gate = AwsProtectedQualificationEd25519Signer(**args)
    assert await gate.retrieve_for_isolated_service(run_id=RUN, branch=BRANCH) is None
    secrets.get_secret_value.assert_not_called()


@pytest.mark.asyncio
async def test_wrong_branch_and_run_never_contact_aws():
    _, sts, secrets, args = setup()
    gate = AwsProtectedQualificationEd25519Signer(**args)
    assert await gate.retrieve_for_isolated_service(run_id=RUN, branch="main") is None
    assert await gate.retrieve_for_isolated_service(run_id="../fake", branch=BRANCH) is None
    sts.get_caller_identity.assert_not_called()
    secrets.get_secret_value.assert_not_called()


@pytest.mark.asyncio
async def test_aws_sts_max_session_length_is_checked():
    _, sts, secrets, args = setup(purpose="release")
    gate = AwsProtectedQualificationEd25519Signer(**args)
    assert await gate.retrieve_for_isolated_service(run_id="a" * 40, branch=BRANCH) is None
    sts.get_caller_identity.assert_not_called()
    secrets.get_secret_value.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("change", [
    {"VersionStages": ["AWSPREVIOUS"]},
    {"ARN": "arn:aws:secretsmanager:us-east-1:123456789012:secret:other"},
    {"SecretBinary": b"not a key"},
    {"SecretBinary": b"x" * 5000},
    {"SecretBinary": None, "SecretString": "unsafe"},
])
async def test_invalid_secrets_manager_response_never_exposes_private_key(change):
    _, _, secrets, args = setup()
    secrets.get_secret_value.return_value.update(change)
    gate = AwsProtectedQualificationEd25519Signer(**args)
    assert await gate.retrieve_for_isolated_service(run_id=RUN, branch=BRANCH) is None


@pytest.mark.asyncio
async def test_rotation_to_unpinned_ed25519_private_key_fails_closed():
    _, _, secrets, args = setup()
    secrets.get_secret_value.return_value["SecretBinary"] = private_bytes(Ed25519PrivateKey.generate())
    gate = AwsProtectedQualificationEd25519Signer(**args)
    assert await gate.retrieve_for_isolated_service(run_id=RUN, branch=BRANCH) is None


@pytest.mark.asyncio
async def test_non_ed25519_private_key_fails_closed():
    _, _, secrets, args = setup()
    rsa = generate_private_key(public_exponent=65537, key_size=2048)
    secrets.get_secret_value.return_value["SecretBinary"] = private_bytes(rsa)
    gate = AwsProtectedQualificationEd25519Signer(**args)
    assert await gate.retrieve_for_isolated_service(run_id=RUN, branch=BRANCH) is None


@pytest.mark.asyncio
async def test_aws_failure_does_not_raise_sensitive_exception():
    _, _, secrets, args = setup()
    secrets.get_secret_value.side_effect = RuntimeError("secret/private-key-must-not-escape")
    gate = AwsProtectedQualificationEd25519Signer(**args)
    assert await gate.retrieve_for_isolated_service(run_id=RUN, branch=BRANCH) is None


@pytest.mark.asyncio
async def test_sts_failure_does_not_read_secret():
    _, sts, secrets, args = setup()
    sts.get_caller_identity.side_effect = RuntimeError("STSError")
    gate = AwsProtectedQualificationEd25519Signer(**args)
    assert await gate.retrieve_for_isolated_service(run_id=RUN, branch=BRANCH) is None
    secrets.get_secret_value.assert_not_called()


@pytest.mark.asyncio
async def test_govcloud_arn_partition_validated():
    original, _, _, args = setup(region="us-gov-west-1")
    gate = AwsProtectedQualificationEd25519Signer(**args)
    result = await gate.retrieve_for_isolated_service(run_id=RUN, branch=BRANCH)
    assert result is not None
    original.public_key().verify(result.sign(b"govcloud"), b"govcloud")


@pytest.mark.parametrize("change", [
    {"purpose": "publisher"},
    {"role_name": "northstarqa-qualification-evidence-publisher"},
    {"account_id": "invalid"},
    {"region": "invalid"},
    {"secret_arn": "arn:aws:secretsmanager:us-west-2:123456789012:secret:wrong"},
    {"secret_arn": "arn:aws:secretsmanager:us-east-1:999999999999:secret:wrong"},
    {"allowed_branch": ""},
    {"timeout_seconds": 0},
    {"trusted_public_key_pem": b"wrong"},
    {"trusted_public_key_pem": generate_private_key(public_exponent=65537, key_size=2048).public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    )},
])
def test_invalid_configuration_rejected_before_sts_or_secret_access(change):
    _, sts, secrets, args = setup()
    with pytest.raises(ValueError):
        AwsProtectedQualificationEd25519Signer(**(args | change))
    sts.get_caller_identity.assert_not_called()
    secrets.get_secret_value.assert_not_called()
