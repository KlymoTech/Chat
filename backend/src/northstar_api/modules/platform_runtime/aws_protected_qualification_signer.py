"""Isolated AWS Ed25519 signing-key gate for protected Jenkins roles.

The adapter never stores or emits a private key in logs, Git, Terraform or
responses. It only supplies a verified key to an *isolated internal* signer
service. It does NOT certify a test, permit an untrusted payload to be signed,
issue qualification proofs, or authorize production workers. Production
callers must separately validate immutable test provenance / release evidence.
"""
from __future__ import annotations

import asyncio
import re
from typing import Any, Literal

import boto3
from botocore.config import Config
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

_ACCOUNT = re.compile(r"[0-9]{12}\Z")
_REGION = re.compile(r"[a-z]{2}(?:-gov)?-[a-z]+-[0-9]+\Z")
_ROLE = re.compile(r"[A-Za-z0-9][A-Za-z0-9+=,.@_-]{1,63}\Z")
_RUN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{7,39}\Z")
_SECRET = re.compile(
    r"arn:(aws|aws-us-gov):secretsmanager:([a-z0-9-]+):([0-9]{12}):"
    r"secret:[A-Za-z0-9/_+=.@-]+\Z"
)
_PURPOSES = {
    "test": ("-test-certification-signer", "northstar-test-jenkins-"),
    "release": ("-release-manifest-signer", "northstar-release-jenkins-"),
}


class AwsProtectedQualificationEd25519Signer:
    """Fetch pinned private key only for the correct isolated assumed role.

    Production deployments MUST protect IAM AssumeRole trust and Secrets
    Manager/KMS policies separately. A session name identifies the requested
    run only; it does not authenticate the Jenkins job or its test outcomes.
    """

    def __init__(
        self,
        *,
        purpose: Literal["test", "release"],
        region: str,
        account_id: str,
        role_name: str,
        secret_arn: str,
        trusted_public_key_pem: bytes,
        allowed_branch: str,
        sts_client: Any = None,
        secrets_client: Any = None,
        timeout_seconds: float = 4.0,
    ) -> None:
        match = _SECRET.fullmatch(secret_arn) if isinstance(secret_arn, str) else None
        role_suffix, session_prefix = _PURPOSES.get(purpose, ("", ""))
        partition = "aws-us-gov" if isinstance(region, str) and region.startswith("us-gov-") else "aws"
        if (
            not role_suffix
            or not isinstance(account_id, str)
            or _ACCOUNT.fullmatch(account_id) is None
            or not isinstance(region, str)
            or _REGION.fullmatch(region) is None
            or not isinstance(role_name, str)
            or _ROLE.fullmatch(role_name) is None
            or not role_name.endswith(role_suffix)
            or match is None
            or match.group(1) != partition
            or match.group(2) != region
            or match.group(3) != account_id
            or not isinstance(allowed_branch, str)
            or not 1 <= len(allowed_branch) <= 200
            or not isinstance(trusted_public_key_pem, bytes)
            or not 0 < timeout_seconds <= 15
        ):
            raise ValueError("invalid protected signing identity configuration")
        try:
            public = serialization.load_pem_public_key(trusted_public_key_pem)
        except (ValueError, TypeError) as exc:
            raise ValueError("invalid pinned Ed25519 public key") from exc
        if not isinstance(public, Ed25519PublicKey):
            raise ValueError("pinned key must be Ed25519")
        self._trusted_public_raw = public.public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw
        )
        self._account = account_id
        self._role_arn_prefix = f"arn:{partition}:sts::{account_id}:assumed-role/{role_name}/"
        self._session_prefix = session_prefix
        self._secret_arn = secret_arn
        self._branch = allowed_branch
        self._timeout = timeout_seconds
        network = Config(connect_timeout=2, read_timeout=2, retries={"max_attempts": 1})
        self._sts = sts_client if sts_client is not None else boto3.client(
            "sts", region_name=region, config=network
        )
        self._secrets = secrets_client if secrets_client is not None else boto3.client(
            "secretsmanager", region_name=region, config=network
        )

    async def retrieve_for_isolated_service(
        self, *, run_id: str, branch: str
    ) -> Ed25519PrivateKey | None:
        """Return a transient key object only when both IAM and pin checks pass.

        Do not expose this method via HTTP or route raw caller content to it.
        A protected service must independently authenticate the Jenkins build
        and verify provenance before it uses the key to sign anything.
        """
        if (
            not isinstance(run_id, str)
            or _RUN.fullmatch(run_id) is None
            or not isinstance(branch, str)
            or branch != self._branch
        ):
            return None
        session = self._session_prefix + run_id
        if len(session) > 64:  # AWS STS RoleSessionName maximum
            return None
        try:
            caller = await asyncio.wait_for(
                asyncio.to_thread(self._sts.get_caller_identity), timeout=self._timeout
            )
            if (
                not isinstance(caller, dict)
                or caller.get("Account") != self._account
                or caller.get("Arn") != self._role_arn_prefix + session
                or not isinstance(caller.get("UserId"), str)
                or caller["UserId"].partition(":")[2] != session
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
                or not isinstance(response.get("VersionStages"), (list, tuple))
                or "AWSCURRENT" not in response["VersionStages"]
            ):
                return None
            raw = response.get("SecretBinary")
            if not isinstance(raw, bytes) or not 48 <= len(raw) <= 4096:
                return None
            key = serialization.load_pem_private_key(raw, password=None)
            if not isinstance(key, Ed25519PrivateKey):
                return None
            actual_public = key.public_key().public_bytes(
                serialization.Encoding.Raw, serialization.PublicFormat.Raw
            )
            if actual_public != self._trusted_public_raw:
                return None
            return key
        except Exception:
            # Avoid surfacing IAM, KMS, secret or key material in errors/logs.
            return None
