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
| 9 | Capacity scoring and forecasting | Pure collector, score, forecast, cost and autoscale advisories present; durable history and live integration pending |
| 10 | Automatic architectural upgrade | Disabled pending signed evidence |
| 11 | Reversible provider migrations | Not implemented |
| 12 | Tenant cells and migration | Not implemented |
| 13 | Malware, age retention and DR drills | Not implemented |
| 14 | Load qualification and quotas | Not tested |
| 15 | Launch | Blocked pending signed readiness |

## Scope audit and outbox increment (2026-10-10)

- The two `Production_Grade_Pluggable_AWS_Platform_Master_Implementation_Specification`
  DOCX copies supplied for this request have the same SHA-256 digest
  (`73140DBF8DC17330D9CF4EC94D077BAE1C092805F528346A6D1E51615EFDEC37`).
  The other supplied standards are distinct and add requirements; identical
  headings or opening text must not be treated as complete overlap.
- `platform.yaml` remains `deployment_status: planned`. It now identifies the
  bounded outbox relay and activity-gated recovery schedule instead of pointing
  a queue process at the legacy infinite polling worker.
- The shared outbox service emits one opt-in, best-effort SQS nudge **after** a
  successful transaction commit and updates the DynamoDB activity marker.
  Rollbacks do not signal. The relay handles one bounded batch; the recovery
  schedule checks the marker before constructing a PostgreSQL engine. Full
  batches enqueue continuations. The existing polling worker is retained.
- The one-shot relay now has an opt-in SNS FIFO publisher using stable event IDs
  for broker deduplication and tenant/aggregate message groups. Kafka remains
  the default for existing deployments. Neither a topic nor a publisher proves
  downstream subscriptions, consumer idempotency or data parity.
- The isolated `scale_to_zero_outbox` Terraform module defines SQS + encrypted
  DLQ, an on-demand DynamoDB marker, an encrypted SNS FIFO domain-event topic,
  SQS event mapping, 15-minute recovery rule
  and least-privilege policy outputs. It is not instantiated or applied. Local
  Terraform validate and one mocked topology test passed; live AWS and CI
  evidence remain absent. Terraform 1.16.5 reports a deprecation warning in
  the account/region precondition inherited from the module style.
- Remaining outbox cutover gates: create/review the Lambda images and IAM roles,
  wire network and broker access, create SNS-to-SQS subscriptions and replace
  the seven Kafka consumer paths, deploy the module in an approved account,
  qualify retry/DLQ/marker-failure behavior and consumer `eventId`
  deduplication, then stop the legacy relay before enabling the event mapping.
  No such cutover has occurred.
- The standards also require independent work across tenant isolation, provider
  migrations, frontend contracts, load/capacity, security, backup/restore and
  disaster recovery. The requested 10,000 and 50,000 RPS reference contracts
  are **not** claims about this deployment; no corresponding load evidence is
  present. This ledger is not a complete requirement-by-requirement sign-off.

## Playbook conformance audit increment (2026-10-10)

- `make conformance` now invokes a fail-closed, read-only 23-rule audit. It
  checks manifest structure, declared handlers, scheduled activity gates,
  image declarations and standard Make targets, and labels the remaining
  dynamic requirements **unverified**. `--report-only` is available for CI
  visibility, not acceptance. A structurally valid manifest is no longer
  presented as full conformance.
- One-shot CRM reconciliation and outbox relay now construct PostgreSQL
  engines with a one-connection pool and zero overflow; the normal API pool
  is unchanged. Focused tests cover the CRM engine parameters.
- `local-up` and `local-down` now reuse the existing Compose-backed `up` and
  `down` targets without changing their behavior. The audit still reports
  gaps that were open at that audit increment: Make deploy/image-push targets
  and dual-architecture image declaration. The declarations are addressed by
  later increments; actual architecture builds and production deployments
  still require the corresponding workflows and evidence.

## Multi-architecture release declaration increment (2026-10-10)

- The existing release workflow now sets up Arm64 emulation and requests both
  `linux/amd64` and `linux/arm64` for its API and web image matrix. The API
  manifest declares the same two platforms. A branch-gate test checks that
  declaration and preserves the existing SBOM, provenance, vulnerability scan
  and attestation steps.
- No image was built or published locally: Docker is unavailable here. Base
  image manifests, successful per-architecture builds, runtime smoke tests,
  registry manifest inspection and production qualification remain unverified.
  The playbook's `image-push` and `deploy` Make targets remain missing; no
  placeholder target was added.

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


## Increment: protected AWS signer key-material access (2026-10-10)

- Added `aws_protected_qualification_signer.py` to bridge the separate,
  Terraform-governed test and release signer roles to pre-existing,
  independently encrypted Secrets Manager Ed25519 private keys.
