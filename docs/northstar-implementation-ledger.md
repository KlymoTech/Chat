# Northstar architecture implementation ledger — 2026-10-08

This ledger is a **requirements tracking aid**, not a completion certificate.
The source of authority is *Adaptive SaaS Architecture Standard v3.0*
over its earlier source standards, together with the Northstar-specific
implementation master plan.

| Master plan phase | Deliverable | Status / evidence |
| --- | --- | --- |
| 0 | Baseline, inventory, full CI, gap register | Partial repository inspection; full baseline tests pending |
| 1 | T0–T4, A/B/C/D/L/E, guards, durable state | Tier and switch advisory modules added; persisted desired state and verified evidence remain pending |
| 2 | Provider ports | Existing contracts present; adapters and isolation review pending |
| 3 | AWS adapters | Not implemented in this branch |
| 4 | Terraform foundation | Not implemented in this branch |
| 5 | ECS production profile | Not qualified |
| 6 | EKS optional profile | Not qualified |
| 7 | Jenkins qualification | Not implemented |
| 8 | OpenTelemetry, Grafana and SLOs | Not implemented in this branch |
| 9 | Capacity scoring and forecasting | Basic advisory resource guard added; collector/forecast and history pending |
| 10 | Automatic architectural upgrade | Disabled pending signed evidence |
| 11 | Reversible provider migrations | Not implemented |
| 12 | Tenant cells and migration | Not implemented |
| 13 | Malware, age retention and DR drills | Not implemented |
| 14 | Load qualification and quotas | Not tested |
| 15 | Launch | Blocked pending signed readiness |

## Safety obligations / current blockers

- Locked controls must stay enforced, including authentication,
  authorization, tenancy, secrets, idempotency, telemetry and audit.
- Any provider migration needs a reversible plan, backup/restore proof,
  canary evidence, independent approval and a trusted artifact verifier.
- The API currently blocks B/C/D deployments without a trusted evidence
  verifier; this is deliberate **fail-closed scaffolding**, not production
  deployment functionality.
- Legacy production fallback semantics require a separate audit to ensure
  no unsafe synchronous queue or local filesystem acceptance.
- No measured capacity is claimed: 70k users / 10k RPS is a reference
  planning contract; Northstar's 500k + 1M population is a target requiring
  its own AWS evidence.

## Release gates

Run backend unit and integration tests, inspect router/OpenAPI generation,
run lint/type checks, browser E2E, Terraform validation, cloud qualification
and restore/chaos tests before marking any phase complete. Keep all
implementation work on `feature/northstar-adaptive-architecture-20261008`;
do not merge without explicit instruction.


## Increment: signed release-manifest verification (2026-10-10)

- `queue_notification_release_manifest.py` adds an independently signed Ed25519
  release-manifest verifier, bound to externally pinned release ID, Jenkins run,
  source Git commit, OCI image SHA-256 digest, environment, source/target
  configuration digests, and the exact signed certification attestation digest.
- The manifest embeds an immutable S3 artifact receipt (bucket, release-scoped
  key, version ID, SHA-256). The optional read-back gate delegates to the
  existing S3 Object Lock/KMS verifier and rejects any mismatched receipt.
- Tests cover signature tampering, duplicate JSON fields, wrong release/image,
  stale evidence, key/version mismatch, fail-before-I/O and unknown readback.
- The feature branch CI includes the new test module. A passing workflow has
  not been observed; none of this authorizes production worker activation.

### Missing before release certification

1. Build and independently sign `evidence/<release-id>/release-manifest.json`
   in a protected Jenkins pipeline, with signer identity pinned to release policy.
2. Collect and verify the full SBOM, image-signature/provenance, functional,
   security, load, resilience, migration, DR, observability and cost evidence
   required by the master plan. A signed manifest alone does not prove them.
3. Persist the signed manifest immutably and verify its **own** S3 object
   version, Object Lock policy and content digest, independently of the
   certification-attestation receipt.
4. Connect manifest verification to the separately governed qualification
   approval/admission path without accepting release coordinates from
   tenant/user input.
5. Obtain passing repository-wide CI, disposable PostgreSQL, live qualification
   AWS IAM/S3/KMS, canary, rollback and security/DR/capacity evidence before
   enabling any production certification or worker delivery.


## Increment: append-only signed release-manifest storage (2026-10-10)

- `aws_immutable_release_manifest_store.py` creates the versioned object
  `evidence/<release-id>/release-manifest.json` only after the independently
  signed release manifest and its exact retained certification attestation
  have passed the existing read-only verification gate.
- The JSON wrapper preserves the complete signed manifest token, with
  a SHA-256 checksum, pinned source/image/attestation metadata,
  SSE-KMS, compliance Object Lock retention and `IfNoneMatch: *`.
