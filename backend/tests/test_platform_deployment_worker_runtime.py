"""Worker runtime boots only through an explicitly authorized Unix socket."""
from pathlib import Path
from unittest.mock import AsyncMock, Mock

import httpx
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.asymmetric.rsa import generate_private_key

from northstar_api.modules.platform_runtime import deployment_worker_runtime as runtime


def env(**updates):
    configured = {
        "NORTHSTAR_DEPLOYMENT_WORKER_ENABLED": "true",
        "NORTHSTAR_DEPLOYMENT_WORKER_SOCKET": "/private/northstar.sock",
        "NORTHSTAR_DEPLOYMENT_WORKER_ENVIRONMENT": "qualification",
        "NORTHSTAR_DEPLOYMENT_WORKER_ISSUER": "northstar-issuer",
        "NORTHSTAR_DEPLOYMENT_WORKER_AUDIENCE": "northstar-worker",
        "NORTHSTAR_DEPLOYMENT_WORKER_SUBJECT": "role/deployment",
        "NORTHSTAR_DEPLOYMENT_WORKER_MACHINE_KEY_FILE": "/private/machine.pem",
        "NORTHSTAR_DEPLOYMENT_WORKER_STEP_KEY_FILE": "/private/step.pem",
    }
    configured.update(updates)
    return configured


def signer_public_pem():
    return Ed25519PrivateKey.generate().public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    )


def private_dir(tmp_path, monkeypatch):
    path = tmp_path / "only-worker"
    path.mkdir(mode=0o700)
    owner = path.stat().st_uid
    if owner == 0:
        pytest.skip("private worker socket tests require a non-root test runner")
    monkeypatch.setattr(runtime.os, "geteuid", lambda: owner)
    monkeypatch.setenv(
        "NORTHSTAR_DEPLOYMENT_WORKER_DATABASE_URL",
        "postgresql+asyncpg://northstar_deployer:ci-worker-secret@localhost/northstar",
    )
    monkeypatch.setenv("NORTHSTAR_DEPLOYMENT_WORKER_DATABASE_ROLE", "northstar_deployer")
    return path


def write_key(directory, name, content):
    file = directory / name
    file.write_bytes(content)
    file.chmod(0o600)
    return file


def configured_settings(directory, **changes):
    source = env(
        NORTHSTAR_DEPLOYMENT_WORKER_SOCKET=str(directory / "worker.sock"),
        NORTHSTAR_DEPLOYMENT_WORKER_MACHINE_KEY_FILE=str(directory / "machine.pem"),
        NORTHSTAR_DEPLOYMENT_WORKER_STEP_KEY_FILE=str(directory / "step.pem"),
    )
    source.update(changes)
    return runtime.DeploymentWorkerRuntimeSettings.from_environment(source)


def test_worker_is_disabled_by_default():
    with pytest.raises(runtime.WorkerRuntimeConfigurationError, match="disabled"):
        runtime.DeploymentWorkerRuntimeSettings.from_environment({})
    with pytest.raises(runtime.WorkerRuntimeConfigurationError, match="disabled"):
        runtime.DeploymentWorkerRuntimeSettings.from_environment(env(
            NORTHSTAR_DEPLOYMENT_WORKER_ENABLED="false",
        ))


def test_all_worker_configuration_is_required():
    for key in env():
        values = env()
        del values[key]
        with pytest.raises(runtime.WorkerRuntimeConfigurationError):
            runtime.DeploymentWorkerRuntimeSettings.from_environment(values)


def test_only_0700_owned_directory_can_host_worker_socket(tmp_path, monkeypatch):
    directory = private_dir(tmp_path, monkeypatch)
    socket = directory / "worker.sock"
    runtime.ensure_private_socket_path(socket)
    directory.chmod(0o750)
    with pytest.raises(runtime.WorkerRuntimeConfigurationError, match="not private"):
        runtime.ensure_private_socket_path(socket)
    directory.chmod(0o700)
    socket.touch()
    with pytest.raises(runtime.WorkerRuntimeConfigurationError, match="already exists"):
        runtime.ensure_private_socket_path(socket)


def test_missing_directory_relative_socket_and_symlink_rejected(tmp_path, monkeypatch):
    directory = private_dir(tmp_path, monkeypatch)
    with pytest.raises(runtime.WorkerRuntimeConfigurationError, match="absolute"):
        runtime.ensure_private_socket_path(Path("worker.sock"))
    with pytest.raises(runtime.WorkerRuntimeConfigurationError, match="pre-provisioned"):
        runtime.ensure_private_socket_path(directory / "missing" / "worker.sock")
    target = directory / "worker.sock"
    target.symlink_to(directory / "nonexistent-target")
    with pytest.raises(runtime.WorkerRuntimeConfigurationError, match="already exists"):
        runtime.ensure_private_socket_path(target)


def test_worker_never_runs_as_root(tmp_path, monkeypatch):
    directory = private_dir(tmp_path, monkeypatch)
    monkeypatch.setattr(runtime.os, "geteuid", lambda: 0)
    with pytest.raises(runtime.WorkerRuntimeConfigurationError, match="unprivileged"):
        runtime.ensure_private_socket_path(directory / "worker.sock")