- Access fails closed unless the current AWS account, exact assumed-role ARN,
  run-specific STS session name, UserId suffix and configured feature branch
  all match. The adapter rejects non-current or mismatched secret versions,
  invalid or non-Ed25519 private keys, unpinned public keys and unsupported
  AWS partitions/account/region configurations.
- The adapter returns transient key material only to an isolated internal
  signing service; it does **not** sign caller-provided payloads, certify
  passed test results, issue proofs, expose a public API, publish S3
  artifacts or enable notification workers. Independent provenance,
  protected signer-process identity, trusted public-key rotation and
  immutable evidence read-back are still required before allowing signing.
- Added focused test cases for both roles, wrong identity, wrong branch,
  malformed run ID, STS session length, AWS/secret errors, key-rotation
  mismatch, wrong signature algorithm and GovCloud. All **27 focused tests
  passed locally** using stand-in AWS clients and generated test keys.
- Registered the new suite with feature-branch GitHub Actions and the
  non-publishing Jenkins preflight. A passing full-repository CI run and
  real AWS IAM/KMS/Jenkins execution have **not been observed**.
- Next: integrate authenticated and independently verified JUnit/test-runner
  result provenance into an isolated signer service, then implement
  release-manifest signing only after verifying the precise retained
  attestation S3 version. Do not make private key retrieval a tenant API.


## Increment: witnessed Jenkins test-result provenance (2026-10-10)

- Added independent Ed25519 Jenkins witness verification in
  `queue_notification_jenkins_test_provenance.py`, pinning the approved
  controller/job, run ID, branch, environment, source SHA and source/target
  digests. The witness key must differ from the attestation signer key.
  Time-bounded, duplicate-key-rejecting, strict signed JSON binds the
  three mandatory suites to exact JUnit XML report SHA-256 hashes/counts.
- Parsed JUnit evidence is restricted in byte size and DTD/entity use;
  zero-failure, zero-skip, zero-error and exact test-count/suite-name
  checks fail closed. Tampering, stale builds, wrong principals, absent
  suites and inconsistent signed counts are rejected.
- Added negative-path tests for signed source/run replay, different signer
  and witness keys, tampered JUnit files, misleading all-passed summaries,
  XML hazards and duplicate signed JSON. Registered the tests with the
  architecture workflow and the **non-signing** root Jenkins preflight.
- **Incomplete production controls:** the witness producer and isolated
  agent-authentication policy are not implemented; raw JUnit bytes are
  currently supplied by the caller, not independently read back from
  protected versioned S3 receipts. Persisted witness receipts, build
  replay prevention, trusted witness key rotation and downstream signing
  integration must be completed before permitting certification signing.
- **Execution:** code/test/CI commits are recorded, but passing
  repository-wide CI and live Jenkins/AWS test execution were **not
  observed**. No production signing, approval or worker startup occurred.
- Next: version-fenced, read-only JUnit report retrieval and witnessed
  report binding; then authenticated, independently qualified signing
  service that self-verifies each issued Ed25519 attestation.


## Increment: pinned S3 JUnit suite archiving and readback (2026-10-10)

- Added `aws_immutable_jenkins_junit_store.py` to enforce an AWS
  `PublicationIdentity` role/session check, then validate the complete
  independently witnessed three-suite JUnit report set before any
  side effect. Writes are `IfNoneMatch=*`, encrypted with pinned
  SSE-KMS, COMPLIANCE-locked and retained with one day of policy margin.
  One original S3 version/checksum receipt is produced per suite.
- Added `aws_jenkins_junit_reconciliation.py`, a read-only reconciler
  that requires externally pinned receipt versions and release/run/suite
  key paths for all three JUnit files, checks per-version encryption,
  Object Lock retention, metadata and byte checksums, and then passes
  the **actual S3 bytes** to the independently signed Jenkins witness
  verifier. It binds each S3 version's stored witness checksum to the
  verified witness body hash. It cannot replace, overwrite, list latest,
  approve or activate workers.
- Added fake-S3 end-to-end and failure-path tests for complete writing
  and readback, different object versions, altered byte content, KMS/
  retention/source/witness metadata tampering, independent signature
  mismatch, authorization denial, partial archive conflict and unknown
  AWS outcomes. Wired into feature-branch GitHub Actions and the
  unchanged non-publishing Jenkins preflight.
- **Outstanding:** a protected Jenkins witness producer and complete
  isolated suite execution, independent durable receipt collection,
  version-locked signed witness archival, partial-write reconciliation,
  production IAM and KMS Object Lock verification, and connection to
  the authenticated private attestation signer. A caller-controlled
  or self-reported witness is never sufficient for qualification.
- **Evidence status:** code/tests/CI hooks are committed. Passing full
  CI or actual AWS/Jenkins execution was not established from this
  session. No main-branch changes, Jodo code or production worker
  activation are part of this increment.


## Increment: one locked Jenkins JUnit evidence index per release/run (2026-10-10)

