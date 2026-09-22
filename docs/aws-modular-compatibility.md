# AWS modular specification compatibility

The supplied AWS Modular Platform Implementation Specification is a proposed
target, not evidence that AWS resources or a production deployment exist in
this repository. The compatible, provider-neutral part is implemented in
`backend/src/northstar_api/modules/platform_runtime/`.

The contract validates desired platform state, semantic dependencies, and
provider-change classes without importing AWS SDKs or requiring cloud
credentials. It is intentionally additive; the current local Docker profile
continues to use the existing PostgreSQL, RabbitMQ, Redis, Kafka, and MinIO
adapters.

Implemented locally:

- strict `PlatformSpec` configuration contracts with forbidden unknown keys;
- explicit local, ECS/AWS-standard, and EKS/AWS-Kubernetes profiles;
- cache, jobs, events, storage, identity, search, vector, notification,
  secrets, and AI provider declarations;
- dependency validation for RAG, optional resources, AWS-only providers,
  authorization, tenant isolation, and audit invariants;
- deterministic dependency graph generation;
- hot-safe, restart, migration, and prohibited provider-change classification;
- immutable desired-state digests and a reviewable `ChangePlan` contract;
- monotonic revision checks that reject stale plans before an adapter can apply them;
- migration plans that require approval and include freeze, copy/verify, cutover,
  reconciliation, and observation steps;
- restart plans that require worker draining/fencing and post-rollout verification;
- immutable OCI image digest validation (`sha256:...`), AWS account/region
  requirements, and explicit ECS/EKS profile contracts;
- a provider-neutral capability registry with locked core capabilities,
  fallbacks, health state, and dependency-aware impact analysis;
- protected super-admin read/plan endpoints for the control center:
  `/platform-admin/runtime/capabilities`, `/dependencies`, and
  `/changes/plan`;
- durable platform capability/change/configuration tables with idempotency,
  approval records, separation of requestor and approver, and deployment
  execution evidence slots with idempotent report keys and source/target
  digest checks;
- persisted change request/list/approve/reject endpoints; approval does not
  execute infrastructure and remains compatible with GitOps handoff. Approved
  plans are emitted as `platform.runtime.change.approved.v1` through the
  transactional outbox so a deployment controller can consume the exact
  immutable plan inputs. A strict provider-neutral event contract and an
  execution-evidence read/report endpoints are included; they validate stage
  ordering and do not perform AWS mutations;
- unit coverage for the contract and negative paths.

Not applied automatically because it requires approved infrastructure inputs:

- AWS accounts, regions, VPC/subnets, IAM roles, KMS keys, ECS/EKS resources;
- S3/SQS/SES/MSK/AppConfig provisioning and production DNS/TLS;
- production RPO/RTO, cost limits, workload sizing, compliance scope, and
  live-provider acceptance evidence.

The runtime must not treat this contract as permission to provision or delete
cloud resources. The provider-neutral planner now produces an explicit,
reviewable change plan, but a separately approved deployment controller is
still required to execute it against AWS. No AWS account, credential, or live
resource is assumed by this repository.
