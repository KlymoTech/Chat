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
- unit coverage for the contract and negative paths.

Not applied automatically because it requires approved infrastructure inputs:

- AWS accounts, regions, VPC/subnets, IAM roles, KMS keys, ECS/EKS resources;
- S3/SQS/SES/MSK/AppConfig provisioning and production DNS/TLS;
- production RPO/RTO, cost limits, workload sizing, compliance scope, and
  live-provider acceptance evidence.

The runtime must not treat this contract as permission to provision or delete
cloud resources. A future control-plane deployment planner can consume a
validated spec and produce an explicit, reviewable change plan.