- Added `aws_jenkins_junit_evidence_index.py` to persist the **signed
  independent Jenkins witness token** and all three original, pinned S3
  JUnit version receipts into one canonical, checksum-protected,
  KMS-encrypted, COMPLIANCE Object Lock S3 index at
  `evidence/<release-id>/jenkins/<run-id>/junit/verified-index.json`.
- The publishing boundary enforces the existing AWS publisher role and
  run/branch identity before verifying all three original report object
  versions with `ReadOnlyWitnessedJunitReconciler`. A single conditional
  S3 `IfNoneMatch=*` write occurs only after full report signature,
  checksum, retention and build provenance read-back.
- The independent readback method requires a separately trusted exact index
  receipt plus exact original report receipts, revalidates all three signed
  reports, and verifies the index's original `VersionId`, metadata,
  unexpired Object Lock, KMS key, SHA-256 and canonical bytes. Unknown or
  conflicting S3 results are blocking; no key listing, inferred latest
  version, overwrite, automatic retry, approval or worker activation.
- Added fake-S3 end-to-end and denial-path tests with real Ed25519-generated
  witnesses for tampered contents, wrong version/receipt, incorrect AWS
  publisher identity, KMS/retention mismatch, S3 faults, replayed witness
  and duplicate writes. Registered the tests with GitHub branch CI and
  the non-signing root Jenkins preflight.
- **Unverified/outstanding:** successful repository-wide CI and live AWS
  Object Lock/KMS/IAM tests; independent durable original index-receipt
  custody; authenticated witness production; controlled partial-write
  recovery; historical audit beyond the witness's 15-minute freshness
  window; and a trusted private attestation signing service. Signed
  release certification, production approvals and worker startup remain
  gated and disabled.


## Increment: immutable PostgreSQL custody of witnessed Jenkins JUnit index (2026-10-10)

- Added migration `0093_notification_jenkins_junit_custody.py` and ORM
  `NotificationJenkinsJunitCustodyRecord` for one append-only witness
  token, original index S3 `VersionId`/checksum, three original JUnit
  version receipts and pinned release/run/build coordinates per release.
  A unique `run_id`, release primary key, PostgreSQL update/delete
  denial trigger and populated-table downgrade refusal protect
  original custody. This is additional to, not a replacement for, the
  existing qualification release-link governance.
- Added `stage_witnessed_junit_custody`: it requires a protected
  publisher machine-identity check and exact suite receipts, independently
  readbacks all three original S3 reports and the locked index against
  the signed witness, checks the resulting build coordinates, and
  inserts/flushes a custody row in the caller-owned transaction. It
  neither commits nor retries an unknown S3 outcome.
- Added `load_and_reconcile_witnessed_junit_custody`: it takes a
  release/build plan and trusted public-key configuration, loads the
  original token and receipts from PostgreSQL (never replacement
  client receipts), locally rejects malformed/mismatched metadata,
  re-reads all version-fenced S3 evidence, and verifies the original
  witness SHA before returning the verified provenance.
- Fixed **existing migration 0092's invalid PL/pgSQL dollar delimiter**
  discovered during pre-migration review. No recorded data was deleted.
  Added custody unit regressions, a disposable PostgreSQL migration/
  uniqueness/immutability/downgrade test, and wired both into the
  existing feature-branch CI and non-publishing Jenkins preflight.
- **Not demonstrated:** successful full repository CI, actual PostgreSQL
  migration, live S3 Object Lock/KMS/IAM authorization, operator replay
  handling, durable role restriction against SQL TRUNCATE/DDL, and
  authenticated private attestation signing that consumes the custody
  reader. Witness verification still enforces 15-minute freshness;
  an archived historical audit verifier is a separate outstanding gate.
- Next increment: bind private attestation signing exclusively to
  `load_and_reconcile_witnessed_junit_custody` with protected AWS test
  signer identity and verify the emitted Ed25519 attestation against
  original run/release digests. Production approval/workers stay disabled.


## Increment: independently reverified JUnit index receipt custody (2026-10-10)

- Added migration `0093_notification_junit_index_custody.py` and ORM model
  for one append-only PostgreSQL custody record per release ID with a
  uniqueness constraint on Jenkins run ID. It pins the signed witness hash,
  release/run/source identity, original index S3 `VersionId`/SHA-256 and
  **all three** original JUnit object `VersionId`/SHA-256 receipts.
  Database triggers reject UPDATE and DELETE; a non-empty table prevents
  destructive migration downgrade.
- `stage_witnessed_junit_custody` checks the dedicated AWS publisher
  session identity and re-verifies the original S3 index/report versions
  before staging an insert. It does not commit/approve/sign/deploy.
  Uniqueness conflicts remain blocking and require caller rollback.
