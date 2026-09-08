# Lead + Omnichannel + Any-CRM Implementation Status

Branch: `feature/lead-crm-omnichannel-platform`

This document is the live implementation tracker for the production-grade Lead + Omnichannel Ingestion + Any-CRM subsystem. It must be updated in the same branch as implementation work.

## Status legend

- ✅ Completed and committed
- 🟡 In progress
- ⏳ Pending
- 🚫 Blocked by external credential/provider validation

## Overall status

| Phase | Scope | Status |
|---|---|---|
| 1 | Repository mapping and regression baseline | ✅ Repository mapped; baseline CI verification pending after first implementation commits |
| 2 | Contact/Identity + upgraded Lead domain + migrations | 🟡 In progress |
| 3 | Canonical channel event abstraction | ⏳ Pending |
| 4 | Lead service + qualification | ⏳ Pending |
| 5 | CRM connector core/registry/error/capabilities | ⏳ Pending |
| 6 | CRM connection/OAuth/credential architecture | ⏳ Pending |
| 7 | Field schema/mapping engine | ⏳ Pending |
| 8 | CRM routing and delivery persistence | ⏳ Pending |
| 9 | Kafka CRM router consumer | ⏳ Pending |
| 10 | CRM delivery worker/retry/DLQ/circuit breaker | ⏳ Pending |
| 11 | Zoho native connector | ⏳ Pending |
| 12 | Generic REST/Webhook connectors | ⏳ Pending |
| 13 | Salesforce/HubSpot/Dynamics/Pipedrive/Freshsales | ⏳ Pending |
| 14 | CRM inbound webhooks/bidirectional framework | ⏳ Pending |
| 15 | Health/metrics/audit | ⏳ Pending |
| 16 | Frontend Leads enhancement | ⏳ Pending |
| 17 | Frontend CRM integration wizard | ⏳ Pending |
| 18 | Kubernetes/CI/runtime | ⏳ Pending |
| 19 | Security/tenant isolation validation | ⏳ Pending |
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

## Current implementation decisions

1. Existing `Lead`, WhatsApp and Integration routes remain backward compatible during migration.
2. New CRM entities are provider-neutral. Provider-specific record IDs are not added directly to `Lead`.
3. New tenant-owned tables receive `tenant_id`, indexes and PostgreSQL RLS policies.
4. Lead lifecycle state is separated from CRM delivery state.
5. CRM delivery is durable, idempotent and outbox/event driven.
6. Channel connectors cannot call CRM connectors directly.
7. CRM connectors cannot depend on WhatsApp/Instagram/Telegram provider types.
8. Production credentials must never be logged or returned to the frontend.

## Completion log

### 2026-09-08

- ✅ Created dedicated implementation branch.
- ✅ Reviewed current Lead API/model, Integration catalog, WhatsApp persistence/workers, outbox publisher, job dispatcher, health endpoints, frontend Leads/Integrations pages, frontend types/API behavior, migrations and tenant RLS foundation.
- ✅ Confirmed `lead.captured.v1` is published by the existing transactional outbox but currently has no CRM routing/delivery consumer.
- 🟡 Building provider-neutral Contact/Identity/CRM domain models and migration.

## External validation policy

Provider code may be marked `CODE-COMPLETE / LIVE-VALIDATION-PENDING` when live credentials are not available. No provider will be reported as live-verified unless an actual provider call is successfully tested.
