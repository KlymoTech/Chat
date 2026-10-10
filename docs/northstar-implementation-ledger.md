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
  missing deploy/image-push targets and an Arm64-only API image declaration.
  Adding placeholder targets or an unbuilt x86 label would not satisfy the
  corresponding runtime and image qualification rules. Keep these gaps open
  until real workflows and builds are implemented and tested.

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