- `verify_custodied_junit_evidence` fetches custody by a protected release
  identifier, reconstructs **all original version receipts solely from
  persisted database fields**, re-verifies locked S3 index and JUnit
  signatures/bytes, and compares the independently witnessed digest.
  Caller-provided S3 versions cannot override database custody.
- Added mock-based staging/readback denial-path tests and included them
  and the migration in branch architecture CI. The schema is registered
  in Alembic. **Actual PostgreSQL migration execution, CI success,
  independent protected DB principal authorization and live AWS KMS/S3
  tests remain unverified.**
- Next gate: independently authenticated and audited attestation signing
  that retrieves the existing pinned Ed25519 key **only after** custody
  readback and protected test-run identity validation, plus a real
  PostgreSQL integration test and replay prevention policy. No Jodo,
  main-branch merge or production worker activation.

## Increment: planned SNS-to-SQS domain-event consumer (2026-10-10)

- Added a one-shot Lambda handler covering the topic set of all seven existing
  Kafka consumers. It reuses their projection/cleanup/routing helpers and
  existing inbox keys, with SNS topic/queue/attribute validation, one-record
  FIFO processing, and partial-batch failure responses.
- Added a FIFO event queue, DLQ, least-privilege consumer policy, filtered SNS
  subscription and Lambda mapping in the outbox Terraform module. The filter
  includes only currently consumed event types. Subscription and mapping are
  **off by default**; the existing Kafka path remains untouched.
- Local checks: 20 targeted Python tests passed, including exact legacy-topic
  and Terraform-filter parity; two mocked Terraform plan tests passed.
- The planned `platform.yaml` event process now references the one-shot Lambda
  handler instead of the infinite Kafka analytics worker. Manifest validation
  and a Zoho webhook failure/retry regression pass; current Compose services
  and Kafka consumers remain unchanged.
- **Not complete:** no live AWS deployment or test of permissions, networking,
  SNS delivery, retries/DLQ, external Zoho idempotency, throughput, or cutover.
  This does not establish complete implementation of the source documents.

## Increment: actionable DLQ visibility (2026-10-10)

- The planned Terraform module now requires an approved same-account/region
  alert SNS topic and creates CloudWatch nonempty alarms for the nudge,
  domain-event consumer, and SNS subscription delivery dead-letter queues.
  The separate subscription DLQ captures SNS-to-SQS delivery failures and
  requires an approved customer-managed KMS key policy for the SNS principal.
  Two mocked plans, formatting, and Terraform
  validation pass. No queue was redriven or deployed.
- Alert-topic policy, human subscription/delivery, live metric behavior, and a
  supervised redrive remain external qualification gates. The alarms do not
  certify the complete platform.

## Increment: fail-closed SNS publisher preflight (2026-10-10)

- The opt-in SNS relay now requires a subscription ARN and target FIFO queue
  ARN. Before opening PostgreSQL, it queries live SNS subscription attributes
  and rejects absent/drifted topic, queue, message-attribute filter, envelope
  mode, or redrive policy. The default-off Terraform plan returns no
  subscription ARN and therefore cannot silently publish into an unsubscribed
  topic. The relay IAM policy includes read access only when activated.
- Local checks: 24 focused Python tests and two mocked Terraform plans pass.
  This is a preflight guard, not proof of live queue delivery or production
  qualification; AWS cutover remains disabled and untested.

## Increment: explicit IAM-role-compatible S3 access (2026-10-10)

- Repository comparison found presigned uploads, checksum/version validation,
  and commit-failure cleanup already present; those were preserved. The missing
  AWS credential path was added as opt-in `S3_AUTH_MODE=aws-default`, using the
  SDK credential chain without application-managed keys or custom S3 endpoints.
  Local MinIO's default static-key mode is unchanged. Configuration rejects
  mixing the two modes; targeted tests cover mode validation and client setup.
- This is not the full upload-session/quarantine/orphan-reconciliation package.
  No AWS bucket policy, workload identity, browser upload, or recovery test was
  run, and no production storage configuration was changed.

## Increment: versioned AWS staging preflight (2026-10-10)

- In opt-in `S3_AUTH_MODE=aws-default`, upload promotion now refuses to copy
  from a staging object if S3 does not return a real `VersionId`. This ensures
  the already-present checksum read and conditional copy are pinned to an
  immutable source version. The default static-key MinIO path is unchanged.
- Source-version preflight alone is not a complete upload lifecycle; see the
  destination-copy verification increment below.

## Increment: verified AWS promoted-copy version (2026-10-10)

- In opt-in AWS mode, the copied object must return a real destination
  `VersionId`. Promotion reads that exact version and hashes it in bounded
  chunks before deleting the staging object or returning success. A missing
  version, size mismatch, digest mismatch or read failure removes the copied
  version where possible and fails closed. The static-key MinIO path retains
  its previous behavior.
