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


## Increment: append-only deployment machine audit (2026-10-09)

- Migration `0087_platform_deployment_worker_audit` creates a per-change
  machine-audit event stream with unique change sequence and attempt/phase.
  It never backfills fabricated historical approvals or worker actions.
- PostgreSQL trigger denies row UPDATE and DELETE; release IAM/database role
  must additionally enforce SELECT/INSERT-only access. Downgrade refuses to
  destroy existing audit history. Operators must archive to independently
  controlled append-only storage before retention or migration.
- `DeploymentWorkerAuditTrail` appends **intent** then **outcome** events,
  hash-linked in change sequence and serialized under the platform change
  record lock. Unknown or unfinished attempts **block** further worker
  operations until a separate audited reconciliation workflow exists.
- `DeploymentWorkerOperations` requires an audit instance and writes durable
  intent **before** invoking any lease/journal action. Missing audit persistence
  blocks the operation, and exceptions produce an `unknown` audit outcome.
  Results are `accepted`, `rejected` or `unknown`—never silently coerced.
- No raw JWT, credential or signed-attestation content is stored; machine
  token IDs are SHA-256 hashed. Audit tests cover chain integrity, exact
  replay denial, unresolved intent protection, and guarded migrations.

### Limitations and release blockers

1. No private machine HTTP ingress has been opened. Workload identity,
   network isolation, key rotation, mTLS and rate controls require separate
   certification before endpoint activation.
2. Machine-auth **denials before identity verification** cannot have a
   trustworthy actor ID. Capture anonymous denials with request IDs and
   security telemetry at the ingress proxy; never log bearer credentials.
3. Hash chaining is tamper-*evident*, not immutable against database
   superusers. Ship evidence to independent WORM storage; audit export,
   external signing and retention controls are still required.
4. Disposable PostgreSQL CI now qualifies competing worker audit intents,
   hash-chain persistence, and database UPDATE/DELETE trigger denial. Production
   workload-role permissions, external WORM export, full migration and recovery
   evidence are still required.
5. Explicit incident reconciliation, step compensation, rollback and
   forward-repair flows remain unimplemented, as do real AWS mutation
   adapters, Terraform, Jenkins, and measured production capacity.


## Increment: standalone deployment worker HTTP boundary (2026-10-09)

- Added `deployment_worker_http.create_deployment_worker_app`, an isolated
  FastAPI ASGI factory. It is not imported, included, mounted, or served by
  `northstar_api.main` or its public customer API/router.
- Six narrowly typed POST contracts are provided for claim, renew, start step,
  verify signed step, mark unknown and close. Body schemas forbid unexpected
  properties and require explicit environment-bound fenced claim material.
- All operations remain OFF by default: `private_ingress_enabled=False`
  yields HTTP 503 regardless of supplied bearer credentials. Enabling the
  flag alone does **not** enforce private networking, TLS, mTLS or workload
  attestation. Deployers must establish those external controls separately.
- Delegation is exclusively through `DeploymentWorkerOperations`; each
  accepted request receives machine signature/audience/issuer/subject/scope
  validation, lease fencing and mandatory durable intent/outcome auditing.
- Endpoints return generic 401/403/409/503 responses, never database error
  details, bearer credentials or signed attestation contents. No public
  CORS, Swagger UI, OpenAPI schema or generic shell/AWS execution API exists.
- API unit tests verify default-disable, invalid identity and environment,
  authorization scope, typed requests, all six paths, audit failure and
  generic response sanitization.

### Mandatory before private deployment (NOT met by the ASGI factory)

1. Host the worker in an isolated deployment (not the public process).
   Bind exclusively to a protected Unix socket or independently certified
   mTLS ingress and apply explicit namespace/security-group isolation.
2. Provision pinned public verification keys through approved secret/config
   management and private JWT signing keys in a separate, controlled issuer.
   Specify key rotation, revocation, request replay protection and workload
   identity lifecycle.
3. Implement ingress denial logging, request metrics, rate limits, traffic
   budgets, secure correlation IDs and security incident routing.
4. Qualify load, malformed input, authorization matrix, PostgreSQL concurrent
   intent handling and downstream failure containment end to end.
5. Implement signed external qualification and AWS executor adapters only
   with reversible IaC, canary, recovery and production release evidence.

The ASGI contract is a non-deployed internal implementation foundation.
No production cloud changes are enabled or certified here.


## Increment: dedicated worker PostgreSQL identity qualification (2026-10-09)

- Added `deployment_worker_database.py` and startup credential/role
  verification, separate from the public application SQLAlchemy engine.
- The worker rejects privileged logins (superuser/CREATEROLE/CREATEDB/
  BYPASSRLS), reused customer DB credentials, mutable audit history, direct
  approval/config writes, table ownership-style broad privileges and
  unexpected INSERT/DELETE/TRUNCATE privileges on execution tables.
