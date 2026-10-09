# Jenkins protected release-evidence publisher — gated integration contract

**Implementation:** `backend/src/northstar_api/modules/platform_runtime/aws_jenkins_evidence_publisher.py`  
**Status:** server-side publishing adapter and regression tests committed. **Not provisioned, deployed or release-qualified.**  
**Branch:** `feature/northstar-adaptive-architecture-20261008`

## Source of authority

The Northstar AI master plan requires Jenkins virtual qualification, independently
verified signed results, immutable evidence in `evidence/<release-id>/`, isolated AWS
qualification, and independent production approval. The Jenkins preflight currently
does **not** issue signing proofs, upload files, apply Terraform or activate workers.

## Roles and boundaries

1. **Test runner signer (separate principal):** produces an Ed25519-signed
   certification result for the exact run, branch, Git SHA, environment and
   source/target digests. The publisher receives only its pinned public key.
2. **Release authority signer (separate principal):** signs a release manifest
   referencing the exact, previously retained attestation object *version*,
   SHA-256 checksum and immutable OCI image digest. The publisher receives only
   this pinned public key.
3. **Jenkins evidence publisher (new adapter):** uses AWS workload credentials,
   verifies `sts:GetCallerIdentity` against an exact AWS account, assumed-role
   name and run-specific STS session name `northstar-evidence-<run-id>`,
   and rejects other branches. It checks the release signature before
   invoking the existing S3 writer. It then reads back the exact locked
   manifest version and only returns success if the receipt matches.
4. **Independent governance reviewer (existing):** separately verifies the
   committed evidence link and issues approval. Publishing does **not**
   approve, revoke, deploy, enable workers or change tenant state.

The expected release ID, Git SHA, OCI digest, branch, environment and signer
public keys must come from a protected immutable release plan. The publisher
does not derive trusted values from the signed token or mutable job parameters.

## Required AWS/Jenkins configuration before enabling publication

- Provision a dedicated Jenkins publisher workload role with a *reviewed* and
  narrowly restricted STS trust policy. Jenkins branch checks and session
  names are defense in depth: an IAM trust policy must independently prevent
  an attacker from assuming the publisher role or spoofing a valid session.
- Pin the allowed AWS account and region; grant only the required
  `s3:PutObject` and version-scoped `s3:GetObjectVersion`/metadata
  operations to one evidence bucket/prefix, with Object Lock permissions only
  as justified. Do **not** grant broad AWS deployment rights, `iam:PassRole`,
  or access to private test/release signing keys.
- Use a dedicated KMS key with restrictive encrypt/decrypt context and
  necessary least-privilege data key permissions; verify the S3 bucket has
  versioning, COMPLIANCE Object Lock, a qualified minimum retention period,
  Block Public Access, and tested cross-account deletion denial.
- Host the publisher in a private, reviewed Jenkins agent or separate
  internal service, with short-lived AWS credentials; do not store long-lived
  AWS keys in Jenkins files, Git, containers or environment dumps.
- Pass only independently signed, verified artifacts into
  `publish_verified_release_manifest`. **Do not call this publisher from a
  public API**. There is currently no callable production entry point.
- Have the protected signer bind the manifest to the attestation's original
  S3 `VersionId`. Therefore the attestation must be published and read back
  **before** the release signer emits the manifest.
- Treat an S3 conflict or unknown write/read-back outcome as blocking:
  **no automatic upload retry, overwrite or latest-version substitution**.
  An operator must independently reconcile the exact version.
- Keep all tests, AWS mutation, release approval, rollout and worker activation
  separated from this one publishing step.

## Gates still missing

1. Real Jenkins Configuration as Code, reviewed ephemeral agents and workload
   identity issuance; supply chain checks, branch policy and source pinning.
2. Isolated attestation uploader and protected signing services, with key
   rotation and revocation, independent approvals and evidence provenance.
3. Terraform evidence bucket, IAM, KMS and CloudTrail policies, isolated AWS
   staging tests, retention and disaster-recovery qualification.
4. Full master-plan qualification bundle (SBOM, build provenance, functional,
   security, load, resilience, migration, DR, observability and cost) and
   read-back validation of each referenced immutable artifact.
