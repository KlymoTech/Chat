# Northstar adaptive architecture — incremental implementation ledger

Branch: `feature/northstar-adaptive-architecture-20261008`

## Engineering invariants

- Preserve customer behavior and existing provider contracts; no wholesale rewrite.
- Production AWS, with local/test development profiles retained.
- Architecture changes use governance and evidence; code cannot claim measured throughput from specifications.
- No application endpoint may call this pure qualification evaluator as an AWS executor.
- Main remains untouched; qualification and rollout occur independently.

## Implemented in this increment

- `qualification_gates.py`: pure change-qualification decision using verified, fresh,
  environment- and digest-bound evidence, independent approval, incidents,
  backup safety, maintenance windows and change budget.
- Tests cover positive qualification plus expired, mismatched, unverified,
  invalid-budget, incident, safety-locked and experimental cases.
- This is a foundational safety component; it is **not yet wired** into
  persistence, API, the executor, or AWS infrastructure. No deployment is claimed.

## Next integration gates

1. Persist immutable evidence receipts, trusted artifact verification status,
   desired/observed snapshots and immutable execution intents.
2. Connect classification and qualification to the existing platform change
   API; authorize only independent approvers and maintain an audit trail.
3. Add execution controller with idempotent steps, canary verification,
   point-of-no-return, rollback/forward-repair, and reconciliation.
4. Implement provider migrations with real dual-run/backfill evidence.
5. Qualify adaptive capacity, budget policy, Terraform environment stacks,
   Jenkins, OTel, AWS credentials, load testing and restore exercises.

## Acceptance evidence required

Do not call production ready until repository test suites, integration tests,
CI, isolated AWS qualification, security review, recovery and capacity gates
have produced artifacts and received owners' approvals.


## Increment: fenced deployment worker ownership (2026-10-08)

- New `platform_deployment_leases` table (Alembic 0085) is populated in the
  **same transaction** as an independently approved change and the durable
  approval outbox event. Pre-existing approved changes are **not** backfilled:
  qualification must be reconciled by an operator before any manual enrollment.
- The opt-in `DeploymentLeaseService` claims ready work using a database
  conditional update, verified approval separation of duties, immutable digests
  and matching active/staged desired-state snapshots.
- Fencing token and expiration are mandatory for lease renewal and close.
  **Expired leases are never automatically reclaimed**: an AWS operation could
  have happened before its result became known. Reconcile observed state and
  receipts before designing any explicit recovery transition.
- Test suites cover status predicates, wrong-token outcomes, migration
  downgrade guard, and a disposable PostgreSQL concurrent-claim race.
- A lease is **not** authorization for Terraform, ECS, EKS, AppConfig, data
  migration or any AWS mutation. The cloud worker and its IAM roles do not
  exist in this increment; no infrastructure has been changed.

### Required integration gates (not done yet)

1. Machine identity and least-privilege control-plane API between approved
   outbox event and deployment-worker claims; authenticate and audit every
   claim, renewal, terminal closure, pause and reconciliation.
2. Verify fresh signed qualifications, live incident/budget/backup guards,
   exact approved plan and current observed AWS state before *each* step.
3. Implement an idempotent step journal and a fencing-aware AWS/GitOps
   execution adapter. Do not rely on lease token alone for exactly-once
   external mutation.
4. Persist canary and health evidence, point-of-no-return decision,
   compensation/forward-repair state and independent terminal verification.
5. Run PostgreSQL migration against a disposable representative environment
   before production; deploy schema before code that writes lease rows.
6. Execute staged load, chaos, restore, security and cost qualifications.
