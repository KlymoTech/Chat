"""Standalone, opt-in Northstar deployment worker runtime.

No public API registration, TCP listener, SSH, shell or cloud mutation command.
The only supported transport is a Unix-domain socket in an operator-provisioned
private (0700) directory, owned by the worker's non-root user.

Requires a dedicated PostgreSQL role, private workload isolation and trusted
public keys delivered through read-only files. These checks do not substitute
for external workload isolation, admission policy or release qualification.
"""
from __future__ import annotations

import os
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

import uvicorn
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from .deployment_worker_http import create_deployment_worker_app
from .deployment_worker_operations import (
    DeploymentWorkerOperations,
    DeploymentWorkerPolicy,
)


class WorkerRuntimeConfigurationError(RuntimeError):
    """Worker remains disabled if any runtime isolation prerequisite is absent."""


@dataclass(frozen=True)
class DeploymentWorkerRuntimeSettings:
    socket_path: Path
    environment: str
    issuer: str
    audience: str
    allowed_subject: str
    machine_key_path: Path
    step_key_path: Path

    @classmethod
    def from_environment(cls, environ: Mapping[str, str] | None = None):
        values = os.environ if environ is None else environ
        if values.get("NORTHSTAR_DEPLOYMENT_WORKER_ENABLED") != "true":
            raise WorkerRuntimeConfigurationError("deployment worker is disabled")
        required = (
            "NORTHSTAR_DEPLOYMENT_WORKER_SOCKET",
            "NORTHSTAR_DEPLOYMENT_WORKER_ENVIRONMENT",
            "NORTHSTAR_DEPLOYMENT_WORKER_ISSUER",
            "NORTHSTAR_DEPLOYMENT_WORKER_AUDIENCE",
            "NORTHSTAR_DEPLOYMENT_WORKER_SUBJECT",
            "NORTHSTAR_DEPLOYMENT_WORKER_MACHINE_KEY_FILE",
            "NORTHSTAR_DEPLOYMENT_WORKER_STEP_KEY_FILE",
        )
        if any(not values.get(name) or values[name].strip() != values[name] for name in required):
            raise WorkerRuntimeConfigurationError("required worker runtime configuration is missing")
        return cls(
            socket_path=Path(values[required[0]]),
            environment=values[required[1]],
            issuer=values[required[2]],
            audience=values[required[3]],
            allowed_subject=values[required[4]],
            machine_key_path=Path(values[required[5]]),
            step_key_path=Path(values[required[6]]),
        )


def ensure_private_socket_path(path: Path) -> None:
    """Forbid pre-existing sockets, symlinks and shared socket directories."""
    if os.name != "posix" or not hasattr(os, "geteuid") or os.geteuid() == 0:
        raise WorkerRuntimeConfigurationError("worker requires an unprivileged POSIX identity")
    if not path.is_absolute() or len(os.fsencode(path)) > 100 or path.name in {".", ".."}:
        raise WorkerRuntimeConfigurationError("worker socket must use a short absolute path")
    parent = path.parent
    try:
        info = parent.lstat()
    except OSError as exc:
        raise WorkerRuntimeConfigurationError("worker socket directory must be pre-provisioned") from exc
    if (
        not stat.S_ISDIR(info.st_mode)
        or info.st_uid != os.geteuid()
        or stat.S_IMODE(info.st_mode) & 0o077
        or parent.resolve(strict=True) != parent
    ):
        raise WorkerRuntimeConfigurationError("worker socket directory is not private")
    if path.is_symlink() or path.exists():
        raise WorkerRuntimeConfigurationError("worker socket already exists")


def read_pinned_ed25519_public_key(path: Path) -> bytes:
    """Read one local public trust anchor without following file symlinks."""
    if not path.is_absolute() or os.name != "posix":
        raise WorkerRuntimeConfigurationError("worker verification key path must be absolute")
    descriptor = None
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
        info = os.fstat(descriptor)
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid not in {0, os.geteuid()}
            or stat.S_IMODE(info.st_mode) & 0o022
            or info.st_size < 40 or info.st_size > 4096
        ):
            raise WorkerRuntimeConfigurationError("worker public key file is unsafe")
        with os.fdopen(descriptor, "rb") as stream:
            descriptor = None
            content = stream.read(4097)
        key = serialization.load_pem_public_key(content)
        if not isinstance(key, Ed25519PublicKey):
            raise WorkerRuntimeConfigurationError("worker trust anchor must be Ed25519")
        return content
    except (OSError, ValueError, TypeError) as exc:
        raise WorkerRuntimeConfigurationError("worker public trust anchor is invalid") from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)


def build_private_worker_app(settings: DeploymentWorkerRuntimeSettings):
    """Build dependencies without importing or mounting the public HTTP app."""
    ensure_private_socket_path(settings.socket_path)
    machine_public_key = read_pinned_ed25519_public_key(settings.machine_key_path)
    step_public_key = read_pinned_ed25519_public_key(settings.step_key_path)
    if machine_public_key == step_public_key:
        raise WorkerRuntimeConfigurationError(
            "machine issuer and independent step verifier must use distinct keys"
        )

    # Defer database import until opt-in, socket and trust configuration pass.
    from northstar_api.database import SessionFactory, engine

    if engine.dialect.name != "postgresql":
        raise WorkerRuntimeConfigurationError("deployment worker requires durable PostgreSQL")

    from .deployment_leases import DeploymentLeaseService
    from .deployment_step_journal import DeploymentStepJournal
    from .deployment_worker_audit import DeploymentWorkerAuditTrail

    operations = DeploymentWorkerOperations(
        policy=DeploymentWorkerPolicy(
            public_key_pem=machine_public_key,
            issuer=settings.issuer,
            audience=settings.audience,
            environment=settings.environment,
            allowed_subject=settings.allowed_subject,
        ),
        leases=DeploymentLeaseService(SessionFactory),
        journal=DeploymentStepJournal(
            SessionFactory, verifier_public_key_pem=step_public_key,
        ),
        audit=DeploymentWorkerAuditTrail(SessionFactory),
    )
    return create_deployment_worker_app(operations, private_ingress_enabled=True)


def run() -> None:
    """Entry point; UDS-only, single process, restrictive umask, no TCP binding."""
    settings = DeploymentWorkerRuntimeSettings.from_environment()
    app = build_private_worker_app(settings)
    # The permission mask remains restrictive while uvicorn creates the socket.
    previous_umask = os.umask(0o177)
    try:
        ensure_private_socket_path(settings.socket_path)
        uvicorn.run(
            app,
            uds=str(settings.socket_path),
            workers=1,
            reload=False,
            proxy_headers=False,
            access_log=False,
            server_header=False,
            date_header=False,
            limit_concurrency=20,
            timeout_keep_alive=5,
        )
    finally:
        os.umask(previous_umask)


if __name__ == "__main__":
    run()