- Focused mocked tests cover success, equal-length tampering, absent/null
  destination versions and cleanup. Live AWS versioning, destination-version
  custody across subsequent reads, malware scanning, quarantine isolation,
  quota reservation, orphan reconciliation, retention and bucket policy
  remain outstanding.

## Increment: staged-upload type screening (2026-10-10)

- The upload API already checks filename extension against declared MIME type,
  and ingestion already limits DOCX archive expansion. Promotion now compares
  the staged bytes against PDF, PNG, JPEG and TIFF signatures, checks DOCX ZIP
  package members, and rejects NUL-containing text before copying to the
  knowledge prefix. Checksum and size verification still happen first.
- This is a narrow format gate, not antivirus, full file validation, safe
  parsing, isolated scanning, quarantine authorization or an upload-session
  quota reservation. Those controls and live object-store tests remain open.

## Increment: version-pinned AWS object reads (2026-10-10)

- In opt-in AWS mode, `ObjectStore.download` now requires a non-null S3
  `VersionId` from `HEAD` and passes it to `GET`, so concurrent latest-version
  changes cannot swap the bytes between the two calls. Static-key MinIO reads
  remain unchanged. The legacy file-materialization path also compares bytes
  to the persisted source checksum before parsing; the primary ingestion path
  already did this.
- Focused storage/extraction tests pass locally. This does not persist the
  approved destination `VersionId` in the source record or prevent an earlier
  overwrite before `HEAD`; approved-version custody, IAM write isolation,
  malware scanning and live AWS qualification are still open.

## Increment: upload-only local storage proxy (2026-10-10)

- The local Nginx `/storage/` route now permits only the browser's presigned
  multipart POST; GET, HEAD and other methods are denied at the proxy.
  Backend object reads and cleanup continue to use the internal S3 client.
  Renderer contract coverage checks that this guard survives config rendering.
- This does not configure private AWS bucket policy, validate live Nginx/MinIO
  behavior, or provide malware scanning, separate quarantine storage or a
  governed download authorization endpoint.

## Increment: workspace-scoped AWS staging keys (2026-10-10)

- AWS-mode presigning now requires the authenticated workspace and stores it
  between the tenant ID and date in the staging key. Both the generic and
  Education promotion routes pass their resolved workspace to the object
  store. Promotion rejects keys from another workspace before contacting S3.
  Static-key MinIO keeps its existing tenant-only key layout.
- Focused tests cover missing workspace, key scoping and cross-workspace
  promotion denial. This is not per-user upload reservation, persisted
  session ownership, or AWS bucket-policy enforcement.

## Increment: governed release/deployment Make targets (2026-10-10)

- `image-push` requires a new `v*` tag at `HEAD` and pushes it to `origin`,
  invoking the existing verified multi-architecture release workflow. It does
  not build or publish around that workflow's vulnerability/provenance gates.
- `deploy` validates the immutable commit, HTTPS health URL, and an existing
  workflow ref, then dispatches the existing deployment workflow. That
  workflow verifies image attestations and still requires approval through
  the protected production environment. Neither target was invoked here.
- These add the missing Make entry points; they do not resolve the many
  qualification findings in the conformance report.

## Increment: feature-branch whole-app CI trigger (2026-10-10)

- CI now runs on pushes to `feature/northstar-adaptive-architecture-20261008`
  as well as its existing pull-request and `main` triggers. Its existing
  integration job builds and starts the complete Compose topology, runs the
  authenticated end-to-end smoke (including a presigned upload), checks
  migration heads and CRM schema, and collects logs before teardown.
- This change does not alter `main`, deploy workloads, or establish a passing
  CI result. A nightly schedule cannot execute solely from an unmerged feature
  branch under GitHub's default-branch scheduling model; that qualification
  remains unverified while the requested no-merge constraint is in force.

## Increment: complete Compose service-presence smoke (2026-10-10)

- The existing authenticated Compose smoke now requires the separate
  WhatsApp worker to become healthy and checks that every declared Compose
  service is running, except the two already-verified successful one-shot
  initialization jobs. This catches stopped or omitted CRM, channel, course,
  and future services that the previous hard-coded shortlist missed.
- This is a process-presence gate, not evidence that every worker consumed a
  message or that live AWS behavior is qualified. No Compose service or
  application feature was removed.

## Increment: failed staging-deletion copy cleanup (2026-10-10)

- After a validated promotion copy, staging-object deletion failure now
  triggers cleanup of the exact copied version and returns an object-store
  error. Previously that failure could leave a promoted object behind while
  the API reported failure. A focused AWS-mode regression covers this path.
- This does not address unknown outcomes of the copy request itself, missing
  copied-version receipts, externally overwritten destinations, or periodic
  orphan reconciliation. Live AWS and full CI remain unverified.

## Increment: approved AWS knowledge-object version custody (2026-10-10)

