# Lead + Omnichannel + Any-CRM Implementation Status

Branch: `feature/lead-crm-omnichannel-platform`
Draft PR: `#30`

This document is the live implementation tracker for the production-grade Lead + Omnichannel Ingestion + Any-CRM subsystem. It is updated with the implementation branch and distinguishes code completion from live-provider validation.

## Status legend

- ✅ Implemented/committed
- 🟡 Implementation or CI hardening in progress
- 🧪 Implemented with automated validation still running/pending
- 🚫 External live-provider validation blocked by credentials/account configuration

## Overall status

| Phase | Scope | Status |
|---|---|---|
| 1 | Repository mapping and regression baseline | ✅ Repository mapped; draft PR CI is now active |
| 2 | Contact/Identity + upgraded Lead domain + migrations | ✅ Complete |
| 3 | Canonical channel event abstraction | ✅ Contract, durable raw events, channel connection model, channel registry/adapters and consumer committed |
| 4 | Lead service + qualification | ✅ Canonical LeadProfile/Identity services plus tenant qualification-rule engine committed |
| 5 | CRM connector core/registry/error/capabilities | ✅ Complete |
| 6 | CRM connection/OAuth/credential architecture | ✅ Multi-connection persistence, encrypted CredentialStore, provider-neutral OAuth state/start/callback/reconnect committed |
| 7 | Field schema/mapping engine | ✅ Schema discovery/hash/drift, dynamic mappings and validation committed |
| 8 | CRM routing and delivery persistence | ✅ Complete |
| 9 | Kafka CRM router consumer | ✅ Complete |
| 10 | CRM delivery worker/retry/DLQ/circuit breaker | ✅ Delivery worker, retry/backoff, DLQ, persistent circuit breaker and reconciliation committed |
| 11 | Zoho native connector | 🧪 Code-complete; 🚫 live validation pending provider credentials |
| 12 | Generic REST/Webhook connectors | 🧪 Code-complete with DNS-pinned outbound transport/HMAC/idempotency; integration validation pending |
| 13 | Salesforce/HubSpot/Dynamics/Pipedrive/Freshsales | 🧪 Native connectors committed and registered; live validation pending provider accounts |
| 14 | CRM inbound webhooks/bidirectional framework | 🧪 Webhook gateway and persistence committed; automated validation in progress |
| 15 | Health/metrics/audit | 🟡 Connection health + integration audit committed; final CI/security verification in progress |
| 16 | Frontend Leads enhancement | ✅ Server-side filters, CRM deliveries/activity, sync/retry and ACK/verification UX committed; frontend tests now pass |
| 17 | Frontend CRM integration wizard | 🟡 Remaining primary product gap; implementation still required before completion |
| 18 | Kubernetes/CI/runtime | 🟡 CI updated; missing Compose/Kubernetes CRM/channel worker workloads still being added |
| 19 | Security/tenant isolation validation | 🟡 RLS, encrypted credentials, SSRF protection and tenant scoping committed; security/CI hardening active |
| 20 | Full E2E regression | 🟡 Draft PR CI active; final topology gate pending earlier jobs |

## Implemented persistence

- `contacts`
- `contact_identities`
- `raw_webhook_events`
- `lead_profiles`
- `lead_consents`
- `crm_connections`
- `crm_field_schema`
- `crm_field_mappings`
- `crm_routes`
- `crm_deliveries`
- `crm_delivery_attempts`
- `crm_external_references`
- `crm_webhook_events`
- `integration_health_snapshots`
- `integration_dead_letters`
- `lead_activity_events`
- `crm_circuit_breakers`
- `channel_connections`
- `lead_qualification_rules`
- `integration_audit_events`

Migration chain currently reaches `0009_integration_audit`.

## Architecture invariants

