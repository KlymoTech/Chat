# Production code organization and release contract

Status: IN PROGRESS. This file defines the migration contract; it does not certify production readiness.

## Canonical ownership

- `frontend/`: authenticated React/TypeScript SaaS console, reusable components, typed API clients, design system, tests.
- `backend/`: FastAPI application, domain services, persistence, workers, migrations, authorization and tests.
- `website/`: public TalkToBot marketing site, SEO, CMS-backed pages, blog, lead forms and public assets. Keep the existing implementation until its routes and data dependencies have been reconciled.
- `website-platform/`: legacy/candidate implementation. Do not include in production builds until a capability-by-capability comparison and migration decision.
- `infrastructure/`, `kubernetes/`, `docker/`: deployment and infrastructure definitions; keep optional Kafka, Redis, RabbitMQ and Kubernetes profiles.
- `docs/`: maintained architecture, deployment, security and operational runbooks.

## Human-maintainable implementation rules

1. Each feature owns its routes/controllers, service logic, schemas/types, repository access and tests; share code only through explicit public interfaces.
2. Never create a second authentication, tenant, workspace, CRM lead, billing or CMS source of truth.
3. No fake responses, placeholder integrations, silent fallbacks, hardcoded credentials or test-only mutations of production code.
4. Use meaningful naming, focused modules, typed interfaces, explicit errors, small functions and documentation of non-obvious business invariants.
5. Preserve existing functionality while moving files; use compatibility imports temporarily and remove them after callers and tests migrate.
6. Review any generated code as carefully as human-authored code. Style cannot prove authorship.
7. Preserve the uploaded dark TalkToBot visual direction for the public website, but do not claim SOC 2 certification, trial terms or commercial guarantees without verification.

## Blocking work before deployment

- Fix the Help router and remove the test workflow step that edits `backend/src/northstar_api/routers/__init__.py`.
- Establish one canonical production website runtime and prevent alternate stacks from deploying concurrently.
- Require release-SHA green checks, secret scans, dependency scans, tenant isolation and permission tests, and database migration verification.
- Fail closed on production secret defaults; use managed credentials and rotate any previously exposed credentials.
- Validate CRM/WhatsApp provider integrations against approved sandboxes; distinguish source-complete from live-verified.
- Prove health, worker recovery, backups/restores, deployment rollback, and production monitoring.
- Only delete duplicate or old modules after usage tracing, migration and passing regression tests.

## Proposed feature layout

```text
frontend/src/
  app/                 # routing, providers and bootstrapping
  features/            # agents, knowledge, conversations, channels, crm, billing, analytics, cms
  components/          # shared presentation primitives
  services/            # typed API client and transport
  hooks/               # shared React hooks
  styles/              # design tokens
backend/src/northstar_api/
  routers/             # thin HTTP entrypoints
  modules/             # feature-owned application/domain services
  models/              # persistence model declarations
  schemas/             # validated API contracts
  workers/             # queue and scheduled consumers
  security/            # auth and authorization primitives
backend/tests/         # unit, integration, authorization and regression suites
website/
  app/                 # public routes
  components/          # marketing and CMS components
  lib/                 # CMS read client, metadata, SEO
  tests/               # rendering, forms, accessibility and SEO tests
```

The layout is a target, not a statement that these paths all currently exist. Keep existing framework conventions where different.

## Release acceptance

No deployment approval without a successful build of the exact candidate SHA, full mandatory CI, zero unresolved critical/high security findings, tenant boundary tests, real database migration smoke, core product E2E tests, provider status disclosure, rollback verification and a documented on-call owner.
