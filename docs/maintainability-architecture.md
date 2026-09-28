# Maintainability Architecture Standard

## Objective

Northstar is organized by business capability, not by technical dumping ground.
Every production file has one cohesive responsibility, a discoverable owner, and
a bounded public API. The standard is intentionally stricter for new code than
for compatibility adapters while the legacy surface is being migrated.

"One function per file" is not the target: it turns small related behaviour
into an unsearchable graph of files. A file may contain closely related helpers
that change together. It must not combine transport, application policy,
persistence, and presentation responsibilities.

## Canonical layout

```text
backend/src/northstar_api/modules/<capability>/
  api/              FastAPI routers, request/response translation
  application/      use cases and orchestration
  domain/           entities, policies, value objects, domain errors
  infrastructure/   repositories and external-provider adapters
  contracts/        public schemas and events
  __init__.py       deliberately small public exports only

frontend/src/features/<capability>/
  api/              typed HTTP client and DTO mapping
  components/       feature-owned presentational components
  hooks/            stateful UI behaviour
  model/            types, constants, pure transformations
  pages/            route-level composition only
  index.ts           deliberately small public exports only
```

Cross-feature UI primitives belong in `frontend/src/components/`; cross-feature
browser utilities belong in `frontend/src/lib/`. They must not import a feature
implementation. Backend routers and workers call a capability's public
application API; they do not query another capability's database model directly.

## Size and cohesion limits

| Artifact | Limit | Rule |
| --- | ---: | --- |
| Frontend route/page | 250 lines | Compose feature components; no network orchestration inline. |
| Frontend component/hook/API module | 200 lines | Extract an independently testable concern. |
| Backend router | 200 lines | Thin HTTP adapter; delegate use cases. |
| Backend application service/repository | 250 lines | One use-case family or one persistence concern. |
| Domain model/contracts/configuration | 300 lines | Split by aggregate or contract family. |
| Function/method | 60 lines | Extract named steps unless a cohesive algorithm is clearer. |

Tests, migrations, generated code, and deliberately documented compatibility
adapters are measured separately. An exception needs a short comment stating
why splitting would reduce cohesion and an issue to remove it if temporary.

## Dependency direction

```text
API / pages / workers  ->  application / hooks  ->  domain / model
                                      ->  infrastructure / feature API
```

The domain/model layer has no imports from FastAPI, React, SQLAlchemy, browser
globals, or provider SDKs. Infrastructure implements ports declared by the
application/domain layer. Public `index.ts` and `__init__.py` files are the
only supported import boundary for another feature.

## Migration sequence

1. Preserve external imports with an adapter at the old path.
2. Create the capability package and move contracts/model first.
3. Extract pure transformations and provider adapters.
4. Move each route/use case/component into a named file; keep the old module as
   a temporary re-export only.
5. Update consumers to use the new public boundary, add focused tests, then
   delete the compatibility adapter.
6. Run the audit in the pull request and ratchet its limits to blocking once a
   capability is compliant.

Current first-wave targets are the knowledge router, conversation router,
hybrid extraction service, chat service, CRM provisioning, chat widget, deploy
page, and shared API client. They are selected by size and fan-out, not by
cosmetic filename changes.

## Required verification

Run `npm run architecture:audit` before a structural pull request. The audit
reports non-test production files over the target limits. New or modified
capabilities must have no violations. The existing architecture check remains
the source of truth for repository roots and dependency-boundary migration.
