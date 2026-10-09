# Northstar Jenkins qualification evidence — Terraform foundation

This **isolated additive module** prepares AWS storage and a least-privilege
publishing role for signed Jenkins certification evidence. It does **not**
create a Jenkins controller, test-runner private key, release-signer private
key, production deployment, approval, or notification worker.

It implements the evidence path required by the Northstar Chat AI Master
Implementation Plan v2.0: `evidence/<release-id>/`.

## Resources

- S3 bucket with Object Lock enabled **at creation**, versioning, default
  COMPLIANCE retention of at least 90 days, no force-destroy, public-access
  blocks, bucket-owner enforcement and dedicated KMS encryption.
- Bucket policy denies non-TLS access, object deletion, unqualified
  non-conditional writes, missing/wrong SSE-KMS headers and wrong KMS key.
  Publisher libraries already use `IfNoneMatch="*"` and the explicit
  `ObjectLockMode="COMPLIANCE"` and retention parameters.
- Dedicated customer-managed KMS key with key rotation, prevent-destroy,
  30-day deletion window and AWS-account-owner administration. The publisher
  IAM policy permits only `kms:GenerateDataKey` and `kms:Decrypt` through
  S3 for evidence-prefix object encryption contexts (S3 Bucket Keys disabled).
- Dedicated publisher IAM role with **mandatory** externally managed
  permissions boundary. Trust is restricted to the exact reviewed Jenkins
  agent role ARN plus `aws:PrincipalArn` and run-scoped
  `sts:RoleSessionName = northstar-evidence-jenkins-*`.
- Publisher S3 IAM grants are limited to `s3:PutObject`,
  `s3:PutObjectRetention` and `s3:GetObjectVersion`, scoped to one
  `evidence/*` prefix. No S3 deletion, broad KMS, Secrets Manager,
  ECS/EKS or production deployment grants.

## Requirements before plan or apply

1. Use a **separate qualification AWS account** with a dedicated Terraform
   state backend, independently reviewed change approval and versioned state.
2. Provision and review the existing protected Jenkins agent role and
   organization-enforced IAM permissions boundary. The module **does not**
   create either. The agent's **own** permission to assume the publishing
   role must be separately reviewed.
3. Confirm IAM trust policies cannot be modified by untrusted pipeline
   jobs; verify the agent cannot assume the independent signing, proof-issuer
   or production deployment roles.
4. Use short-lived AWS credentials and set the caller AWS provider's
   `allowed_account_ids` and region. The module also checks live
   `aws_caller_identity` and `aws_region` at plan/apply time.
5. Review the minimum retention value and object-lock rules. COMPLIANCE
   retention cannot be shortened or bypassed by the publisher; even the
   account root cannot remove retained object versions while protected.
6. Obtain explicit Security/Operations approval for CloudTrail S3 data
   events, KMS policy boundaries, evidence read access, an encrypted
   audit/log archive and cross-region backup/restore evidence. Those
   supporting controls are **not** provisioned here.
7. Apply only from a separately approved infrastructure release pipeline,
   never from the feature-branch GitHub Actions validation or root Jenkins
   preflight. The CI gate does **not** require AWS credentials.

Reference wiring is in
`infrastructure/terraform/examples/qualification-evidence/`.

## Required publication sequence

1. Independent test runner signs passing certification results.
2. Protected publisher stores the *signed attestation*, and reads back the
   exact version with compliance retention and KMS verification.
3. Separate release signer signs the manifest against that exact version ID,
   release ID, Git commit, OCI image digest, environment and source/target
   configuration hashes.
4. Protected publisher writes the locked release manifest conditionally and
   reads back its exact version.
5. Separate governance service verifies both receipts and stages the
   immutable PostgreSQL release link; an independent reviewer must approve.
6. Only then may separately qualified runtime admission check short-lived
   worker proofs. These infrastructure objects **never** enable workers.

No automatic retry or alternate object-key publishing may follow an
unknown S3 write result. Retained objects must be reconciled by their
original version IDs. Neither a committed Terraform plan nor a mocked
Terraform test is proof of a live AWS qualification.

## Validation commands (no apply)

```bash
terraform fmt -check -recursive infrastructure/terraform/modules/jenkins_qualification_evidence infrastructure/terraform/examples/qualification-evidence
terraform -chdir=infrastructure/terraform/modules/jenkins_qualification_evidence init -backend=false -input=false
terraform -chdir=infrastructure/terraform/modules/jenkins_qualification_evidence validate
terraform -chdir=infrastructure/terraform/modules/jenkins_qualification_evidence test
terraform -chdir=infrastructure/terraform/examples/qualification-evidence init -backend=false -input=false
terraform -chdir=infrastructure/terraform/examples/qualification-evidence validate
```

**Incomplete:** no running Jenkins integration, reviewed IAM permission-boundary
document, KMS key rotation recovery, S3 Object Lock live test, CloudTrail
data-event archival, replication/DR, full qualification suite or completed
GitHub Actions validation has been demonstrated here.