5. Durable publisher attempt/audit log and idempotent reconciliation after
   unknown S3 outcomes, automated safe approval-link staging, and verified
   rollback/forward repair.
6. Passing full repository CI, database migrations, live AWS qualification
   and recorded independent security/operations go-live approvals.

**Never infer production readiness or successful publication from a mocked
regression test, a GitHub commit or a Jenkins preflight check.**


## Increment: independently signed attestation publishing boundary

A protected publisher now has a separate, fail-closed first-stage publishing
contract in `aws_jenkins_attestation_publisher.py`:

1. Require the same reviewed `AwsJenkinsEvidencePublisherIdentity` for the
   exact run and feature branch; its AWS IAM trust policy remains an external
   prerequisite and must be verified independently.
2. Require the **independently signed** test-runner Ed25519 attestation with
   exact run, source commit, environment and source/target digests. The issuer
   private key must not be available to the publisher.
3. Call the existing `AwsImmutableCertificationArtifactStore` with compliance
   Object Lock, SSE-KMS and a conditional `IfNoneMatch=*` write for
   `evidence/<release-id>/jenkins/<run-id>/certification-attestation.token`.
4. Read back the **same version** via
   `ReadOnlyCertificationArtifactReconciler`, verifying exact bytes, checksum,
   retention and encryption. Return its versioned receipt only on success.
5. Make a separate release authority sign the resulting exact receipt into
   the release manifest, then use `publish_verified_release_manifest`
   to verify/write/read-back that immutable manifest.

**Limitations:** Both publishing steps are server-side libraries, not active
Jenkins jobs. They do not generate real signed test results, create AWS roles,
issue credentials, migrate database records, approve evidence or deploy.
No automatic retry is allowed after a possibly successful S3 write. A failed
readback requires operator reconciliation, not an overwrite or selecting
the latest object version. Passing local mocks is not AWS qualification.

The existing root `Jenkinsfile` is still a **no-credentials, non-publishing
preflight**, and its new test hook only runs the publishing contract tests.
A future protected job needs separately audited machine authentication,
private agent isolation, pinned release coordinates, two separate signing
services, actual AWS bucket/KMS/IAM policy review, complete qualification
bundle retention, and end-to-end tests before being enabled.


## Increment: independent test/release signer IAM isolation (2026-10-10)

New additive Terraform module:
`infrastructure/terraform/modules/protected_qualification_signers/`.

- Two dedicated short-session IAM roles now have different *pre-existing*
  agent trust principals. Neither trusts the Jenkins publisher agent or
  the other signer's agent. Trust pins `aws:PrincipalArn` and uses distinct
  `sts:RoleSessionName` patterns. Those session names are only defense in
  depth, not verifiable source-commit/build provenance.
- The test signer role has `secretsmanager:GetSecretValue` on **only** its
  pre-existing Ed25519 attestation secret, and `kms:Decrypt` on **only**
  its pre-existing test KMS key, restricted by `kms:ViaService` and
  `kms:EncryptionContext:SecretARN`.
- The release signer role has the corresponding independent release
  secret and KMS key. Each role is subject to a mandatory, independently
  controlled signer permissions boundary. No secret value or private key
  is entered into Terraform state or repository source.
- There are no AWS resource, S3 evidence, IAM mutation or production
  deployment grants in either signer's inline policy.
- Mock Terraform tests check trusted role separation, distinct secrets,
  different KMS keys, correct account/region, ARN validation and
  permission boundaries. Backend security-policy tests inspect the
  actual authored trust/secret policies. A separate GitHub Actions
  workflow is non-deploying and has no AWS credentials.

**Not yet implemented:** protected Jenkins attestation/release signer
services, signer lifecycle and public-key pinning, workload identity
issuance, live AWS KMS/Secrets Manager/IAM permissions tests, explicit
organization permissions boundary definitions and comprehensive CloudTrail
auditing. The module is **unapplied**; actual CI success is unconfirmed.


## Increment: AWS-backed Ed25519 signer key access (2026-10-10)

Added `aws_protected_qualification_signer.py`, an internal-only credential
boundary matching the separately governed test and release signing IAM roles.

