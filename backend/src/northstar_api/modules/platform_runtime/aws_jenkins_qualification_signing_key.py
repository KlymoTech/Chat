"""AWS-bound signing key for a separately controlled Jenkins certification role.

Uses the workload credential chain, not long-lived keys or Jenkins parameters.
A successful lookup does NOT certify a build or authorize an evidence record;
the independently verified test/provenance gates remain mandatory.
"""
from __future__ import annotations

import asyncio
import re
from typing import Any

import boto3
from botocore.config import Config

_ACCOUNT = re.compile(r"\d{12}\Z")
_REGION = re.compile(r"[a-z]{2}(?:-gov)?-[a-z]+-\d+\Z")
_ROLE = re.compile(r"[A-Za-z0-9][A-Za-z0-9+=,.@_-]{1,63}\Z")
_SESSION = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{7,39}\Z")
_SECRET_ARN = re.compile(
    r"arn:(aws|aws-us-gov):secretsmanager:([a-z0-9-]+):(\d{12}):secret:[A-Za-z0-9/_+=.@-]+\Z"
)


class AwsJenkinsQualificationSigningKey:
    """Require the pinned AWS role *and* build session before reading a key.

    Both STS and Secrets Manager calls use the same IAM workload credentials.
    IAM trust policies must separately restrict who can assume this issuer role.
    """

    def __init__(
        self,
        *,
        region: str,
        account_id: str,
        role_name: str,
        secret_arn: str,
        sts_client: Any = None,
        secrets_client: Any = None,
        timeout_seconds: float = 4.0,
    ) -> None:
        match = _SECRET_ARN.fullmatch(secret_arn)
        if (
            not _REGION.fullmatch(region)
            or not _ACCOUNT.fullmatch(account_id)
            or not _ROLE.fullmatch(role_name)
            or match is None
            or match.group(2) != region
            or match.group(3) != account_id
            or not 0 < timeout_seconds <= 15
        ):
            raise ValueError("invalid pinned qualification signing-key configuration")
        partition = match.group(1)
        self._role_prefix = f"arn:{partition}:sts::{account_id}:assumed-role/{role_name}/"
        self._account_id = account_id
        self._secret_arn = secret_arn
        self._timeout = timeout_seconds
        network = Config(connect_timeout=2, read_timeout=2, retries={"max_attempts": 1})
        self._sts = sts_client if sts_client is not None else boto3.client(
            "sts", region_name=region, config=network
        )
        self._secrets = secrets_client if secrets_client is not None else boto3.client(
            "secretsmanager", region_name=region, config=network
        )

    async def retrieve(self, *, run_id: str) -> bytes | None:
        """Return key material only to an authorized server-side issuer process.

        The Jenkins role must assume a session named ``northstar-qual-{run_id}``.
        User-facing identifiers or caller-provided role claims are never trusted.
        """
        if not isinstance(run_id, str) or not _SESSION.fullmatch(run_id):
            return None
        session_name = f"northstar-qual-{run_id}"
        try:
            caller = await asyncio.wait_for(
                asyncio.to_thread(self._sts.get_caller_identity), timeout=self._timeout
            )
            if (
                not isinstance(caller, dict)
                or caller.get("Account") != self._account_id
                or caller.get("Arn") != self._role_prefix + session_name
                or not isinstance(caller.get("UserId"), str)
                or caller["UserId"].partition(":")[2] != session_name
            ):
                return None
            response = await asyncio.wait_for(
                asyncio.to_thread(
                    self._secrets.get_secret_value,
                    SecretId=self._secret_arn,
                    VersionStage="AWSCURRENT",
                ),
                timeout=self._timeout,
            )
            if (
                not isinstance(response, dict)
                or response.get("ARN") != self._secret_arn
                or "AWSCURRENT" not in response.get("VersionStages", [])
            ):
                return None
            key = response.get("SecretBinary")
            if not isinstance(key, bytes) or not 32 <= len(key) <= 256:
                return None
            return key
        except Exception:
            # Never reveal secret values, ARN details or IAM/network failures.
            return None
