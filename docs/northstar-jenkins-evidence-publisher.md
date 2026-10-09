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
