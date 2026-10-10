# Northstar private deployment worker — dedicated PostgreSQL role

Status: **implementation and qualification guidance, not authorization to deploy**.
Related safety controls: v3 governed changes; Northstar implementation master plan;
migrations 0085–0087, machine identity, worker journal, and append-only audit.

## Hard prerequisites

1. Run migrations 0085 (leases), 0086 (step journal), 0087 (audit) **using a
   separate migrations role** before starting any deployment worker.
2. Provision a dedicated **LOGIN** role with randomized credentials managed
   outside Git (for example through approved AWS secrets/identity provisioning).
   The worker runtime requires the direct login identity to match the configured
   role; `SET ROLE` from the public customer login is forbidden.
3. Do not use the database owner, a superuser, a replication/CREATEROLE/
   CREATEDB/BYPASSRLS role, or a member of PostgreSQL privileged file or
   `pg_write_all_data` roles. Do not grant CREATE on the application schema
   or database.
4. Require a different DSN and login from `DATABASE_URL`, TLS according to
   the approved AWS RDS policy, private-network routing, and an operator-set
   PostgreSQL `search_path` to the migrated application schema.
5. Run the worker as a separate unprivileged process on a protected Unix socket.
   Worker bearer-token public keys and independent step-verifier public keys
   must be distinct and pinned. The signing keys remain in separate issuers.

## Object privilege policy

| Object | Required grants | Forbidden grants |
| --- | --- | --- |
| `platform_changes` | SELECT | INSERT, UPDATE, DELETE, TRUNCATE |
| `platform_config_versions` | SELECT | INSERT, UPDATE, DELETE, TRUNCATE |
| `platform_deployment_leases` | SELECT, UPDATE | INSERT, DELETE, TRUNCATE |
| `platform_deployment_steps` | SELECT, INSERT, UPDATE | DELETE, TRUNCATE |
| `platform_deployment_worker_audit` | SELECT, INSERT | UPDATE, DELETE, TRUNCATE |

The worker only reads the approved plan/configuration; the approval API creates
the lease eligibility row in its approval/outbox transaction. The worker
conditionally claims an existing row, appends an independently verified step,
and writes immutable audit events. PostgreSQL transaction-scoped advisory locks
serialize audit chains without UPDATE access to `platform_changes`.

Provision using a **separate, audited administrator workflow**. The following
are illustrative grants *after* the operator has reviewed the schema and
created the login via its secret-management process; replace placeholders
with safe, provisioned SQL identifiers rather than interpolating user input:

```sql
GRANT USAGE ON SCHEMA application_schema TO northstar_deployer;
GRANT SELECT ON application_schema.platform_changes,
                application_schema.platform_config_versions
  TO northstar_deployer;
GRANT SELECT, UPDATE ON application_schema.platform_deployment_leases
  TO northstar_deployer;
GRANT SELECT, INSERT, UPDATE ON application_schema.platform_deployment_steps
  TO northstar_deployer;
GRANT SELECT, INSERT ON application_schema.platform_deployment_worker_audit
  TO northstar_deployer;
```

A grant template is NOT a complete privileges audit: inherited roles,
`PUBLIC` grants, schema ownership, default privileges, and database-level
CREATE rights may override it. The runtime validates the *effective*
permissions on its actual login at startup, then refuses access if they do
not match. Keep deployment credentials out of logs, Git and client browsers.

## Required worker environment

```text
NORTHSTAR_DEPLOYMENT_WORKER_ENABLED=true
NORTHSTAR_DEPLOYMENT_WORKER_DATABASE_URL=<separate managed PostgreSQL DSN>
NORTHSTAR_DEPLOYMENT_WORKER_DATABASE_ROLE=<dedicated login>
NORTHSTAR_DEPLOYMENT_WORKER_SOCKET=<absolute path within owned 0700 directory>
NORTHSTAR_DEPLOYMENT_WORKER_ENVIRONMENT=<approved environment>
NORTHSTAR_DEPLOYMENT_WORKER_ISSUER=<approved machine issuer>
NORTHSTAR_DEPLOYMENT_WORKER_AUDIENCE=<dedicated worker audience>
NORTHSTAR_DEPLOYMENT_WORKER_SUBJECT=<authorized workload subject>
NORTHSTAR_DEPLOYMENT_WORKER_MACHINE_KEY_FILE=<pinned Ed25519 public key file>
NORTHSTAR_DEPLOYMENT_WORKER_STEP_KEY_FILE=<separate verifier public key file>
```

Never set these controls for the public application. The worker is not
registered as a customer route and does not contain AWS mutation adapters.

## Qualification and rollout sequence

1. Apply schema migrations in a disposable/rehearsal PostgreSQL environment.
2. Provision the dedicated login with no inherited elevated privileges.
3. Confirm the startup probe passes as that exact login.
4. Execute the disposable PostgreSQL real-role test: signed machine operations
   can write audit intent/outcomes, but cannot modify approval records.
5. Deliberately grant extra UPDATE on `platform_changes` or DELETE on audit
   in the isolated qualification environment; startup must refuse the role.
6. Verify concurrent audit intents remain serialized and the append-only
   PostgreSQL trigger rejects UPDATE/DELETE.
7. Confirm a crash leaves an unresolved intent and blocks new actions.
8. Obtain security, DBA, IAM, change-owner and recovery approvals before
   enabling isolated ingress. Review actual AWS quotas, backup/restore, budget,
   incident guard, audit export and canary readiness separately.

## Incident and rollback rules

On detection of an overprivileged worker role, disable the worker and revoke
its credential via the authoritative issuer. Do not auto-retry an ambiguous
provider action. Reconcile actual observed state and evidence before approving
a new plan. Preserve all lease, journal and audit records; migrations forbid
downgrades that would silently destroy those records.

**Not yet delivered:** AWS private workload provisioning, secrets rotation,
independent WORM audit export, real provider executors, rollback/forward
repair, Jenkins release certification, capacity qualification and production
security sign-off. Passing these tests is not production certification.
