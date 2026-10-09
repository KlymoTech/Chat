# Independent Northstar Jenkins qualification signer roles

This is an **additive, unapplied Terraform module** for two separate IAM
assumed-role boundaries. It is not the Jenkins controller, a signing service,
an Ed25519 key generator, or proof of production qualification.

## Trust separation

| Role | May be assumed only by | Secret access | KMS decryption |
|---|---|---|---|
| `<prefix>-test-certification-signer` | Existing, independently reviewed **test signer agent** | One exact **pre-existing test attestation** secret ARN | One exact test key, **only via Secrets Manager** with that secret ARN encryption context |
| `<prefix>-release-manifest-signer` | Existing, independently reviewed **release authority agent** | One exact **pre-existing release signer** secret ARN | One exact release key, **only via Secrets Manager** with the release secret's ARN encryption context |

Neither role can upload evidence to S3, assume the publisher role, deploy
infrastructure, use long-lived IAM user access keys, or read the other
signer's private key through this module's IAM policies. Their distinct
parent agent roles, secrets and encryption keys are checked at plan time.
The pre-existing publisher agent is also an explicit input so its identity
cannot silently become either signer's agent.

Both signer roles have mandatory **externally governed signer permissions
boundaries** and a maximum 3600-second assumed session. The trust policies
pin an exact IAM principal and a different `sts:RoleSessionName` prefix:
`northstar-test-jenkins-*` or `northstar-release-jenkins-*`.
A session name alone is **not** proof of Jenkins run provenance. Before use,
the independently maintained agent trust policies must enforce the intended
Jenkins job identity and isolate workloads at the host/pod level.

The publisher already has its own dedicated role and S3/KMS scope under
`../jenkins_qualification_evidence/`. Do not merge that IAM policy into
either signer. The independent qualification proof issuer, separate
governance reviewer and production deployer retain separate roles.

## Security prerequisites before an approved apply

1. Provision **three separate pre-approved parent workloads**: evidence
   publisher, attestation signer and release signer. Verify their respective
   IAM principals and session-issuance protections independently.
2. Provision **two independently encrypted Ed25519 private signing secrets**
   outside Terraform with independent Secrets Manager/KMS administration.
   This module never accepts private key bytes and never writes secret values.
   Their account/region and exact ARNs must match the inputs. KMS key policies
   must allow only the correct role and service context.
3. Apply a signer-specific permissions boundary that prevents unrelated
   permissions even if someone later attaches additional IAM policies.
   The module requires the boundary ARN but **does not create or validate
   its contents**. Confirm that signers cannot publish, deploy, change IAM,
   read another secret or delegate identity.
4. Establish key rotation, revocation, public-key pinning and verified
   signer identity in the separate signing service and certificate policy.
   This Terraform module provisions only AWS IAM access control boundaries.
5. Require signed test results to be independently checked before publishing.
   Sign the release manifest **after** S3 has durably stored and read back the
   attestation version; release signing must not reuse the test agent.
6. Apply from a reviewed infrastructure release in the qualification AWS
   account, with remote state, CloudTrail, KMS audit, workload isolation and
   approved rollback/recovery procedures. No feature-branch CI job may apply.
7. Independently test real IAM AssumeRole denial, wrong-secret denial,
   KMS ciphertext separation, key rotation, attempted cross-role access,
   audit visibility, and emergency revocation.

## Validation

The no-credentials GitHub Actions gate in
`.github/workflows/northstar-terraform-qualification-signers.yml` runs
`terraform fmt -check`, `init -backend=false`, `validate` and mocked
`terraform test`. Its reference wiring lives in
`infrastructure/terraform/examples/qualification-signers/`.

A mocked Terraform test verifies the structural plan, **not** the actual
security of AWS IAM, Jenkins workloads, KMS key policies, or pre-existing
Secrets Manager secrets. Actual Terraform execution and live AWS tests
remain outstanding.

No Jenkins signing task, production rollout, tenant API, proof issuance,
qualification approval or notification worker is started by these roles.
