# Architecture decisions — Website Master Blueprint v1.3

## ADR-001: Isolate the platform from Northstar
Decision: Implement the reusable website system inside `website-platform/`. Existing `frontend/`, `backend/`, database migrations, Compose files, and application routing are unchanged. No existing feature is replaced. Branch is `feature/website-master-blueprint-v1-3-20261009`; do not merge without a separate future instruction.

## ADR-002: Adopt blueprint default architecture
Next.js 15 + TypeScript serves public pages and owner UI. NestJS 10 REST controllers handle domain logic and owner authentication. PostgreSQL/Prisma stores content and leads. Same-origin Next rewrites route /api traffic to NestJS. This matches the intended architectural roles in blueprint Chapter 03 while keeping the original FastAPI Northstar system independent.

## ADR-003: Correct publication semantics
Draft fields and immutable published snapshots are kept separately. Public routes only read records marked PUBLISHED and their published snapshots. Published snapshots are recorded in PageRevision/ArticleRevision, alongside authenticated audit rows and outbox events. A draft save does not overwrite the current published body. No blog or page deletion API exists; manual trash, restore and independent purge approval remain pending.

## ADR-004: Honest lead acknowledgement
Create the lead and outbox event in the same database transaction; report success only after commit. Duplicate request UUIDs return the original acknowledged ID. No automatic external CRM, email, or ad-server delivery is claimed; rows remain PENDING until a compliant worker/provider integration is built and tested.

## ADR-005: Privacy and transport controls
Optional marketing measurement is off. No visitor IP, precise location, replay, or third-party pixel is collected by the website platform. Marketing attribution is stored only when separately opted in. Admin uses random hashed sessions, HttpOnly cookies, SameSite Strict, origin enforcement for mutations, and audited writes. Rate limiting, access review, CSRF/proxy deployment checks, threat testing, provider policies, data rights and retention procedures are still launch blockers.

## ADR-006: Temporary limitations
This is the first implementation work package, not a full release. Manual provisioning is needed for a database, environment configuration and admin bootstrap. Migration SQL and operational release verification must be generated/reviewed. The 78 chapters and 16 appendices are not equivalent to 94 features; implementation and acceptance must follow site-specific applicability decisions.
