"""Read-only AWS Secrets Manager adapter for approved notification secret IDs.

IAM comes from the workload credential chain; this module never handles AWS
access keys or accepts a caller-provided region/endpoint. An explicit allowlist
prevents a catalog mistake from fetching an unrelated secret.
"""
from __future__ import annotations

import asyncio
import re
from typing import Any

import boto3

_SECRET_ARN = re.compile(
    r"^arn:aws[a-z-]*:secretsmanager:[a-z0-9-]+:\d{12}:secret:[A-Za-z0-9/_+=.@-]+$"
)


class AwsNotificationSecretStore:
    def __init__(
        self,
        *,
        region: str,
        approved_secret_ids: frozenset[str],
        client: Any = None,
        timeout_seconds: float = 4.0,
    ) -> None:
        if not region or not re.fullmatch(r"[a-z]{2}(?:-gov)?-[a-z]+-\d+", region):
            raise ValueError("invalid AWS region")
        if timeout_seconds <= 0 or timeout_seconds > 20:
            raise ValueError("invalid AWS secret timeout")
        if not approved_secret_ids or any(
            not _SECRET_ARN.fullmatch(secret_id)
            or secret_id.split(":")[3] != region
            for secret_id in approved_secret_ids
        ):
            raise ValueError("invalid approved secret allowlist")
        self._approved = approved_secret_ids
        self._timeout = timeout_seconds
        self._client = client if client is not None else boto3.client(
            "secretsmanager", region_name=region
        )

    async def retrieve(self, secret_id: str) -> bytes | None:
        if secret_id not in self._approved:
            return None
        try:
            response = await asyncio.wait_for(
                asyncio.to_thread(
                    self._client.get_secret_value,
                    SecretId=secret_id,
                    VersionStage="AWSCURRENT",
                ),
                timeout=self._timeout,
            )
            if response.get("VersionStages") and "AWSCURRENT" not in response["VersionStages"]:
                return None
            secret = response.get("SecretBinary")
            if secret is None and isinstance(response.get("SecretString"), str):
                secret = response["SecretString"].encode("utf-8")
            if not isinstance(secret, bytes) or len(secret) < 32:
                return None
            return secret
        except Exception:
            # IAM, network and rotation errors are not returned to callers.
            return None
