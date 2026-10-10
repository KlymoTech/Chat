# Northstar: offline implementation and deferred real integrations

## Branch and release safety

Active development branch: `feature/northstar-adaptive-architecture-20261008`.
Do not merge into `main` without explicit approval, review and passing quality gates.
All AWS mutation/deployment, production certification, private signing
endpoints and notification worker activation remain OFF.

## Work that can be developed and qualified without production credentials

| Area | Offline engineering gate | External boundary |
| --- | --- | --- |
| Python architecture and domain code | Ruff, pytest, type checking, dependency locking | None |
| Append-only release evidence migrations | Alembic graph tests and disposable PostgreSQL integration | Managed production RDS and DBA sign-off |
| Custody-first signing | Witness/migration tests, fake S3 and generated Ed25519 fixtures | Independent signer workload + AWS key access |
| Replay prevention | Failure-path tests; disposable PostgreSQL concurrency and privilege tests | Restricted production PostgreSQL role |
| Queue/notification logic | Fake adapters, idempotency/retry tests, local broker failure tests | Production endpoints, destinations and secrets |
| Infrastructure-as-code | terraform fmt/validate/test with mock providers and static policy | AWS account/VPC/state/credentials/apply |
| CI/CD | GitHub Actions on feature branch, non-deploying Jenkinsfile tests | Real Jenkins agents and protected approvals |
| Frontend and API | lint, types, build, unit and isolated HTTP contract tests | DNS/TLS, real external identity/providers |

The dedicated `.github/workflows/northstar-offline-security-contracts.yml`
is a **credential-free** subset for the recent custody, signing and migration
files. The broader `adaptive-architecture.yml` also remains in force.

## Deferred integration checklist (not an excuse to mark implementation complete)

1. AWS account isolation, VPC routing/endpoint access, Terraform remote state,
   ECS task/workload identity and approved production apply.
2. RDS credentials, least-privilege DB roles, actual migrations and real
   PostgreSQL concurrency/failover qualification.
3. S3 Object Lock, KMS/Secrets Manager authorization, immutable evidence
   receipt custody and independently protected signing keys.
4. Jenkins isolated agents, authenticated witnesses and signed build provenance.
5. Monitoring destination credentials, real alert deliveries, production
   operations, costs, load testing and disaster-recovery drills.
6. CRM, WhatsApp, SMTP/AI providers and other customer-account integrations
   are separate application-level external integration tracks.

## Gate policy

- A committed file is not a passing test.
- A simulated service is not a live deployment.
- Successful unit tests are not evidence of IAM, Object Lock or database
  privilege enforcement in the target AWS account.
- Never put secrets into fixtures, GitHub commits or public CI logs.
- Do not silently replace rejected, duplicate or uncertain signing claims.
- Preserve backward compatibility and never delete existing data to clear
  failed certification.
- Every release claim must link to immutable build provenance, qualified tests
  and explicit authorization.

### Current state

Offline code for migration-graph convergence, immutable replay claims and
custody-first signing has been committed; live PostgreSQL, AWS and Jenkins
acceptance remains **unverified**. The isolated CI workflow was registered,
but its latest result has not been established in this session.
