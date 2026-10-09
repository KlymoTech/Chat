# Northstar architecture implementation ledger — 2026-10-08

This ledger is a **requirements tracking aid**, not a completion certificate.
The source of authority is *Adaptive SaaS Architecture Standard v3.0*
over its earlier source standards, together with the Northstar-specific
implementation master plan.

| Master plan phase | Deliverable | Status / evidence |
| --- | --- | --- |
| 0 | Baseline, inventory, full CI, gap register | Partial repository inspection; full baseline tests pending |
| 1 | T0–T4, A/B/C/D/L/E, guards, durable state | Tier and switch advisory modules added; persisted desired state and verified evidence remain pending |
| 2 | Provider ports | Existing contracts present; adapters and isolation review pending |
| 3 | AWS adapters | Not implemented in this branch |
| 4 | Terraform foundation | Not implemented in this branch |
| 5 | ECS production profile | Not qualified |
| 6 | EKS optional profile | Not qualified |
| 7 | Jenkins qualification | Not implemented |
| 8 | OpenTelemetry, Grafana and SLOs | Not implemented in this branch |
| 9 | Capacity scoring and forecasting | Basic advisory resource guard added; collector/forecast and history pending |
| 10 | Automatic architectural upgrade | Disabled pending signed evidence |
| 11 | Reversible provider migrations | Not implemented |
| 12 | Tenant cells and migration | Not implemented |
| 13 | Malware, age retention and DR drills | Not implemented |
| 14 | Load qualification and quotas | Not tested |
| 15 | Launch | Blocked pending signed readiness |

## Safety obligations / current blockers

- Locked controls must stay enforced, including authentication,
  authorization, tenancy, secrets, idempotency, telemetry and audit.
- Any provider migration needs a reversible plan, backup/restore proof,
  canary evidence, independent approval and a trusted artifact verifier.
- The API currently blocks B/C/D deployments without a trusted evidence
  verifier; this is deliberate **fail-closed scaffolding**, not production
  deployment functionality.
- Legacy production fallback semantics require a separate audit to ensure
  no unsafe synchronous queue or local filesystem acceptance.
- No measured capacity is claimed: 70k users / 10k RPS is a reference
  planning contract; Northstar's 500k + 1M population is a target requiring
  its own AWS evidence.

## Release gates

Run backend unit and integration tests, inspect router/OpenAPI generation,
run lint/type checks, browser E2E, Terraform validation, cloud qualification
and restore/chaos tests before marking any phase complete. Keep all
implementation work on `feature/northstar-adaptive-architecture-20261008`;
do not merge without explicit instruction.


## Increment: signed release-manifest verification (2026-10-10)

- `queue_notification_release_manifest.py` adds an independently signed Ed25519
  release-manifest verifier, bound to externally pinned release ID, Jenkins run,
  source Git commit, OCI image SHA-256 digest, environment, source/target
  configuration digests, and the exact signed certification attestation digest.
- The manifest embeds an immutable S3 artifact receipt (bucket, release-scoped
  key, version ID, SHA-256). The optional read-back gate delegates to the
  existing S3 Object Lock/KMS verifier and rejects any mismatched receipt.
- Tests cover signature tampering, duplicate JSON fields, wrong release/image,
  stale evidence, key/version mismatch, fail-before-I/O and unknown readback.
- The feature branch CI includes the new test module. A passing workflow has
  not been observed; none of this authorizes production worker activation.

### Missing before release certification

1. Build and independently sign `evidence/<release-id>/release-manifest.json`
   in a protected Jenkins pipeline, with signer identity pinned to release policy.
2. Collect and verify the full SBOM, image-signature/provenance, functional,
   security, load, resilience, migration, DR, observability and cost evidence
   required by the master plan. A signed manifest alone does not prove them.
3. Persist the signed manifest immutably and verify its **own** S3 object
   version, Object Lock policy and content digest, independently of the
   certification-attestation receipt.
4. Connect manifest verification to the separately governed qualification
   approval/admission path without accepting release coordinates from
   tenant/user input.
5. Obtain passing repository-wide CI, disposable PostgreSQL, live qualification
   AWS IAM/S3/KMS, canary, rollback and security/DR/capacity evidence before
   enabling any production certification or worker delivery.
