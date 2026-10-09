"""Fail-closed machine identity verification for Northstar deployment workers.

A worker token is *not* a user session or a deployment approval. Tokens must
be signed by a separately controlled Ed25519 key, scoped to one environment,
short-lived and bound to one permitted machine subject. Production callers
must additionally use private networking, least-privilege roles, and the
transactional deployment lease / signed step evidence boundaries.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

WorkerAction = Literal["claim", "renew", "begin", "verify", "mark_unknown", "close"]

_WORKER_SUBJECT = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._:/-]{2,159}$")
_ACTION_SCOPE = {
    "claim": "northstar.deploy.claim",
    "renew": "northstar.deploy.renew",
    "begin": "northstar.deploy.step.begin",
    "verify": "northstar.deploy.step.verify",
    "mark_unknown": "northstar.deploy.step.unknown",
    "close": "northstar.deploy.close",
}


@dataclass(frozen=True)
class DeploymentMachinePrincipal:
    subject: str
    environment: str
    token_id: str
    scopes: frozenset[str]


class MachineAuthenticationError(ValueError):
    """Invalid or insufficiently scoped deployment-machine credentials."""


def authenticate_deployment_worker(
    token: str,
    *,
    public_key_pem: bytes,
    issuer: str,
    audience: str,
    environment: str,
    allowed_subject: str,
    action: WorkerAction,
    now: datetime | None = None,
) -> DeploymentMachinePrincipal:
    """Verify a pinned asymmetric JWT; never accept client-provided trust keys."""
    instant = now or datetime.now(UTC)
    if (
        instant.tzinfo is None
        or not token or len(token) > 8192
        or not public_key_pem or not issuer or not audience
        or not environment or not allowed_subject
        or action not in _ACTION_SCOPE
    ):
        raise MachineAuthenticationError("deployment machine authentication unavailable")
    try:
        public_key = serialization.load_pem_public_key(public_key_pem)
        if not isinstance(public_key, Ed25519PublicKey):
            raise MachineAuthenticationError("deployment machine key invalid")
        claims = jwt.decode(
            token,
            public_key,
            algorithms=["EdDSA"],
            audience=audience,
            issuer=issuer,
            options={"require": [
                "iss", "aud", "sub", "iat", "nbf", "exp", "jti", "environment", "scope",
            ]},
            leeway=0,
        )
        subject = claims["sub"]
        token_id = claims["jti"]
        scopes_raw = claims["scope"]
        issued = claims["iat"]
        not_before = claims["nbf"]
        expires = claims["exp"]
        if (
            not isinstance(subject, str)
            or not _WORKER_SUBJECT.fullmatch(subject)
            or subject != allowed_subject
            or not isinstance(token_id, str) or len(token_id) < 16 or len(token_id) > 128
            or not isinstance(scopes_raw, str)
            or not isinstance(issued, int) or isinstance(issued, bool)
            or not isinstance(not_before, int) or isinstance(not_before, bool)
            or not isinstance(expires, int) or isinstance(expires, bool)
            or issued > int(instant.timestamp())
            or not_before > issued
            or expires <= issued
            or expires - issued > 300
            or claims["environment"] != environment
        ):
            raise MachineAuthenticationError("invalid deployment machine claims")
        scopes = frozenset(scopes_raw.split())
        if _ACTION_SCOPE[action] not in scopes:
            raise MachineAuthenticationError("deployment machine capability denied")
        return DeploymentMachinePrincipal(
            subject=subject, environment=environment, token_id=token_id, scopes=scopes,
        )
    except (jwt.PyJWTError, ValueError, TypeError, KeyError) as exc:
        raise MachineAuthenticationError("deployment machine authentication denied") from exc
