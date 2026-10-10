# Northstar private signing: offline qualification

This checklist verifies the **code-level** signing boundary without a live AWS
account, Jenkins controller, signing service, secrets, or production database.
It does **not** qualify a deployment, provision workload identity, replace a
production signer, or prove immutable AWS S3 readback.

## Run the credential-free checks

From the repository root:

```bash
cd backend
uv sync --all-groups --locked
uv run python scripts/verify_offline_signing.py
```

The command exits nonzero on Ruff failures, failed unit tests, or integration
failures. It covers the signed Ed25519 authorization statement, the one-use
authorization-to-custody ordering, refusal of replay/invalid inputs, signed
custody attestation, append-only migration contract tests, and the raw Jenkins
JUnit verifier. The offline crypto integration test substitutes an in-memory
custody reader and claim stores; it is **not** a substitute for PostgreSQL or
S3 verification.

## Validate PostgreSQL without production credentials

Start a disposable local PostgreSQL database and point
`PLATFORM_TEST_POSTGRES_DSN` at it. The PostgreSQL test modules each create a
unique schema, apply their migration within that schema, exercise concurrency
and mutation rejection, then destroy only their test schema.

PowerShell:

```powershell
cd backend
$env:PLATFORM_TEST_POSTGRES_DSN = "postgresql://northstar_ci:northstar_ci_only@127.0.0.1:5432/northstar_ci"
uv run python scripts/verify_offline_signing.py --postgres
```

Bash:

```bash
cd backend
export PLATFORM_TEST_POSTGRES_DSN='postgresql://northstar_ci:northstar_ci_only@127.0.0.1:5432/northstar_ci'
uv run python scripts/verify_offline_signing.py --postgres
```

The command rejects a missing DSN or a nonlocal database host rather than
silently marking PostgreSQL tests passed. Use a **disposable** local instance:
not an existing developer, staging or production database.

## GitHub Actions gate

`.github/workflows/northstar-offline-security-contracts.yml` runs equivalent
tests (including a PostgreSQL 16 service) on pushes to the isolated feature
branch and on relevant pull requests. The adaptive branch gate also exercises
the cryptographic integration test.

If a GitHub Actions run reports **failure with no assigned runner and zero
steps**, no assertion about Ruff, pytest or PostgreSQL can be made from that
run. An administrator must inspect GitHub Actions runner access, account
billing/usage restrictions, permissions and organizational policies. Changing
test code cannot establish a passing run when jobs never start.

## Production sign-off blockers

Before activating real signing, independently verify workload identity
(mTLS/IAM as appropriate), configure pinned issuer/witness/signer keys from
protected deployment configuration, provision the isolated private signer,
apply the migrations through the entire Alembic chain, enable immutable AWS
artifact retention/versioning, and verify rollback/recovery and security
monitoring. Never copy test credentials into production, and never retry an
authorization whose commit outcome is unknown.

The current branch must remain separate from `main` until the user explicitly
requests a merge.