- A successful upload returns an exact manifest object-version receipt;
  precondition failure is distinct from unknown S3/network results.
  No unconditional overwrite, automatic retry, object deletion or
  production release approval is permitted.
- Added focused unit/failure-path regression tests and an integration-style
  signature-to-storage test, and wired them into the branch CI.
- **Qualification outstanding:** The focused adapter tests used stand-ins
  for external contracts; repository-wide CI and live AWS S3/IAM/KMS
  tests have not been confirmed. S3 write parameters alone do not prove
  real bucket retention, locking, IAM isolation or object durability.
- Next: independently read back and verify the *manifest's own* exact
  S3 version and encrypted/locked bytes; connect Jenkins artifact
  publishing only after protected runner identity, signer trust and
  full evidence-suite qualifications are established.


## Increment: pinned release-manifest S3 read-back (2026-10-10)

- `aws_release_manifest_reconciliation.py` verifies the independently
  signed release manifest against trusted release coordinates before reading
  S3. It requires the *manifest's own* original `VersionId` and SHA-256
  receipt, distinct from the attestation receipt embedded within it.
- Read-back checks exact key/version, SSE-KMS key, compliance Object Lock
  mode and unexpired retention, JSON content type/length, release Git commit,
  image digest, Jenkins run and linked attestation digest.
- It compares the exact canonical signed-manifest JSON wrapper bytes with
  the persisted S3 version and rejects different content even with the same
  length. All S3 operations are read-only.
- Unit tests cover conflicting identities, signatures, headers, metadata,
  bytes, missing versions and unknown AWS failures; branch CI test references
  are updated. Successful CI/AWS execution has **not** been independently
  established.
- A write whose original S3 version receipt is unknown remains an
  indeterminate outcome. This module intentionally cannot infer one from
  the latest key or automatically overwrite/recreate it.
- Next acceptance gates: protected Jenkins signer/runner configuration,
  actual S3/KMS/Object Lock/IAM tests, persisted release-to-certification
  linkage, complete functional/security/load/restore evidence and independent
  production approval. No worker or deployment activation is authorized.


## Increment: governance-linked immutable Jenkins release evidence (2026-10-10)

- Added `platform_notification_qualification_release_links` (migration `0092`)
  with one verified, unique release link per Jenkins qualification ID, exact
  S3 manifest/attestation versions and checksums, Git commit, OCI digest,
  source/target digests and environment. PostgreSQL prevents UPDATE/DELETE
  on the link using an append-only trigger. Existing qualification rows and
  non-Jenkins approvals are preserved.
- `stage_qualification_release_link` verifies the independently signed test
  attestation against the pinned S3 version **and** the release manifest
  against its own pinned locked S3 version before row locking, exact pending
  issuer/run/digest checks, insertion and flush. The caller owns commit or
  rollback; no tenant/public endpoint or worker startup is added.
- Jenkins-origin approvals now require a matching release link, and the
  runtime's persistent qualification reader denies unlinked Jenkins
  records even if they are marked approved. Existing non-Jenkins records
  retain their previous path.
- Added mock-based negative-path tests, PostgreSQL CI tests for approval and
  database immutability, and registered the new model with Alembic.
- **Not proven:** A successful GitHub Actions run, live PostgreSQL migration
  execution, live S3 Object Lock/KMS tests, and certified release-signer/
  Jenkins/approval identities. Existing proof expiry and independent
  approval remain mandatory; this link alone is not certification.
- Next: protected Jenkins publishing integration and genuine end-to-end
  environment qualification of release artifact publication, read-back,
  linking, audit and human approval. Main remains untouched; Jodo excluded.


## Increment: protected Jenkins evidence publisher boundary (2026-10-10)

- `aws_jenkins_evidence_publisher.py` adds a dedicated AWS STS identity
  verifier for the **publishing** role, separate from the test-runner,
  release signer, proof issuer and independent approval reviewer. The
  principal must match a pinned account, publisher role and STS session
  `northstar-evidence-<run-id>`; unapproved branch/session fails closed.
  Standard AWS and GovCloud STS partitions are supported.
- `publish_verified_release_manifest` requires the caller's protected
  release coordinates and pinned public release key, verifies the signed
  manifest before any S3 write, delegates to the existing immutable S3
  publication/attestation read-back contract and verifies the exact
  manifest S3 version afterward. An unknown read-back is not success.
- The publisher has **no signing private key**, tenant API, approval,
  deployment or worker-start method. The existing `Jenkinsfile` remains a
  preflight and now tests the publishing contract without publishing.
  Related negative-path tests have been added to the architecture CI.
- Dedicated operations guide: `docs/northstar-jenkins-evidence-publisher.md`.
  Live IAM trust, bucket/KMS policy, isolated agent identity, separate
  protected signer, full evidence bundle, AWS qualification and production
  approval remain outstanding. CI has not been confirmed passing; this
  increment is **not production-ready**.


