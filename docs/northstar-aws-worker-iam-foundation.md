# Northstar private deployment worker — AWS identity foundation

**Status:** Terraform IAM implementation only. Not approved for `terraform apply`.
This does not create an ECS cluster, ECS task, VPC, public/private load
balancer, RDS instance, public endpoint, signer, AWS executor, or production
credentials.

## Why the module exists

The Northstar architecture requires production to use AWS workload identity,
independent control-plane authorization, an audited execution worker, managed
secrets, and testable provider migrations. It also prohibits direct control-panel
shell commands and silent infrastructure mutations. The application worker
already has a separate Python entry point, private Unix-domain socket contract,
dedicated restricted PostgreSQL identity, short-lived Ed25519 JWT checks,
fenced step journal and append-only audit trail.

This module creates **identity only**, not deployment authority.

## Module

`infrastructure/terraform/modules/private_deployment_worker_identity`

| Identity | Allowed | Explicitly not provided |
| --- | --- | --- |
| ECS worker **task role** | ECS task-service trust in one account and region | No AWS API grants, no provider execution, no `iam:PassRole`, no `sts:AssumeRole` outbound grants |
| ECS **execution role** | ECR auth + pulls from one repository, log stream creation/writes for one group, optional exact bootstrap secrets and KMS decrypt through Secrets Manager with secret context | No Terraform/CloudFormation deployment API; no broad S3/ECS/EKS or IAM privilege |

Both roles are distinct, tagged for the approved environment, have
restricted ECS task-service trust and can use an organizational permissions
boundary. Inputs are validated, including the expected account/region for
ECR, logs, Secrets Manager and KMS references. ECR's authorization-token
action is the only intentionally unavoidable `Resource = "*"` in the execution
policy.

**Important:** absence of an IAM grant is not a substitute for reviewing
resource-based grants, SCPs, boundaries and trust relationships in the target
account. The task role is not certified for use until an independent IAM
review confirms that it cannot mutate cloud resources.

## Test-only reference stack

`infrastructure/terraform/examples/worker-identity` demonstrates connecting
the module to one pre-existing ECR repository and CloudWatch log group.
AWS provider account allowlisting prevents plans against an unexpected
account. The example intentionally does not supply real account IDs or
secrets and does not create the missing infrastructure.

The Terraform CI workflow:
- checks formatting;
- initializes without any remote-state backend;
- validates the module and reference integration;
- runs a mock-provider Terraform test;
- does **not** assume any AWS role or execute `plan` against an AWS account,
  `apply` or `destroy`.

## Required before deploying the real worker

1. **Separate environment stacks** for development, test, staging and
   production, with isolated AWS account boundaries and approved remote
   state+locking. No production state in a developer workspace.
2. Dedicated VPC, private application subnets, outbound controls, VPC
   endpoints and a private deployment-worker task definition. No public IP
   and no ALB forwarding deployment-worker actions to public tenants.
3. The existing Python runtime listens on **a Unix-domain socket only**.
   The approved in-task caller/proxy must share that socket locally; an
   ECS service in a separate task cannot simply make a TCP request to it.
   Do not change the runtime to bind `0.0.0.0` as a shortcut.
4. An audited, pre-provisioned secret-bootstrap mechanism: database DSN
   from managed Secrets Manager, two independent pinned **public** keys
   placed into safe read-only files, and private signing keys held in
   separate trusted services. The IAM module alone does not supply files.
5. Dedicated RDS role with the privileges documented in
   `docs/northstar-private-worker-db-role.md`, including actual role
   ownership and restricted schema/search path.
6. Certified Docker image digest, non-root runtime, readonly filesystem
   (with a dedicated writable socket volume), malware/CVE scan, shutdown,
   health and lease-fencing tests.
7. Proven infrastructure change workflow: independent approval, signed
   preflight, budget/backup/incident guards, canary, immutable audit export,
   forward repair and rollback. **Do not give this worker cloud change
   credentials** merely to pass a plan step.
8. Terraform state bootstrap, policy-as-code/IAM checks, integration tests
   in a disposable AWS test account, Jenkins qualification, capacity/DR
   evidence and operator approval before any production rollout.

Do not mistake this identity module, a successful `terraform validate`, or
mock-provider tests for AWS functionality or production certification.
