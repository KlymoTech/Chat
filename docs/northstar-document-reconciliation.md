# Northstar architecture document reconciliation

This branch implements the attached architecture documents incrementally. The
documents are design instructions and acceptance criteria; they are not shell
commands, credentials, approval to provision AWS, or evidence that a target
capacity/security/recovery claim has been measured.

## Authority used for this branch

1. Non-overridable safety, tenant-isolation, audit, secret-handling, and
   recovery requirements.
2. The unified/adaptive standards' conflict resolutions and governed tier model.
3. The pluggable AWS specification's ports, adapters, control-plane, and IaC
   requirements.
4. The Northstar implementation plan's repository mapping and phased delivery.
5. The scale-to-zero playbook's cost-aware Stage 0 defaults where they do not
   conflict with the stricter safety rules.

The two production-grade AWS specification copies share the same title and
opening contract. Their full contents still need a section-level comparison
before either is treated as a duplicate. The Markdown backend standard is an
additional source for requirements; its overlap with the DOCX has not been
fully audited.

## Implemented on this feature branch

- Provider-neutral capability catalog and dependency validation.
- T0–T4 tier metadata and adjacent, evidence-gated transition planning.
- Governed switch classes, qualification gates, desired/observed state, and
  durable deployment leases/step/audit controls.
- PostgreSQL, SQS, and RabbitMQ queue adapters plus outbox/event contracts.
- Private deployment-worker IAM/network Terraform foundations and Jenkins
  qualification/evidence workflows.
- Provider-neutral capacity collection, scoring, forecasting, budget, safety,
  and autoscaling recommendation modules with unit coverage.
- Legacy plans now require migration and reconciliation steps for event,
  search, and vector provider changes. Capacity telemetry and cost inputs
  reject non-finite values before making recommendations.
- A DynamoDB activity marker adapter and fail-closed scheduled-operation gate
  are available for new scheduled handlers. CRM reconciliation now exposes a
  gated one-shot entry point and an opt-in Lambda handler declared in the
  planned manifest. It opens PostgreSQL only after recent activity.
  Successful authenticated API mutations mark activity when the marker table
  and key are configured; marker failures are logged and do not alter a
  completed customer response.
  Existing always-on polling entry points remain for current deployments and
  still prevent full scale-to-zero operation until their callers migrate.
- Repository-level `platform.yaml`, `CLAUDE.md`, and `make conformance` entrypoint.

`platform.yaml` has `deployment_status: planned`. Its process and tier entries
describe a proposed target; the current Compose and Kubernetes runtimes remain
the deployed contracts. A successful manifest check does not authorize deploy.

## Deliberately not claimed as complete

Local verification on 10 October 2026: 55 targeted platform and activity-gate
tests passed, as did Ruff, the manifest structural check, and `git diff
--check`. A broader API regression attempt yielded 10 fixture setup errors
(`Runner.run() cannot be called from a running event loop`) and 5 passing CRM
health tests; it did not establish API regression coverage. The full suite and
branch CI have not been qualified here.

- No AWS apply, production deployment, live capacity result, penetration test,
  disaster-recovery result, or cost certification has been performed here.
- Public control-panel mutation is not enabled; deployment-worker ingress is
  disabled by default and requires separately qualified private networking,
  identity, signing, and audit export.
- Provider migrations, tenant-cell moves, rollback/forward-repair, and
  production qualification remain staged work until independent evidence exists.

## Branch boundary

All work for this reconciliation belongs on
`feature/northstar-adaptive-architecture-20261008`. It must not be merged into
`main` as part of document implementation.