- Audit intent ordering now uses PostgreSQL transaction-scoped advisory locks
  keyed by the change UUID instead of `SELECT FOR UPDATE` on
  `platform_changes`, preserving serialized audit events **without** granting
  worker UPDATE on approved changes.
- A disposable PostgreSQL integration test provisions a unique limited LOGIN
  and isolated schema; checks actual startup probe, audit intent/outcome
  persistence, denial of direct approval UPDATE, rejection of unsafe added
  privileges, and finally removes both the login and schema.
- Operator runbook: `docs/northstar-private-worker-db-role.md`. It lists the
  required per-table grants, separate managed credentials, worker-only UDS
  deployment and rollback/incident requirements.

### Remaining production blockers

- Provision real AWS-managed worker credentials / database roles, enforce
  network segmentation and independent workload identity.
- Implement signed external verifier issuer, WORM audit export, live AWS
  execution adapters, certified rollback/forward-repair, Jenkins release
  qualification and canary observability.
- Qualify migrations, backups, recovery, quotas, cost and load under the
  contracted environment; these CI checks are not production certification.


## Increment: AWS private deployment worker IAM foundation (2026-10-09)

- Created `infrastructure/terraform/modules/private_deployment_worker_identity`.
  It defines distinct AWS ECS worker **task** and **execution** identities
  with service trust constrained by source account/ARN. The application task
  role has no AWS mutation grants; the execution role has scoped ECR pulls,
  log-stream writes and optional exact bootstrap secret/KMS access only.
- Module inputs validate environment, account ID, region and resource ARNs;
  preconditions prevent cross-account/region ECR, log, secret or KMS grants.
  A Terraform example demonstrates wiring a pre-existing ECR repo and log
  group without provisioning a task or network.
- Added `.github/workflows/northstar-terraform-worker-identity.yml`:
  Terraform 1.9.8 formatting, init with backend disabled, validation and
  mock-provider topology tests, with no AWS credentials or apply/destroy.
  Terraform and existing architecture CI passed on the implementation commit.
- Technical constraints and rollout prerequisites are documented at
  `docs/northstar-aws-worker-iam-foundation.md`. In particular, the worker
  has a Unix socket; an in-task caller is required rather than exposing it
  through public TCP.

### AWS infrastructure still missing

1. Separately approved Terraform remote state, isolation across development,
   test, staging and production AWS accounts.
2. VPC/private-subnet/endpoints/security-group layers; private ECS task
   definition, sidecar/socket integration and audited secret bootstrap.
3. Workload image digest promotion, RDS credentials/DB role provisioning,
   machine issuer/verifier integration and WORM audit export.
4. Independently governed AWS deployment **executor** with canary, verified
   observed state, rollback/forward-repair, Jenkins gates, load/DR/security
   qualification and budget/incident guards.

IAM topology CI is NOT an AWS deployment, authorization to apply, or evidence
of any production request-per-second / user-population capacity.


## Increment: private AWS worker networking foundation (2026-10-09)

- Added Terraform module `private_deployment_worker_network`: no worker
  ingress rules, dedicated security groups, explicit worker egress limited
  to the existing RDS security group TCP/5432, dedicated VPC interface
  endpoints TCP/443 and an S3 gateway prefix list TCP/443.
- Private AWS endpoints: ECR API, ECR Docker registry, CloudWatch Logs,
  Secrets Manager and STS (KMS is opt-in). S3 gateway endpoint uses the
  supplied private route tables. No NAT gateway, ALB, SSH, public IP or
  generic internet egress is created.
- Existing subnet and RDS SG metadata are validated in Terraform for VPC
  consistency, public-IP autoassignment disabled and two-AZ diversity.
  This is NOT route-table certification or proof that subnets lack an IGW
  route; manual reviewed route evidence and AWS account qualification
  remain mandatory.
- Added reference integration `examples/worker-network`, mock-provider
  Terraform contract tests, negative tests for an auto-public-IP subnet,
  wrong-VPC RDS group and single-AZ placement, and extended the isolated
  Terraform CI gate.
- Deployment requirements, network/data-plane boundary and further
  qualification are recorded at `docs/northstar-aws-worker-network-foundation.md`.

### Still blocked before AWS rollout

1. Audited AWS account isolation, actual private route and endpoint
   policies, remote-state/locking bootstrap and approved RDS ingress.
2. ECS/Fargate worker task and local Unix socket caller/proxy, IAM runtime
   bootstrap, independent signing/verifier identities and WORM audit export.
3. Measured network connectivity, failover, cost, backup/restore,
   reconciliation, controlled mutation executor and Jenkins qualification.
4. Complete AWS evidence, capacity, security and disaster recovery sign-off.

No Terraform apply or live infrastructure mutation was performed.
