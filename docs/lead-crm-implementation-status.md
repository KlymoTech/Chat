# Lead + Omnichannel + Any-CRM Implementation Status

Branch: `feature/lead-crm-omnichannel-platform`

This document is the live implementation tracker for the production-grade Lead + Omnichannel Ingestion + Any-CRM subsystem. It must be updated in the same branch as implementation work.

## Status legend

- ✅ Completed and committed
- 🟡 In progress
- ⏳ Pending
- 🚫 Blocked by external credential/provider validation
- 🧪 Tests committed; execution/CI verification pending

## Overall status

| Phase | Scope | Status |
|---|---|---|
| 1 | Repository mapping and regression baseline | ✅ Repository mapped; branch has no workflow run and sandbox cannot resolve GitHub, so executable regression remains pending |
| 2 | Contact/Identity + upgraded Lead domain + migrations | ✅ Provider-neutral persistence, LeadProfile compatibility extension, backfill migration, indexes and RLS committed |
| 3 | Canonical channel event abstraction | 🟡 ChannelConnector + CanonicalInboundEvent contract committed; provider webhook migration/wiring pending |
| 4 | Lead service + qualification | 🟡 Contact identity resolution, canonical profile creation, qualification, manual sync and controlled lifecycle committed; tenant rule-policy engine still pending |
| 5 | CRM connector core/registry/error/capabilities | ✅ Base contract, lazy registry, capabilities, health/result/schema/error types committed |
| 6 | CRM connection/OAuth/credential architecture | 🟡 Multi-connection persistence + encrypted CredentialStore committed; provider-neutral browser OAuth start/callback framework pending |
| 7 | Field schema/mapping engine | 🟡 Mapping engine + schema refresh/hash/drift/validation APIs committed; transformation coverage/provider tests remain |
| 8 | CRM routing and delivery persistence | ✅ Routes, deliveries, attempts, external references, DLQ, activity persistence and route evaluator committed |
| 9 | Kafka CRM router consumer | ✅ `lead.crm.sync.requested.v1` consumer committed using ProcessedEvent idempotency/quarantine pattern |
| 10 | CRM delivery worker/retry/DLQ/circuit breaker | 🟡 Durable ACK/retry/rate-limit/auth/DLQ/read-back worker committed; explicit circuit-breaker + reconciliation worker pending |
| 11 | Zoho native connector | 🟡 V8 OAuth refresh, health, Fields Metadata, create/update/upsert/get/read-back committed; 🚫 live credential validation pending |
| 12 | Generic REST/Webhook connectors | 🟡 HTTPS/auth/idempotency/HMAC/error handling committed; hardened pinned-IP transport refactor + mock E2E pending |
| 13 | Salesforce/HubSpot/Dynamics/Pipedrive/Freshsales | ⏳ Pending native connectors |
| 14 | CRM inbound webhooks/bidirectional framework | ⏳ Persistence foundation exists; webhook gateway/event conflict processing pending |
| 15 | Health/metrics/audit | 🟡 Per-connection health API + activity events committed; expanded Prometheus/audit coverage pending |
| 16 | Frontend Leads enhancement | ⏳ Pending |
| 17 | Frontend CRM integration wizard | ⏳ Pending |
| 18 | Kubernetes/CI/runtime | 🟡 CLI worker entry points committed; Compose/Kubernetes workloads and CI coverage pending |
| 19 | Security/tenant isolation validation | 🟡 RLS/credential/tenant/API ownership controls committed; executable adversarial tests pending |
| 20 | Full E2E regression | ⏳ Pending |

## Existing foundations preserved

- FastAPI + async SQLAlchemy + PostgreSQL/Alembic
- PostgreSQL tenant row-level security
- Redis rate-limit/cache infrastructure
- Kafka transactional outbox publisher
- Celery/background dispatcher patterns
- Existing WhatsApp Embedded Signup and durable inbound/outbound processing
- Existing Leads, Conversations and Integrations APIs/UI
- Existing Prometheus health/metrics conventions
- Existing Docker/Kubernetes/CI structure

## New persistence committed

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

Migration: `0005_lead_crm_platform`.

## Current implementation decisions

1. Existing `Lead`, WhatsApp and Integration routes remain backward compatible during migration.
2. `LeadProfile` is a one-to-one production extension of the existing `leads` row so existing API IDs/contracts are preserved while canonical fields are introduced.
3. New CRM entities are provider-neutral. Provider-specific record IDs are not added directly to `Lead`.
4. New tenant-owned tables receive `tenant_id`, indexes and PostgreSQL RLS policies.
5. Lead lifecycle state is separated from CRM delivery state.
6. CRM delivery is durable, idempotent and outbox/event driven.
7. Channel connectors cannot call CRM connectors directly.
8. CRM connectors cannot depend on WhatsApp/Instagram/Telegram provider types.
9. Production credentials must never be logged or returned to frontend responses.
10. Phone normalization does not guess country codes; channel adapters must supply E.164 when provider context makes it known.
11. Connector capabilities explicitly declare OAuth/schema/upsert/read-back/webhook support.
12. Provider schema hash is persisted; mappings can become `degraded` after schema drift.
13. ACK1/ACK2/ACK3 remain distinct: ingress persistence, provider acceptance, and read-back verification.
14. Generic provider URLs must remain SSRF-safe; existing `safe_fetch` provides a stronger DNS-pinning pattern that will be reused by the final generic outbound transport.