- The two knowledge upload routes now persist the exact copied S3 `VersionId`
  alongside the source key and checksum. File ingestion (including legacy
  materialization) sends this ID to the object store, which HEADs and GETs
  the same approved version rather than the current latest version. Migration
  `0097` adds a nullable field so older records and static-key MinIO retain
  their existing behavior.
- Historical AWS rows with no version remain checksum-checked but cannot be
  retroactively pinned; a controlled backfill or re-upload is still needed.
  This does not establish IAM write isolation, object-lock retention, malware
  scanning, or live AWS qualification.

## Increment: post-delete exact-key reconciliation (2026-10-10)

- Versioned object purges now re-list the exact key after batch deletion and
  fail if any version or delete marker remains. The existing event consumer
  only acknowledges a successful purge, so a concurrent new version remains
  eligible for retry rather than being silently marked clean. A focused test
  simulates a version added after the first enumeration.
- This does not replace periodic orphan discovery, prevent new writes to a
  deleted key, or prove S3/IAM behavior in a live account.

## Increment: no unversioned AWS destination cleanup (2026-10-10)

- AWS promotion no longer issues a plain destination DELETE when S3 omits or
  returns a null copied `VersionId`. That delete could hide a newer writer's
  object behind a delete marker. The operation now fails with an indeterminate
  cleanup error and leaves the object for supervised version-aware repair.
  Static-key MinIO cleanup retains its existing behavior.
- The unreceipted object remains a possible orphan; periodic discovery and
  safe reconciliation still need implementation and live AWS qualification.

## Increment: fail-closed AWS exact-key purge versioning (2026-10-10)

- AWS-mode exact-key cleanup now refuses a bucket whose versioning status is
  absent or suspended instead of issuing an unversioned delete or treating a
  suspended bucket as fully version-safe. Static-key local MinIO retains its
  existing deletion path. Focused regressions cover both AWS drift states.
- This is a fail-closed guard, not a complete retention, legal-hold, or orphan
  reconciliation system; real S3 bucket policy and IAM qualification remain.

## Increment: consistent extraction cleanup guard (2026-10-10)

- Exact-key and extraction-prefix purges now share the AWS enabled-versioning
  precondition. The prefix purge also re-lists after deletion and refuses to
  report success if a version or delete marker appears or survives. Existing
  local MinIO behavior is retained.
- This only covers the event-driven cleanup path; concurrent writers can still
  race after the final check. Storage write isolation, periodic orphan scans,
  and live AWS qualification remain required.

## Increment: version-scoped rollback after failed upload transaction (2026-10-10)

- Both knowledge upload routes now use one rollback helper after a failed
  database transaction. AWS mode deletes only the exact copied S3 version
  returned by promotion; it refuses to delete latest when that receipt is
  missing. Static-key MinIO retains the prior exact-key purge behavior.
- This avoids broad AWS key deletion on a commit failure. It does not solve
  unknown S3 outcomes, concurrent writes, legal holds or periodic orphan
  reconciliation. Live AWS and repository-wide CI remain unverified.

## Increment: bounded stale-staging discovery (2026-10-10)

- An internal read-only staging inventory now lists aged objects under an
  explicit tenant prefix and, for AWS, an explicit workspace prefix. It
  requires an age beyond the presigned capability lifetime and caps examined
  objects, reporting truncation instead of implying a complete scan.
- This is discovery only. It does not authorize deletion: upload-session
  ownership, version receipts, legal holds, quota release, retry policy and
  supervised orphan reconciliation remain unimplemented and require review.

## Increment: full-payload text upload NUL screening (2026-10-10)

- Promotion now screens the entire already-read text/Markdown payload for NUL
  bytes rather than only its first 8 KiB. Tests cover binary content after
  that former boundary. This narrows one mislabeled-binary acceptance gap.
- This is not malware scanning, text-encoding validation or comprehensive
  content classification; the rest of the upload lifecycle remains open.

## Increment: real frontend qualification findings (2026-10-10)

- Installed locked npm dependencies and ran broader local checks. TypeScript
  typecheck passed. The integration-catalogue test had three obsolete Zoho
  dialog expectations after the platform-managed one-click UI replaced that
  flow; its mock and assertions now cover the current no-customer-secret
  contract and all seven tests pass.
- The repository is **not green**: frontend lint reported 56 problems, backend
  repo-wide Ruff reported 219 findings, and the full frontend test run showed
  additional failures before being stopped. These are not waived or counted
  as passing CI. Docker, PostgreSQL integration and live AWS remain untested.

## Increment: stable workspace branding fetch identity (2026-10-10)

- Workspace branding now depends on the active workspace ID, not the identity
  of its context object. This prevents duplicate fetches when the provider
  returns a new object for the same workspace while retaining immediate
  cross-workspace brand isolation and late-response rejection. Focused tests
  cover same-ID rerenders and workspace switches.
- This resolves one observed frontend test failure, not the other frontend
  lint/test findings or production browser qualification.

