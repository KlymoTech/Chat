# Platform control center

The supplied architecture notes describe a DevOps switch panel. They are
design requirements, not proof that AWS accounts, Terraform, Step Functions,
or live deployment evidence exist. This repository now implements the safe
provider-neutral portion of that design.

## Implemented locally

- A single capability catalog covers core, data, messaging, AI, runtime, and
  observability capabilities.
- Every capability declares whether it is required or locked, its provider
  choices, fallback, and dependencies.
- A deterministic dependency graph is exposed for impact analysis.
- Desired state is separated from observed health (`on/off` versus
  `healthy/degraded/unhealthy/unknown`); optional providers can be disabled
  without making the whole catalog unhealthy.
- Change planning classifies hot-safe, restart, migration, prohibited, and
  stale-revision changes. It never executes infrastructure mutations.
- Super-admin read endpoints are available at:
  - `GET /api/v1/platform-admin/runtime/capabilities`
  - `GET /api/v1/platform-admin/runtime/dependencies`
  - `GET /api/v1/platform-admin/runtime/capacity?api_replicas=N`
  - `POST /api/v1/platform-admin/runtime/changes/plan`
  - `POST /api/v1/platform-admin/runtime/changes`
  - `GET /api/v1/platform-admin/runtime/changes`
  - `GET /api/v1/platform-admin/runtime/changes/{id}`
  - `GET /api/v1/platform-admin/runtime/changes/{id}/executions`
  - `POST /api/v1/platform-admin/runtime/changes/{id}/executions`
  - `POST /api/v1/platform-admin/runtime/changes/{id}/approve`
  - `POST /api/v1/platform-admin/runtime/changes/{id}/reject`
- Change requests are idempotent, persisted with immutable source/target
  digests, and require a different platform operator to approve them.
- Approved changes are also emitted through the transactional outbox as
  `platform.runtime.change.approved.v1`. The event carries the immutable
  source/target digests, revisions, idempotency key, plan steps, and serialized
  specifications for a deployment controller or GitOps worker. The event shape
  is validated by a strict provider-neutral contract, and execution evidence
  can be reported idempotently by stage and read back from the control center.
  Digest matching and lifecycle transitions reject stale or out-of-order
  reports. The API never applies Terraform or treats event publication as
  deployment completion.
- The existing platform-admin RBAC protects the endpoints. API keys are not
  accepted by the platform control plane.
- The super-admin page shows the declared profile, providers, and health state.

## Deliberately not automatic

The control plane does not stop containers, delete AWS resources, rotate
secrets, apply Terraform, or assume administrator credentials. Those actions
require an approved deployment controller/GitOps pipeline with environment
policies, least-privilege roles, change approvals, smoke tests, rollback, and
live evidence.

## Next production gates

1. Add provider adapters to the deployment executor consuming the approved
   outbox event, with fencing, reconciliation, rollback, and drift detection.
2. Bind the registry to real health probes and required/optional readiness.
3. Add Terraform/Helm/GitOps adapters and environment-specific policies.
4. Run repeatable load, restore, failover, security, and chaos tests against
   the exact release SHA.

Until those gates pass, the application should not be marketed as a fully
qualified AWS production platform.