## Increment: independent Jenkins attestation publication (2026-10-10)

- Added `aws_jenkins_attestation_publisher.py` as the protected first-stage
  certification publication contract. It checks the existing AWS STS publisher
  role/session and independently signed Jenkins test-runner results against
  protected build coordinates before any S3 write.
- The contract calls existing append-only S3 attestation storage, then verifies
  **the exact immutable object version** using the read-only reconciler. Only
  the original matching versioned receipt may advance to the separate release
  manifest signer. A failed/unknown write or readback does not trigger retry,
  overwrite, or automatic approval.
- Added real Ed25519 signature regression cases for valid and invalid build
  identities, expired/tampered attestations, IAM denial, S3 conflict, and
  mismatched/unknown readback. Registered them in GitHub branch CI and the
  offline root Jenkins preflight, which still cannot write to AWS.
- Still required: protected independent test-runner and release signing
  infrastructure; reviewed AWS publisher IAM trust/KMS/retention policy;
  real S3 version/metadata tests; evidence bundle and immutable release link
  tests; complete certification and independent approval. No production
  workload or notification worker is activated by this increment.
- **Execution status:** committed test code is not a passing CI/test report;
  repository-wide tests and real AWS/Jenkins qualification remain unverified.


## Increment: Terraform isolation of Jenkins qualification evidence storage (2026-10-10)

- Added `infrastructure/terraform/modules/jenkins_qualification_evidence/` as
  an isolated, **not-applied** AWS foundation for evidence publication. The
  module defines an Object Lock enabled, versioned, private S3 bucket with
  COMPLIANCE retention, customer-managed SSE-KMS, default-deny TLS/write
  guards, no force-destroy, and account/region sanity checks.
- Added a dedicated publisher IAM role that trusts only one separately
  reviewed Jenkins agent role with run-scoped STS session names and a
  mandatory permissions boundary. IAM S3 grants cover one `evidence/*`
  prefix; KMS cryptographic grants require S3 service and scoped object
  encryption context. No publisher permission to delete evidence, modify
  production workloads, fetch private signer keys or deploy Terraform.
- Added an additive example `examples/qualification-evidence/`,
  `terraform test` mock-provider topology checks, a no-credentials/no-apply
  GitHub Actions Terraform gate and backend-authored policy security checks.
  The existing private worker Terraform and root Jenkins preflight remain
  unchanged. Deployment continues to require separate review.
- The module does **not** create the Jenkins agent role, signing roles,
  organization permissions boundary, state backend, audit archive, CloudTrail
  S3 data-event logging, full evidence suite, cross-region replication or
  live qualification environment.
- **Verification limitation:** Terraform binaries/provider packages were
  unavailable in the current execution environment. The files were
  committed, but actual `terraform fmt`, `init`, `validate`, mock
  `test`, IAM/S3/KMS qualification and production operation have not been
  demonstrated. No CI success or active publishing should be inferred.
- Next incremental gate: secure release-signing/test-runner agent identities
  and protected Jenkins-to-AWS identity issuance, followed by real
  qualification S3 Object Lock/KMS read-back and CloudTrail evidence.


## Increment: independent Jenkins signer IAM roles (2026-10-10)

- Added an independent `infrastructure/terraform/modules/protected_qualification_signers/`
  module and isolated reference example. It provisions separately named
  **test attestation** and **release authority** IAM roles with mandatory
  signer permissions boundaries and distinct reviewed parent agent roles.
  Both have a one-hour maximum STS session and pinned session-name patterns;
  the pre-existing publisher agent is expressly excluded from signer trust.
- Only one exact existing Secrets Manager Ed25519 signing secret is readable
  per signer, with `kms:Decrypt` restricted to its independently named KMS
  key via Secrets Manager and exact secret encryption context. Neither role
  has S3 publishing, production deployment, IAM changes or secret creation
  rights. No private-key content enters Terraform or the repository.
- Offline `terraform test` mock-provider coverage now includes role
  collision, reused secrets or KMS keys, wrong account/region, cross-account
  secret/KMS ARNs and wildcard principals. A separate no-credentials,
  no-apply GitHub Actions workflow, source-policy Python tests and operator
  documentation were added.
- **Unverified:** actual `terraform fmt`, `init`, `validate`, `test`
  execution, live AWS agent/trust/Secrets Manager/KMS authorization,
  protected signing services, rotation/revocation and public-key pinning.
  The Terraform binary was unavailable locally and GitHub CI has not yet
  supplied passing evidence. Pre-existing signer parent roles, secrets and
  permissions boundaries must be independently provisioned and audited.
- Next: protected signer service implementations and negative IAM/Jenkins
  integration verification; do not use mock Terraform plans as production
  approval or as evidence that a private signing service exists.