## Increment: locale-aware billing usage test (2026-10-10)

- The billing panel test now compares token usage using the same locale-aware
  number formatting as the existing UI. Its former US-only comma grouping
  failed on an India-locale development machine despite correct usage data.
  No billing logic, plan limit or displayed value was changed.
- The broader frontend suite and billing/provider qualification remain open.

## Increment: session-scoped delivery API test context (2026-10-10)

- Three delivery API tests now use the existing workspace-selection API rather
  than an obsolete localStorage key. They again assert that list, history and
  requeue requests include the active workspace header and bearer context.
  No duplicate selection state or production API behavior was added.
- The wider frontend suite and live channel-provider qualification remain open.

## Increment: current workspace context in API client tests (2026-10-10)

- Lead CRM, channel health history, channel operations, and notifications API
  tests now select their workspace through the existing session-scoped API
  instead of the obsolete localStorage key. All eight focused tests pass and
  retain their bearer-token and workspace-header assertions. No production
  behavior or second selection mechanism was added.
- This does not resolve other stale tests, repo-wide lint findings, or live
  provider and deployment qualification.

## Increment: CRM/channel test context and invitation mock (2026-10-10)

- Channel webhook event, CRM operations health, and CRM dead-letter replay
  tests now use the existing session-scoped workspace selection. All four
  focused tests pass without adding duplicate state or changing API behavior.
- The workspace invitation test provider mock now exposes the optional
  workspace hook used by branding. All six invitation tests pass again.
- The interrupted broader frontend run also showed failures in the workspace
  team panel suite. The complete frontend suite, repo-wide lint, deployment,
  and live-provider checks remain open; this is not a production sign-off.

## Increment: explicit team-permission test fixture (2026-10-10)

- The workspace team panel test fixture now grants the named membership
  permissions that its action tests require. The previous wildcard placeholder
  did not satisfy the component's explicit permission checks and caused three
  false-negative tests. All four focused team-panel tests pass, including the
  read-only member-viewer scenario. Authorization behavior was not weakened.
- Full-suite and deployment qualification remain outstanding.

## Increment: authenticated API test workspace scope (2026-10-10)

- Analytics, audit, CRM workflow, and CRM one-click API tests now use the
  existing session-scoped workspace selector, preserving their assertions that
  authenticated requests carry the workspace header. A targeted batch of five
  API test files now passes all 34 tests (including billing). This removes
  obsolete test setup, not any production feature or authorization check.
- Full-suite, repo-wide lint, live provider, and deployment checks remain open.

## Increment: direct presign checksum validation (2026-10-10)

- The shared object-store presign method now rejects malformed SHA-256 values
  before calling S3/MinIO, matching the existing HTTP schema's checksum
  contract for callers that invoke the service directly. It uses the same
  upload path; no duplicate storage mechanism or existing feature was removed.
- The full object-store test module passes (61 tests), including three new
  malformed-checksum cases, and Ruff passes on the changed Python files.
  Malware scanning, upload quotas, live object-store qualification and broader
  release gates remain open.

## Increment: shared bounded DOCX archive gate (2026-10-10)

- DOCX package validation now has one shared validator for required members,
  at most 5,000 archive entries, and the configured expanded-byte limit.
  Promotion uses it before copying staged bytes to the knowledge prefix;
  ingestion reuses it rather than maintaining a second limit implementation.
- Focused checks pass: 63 object-store tests, 4 ingestion tests, and Ruff on
  the changed Python files. This does not prove full DOCX safety, malware
  screening, upload quota reservation, or live S3 behavior.

## Increment: unambiguous DOCX package members (2026-10-10)

- The shared DOCX validator also rejects duplicate ZIP member names, so
  validation and downstream parsers cannot choose different versions of the
  same package part. Promotion rejects such archives before copying them, and
  ingestion applies the identical rule. No new upload path was introduced.
- The focused object-store and ingestion suites pass (68 tests total), and
  Ruff passes on the changed files. This remains a bounded structural check,
  not antivirus, full archive validation, or live AWS qualification.

## Increment: conservative governed-switch classification (2026-10-10)

- The existing advisory switch classifier now marks cross-environment spec
  changes as locked rather than Class A. AI provider changes and external AI
  egress changes now require Class B deployment review and evidence instead
  of being labeled reversible runtime preferences. The existing pre-dispatch
  verifier and execution path remain unchanged; no second switch layer was
  added.
- Focused tier, switch, preflight, contract and runtime API suites pass (50
  tests), and Ruff passes on the changed Python files. This does not qualify
  automatic switch execution or substitute for signed production evidence.

## Increment: current-spend budget guard (2026-10-10)

- The existing advisory cost controller now uses the higher of current and
  projected monthly spend for warning and hard-limit decisions. A low forecast
  cannot mask an already-breached budget. Policy hard fractions may not exceed
  the declared monthly budget. No second cost-control path was added.
