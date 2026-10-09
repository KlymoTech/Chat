# Jenkins custody signing: at-most-once replay guard

This is a **development security boundary**, not approval to deploy or sign production evidence.

## Order of operations

1. Verify the original, pinned PostgreSQL Jenkins witness and original S3 JUnit/index versions.
2. Require the exact build/run metadata and all three passing witnessed suites.
3. Use an **independent protected PostgreSQL transaction** to insert exactly one immutable signing claim (release ID, Jenkins run ID and witness digest), and wait for the commit to succeed.
4. Only after a confirmed commit, retrieve the protected Ed25519 private key and sign the canonical, server-constructed evidence payload.
5. Self-verify the signature against the independently pinned public key.

There must be no signing when the claim insert or commit is rejected, times out, raises, or has an uncertain outcome. A crash after the claim has committed **burns** that claim: do not delete, reset, retry or upsert it, including if no token was delivered. An operator must open an audited incident and initiate a fresh, independently witnessed release/run if necessary.

## Production blockers

- Provision a dedicated IAM/workload and PostgreSQL role allowing INSERT only on the claim table (no UPDATE, DELETE, TRUNCATE, DDL, trigger changes, or broad table ownership); verify this in a live PostgreSQL permission test.
- Verify the caller is a separately authenticated isolated signing service: the current Python protocol alone does **not** authenticate a remote caller or distinguish production from a test implementation.
- Make the trusted build plan and public keys independently provisioned and immutable. Configure mandatory identity, job/run authorization and secret rotation; do not accept tenant-controlled run identifiers.
- Apply migration 0095 and all preceding migrations to a disposable Postgres instance, then run concurrent double-claim, rollback, network timeout and process crash tests.
- Retain external tamper-evident signing-claim audit and build provenance, and design explicit incident recovery for unknown claim outcomes. Never automatically reuse a claim.
- Confirm end-to-end CI, real AWS Secrets Manager/KMS/S3 authorization, independent Jenkins witness production and protected signer isolation. None are certified by these source commits.

The signing helper does not activate notification workers, publish qualification approvals or expose HTTP endpoints. The test fake replay store does not establish actual PostgreSQL durability.
