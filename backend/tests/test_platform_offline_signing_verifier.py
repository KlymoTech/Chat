"""Regression checks for the credential-free signing qualification CLI."""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/verify_offline_signing.py"


@pytest.fixture
def verifier():
    spec = importlib.util.spec_from_file_location("offline_signing_verifier", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_offline_mode_does_not_silently_qualify_postgres(monkeypatch, verifier):
    calls = []
    monkeypatch.setattr(verifier, "_execute", lambda args: calls.append(args) or 0)
    assert verifier.main([]) == 0
    assert len(calls) == 2
    assert calls[0][:2] == ["ruff", "check"]
    assert calls[1][:2] == ["pytest", "-q"]
    assert "tests/test_platform_authorized_signing_integration.py" in calls[1]
    assert "tests/test_platform_runtime_contracts.py" in calls[1]
    assert "src/northstar_api/modules/platform_runtime/validation.py" in calls[0]
    assert not any(
        "tests/test_platform_postgres_signing_authorization_replay.py" in args
        for args in calls[1:]
    )


def test_failed_lint_blocks_unverified_test_claim(monkeypatch, verifier):
    calls = []
    monkeypatch.setattr(verifier, "_execute", lambda args: calls.append(args) or 3)
    assert verifier.main([]) == 3
    assert len(calls) == 1


@pytest.mark.parametrize(
    "dsn",
    ["", "postgresql://test@production.example/db", "postgresql://test@10.0.1.1/db"],
)
def test_disposable_postgres_option_rejects_missing_or_remote_db(monkeypatch, verifier, dsn):
    monkeypatch.setenv("PLATFORM_TEST_POSTGRES_DSN", dsn)
    monkeypatch.setattr(
        verifier, "_execute", lambda _: pytest.fail("rejected DSN must not execute checks"),
    )
    with pytest.raises(SystemExit) as rejection:
        verifier.main(["--postgres"])
    assert rejection.value.code == 2


def test_disposable_local_postgres_mode_runs_database_tests(monkeypatch, verifier):
    monkeypatch.setenv(
        "PLATFORM_TEST_POSTGRES_DSN", "postgresql://test:ci@127.0.0.1:5432/northstar_ci",
    )
    calls = []
    monkeypatch.setattr(verifier, "_execute", lambda args: calls.append(args) or 0)
    assert verifier.main(["--postgres"]) == 0
    assert len(calls) == 3
    assert calls[2][:3] == ["pytest", "-q", "-rs"]
    assert "tests/test_platform_postgres_custody_signing_claims.py" in calls[2]
    assert "tests/test_platform_postgres_signing_authorization_replay.py" in calls[2]