- The test signer must run with the exact `<prefix>-test-certification-signer`
  assumed role and a `northstar-test-jenkins-<run-id>` STS session.
- The release signer must run with the exact `<prefix>-release-manifest-signer`
  assumed role and a `northstar-release-jenkins-<run-id>` STS session.
  The adapter rejects names exceeding the 64-character AWS session limit.
- Before contacting Secrets Manager, the adapter checks the actual STS
  account, assumed role ARN, session and UserId alongside the independently
  approved branch. No broad or wildcard IAM identity is accepted.
- It requests one exact existing secret ARN at `VersionStage=AWSCURRENT`,
  accepts only binary PEM PKCS#8 Ed25519 private key material, and rejects a
  missing version label, mismatched ARN, unsupported key algorithm, invalid
  PEM or rotated key with a public half that is not explicitly pinned.
- Failure returns `None` without including IAM/secret details in an
  application error. The key object is returned **only to a separately
  authenticated internal signing process**, never through a public HTTP
  endpoint or Jenkins agent workspace.
- Standard AWS and GovCloud partitions are supported.

**This does not yet sign certification results or release manifests.**
Independent Jenkins test-result provenance and immutable release evidence
validation MUST occur before any private key is used. A matching STS session
string is not sufficient proof that the requested test suite really ran.
A compromised publisher role must remain unable to assume either signer
role or to read either secret; this requires live IAM trust and KMS policy
verification, not just the Python runtime identity check.

27 focused local tests passed against mocked STS/Secrets Manager clients and
locally generated Ed25519/RSA test keys. This is **not** a passing repository
CI run, real AWS IAM test, key-rotation certification, or live signing service.
The existing Jenkinsfile only runs the unit tests and does not gain
signing credentials, AWS mutation permissions or qualification approval.


## Increment: independently witnessed Jenkins test-result provenance (2026-10-10)

A new verification-only contract in
`queue_notification_jenkins_test_provenance.py` requires that a **separate,
pinned Jenkins witness authority** sign a v1 run statement for the exact
approved Jenkins controller, job, run, branch, environment, Git commit,
source/target configuration digests and observed run times. The witness key
must differ from the test-attestation signer key.

The witness must commit to SHA-256 hashes and test counts of the **three
mandatory** raw JUnit XML reports: `notification_worker`,
`notification_egress` and `notification_secrets`.

Verification refuses:

- Absent, extra, repeated or malformed suite evidence; hash mismatches;
  unqualified XML, missing test cases, skipped/failing/error test cases,
  conflicting suite counts, XML DTD/entity declarations and oversized
  report bytes.
- Incorrect or replayed job/run/branch/build/environment coordinates,
  an untrusted witness key, forged signatures, duplicate signed JSON
  fields, timestamps in the future or older than 15 minutes, or a report
  duration exceeding two hours.
- Reuse of the test-signing public key as the supposedly independent
  Jenkins witness public key.

The returned value records validated metadata and suite counts only. No
private key is read, no certification token is signed, no object is
published and no worker or qualification is activated.

**Required separate work before permitting signing:**

1. Implement and review an isolated witness producer under a
   separately governed Jenkins job/controller identity and protected
   workload-authentication policy. The signer MUST NOT accept witness
   assertions from a shared unprotected Jenkins workspace or request.
2. Store and independently read the raw JUnit reports under immutable,
   version-fenced S3 receipts; the reports passed to this gate currently
   come from the calling component. Matching a signed digest alone does
   not prove that the reports came from a qualified isolated test execution.
3. Bind the witnessed report hashes and witness identity to durable release
   evidence with rollback/replay protection and a witnessed build-run
   uniqueness constraint. Independently qualify key rotation/revocation.
4. Connect the verified provenance to a private, independently authenticated
   signer service and produce the existing Ed25519 v1 certification token
   format only AFTER this gate and the exact AWS signer credential gate pass.
   Re-verify that resulting signature against the pinned test signer key.
5. Run the full suite in repository CI and on the isolated Jenkins controller.
   The new tests are committed and scheduled; no passing CI or live Jenkins
   proof has been confirmed from this development session.

This is a **verification boundary, not a complete certification or
production signing service**.


## Increment: immutable witnessed JUnit report storage and exact S3 readback (2026-10-10)

