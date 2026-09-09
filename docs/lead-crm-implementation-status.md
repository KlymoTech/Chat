# Lead + Omnichannel + Any-CRM Implementation Status

Branch: `feature/lead-crm-omnichannel-platform`  
Draft PR: [#30](https://github.com/ooarchitect92/Chat/pull/30)  
Updated: 2026-09-08

This is the implementation tracker for the Lead + Omnichannel Ingestion + Any-CRM subsystem. It distinguishes committed implementation, executed tests, full feature acceptance, and live-provider validation. The submitted full module scope remains the acceptance basis; the tests below do not replace or reduce that scope.

## Status legend

- ✅ A specifically identified implementation or executable gate is verified.
- 🟡 Implementation exists, but the complete phase acceptance is not established.
- 🧪 Code exists; additional contract, integration, or fault-injection validation is required.
- 🚫 An external account, permission, credential, or repository capability blocks validation.

## Overall status

**IN PROGRESS / RELEASE BLOCKED — NOT MODULE COMPLETE.**

The latest verified executable change is `f650e7379e990d380e0eb2de2e2613eba371a34a`. Its [CI run 34257700348](https://github.com/ooarchitect92/Chat/actions/runs/34257700348) completed successfully, including frontend, backend, source/secret security, deployment configuration, runtime image scans, Docker smoke checks, migration head, and CRM API/database contract checks. PR CI tested merge commit `a879f694190be4fc6aec2daa72b99cc9aa091d45`.

The separate [CodeQL run 34257700342](https://github.com/ooarchitect92/Chat/actions/runs/34257700342) failed. Analysis produced SARIF, but GitHub rejected publishing because code scanning is not enabled for this private repository. The workflow has `actions: read`, `contents: read`, and `security-events: write`; the remaining repository-capability blocker is tracked in [issue #31](https://github.com/ooarchitect92/Chat/issues/31). A produced SARIF file is not security sign-off or evidence of zero findings.

**CodeQL is not the only remaining acceptance item.** The functional/security/test gaps below also remain open. PR #30 stays draft, unmerged, and not approved for production. Documentation-only updates after the verified code commit do not imply that their own CI runs have already passed.

| Phase | Scope | Current verified position and remaining acceptance |
|---|---|---|
| 1 | Repository mapping and regression baseline | ✅ Existing architecture mapped; normal PR CI runs against the proposed merge |
| 2 | Contact/Identity + upgraded Lead domain + migrations | 🟡 Models and migrations exist; `0010_crm_verification` and its columns pass fresh PostgreSQL topology checks; production upgrade/backfill and full RLS/concurrency acceptance remain |
| 3 | Canonical channel event abstraction | 🧪 Contracts, durable raw events, adapters and consumer are committed; full ingress-to-lead provider/failure matrix is not verified |
| 4 | Lead service + qualification | 🟡 Canonical profile/contact, manual qualification and outbox paths pass new persisted tests; rule-engine and channel-driven qualification acceptance remain |
| 5 | CRM connector core/registry/error/capabilities | 🟡 Shared interfaces and registry exist; complete capability accuracy and provider contract matrix still require validation |
| 6 | CRM connection/OAuth/credential architecture | 🟡 Encrypted credentials and OAuth flow exist; worker/reconciliation refresh now shares a tenant-scoped row-locked context; complete callback/refresh/disable races and native outbound URL hardening remain |
| 7 | Field schema/mapping engine | 🟡 Schema/hash/drift and mapping APIs exist; draft/degraded mappings and empty mapped payloads are blocked in tested delivery paths; complete provider schema/type/drift acceptance remains |
| 8 | CRM routing and delivery persistence | ✅ Tested same-payload deduplication, changed-payload new delivery, frozen JSON payload and persisted external reference; broader routing/ordering races remain part of phase 20 |
| 9 | Kafka CRM router consumer | 🟡 Failed-offset regression confirms later records in the same batch are not processed/committed; actual broker replay and consumer failure tests remain |
| 10 | CRM delivery worker/retry/DLQ/circuit breaker | ✅ Scoped hardening tests cover ACK preservation, GET-only verification retry, bounded budgets, DLQ evidence, half-open probe lease and manual retry guards; full distributed fault matrix is not claimed |
| 11 | Zoho native connector | 🧪 Connector committed; comprehensive provider contract tests and 🚫 live credentials/account validation remain |
| 12 | Generic REST/Webhook connectors | 🧪 Generic transport and connector code exist; injected-connector delivery tests pass, but complete real HTTP/status/partial-ACK/security acceptance remains |
| 13 | Salesforce/HubSpot/Dynamics/Pipedrive/Freshsales | 🧪 Native connectors registered; full contract validation and 🚫 live provider accounts remain |
| 14 | CRM inbound webhooks/bidirectional framework | 🧪 Gateway/persistence/consumer committed; missing consumer is now deployed in Compose/Kubernetes; processing/conflict/loop-prevention acceptance remains |
| 15 | Health/metrics/audit | 🟡 Health and audit foundations exist; audit router is registered; complete mutation audit coverage, snapshots, worker readiness and operational dashboards remain |
| 16 | Frontend Leads enhancement | 🟡 Filters, page export, delivery/activity and explicit ACK/verification proof UI build and test successfully; complete requested detail tabs, advanced filters and recovery controls remain |
| 17 | Frontend CRM integration wizard | 🟡 Connection, JSON mapping/validation and route controls exist; this is not acceptance of the complete requested setup wizard; connection-switch/race isolation and full UX tests remain |
| 18 | Kubernetes/CI/runtime | ✅ Compose topology, manifest validation and migration/API/column gates pass; temporary branch-repair/snapshot workflows removed; Kubernetes cluster deployment and HA/failure acceptance are not claimed |
| 19 | Security/tenant isolation validation | 🟡 Gitleaks/Trivy and scoped tenant retry/cancel denial tests pass; CodeQL publishing/review is 🚫 blocked, native connector outbound hardening and complete production RLS/security matrix remain |
| 20 | Full E2E regression | 🟡 Platform Docker smoke passes and persisted mocked-provider CRM path passes; full real Kafka/PostgreSQL/provider fault-injection and live-provider acceptance remain |

## Executed evidence

Evidence is attached to the code commit above, not to an untested future branch head.

| Gate | Result | Evidence |
|---|---|---|
| Backend Ruff lint | PASS | CI job `102167576216` |
| Backend Ruff format | PASS; 114 files already formatted | Same backend job |
| Backend strict mypy | PASS; 86 source files | Same backend job |
| Backend regression | **107 passed** | Same backend job; `test-results.xml` |
| New CRM acceptance tests | **25 cases passed**, included in 107 | `backend/tests/test_crm_acceptance.py` |
| Backend line coverage | **56% overall** | `coverage.xml`; this is not full module acceptance coverage |
| Frontend lint, typecheck, tests, build | PASS | CI job `102167576500` |
| New verification presentation tests | **7 cases**, included in frontend suite | `frontend/src/lib/crm-delivery-status.test.ts` |
| Deployment configuration / manifests | PASS | CI job `102167576612` |
| Source and secret security | PASS for configured Gitleaks/Trivy policies | CI job `102167576667` |
| Docker builds / API and web image scans | PASS | CI topology job `102168033263` |
| Complete local topology / platform smoke | PASS | Same topology job |
| Migration head | PASS: `0010_crm_verification (head)` | Same topology job |
| CRM API and verification columns | PASS | Same topology job; actual PostgreSQL `information_schema` check |
| CodeQL Python and JavaScript/TypeScript publication | **FAIL / external repository capability** | Run `34257700342`; issue #31 |
| Live CRM/provider account tests | **NOT EXECUTED** | No live-validation claim |

Backend evidence artifact: [backend-coverage, artifact 10068587500](https://github.com/ooarchitect92/Chat/actions/runs/34257700348/artifacts/10068587500), containing coverage and JUnit results.

The new CRM tests use actual SQLite persistence and an injected recording connector. One router-loop test uses controlled Kafka/session doubles to check the failed-offset boundary. They do not demonstrate live external HTTP success, actual Kafka replay, PostgreSQL concurrent locking, or production RLS. Native provider, inbound consumer, qualification-rule and audit coverage still need substantial expansion.

## Hardening completed in the verified change

1. **Provider ACK cannot be undone by a read-back failure.** Verification failures retain `acknowledged_at`, preserve the acknowledged delivery, and never queue the original remote write again.
2. **Positive read-back proof is required.** Empty/malformed/wrong-ID results cannot become verified. Salesforce `Id`, Dynamics `leadid`, the default `id`, and configurable read-back ID paths are handled explicitly.
3. **Verification scope is visible.** Default evidence proves record identity only. Configured `verificationFields` additionally compare transmitted values. Unsupported read-back is shown as unsupported, not verified.
4. **Retry budgets are separate and bounded.** Write retries and verification retries have separate cycle counters; total attempt history remains monotonic. Terminal verification failure records DLQ phase evidence.
5. **Mapped payloads are frozen before sending.** Invalid draft/degraded mappings stop delivery; explicit empty mappings no longer silently substitute a generic full-contact payload. Canonical timestamps are JSON-safe.
6. **Updated leads can synchronize again.** The delivery idempotency key includes a canonical business-payload digest and mapping version. Repeated unchanged requests deduplicate; changed business data creates a new delivery. Existing external references can select update instead of a new create.
7. **Recovery cannot blindly resend an ambiguous ACK.** A provider acceptance followed by failed local ACK persistence is surfaced as `ambiguous_provider_ack` and blocked from automatic/manual blind retry.
8. **Concurrency and audit evidence improved.** Credential refresh is row-locked and persisted encrypted; half-open circuit probes use a lease; failed partition processing stops the remaining batch; retry actions create actor/phase activity; normalized email/phone is no longer mislabeled as ownership verification.
9. **API and UI contracts reflect reality.** Retry/cancel responses refresh async ORM state; acknowledged deliveries cannot be cancelled or retried as new writes; UI separates delivery state, ACK, verification scope, attempts, retry/error state and missing evidence.
10. **Runtime wiring is present.** CRM webhook consumer is in Compose and Kubernetes. Normal CI validates the new migration and API/DB contracts. Temporary source-snapshot and branch-repair workflows and the one-use patch script are removed.

## Implemented persistence

- `contacts`, `contact_identities`, `raw_webhook_events`
- `lead_profiles`, `lead_consents`, `lead_activity_events`, `lead_qualification_rules`
- `crm_connections`, `crm_field_schema`, `crm_field_mappings`, `crm_routes`
- `crm_deliveries`, `crm_delivery_attempts`, `crm_external_references`, `crm_webhook_events`, `crm_circuit_breakers`
- `integration_health_snapshots`, `integration_dead_letters`, `integration_audit_events`
- `channel_connections`

Migration chain reaches `0010_crm_verification`. Added delivery columns include `retry_cycle_attempts`, `payload_json`, `verification_status`, `verification_attempt_count`, `verification_cycle_attempts`, `next_verification_at`, verification errors, and `verification_evidence_json`.

The migration invalidates older unproven verification states on acknowledged records and schedules them for the new positive-evidence path. Test production-data upgrades and take a recoverable backup before deployment; a fresh CI database is not an upgrade rehearsal.

## Architecture invariants

These remain requirements, not a claim that every invariant has already passed the full acceptance matrix.

1. Preserve existing Lead, WhatsApp and Integration behavior while extending the domain.
2. Keep provider-specific fields out of the canonical Lead identity.
3. Normalize channels into canonical events before business logic.
4. Keep provider implementations behind the common connector contract.
5. Keep lead lifecycle and CRM delivery/verification states separate.
6. Scope tenant persistence and verify PostgreSQL RLS under production roles.
7. Persist deliveries/outbox before external effects and bound retry/recovery behavior.
8. Distinguish ACK1 durable ingress, ACK2 provider acceptance, and ACK3 explicit read-back proof.
9. Provider failures must not silently discard committed leads or advance past failed event offsets.
10. Harden outbound destinations against SSRF and unsafe redirects across all connectors, not only generic transport.
11. Encrypt credentials and exclude secrets/customer payloads from frontend status responses and logs.
12. Block invalid schema/mapping states instead of silently dropping or substituting fields.

## Key APIs implemented

CRM providers/connections, OAuth start/callback/reconnect, health, schema refresh, mappings, routes, deliveries/retry/cancel, CRM inbound webhooks, channel connections, qualification rules, lead qualification/sync, lead deliveries/activity, and lead filters are exposed under `/api/v1`. Existing audit routes are registered. Endpoint presence is not evidence that all provider flows and permissions are accepted.

## Event/worker chain

```text
Channel webhook → verify / deduplicate / persist → ACK1
    → canonical event → contact/identity → conversation/qualification → LeadProfile
    → transactional outbox → Kafka lead.crm.sync.requested.v1
    → CRM router → tenant routes → CRMDelivery → frozen mapped payload
    → connector write → persisted provider ACK2 / external reference
    → separate read-back verification
        positive record ID (+ configured field comparison) → VERIFIED / ACK3 evidence
        transient GET failure → bounded verification-only retry
        unsupported GET → ACKNOWLEDGED / verification unsupported
        permanent/exhausted GET failure → ACKNOWLEDGED / verification failed / DLQ evidence
```

A GET/verification failure never queues the acknowledged write. Unacknowledged write failures have their own bounded retry/backoff/circuit/DLQ path. Actual broker/provider end-to-end execution remains an outstanding acceptance item.

## Connector matrix

| Provider | Implementation present | Validation position |
|---|---|---|
| Zoho CRM | Native connector | Additional contract/fault tests and live account validation pending |
| Salesforce | Native connector | Additional contract/fault tests and live account validation pending |
| HubSpot | Native connector | Additional contract/fault tests and live account validation pending |
| Dynamics 365 / Dataverse | Native connector | Additional contract/fault tests and live tenant/app validation pending |
| Pipedrive | Native connector | Additional contract/fault tests and live account validation pending |
| Freshsales | Native connector | Additional contract/fault tests and live account validation pending |
| Generic REST | Generic connector | Delivery logic tested with injected connector; complete real transport/ACK matrix pending |
| Generic Webhook | Signed/HMAC generic connector | Complete real transport/signature/ACK matrix pending; no read-back must not imply verification |

Do not describe a connector as live-verified, or the full module as code-complete, simply because it is registered or its imports/build pass.

## Remaining work before this module may be marked complete

1. **External security gate:** resolve issue #31 through an authorized repository administrator, rerun CodeQL for the final head, and review actual findings. Do not disable publishing or make CodeQL optional to remove the failure.
2. **Provider and outbound security:** complete native connector URL/SSRF protections, credential/configuration boundaries, capability accuracy and provider-specific status/error/partial-ACK/refresh contract tests.
3. **Full requested product UX:** finish and test the complete CRM setup workflow, lead detail/filter/recovery interfaces, safe connection switching, delivery-attempt/DLQ operations, and health/audit presentation. The current JSON mapping/routing panel is a subset, not the entire requested wizard.
4. **Ingress and bidirectional behavior:** execute the channel-to-contact/lead qualification path and CRM webhook conflict/loop-prevention matrix, including invalid signatures, duplicates, retries, dead letters and revoked credentials.
5. **Production persistence and distributed faults:** validate RLS, actual PostgreSQL concurrent workers, real Kafka failure/replay/offset behavior, interrupted writes/ACKs, upgrade/backfill against prior data, and recovery rather than relying only on SQLite tests or a fresh topology.
6. **Operational completeness:** complete mutation audit emission, readiness/health snapshots and worker probes, DLQ resolution/replay lifecycle, monitoring and recovery evidence.
7. **Live-provider acceptance:** use authorized sandbox accounts and approved synthetic records to verify supported operations and read-back per provider. Keep untested accounts clearly pending; do not use customer production data for smoke tests.

## Completion rule

**MODULE COMPLETE is not authorized by the current evidence.** The complete submitted scope and executable acceptance criteria must be satisfied, required quality/security/topology gates must pass for the final code, and findings must be reviewed. Live-provider validation remains separately and explicitly labeled; no untested provider is live-verified. Changes to that rule or scope require an explicit decision, not an undocumented relaxation.

Operations for the implemented verification path: [CRM delivery verification and recovery](operations/crm-delivery-verification.md).