- Ten focused capacity/safety tests and Ruff pass. The phase-9 ledger now
  acknowledges the existing pure collector/forecast modules rather than
  listing them as absent. Durable measurements, calibrated forecasts, and
  qualified live autoscaling remain unimplemented.

## Increment: cost-gated autoscale eligibility (2026-10-10)

- The existing recommendation-only autoscaler now uses the existing cost
  controller before setting `eligible_for_scaling_policy`. A scale-out can
  remain visible as an advisory target, but missing/incomplete cost evidence,
  warning-level spend, or a breached budget cannot mark it eligible. Incomplete
  supplied inputs raise instead of silently bypassing the guard.
- Eleven focused capacity/safety tests and Ruff pass. No provider API calls,
  scaling executor, durable metrics or automatic activation were added;
  production scaling remains unqualified.

## Increment: strict DOCX ZIP member handling (2026-10-11)

- Hardened the **existing shared** DOCX archive validator used by S3/MinIO
  staged-upload promotion and knowledge ingestion. In addition to previous
  member-count, duplicate and expanded-byte checks it now rejects path
  traversal, absolute/drive/backslash/dot-segment members, case-insensitive
  duplicate package names, Unix symbolic links, encrypted members, and
  unsupported ZIP compression. Ordinary directory entries still pass.
- A self-contained local pytest reproduction of the changed ZIP-member
  predicates passed 12 tests. This was **not** the repository's full pytest
  suite, its Ruff gate, or a live object-store integration run. GitHub Actions
  still fails before executing runner steps; see issue #141.
- This is a package-structure guard, **not** antivirus/malware scanning,
  complete OPC validation, age-based retention, upload quota reservation,
  or production release authorization.

## Increment: clean-verdict gate before knowledge upload promotion (2026-10-11)

- Extended the existing staged-upload promotion path with a local ClamAV
  INSTREAM protocol adapter. Once SHA-256, version and MIME/signature checks
  pass, staging/production require an explicit clean antivirus verdict before
  copying the object into its permanent knowledge prefix.
- The connection is loopback-only to a local/private sidecar. Detected malware
  returns a generic upload rejection; unreachable, error, unknown or incomplete
  scanner verdicts block promotion. Files remain staged for policy-governed
  cleanup rather than being silently promoted or erased.
- KNOWLEDGE_CLAMAV_ENABLED defaults to false for development/test compatibility;
  staging and production refuse unscanned promotion. Operators must deploy,
  configure and qualify ClamAV (including signatures, StreamMaxLength, resource
  budgets and health alerting) before enabling protected uploads.
- Seven isolated ClamAV protocol cases passed locally. The added repository
  integration tests, full backend suite, Ruff gate and live ClamAV + S3/MinIO
  verification have NOT passed during this change; GitHub Actions is
  failing before step execution (issue #141).
- This is not proof of zero malware risk, retrospective cleaning of legacy
  objects, complete quota/retention enforcement or production release approval.

## Increment: opt-in Compose ClamAV knowledge-upload sidecar (2026-10-11)

- Added `compose.knowledge-clamav.yaml` as an optional override without
  changing the normal Compose services or their default startup. It configures
  the existing `api` to scan knowledge uploads and starts an official ClamAV
  image sharing the API network namespace; clamd binds only to loopback.
- The scanner has persistent FreshClam signatures, no published ports,
  bounded resources, and size-limit alerts rather than silent clean results.
  The existing knowledge-upload fail-closed gate remains the authority.
- Added read-only YAML contract tests and environment documentation; no Docker
  engine, ClamAV service, malware signature, live S3, or production AWS runtime
  was exercised. GitHub Actions remains blocked before runner execution (#141).
- Production image digests, real scan/timeout tests, health monitoring,
  rollout, retention, and release approval remain outstanding.

## Increment: tenant-scoped read-only conversation retention preview (2026-10-11)

- Added a bounded, tenant-and-workspace-scoped retention inventory using
  existing `Agent.security.retentionDays`, `Conversation` timestamps and the
  latest `Message.created_at`. No conversation/message content or visitor
  identifiers are fetched. Invalid policy, unknown timestamps and explicit
  local hold flags fail closed.
- An operator-only CLI uses a PostgreSQL READ ONLY transaction and tenant
  context, limits the inspected rows and emits provisional UUID identifiers
  and summary counts. External website privacy-rights `legal_hold` cases are
  **not integrated**; every preview requires external hold review.
- Added read-only policy/query regression tests and an operating guide.
  A standalone PostgreSQL SQLAlchemy SELECT compilation passed locally, but
  the actual repository test suite and real PostgreSQL/RLS behavior remain
  **unverified** while Actions fails before running jobs (issue #141).
- This is **not scheduled retention**, not a deletion executor, not a legal
  hold registry, not S3/Kafka/backup erasure, and not release authorization.
