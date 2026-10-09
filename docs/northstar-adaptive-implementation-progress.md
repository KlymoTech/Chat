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


## Increment: independently verified deployment step journal (2026-10-08)

- Alembic 0086 adds `platform_deployment_steps` with immutable
  `(change_id, step_index)` identity and step name; historical approvals are
  not backfilled and a downgrade refuses to discard evidence.
- `DeploymentStepJournal` validates worker token/expiry/owner, approved
  change integrity, canonical plan steps, and strict step ordering under the
  deployment lease row lock. Repeated starts, invalid leases, modified plans,
  missing previous verification and uncertain effects fail closed.
- `verify_step` requires a short-lived Ed25519 proof signed **outside the
  application and worker**, bound to change ID, lease token, environment,
  step index/name and source/target digests. The application receives only
  an approved verifier public key; the issuer private key is not in Git.
- `mark_unknown` intentionally freezes an indeterminate effect; no automatic
  replay, reset or retry is implemented. The verifier proof records an evidence
  SHA-256 and run identifier, not a claim that a load/restore test was run.
- Architecture branch CI runs the new signature, sequencing and SQLite
  migration tests. AWS qualifications and external execution are not implied.

### Not implemented or authorized by these commits

1. Machine-role authentication and audited worker service endpoints; the
   journal is an internal library and **not an exposed production worker API**.
2. Trusted independent verifier service, private-key rotation, tamper-resistant
   artifact storage and proof provenance/revocation.
3. Actual Terraform/Step Functions/ECS/EKS/AppConfig execution, step receipts,
   provider rollback, forward-repair and observability.
4. Integrated PostgreSQL contention and fault-injection qualification for
   step journal, and release-safe schema roll-forward/rollback runbooks.
5. Production load, cost, tenant-isolation, AWS quota and security certification.

The branch is not production ready. Completion requires separate measured
and independently signed release evidence.


## Increment: short-lived deployment machine authorization (2026-10-09)

- `deployment_machine_identity.py` validates EdDSA JWT signatures against a
  pinned Ed25519 public key, exact issuer/audience, one allowed machine
  subject, environment, required `jti`, strict token lifetime (<= 5 min)
  and operation-specific scopes. Human sessions and API keys are not machine
  credentials.
- `deployment_worker_operations.py` wraps existing lease and journal methods
  with fresh authorization for **every** claim, renewal, step start, signed
  verification, unknown-result report, and terminal closure. Callers cannot
  inject trust keys or choose the worker's subject or environment.
- Leases retain an optional environment field to preserve internal legacy
  consumers, but **the authenticated facade rejects unscoped legacy claims**
  and always provides a mandatory environment predicate for its database
  calls. Journal ownership also rejects a conflicting bound environment.
- Negative tests cover cross-environment identities, mismatched worker
  subjects, missing scopes, invalid signers/tokens, wrong lease ownership and
  SQL environment predicates.
- No HTTP route, issuer private key, production workload identity mapping or
  cloud mutation has been enabled in this increment. The facade is a
  server-side library only.

### Gate before exposing machine endpoints

1. Restrict ingress at the private service boundary, with approved mTLS or
   workload-identity attestation; do not expose these routes to user traffic.
2. Provision issuer public keys via managed configuration with rotation and
   emergency revocation, keeping private signing keys outside the API.
3. Persist machine token ID / principal / change ID / operation decisions
   into a durable audit record, with concurrency and denial-path tests.
4. Add role-specific deployment worker runtime, signed admission policy,
   dry-run executor, reconciliation/forward-repair runbooks and AWS IAM.
5. Qualify all components against a disposable production-shaped PostgreSQL
   environment before enabling any live infrastructure side effects.
