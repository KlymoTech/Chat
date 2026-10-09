"""Pinned Jenkins IAM identity is mandatory before reading protected keys."""
from unittest.mock import MagicMock

import pytest

from northstar_api.modules.platform_runtime.aws_jenkins_qualification_signing_key import (
    AwsJenkinsQualificationSigningKey,
)

ACCOUNT = "123456789012"
REGION = "us-east-1"
ROLE = "northstar-qualification-issuer"
SECRET = (
    "arn:aws:secretsmanager:us-east-1:123456789012:"
    "secret:northstar/qualification/signing-ABC123"
)
RUN = "jenkins-build-123"
SESSION = f"northstar-qual-{RUN}"
IDENTITY = {
    "Account": ACCOUNT,
    "Arn": f"arn:aws:sts::{ACCOUNT}:assumed-role/{ROLE}/{SESSION}",
    "UserId": f"AROEXAMPLE123456789:{SESSION}",
}
RESPONSE = {"ARN": SECRET, "VersionStages": ["AWSCURRENT"], "SecretBinary": b"x" * 32}


def adapter(identity=None, secret=None):
    sts = MagicMock()
    sts.get_caller_identity.return_value = IDENTITY if identity is None else identity
    secrets = MagicMock()
    secrets.get_secret_value.return_value = RESPONSE if secret is None else secret
    store = AwsJenkinsQualificationSigningKey(
        region=REGION, account_id=ACCOUNT, role_name=ROLE,
        secret_arn=SECRET, sts_client=sts, secrets_client=secrets,
    )
    return store, sts, secrets


@pytest.mark.asyncio
async def test_exact_sts_role_and_run_session_can_read_current_secret():
    store, sts, secrets = adapter()
    assert await store.retrieve(run_id=RUN) == b"x" * 32
    sts.get_caller_identity.assert_called_once_with()
    secrets.get_secret_value.assert_called_once_with(
        SecretId=SECRET, VersionStage="AWSCURRENT"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("changed", [
    {"Account": "000000000000"},
    {"Arn": IDENTITY["Arn"].replace(ROLE, "untrusted-role")},
    {"Arn": IDENTITY["Arn"].replace(SESSION, "other-build")},
    {"UserId": "AROEXAMPLE123456789:another-session"},
])
async def test_incorrect_iam_identity_denied_before_secret_fetch(changed):
    store, _sts, secrets = adapter(identity={**IDENTITY, **changed})
    assert await store.retrieve(run_id=RUN) is None
    secrets.get_secret_value.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("secret", [
    {**RESPONSE, "ARN": SECRET.replace("ABC123", "OTHER0")},
    {**RESPONSE, "VersionStages": ["AWSPREVIOUS"]},
    {**RESPONSE, "SecretBinary": b"short"},
    {**RESPONSE, "SecretBinary": "not binary"},
    {**RESPONSE, "SecretBinary": b"x" * 257},
])
async def test_noncurrent_foreign_or_invalid_secret_fails_closed(secret):
    store, _, _ = adapter(secret=secret)
    assert await store.retrieve(run_id=RUN) is None


@pytest.mark.asyncio
async def test_untrusted_run_id_never_calls_aws():
    store, sts, secrets = adapter()
    assert await store.retrieve(run_id="../../other") is None
    assert await store.retrieve(run_id=None) is None
    sts.get_caller_identity.assert_not_called()
    secrets.get_secret_value.assert_not_called()


@pytest.mark.asyncio
async def test_aws_failure_fails_closed():
    store, sts, secrets = adapter()
    sts.get_caller_identity.side_effect = RuntimeError("private IAM error")
    assert await store.retrieve(run_id=RUN) is None
    secrets.get_secret_value.assert_not_called()


@pytest.mark.parametrize("changes", [
    {"account_id": "123"}, {"region": "localhost"}, {"role_name": "../bad"},
    {"secret_arn": SECRET.replace(ACCOUNT, "000000000000")},
    {"timeout_seconds": 0},
])
def test_rejects_unpinned_configuration(changes):
    params = dict(
        region=REGION, account_id=ACCOUNT, role_name=ROLE,
        secret_arn=SECRET, sts_client=MagicMock(), secrets_client=MagicMock(),
    )
    params.update(changes)
    with pytest.raises(ValueError):
        AwsJenkinsQualificationSigningKey(**params)
