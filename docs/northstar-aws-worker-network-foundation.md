# Northstar private deployment worker — AWS networking foundation

**Status:** Terraform module and mocked validation only; NOT approved for `terraform apply`, live traffic, or production AWS execution.

## Scope and authority

The v3 standard requires governed changes, private application workloads, AWS-only production and no blind deployment-controller fallback. The Northstar master plan places networking and IAM in Phase 4 and the full ECS profile in Phase 5. This increment does not change `main` or enable an AWS mutation API.

Module: `infrastructure/terraform/modules/private_deployment_worker_network`
Example: `infrastructure/terraform/examples/worker-network`

| Resource | Behavior |
| --- | --- |
| Worker security group | No inbound rules. Dedicated egress to RDS SG TCP/5432, worker-only interface endpoint SG TCP/443, and S3 managed prefix list TCP/443 |
| Endpoint security group | Dedicated SG permitting TCP/443 exclusively from worker SG; no broad ingress |
| AWS interface VPC endpoints | ECR API, ECR Docker registry, CloudWatch Logs, Secrets Manager, STS; optional KMS, all with private DNS |
| S3 gateway endpoint | Associated with supplied private route tables for ECR image-layer download |
| Existing VPC/subnets/RDS SG | Caller-supplied, with VPC consistency, disabled automatic public IP assignment and minimum two AZs checked through AWS data |

**No ALB, NAT gateway, internet gateway, public-IP assignment, open inbound rule, SSH, or deployment executor is created by this module.**

## Integration with the existing worker

1. Provision a dedicated private VPC and at least two private application subnets in different Availability Zones, with reviewed route tables and DNS resolution enabled.
2. Confirm that the subnet route tables **do not** contain an unexpected internet-gateway path or a public default route. Terraform verifies `map_public_ip_on_launch = false`, but that does **not prove** a subnet is private.
3. Use the module outputs for ECS task `network_configuration`: `security_groups = [worker_security_group_id]`, `subnets = private_subnet_ids`, and `assign_public_ip = false`. ECS deployment infrastructure is not yet included in this increment.
4. Separately approve a narrow RDS inbound rule allowing only the worker SG on PostgreSQL port 5432. The networking module intentionally does **not** alter a shared RDS security group.
5. Restrict VPC endpoints by endpoint policies, IAM boundaries and private DNS review. A VPC endpoint network path does not authorize secrets or API mutations. The worker task IAM role still has no AWS mutation grants.
6. Ensure ECR and S3 gateway routes work without public NAT. The image pull uses the ECS execution role, not the application worker task role.
7. Provide the database URL and pinned independent public keys through a controlled Secrets Manager bootstrap. Task-injected secrets should be narrowly authorized, audited, rotated, and never checked into source.
8. Confirm the application's separate Unix-domain socket remains accessible only to an authorized local caller. A VPC security group does **not** directly protect access to a Unix-domain socket; filesystem ownership/permissions and workload isolation remain mandatory.

## Pre-apply and release gates

- Independent review of VPC IDs, actual subnet routes, security group ownership, two-AZ placement, AWS account/region, endpoint availability and cost.
- Planned private endpoint access only to required services. No broad outbound to `0.0.0.0/0` or `::/0`, and no public security-group ingress.
- Terraform remote state encryption, isolation and locking, approved IAM runner and change ticket; never apply from the repository CI.
- Disposable AWS-account integration test: ECR image pull, S3-layer download, CloudWatch logging, short-lived credential retrieval, PostgreSQL TLS, isolation from public internet, route failover, worker token and database-role checks.
- Backup/restore, audit WORM export, production IAM permission evaluation, cost alarms, security review and independently approved deployment/rollback plan.

## Scope not yet implemented

Actual VPC/subnet/route-table creation, ECS/Fargate task definition and service,
RDS resource provisioning, controlled secret injection and rotation, private local
caller/proxy, WORM audit export, Jenkins qualification, provider executors,
rollback/forward-repair workflows, scaling and production capacity testing.

The Terraform validation tests prove syntactic/model contracts only; they do not certify any AWS network, security posture, availability target or throughput.
