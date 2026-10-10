"""Credential-free, cross-platform verifier for the Northstar signing boundary.

Run from anywhere: python backend/scripts/verify_offline_signing.py
Optional disposable PostgreSQL: --postgres plus PLATFORM_TEST_POSTGRES_DSN.
The --postgres mode rejects missing DSNs; it never silently skips database tests.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlsplit

BACKEND = Path(__file__).resolve().parents[1]

LINT_PATHS = (
    "src/northstar_api/modules/platform_runtime/queue_notification_authorized_signing.py",
    "src/northstar_api/modules/platform_runtime/queue_notification_custody_attestation_signer.py",
    "src/northstar_api/modules/platform_runtime/queue_notification_custody_signing_claims.py",
    "src/northstar_api/modules/platform_runtime/queue_notification_signing_authorization.py",
    "src/northstar_api/modules/platform_runtime/queue_notification_signing_authorization_replay.py",
    "src/northstar_api/modules/platform_runtime/queue_notification_jenkins_junit_custody.py",
    "src/northstar_api/modules/platform_runtime/queue_notification_jenkins_test_provenance.py",
)

OFFLINE_TESTS = (
    "tests/test_platform_authorized_signing.py",
    "tests/test_platform_authorized_signing_integration.py",
    "tests/test_platform_custody_attestation_signer.py",
    "tests/test_platform_custody_signing_claims.py",
    "tests/test_platform_custody_signing_claim_migration.py",
    "tests/test_platform_signing_authorization.py",
    "tests/test_platform_signing_authorization_replay.py",
    "tests/test_platform_signing_authorization_migration.py",
    "tests/test_platform_notification_junit_migration_merge.py",
    "tests/test_platform_jenkins_junit_custody.py",
    "tests/test_platform_jenkins_test_provenance.py",
)

POSTGRES_TESTS = (
    "tests/test_platform_postgres_custody_signing_claims.py",
    "tests/test_platform_postgres_signing_authorization_replay.py",
)


def _execute(arguments: list[str]) -> int:
    result = subprocess.run(
        [sys.executable, "-m", *arguments],
        cwd=BACKEND,
        check=False,
    )
    return result.returncode


def main(arguments: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--postgres",
        action="store_true",
        help="Require a disposable local PostgreSQL DSN and execute database checks",
    )
    options = parser.parse_args(arguments)
    if options.postgres:
        dsn = os.environ.get("PLATFORM_TEST_POSTGRES_DSN")
        if not dsn:
            parser.error("--postgres requires PLATFORM_TEST_POSTGRES_DSN for disposable PostgreSQL")
        parsed = urlsplit(dsn.replace("postgresql+asyncpg://", "postgresql://", 1))
        if parsed.hostname not in {"localhost", "127.0.0.1", "postgres"}:
            parser.error("--postgres refuses nonlocal database hosts")
    for command in (
        ["ruff", "check", *LINT_PATHS, *OFFLINE_TESTS, *POSTGRES_TESTS],
        ["pytest", "-q", *OFFLINE_TESTS],
    ):
        result = _execute(command)
        if result != 0:
            return result
    if options.postgres:
        return _execute(["pytest", "-q", "-rs", *POSTGRES_TESTS])
    print(
        "Offline signer contracts finished; PostgreSQL tests NOT run. "
        "Use --postgres with a disposable local DSN for database qualification."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
