"""Guard Workspace mail wiring without changing any existing worker's queues."""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _section(document: str, start: str, following: str) -> str:
    assert start in document, f"Missing Compose service {start.strip()}"
    body = document.split(start, 1)[1]
    assert following in body, f"Missing next Compose service {following.strip()}"
    return body.split(following, 1)[0]


def _queues(service: str) -> set[str]:
    match = re.search(r"--queues=([a-zA-Z0-9.,_-]+)", service)
    assert match is not None, "The Celery worker must explicitly declare its queues"
    values = match.group(1).split(",")
    assert len(values) == len(set(values)), "Worker queues must not be duplicated"
    return set(values)


def test_workspace_email_compose_wiring_keeps_existing_worker_queues() -> None:
    base = (ROOT / "compose.yaml").read_text(encoding="utf-8")
    override = (ROOT / "compose.override.yaml").read_text(encoding="utf-8")
    original_worker = _section(base, "\n  worker: &celery-worker\n", "\n  whatsapp-worker:")
    workspace_worker = _section(override, "\n  worker:\n", "\n  migrate:")
    assert _queues(workspace_worker) == _queues(original_worker) | {"workspace.email"}
    assert "--queues=whatsapp.inbound,whatsapp.outbound" in base
    assert "--queues=whatsapp.inbound,whatsapp.outbound" not in workspace_worker


def test_workspace_email_api_and_worker_receive_matching_secret_and_smtp_settings() -> None:
    override = (ROOT / "compose.override.yaml").read_text(encoding="utf-8")
    api = _section(override, "\n  api:\n", "\n  worker:")
    worker = _section(override, "\n  worker:\n", "\n  migrate:")
    for name in (
        "WORKSPACE_INVITATION_DELIVERY_KEY",
        "WORKSPACE_INVITATION_DELIVERY_PREVIOUS_KEYS",
        "EMAIL_DELIVERY_MODE",
        "EMAIL_FROM_ADDRESS",
        "EMAIL_FROM_NAME",
        "SMTP_HOST",
        "SMTP_PORT",
        "SMTP_USERNAME",
        "SMTP_PASSWORD",
        "SMTP_STARTTLS",
        "SMTP_SSL",
        "SMTP_TIMEOUT_SECONDS",
    ):
        assert f"{name}: ${{{name}:-" in api, name
        assert f"{name}: ${{{name}:-" in worker, name


def test_workspace_email_queue_is_registered_and_kubernetes_worker_is_unrestricted() -> None:
    celery = (ROOT / "backend/src/northstar_api/workers/celery_app.py").read_text(encoding="utf-8")
    kubernetes_worker = (ROOT / "kubernetes/base/worker.yaml").read_text(encoding="utf-8")
    assert '"workspace.email"' in celery
    assert '"northstar.send_workspace_invitation_email"' in celery
    assert "--queues=" not in kubernetes_worker