## APIs committed

- `GET /api/v1/crm/providers`
- `POST /api/v1/crm/connections`
- `GET /api/v1/crm/connections`
- `GET /api/v1/crm/connections/{id}`
- `DELETE /api/v1/crm/connections/{id}` (safe disable + credential removal)
- `POST /api/v1/crm/connections/{id}/test`
- `GET /api/v1/crm/connections/{id}/health`
- `GET /api/v1/crm/connections/{id}/schema`
- `POST /api/v1/crm/connections/{id}/schema/refresh`
- `GET /api/v1/crm/connections/{id}/mappings`
- `PUT /api/v1/crm/connections/{id}/mappings`
- `POST /api/v1/crm/connections/{id}/mappings/validate`
- `GET /api/v1/crm/routes`
- `POST /api/v1/crm/routes`
- `GET /api/v1/crm/deliveries`
- `POST /api/v1/crm/deliveries/{id}/retry`
- `POST /api/v1/crm/deliveries/{id}/cancel`
- `POST /api/v1/leads/{id}/qualify`
- `POST /api/v1/leads/{id}/sync`
- `GET /api/v1/leads/{id}/deliveries`
- `GET /api/v1/leads/{id}/activity`
- Existing `GET /api/v1/leads` now supports server-side `search`, `status`, and `agent_id` filters.

## Event/worker chain committed

```text
Lead create/update/qualify
        ↓
Transactional Outbox
        ↓
lead.crm.sync.requested.v1
        ↓
Kafka CRM Router Consumer
        ↓
CRMRoute evaluation
        ↓
CRMDelivery (idempotent)
        ↓
CRM Delivery Worker
        ↓
Connector
        ↓
ACKNOWLEDGED
        ↓
External reference
        ↓
Read-back if supported
        ↓
VERIFIED
```

Failure path supports normalized classification, retry scheduling, Retry-After, auth-required, rate-limited, failed and dead-letter states.

## Connector status

| Provider | Code status | Live status |
|---|---|---|
| Zoho CRM V8 | 🟡 Native connector committed | 🚫 LIVE-VALIDATION-PENDING |
| Generic REST | 🟡 Connector committed; hardened pinned-IP transport refactor pending | 🧪 mock/E2E pending |
| Generic Webhook | 🟡 HMAC/idempotency connector committed | 🧪 mock/E2E pending |
| Salesforce | ⏳ Pending | Not tested |
| HubSpot | ⏳ Pending | Not tested |
| Dynamics 365 | ⏳ Pending | Not tested |
| Pipedrive | ⏳ Pending | Not tested |
| Freshsales | ⏳ Pending | Not tested |

## Tests committed

`backend/tests/test_lead_crm.py` currently covers:

- identity normalization
- CRM delivery transition validation
- credential encryption round-trip/wrong-key failure
- initial connector registry loading
- generic JSON response extraction
- normalized 401/422/429/503 classification
- canonical mapping transforms/defaults/constants/value maps
- Zoho default mapping + external application lead ID
- Zoho record-level ACK parsing and failure rejection

Status: 🧪 committed but not executed in this session because direct repository clone cannot resolve `github.com` and no GitHub workflow run exists for the branch commit.

## Completion log

### 2026-09-08

- ✅ Created implementation branch `feature/lead-crm-omnichannel-platform`.
- ✅ Repository architecture mapped before changes.
- ✅ Added Lead/CRM non-negotiables document.
- ✅ Added domain enums, strict delivery state-transition validator and deterministic identity normalization.
- ✅ Added provider-neutral ChannelConnector and CRMConnector contracts/registries.
- ✅ Added complete provider-neutral persistence and Alembic migration with RLS/backfill.
- ✅ Added canonical Contact/Identity/LeadProfile services and upgraded Lead create/update flow.
- ✅ Added multi-connection CRM management, mapping, route, health, lead sync and delivery APIs.
- ✅ Added canonical field mapping engine.
- ✅ Added Kafka CRM route consumer.
- ✅ Added durable CRM delivery worker with ACK/attempt/retry/rate-limit/auth/DLQ/external-reference/read-back flow.
- ✅ Added Zoho CRM V8 connector code based on current V8 endpoints.
- ✅ Added Generic REST + signed Generic Webhook connector code.
- ✅ Added root README progress dashboard and kept this detailed tracker as the source of truth.
- ✅ Added initial backend test suite for the Lead/CRM domain.
- 🟡 Next: generic hardened outbound transport, reconciliation/circuit breaker, native CRM providers, channel webhook normalization/wiring, metrics/audit expansion, frontend, deployment and full regression.

## External validation policy

Provider code may be marked `CODE-COMPLETE / LIVE-VALIDATION-PENDING` when live credentials are unavailable. No provider is reported as live-verified unless an actual provider call succeeds and the result is recorded here.