def test_pinned_keys_must_be_ed25519_and_not_writable_or_symlinked(tmp_path):
    key = write_key(tmp_path, "valid.pem", signer_public_pem())
    assert runtime.read_pinned_ed25519_public_key(key) == key.read_bytes()
    key.chmod(0o666)
    with pytest.raises(runtime.WorkerRuntimeConfigurationError, match="unsafe"):
        runtime.read_pinned_ed25519_public_key(key)
    key.chmod(0o600)
    alias = tmp_path / "alias.pem"
    alias.symlink_to(key)
    with pytest.raises(runtime.WorkerRuntimeConfigurationError, match="invalid"):
        runtime.read_pinned_ed25519_public_key(alias)
    rsa = generate_private_key(public_exponent=65537, key_size=2048)
    key.write_bytes(rsa.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    ))
    with pytest.raises(runtime.WorkerRuntimeConfigurationError, match="Ed25519"):
        runtime.read_pinned_ed25519_public_key(key)


@pytest.mark.asyncio
async def test_private_app_constructs_without_public_customer_routes(tmp_path, monkeypatch):
    directory = private_dir(tmp_path, monkeypatch)
    write_key(directory, "machine.pem", signer_public_pem())
    write_key(directory, "step.pem", signer_public_pem())
    settings = configured_settings(directory)
    verified = AsyncMock()
    monkeypatch.setattr(runtime, "verify_worker_database_identity", verified)
    app = runtime.build_private_worker_app(settings)
    async with app.router.lifespan_context(app):
        verified.assert_awaited_once()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://worker.internal"
    ) as http:
        assert (await http.post("/internal/deployment/claims", json={
            "change_id": "fd4fd9d9-67d4-48e2-aab8-114514565619",
        })).status_code == 401
        assert (await http.get("/v1/health")).status_code == 404
        assert (await http.get("/docs")).status_code == 404


def test_different_independent_verifier_keys_are_mandatory(tmp_path, monkeypatch):
    directory = private_dir(tmp_path, monkeypatch)
    public = signer_public_pem()
    write_key(directory, "machine.pem", public)
    write_key(directory, "step.pem", public)
    with pytest.raises(runtime.WorkerRuntimeConfigurationError, match="distinct keys"):
        runtime.build_private_worker_app(configured_settings(directory))


def test_production_runtime_refuses_sqlite(tmp_path, monkeypatch):
    directory = private_dir(tmp_path, monkeypatch)
    write_key(directory, "machine.pem", signer_public_pem())
    write_key(directory, "step.pem", signer_public_pem())
    monkeypatch.setenv("NORTHSTAR_DEPLOYMENT_WORKER_DATABASE_URL", "sqlite+aiosqlite:///unsafe.db")
    with pytest.raises(runtime.WorkerDatabaseSecurityError, match="PostgreSQL|worker"):
        runtime.build_private_worker_app(configured_settings(directory))


def test_launch_uses_only_unix_socket_and_restores_umask(monkeypatch):
    settings = runtime.DeploymentWorkerRuntimeSettings.from_environment(env())
    monkeypatch.setattr(runtime.DeploymentWorkerRuntimeSettings, "from_environment",
                        lambda: settings)
    monkeypatch.setattr(runtime, "build_private_worker_app", lambda _: "ASGI-APP")
    monkeypatch.setattr(runtime, "ensure_private_socket_path", lambda _: None)
    called = Mock()
    monkeypatch.setattr(runtime.uvicorn, "run", called)
    original_umask = runtime.os.umask
    masks = []

    def fake_umask(mask):
        masks.append(mask)
        return 0o022

    monkeypatch.setattr(runtime.os, "umask", fake_umask)
    try:
        runtime.run()
        called.assert_called_once()
        args, kwargs = called.call_args
        assert args == ("ASGI-APP",)
        assert kwargs["uds"] == "/private/northstar.sock"
        assert "host" not in kwargs and "port" not in kwargs
        assert kwargs["workers"] == 1
        assert kwargs["reload"] is False
        assert kwargs["proxy_headers"] is False
        assert masks == [0o177, 0o022]
    finally:
        monkeypatch.setattr(runtime.os, "umask", original_umask)


@pytest.mark.asyncio
async def test_worker_startup_rejects_unqualified_database_role(tmp_path, monkeypatch):
    directory = private_dir(tmp_path, monkeypatch)
    write_key(directory, "machine.pem", signer_public_pem())
    write_key(directory, "step.pem", signer_public_pem())
    verified = AsyncMock(side_effect=runtime.WorkerDatabaseSecurityError(
        "unqualified role: high privilege",
    ))
    monkeypatch.setattr(runtime, "verify_worker_database_identity", verified)
    app = runtime.build_private_worker_app(configured_settings(directory))
    with pytest.raises(runtime.WorkerDatabaseSecurityError, match="unqualified role"):
        async with app.router.lifespan_context(app):
            pytest.fail("worker served requests despite unqualified database")
    verified.assert_awaited_once()