Two new internal-only components protect the source evidence used by the
independent Jenkins witness verifier:

- `aws_immutable_jenkins_junit_store.py`: requires the existing
  `PublicationIdentity.verify(run_id, branch)` AWS identity gate and
  validates **all three** independently signed, pinned JUnit reports
  *before the first write*. It conditionally uploads each suite to
  `evidence/<release-id>/jenkins/<run-id>/junit/<suite>.xml`,
  storing SHA-256, witness SHA-256, exact build/run metadata,
  `IfNoneMatch=*`, SSE-KMS, and COMPLIANCE Object Lock with a
  minimum-retention safety margin. Each successful upload returns a
  receipt naming its original S3 `VersionId`.
- `aws_jenkins_junit_reconciliation.py`: checks exactly those three
  externally pinned receipts; each S3 `head_object` and
  `get_object` is requested with its original `VersionId`.
  It checks bucket/key, locked retention, KMS key, report bytes and hash,
  signed-witness hash and exact job/build metadata, then re-verifies the
  independent Ed25519 witness over **the bytes read from S3**.

The complete result is a `VerifiedJenkinsProvenance` value. It does NOT
contain or unlock signing credentials. The root `Jenkinsfile` invokes
only regression tests; it does not upload files or contact AWS.

**Partial-write constraint:** The three reports are separate S3 objects;
S3 provides no atomic multi-object commit. If a later report write fails,
earlier writes remain immutable. No retry, overwrite, reconstructed
receipt, or use of the latest unversioned key is automatic. Operators must
reconcile with externally controlled receipt state and restart from a new,
reviewed release/run after incomplete attempts.

**Remaining required production gates:** protect and persist all original
suite receipts under an independent release/run record; independently
qualify the witness issuer and signature lifecycle; add an isolated test
executor and authenticated Jenkins report publication job; verify S3
Object Lock/KMS/IAM in live AWS; implement replay prevention and recovery
for partial archives; retain the signed witness itself; connect the
**verified** readback result to a separately authenticated private
Ed25519 signer service. Source metadata and release IDs must come from
a protected immutable build plan, not tenant-supplied parameters.
A mock-S3 passing test is not evidence that live S3 retention or AWS trust
policies work correctly.


## Increment: immutable witnessed JUnit evidence index (2026-10-10)

Added an additive server-only S3 index adapter:
`aws_jenkins_junit_evidence_index.py`.

The index stores the exact independently signed witness token, release ID,
Jenkins run, branch, environment, Git source commit, source/target digests,
witness body SHA-256 and all three original JUnit
`{bucket,key,version_id,sha256}` receipts in one canonical JSON object at:

`evidence/<release-id>/jenkins/<run-id>/junit/verified-index.json`

Publication requires the dedicated AWS publisher's STS role/session identity
and a full read-only reconciliation of the three **original** versioned
JUnit S3 objects against the independent witness. Only then may the
publisher create the index using `IfNoneMatch=*`, pinned SSE-KMS,
COMPLIANCE Object Lock, SHA-256 checksum and explicit per-object retention.
It never overwrites a conflicting index and does not retry an unknown
S3 write. The returned `JenkinsJunitIndexReceipt` includes the exact
index `VersionId` and checksum.

Readback requires an **externally trusted**, original index receipt AND
three externally trusted original report receipts. It revalidates all
three pinned report versions and the witness signature, reconstructs
the exact expected canonical index JSON, and checks the exact index S3
version, compliance lock, KMS identity, metadata and all bytes. It never
uses a latest/unversioned key or reconstructs trust from index contents.

**Remaining controls:** original receipt/index receipt custody in a
separately protected persistent qualification ledger, independent witness
producer and identity, durable idempotent partial-write incident handling,
full IAM and S3 Object Lock qualification, and a signer service that uses
the validated index only after authenticated build authorization. The
current witness verifier enforces a 15-minute freshness window; historical
audit and long-term replay-resistant verification must be designed
separately before treating archived objects as perennial proof.

The unit tests use a fake S3 implementation and real generated Ed25519
witnesses. An offline Jenkins test hook does not upload to AWS, sign
results or approve worker startup. No release signing authority or
production notification credentials are exposed.