1. Existing `Lead`, WhatsApp and Integration behavior remains backward compatible during migration.
2. `LeadProfile` extends the existing lead identity without provider-specific columns.
3. Channels normalize into canonical events before lead/CRM business logic.
4. CRM providers implement the common `CRMConnector`; LeadService does not import provider implementations.
5. Lead lifecycle state and CRM-delivery state remain separate.
6. All tenant-owned persistence is tenant-scoped and protected by PostgreSQL RLS in production.
7. CRM delivery is durable, idempotent, outbox/event driven and retryable.
8. ACK1/ACK2/ACK3 are distinct: ingress persistence, provider acceptance and read-back verification.
9. External provider failures cannot silently discard persisted leads.
10. Generic outbound destinations use hardened public-address validation/DNS pinning and do not follow unsafe redirects.
11. Credentials are encrypted and never returned to the frontend or written to application logs.
12. Provider schema drift degrades invalid mappings instead of silently dropping fields.

## Key APIs implemented

CRM provider/connection APIs, OAuth start/callback/reconnect, health, schema refresh, field mappings, routes, deliveries/retry/cancel, CRM inbound webhook endpoints, channel connection endpoints, qualification-rule endpoints, lead qualification/manual sync, lead deliveries/activity, and server-side Lead filters are registered under `/api/v1`.

## Event/worker chain

```text
Channel webhook
    ↓ verify / deduplicate / persist / ACK
Canonical channel event
    ↓
Contact + Identity
    ↓
Conversation / Lead qualification
    ↓
Canonical LeadProfile
    ↓
Transactional Outbox
    ↓
lead.crm.sync.requested.v1
    ↓
Kafka CRM Router
    ↓
Tenant CRM routes
    ↓
CRMDelivery
    ↓
Delivery worker
    ↓
Connector
    ↓
ACKNOWLEDGED
    ↓
External CRM reference
    ↓
Read-back verification where supported
    ↓
VERIFIED
```

Transient failures use exponential backoff + jitter/Retry-After, connection circuit state and eventual dead-letter handling. Reconciliation recovers stale processing and incomplete verification records.

## Connector matrix

| Provider | Code status | Validation status |
|---|---|---|
| Zoho CRM V8 | ✅ Native connector | 🚫 Live credentials required |
| Salesforce | ✅ Native connector | 🚫 Live account required |
| HubSpot | ✅ Native connector | 🚫 Live account required |
| Microsoft Dynamics 365 / Dataverse | ✅ Native connector | 🚫 Live tenant/app required |
| Pipedrive | ✅ Native connector | 🚫 Live account required |
| Freshsales | ✅ Native connector | 🚫 Live account required |
| Generic REST | ✅ Native generic connector | 🧪 Automated integration gate pending |
| Generic Webhook | ✅ Signed/HMAC generic connector | 🧪 Automated integration gate pending |

## CI status as of 2026-09-08

- ✅ Deployment configuration gate passes.
- ✅ Frontend lint passes.
- ✅ Frontend typecheck passes.
- ✅ Frontend tests pass after updating Leads tests to the server-filter/`leadCrmApi` contract.
- 🟡 Frontend build is part of the current active run.
- 🟡 Backend Ruff has been reduced to five reviewed semantic findings; targeted fixes are being applied now.
- 🟡 Secret scanning is operational. Its only finding was a reviewed documentation false positive and the exact historical fingerprint was added to `.gitleaksignore`; scanning remains blocking for all other findings.
- ℹ️ GitHub Dependency Review is unavailable because this repository does not expose the required Dependency Graph/GHAS capability; the job is optional while Trivy/lockfile/security gates remain blocking.
- ⏳ Full topology integration waits for frontend/backend/security prerequisites.

## Remaining work before this module may be marked complete

1. Finish the CRM Integrations wizard/details UI and tests.
2. Add Compose workloads for CRM router, delivery, reconciliation and channel-event consumer, including CRM credential encryption environment configuration.
3. Add equivalent Kubernetes deployments and Kustomize references.
4. Resolve remaining backend Ruff/mypy/test failures revealed by CI.
5. Remove temporary branch-only autofix workflows used during implementation.
6. Run the full PR gates: frontend, backend, configuration, security, integration topology and CodeQL.
7. Update README/docs/provider matrix/runbooks with final verified results.

## Completion rule

This tracker will only be changed to **MODULE COMPLETE** after the repository's executable quality/security/topology gates are green. Providers without credentials will be explicitly labeled `CODE-COMPLETE / LIVE-VALIDATION-PENDING`; no untested provider will be described as live-verified.
