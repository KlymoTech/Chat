# Hosting instructions for Claude

This repository follows the Scale-to-Zero AWS Platform Playbook.

## Before changing anything

1. Read `platform.yaml`; it is the source of truth for processes, resources, and stage.
2. Run `make conformance` and report every failed rule with its file and line.
3. Do not add always-on infrastructure unless the declared stage and a measured trigger require it.

## Deployment rules

- Use make targets for build, image-push, migrate, deploy, and smoke.
- Deploy to dev first; never apply production Terraform from an interactive session.
- Use IAM roles or OIDC. Never add static cloud credentials.
- Keep infrastructure changes in Terraform and application dependencies behind existing ports.
- Do not add polling loops. Scheduled work must declare an activity gate.

## Repository locations

- Infrastructure: `infrastructure/` and `kubernetes/`
- Runbooks: `docs/runbooks/`
- Decisions: `docs/adr/`
- Platform runtime: `backend/src/northstar_api/modules/platform_runtime/`

The adaptive architecture branch is not production-certified. Cloud mutation, rollout,
capacity, recovery, and cost claims require independently reviewed evidence.
