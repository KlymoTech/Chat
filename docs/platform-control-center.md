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
  - `POST /api/v1/platform-admin/runtime/changes/{id}/approve`
  - `POST /api/v1/platform-admin/runtime/changes/{id}/reject`
- Change requests are idempotent, persisted with immutable source/target
  digests, and require a different platform operator to approve them.
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

1. Add an outbox-backed deployment executor with fencing, reconciliation,
   rollback, and drift detection.
3. Bind the registry to real health probes and required/optional readiness.
4. Add Terraform/Helm/GitOps adapters and environment-specific policies.
5. Run repeatable load, restore, failover, security, and chaos tests against
   the exact release SHA.

Until those gates pass, the application should not be marketed as a fully
qualified AWS production platform.
