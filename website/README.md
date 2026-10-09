# Website Blueprint v1.3 implementation

This independent Next.js public-site scaffold is isolated from the existing React/Vite control plane and FastAPI product API. It does **not** replace, rewrite, or deploy either existing service.

## Run

From the `website` directory: `npm install`, `npm run dev`; browse http://localhost:3000. Set variables from `.env.example` in `.env.local` after confirming all public claims. Run `npm run typecheck` and `npm run build` before considering a deployment.

## What is currently implemented

- Responsive semantic HTML, keyboard skip link, primary and legal navigation, focus indicators, reduced-motion handling.
- Accessible home, services, about, resources, contact, privacy and terms **starter** routes.
- Per-route titles, global metadata, and configurable site identity. Search indexing is withheld until an explicit site URL is configured.
- Contact uses a configured mailto address; it **does not claim to store a lead**.\n- Schema-only revision/audit/outbox tables and a read-only published-content renderer are introduced; no CMS service or database installation has occurred.

## Release blocking gaps

These pages contain conspicuous placeholders, not approved business claims or legal policies. No functioning CMS, owner console, durable form ingestion, transactional outbox, authentication, audit trail, blog publishing, media storage, consent manager, analytics, paid-media conversion delivery, rollback, backups, or production acceptance exists in this starter. Do **not** advertise it as a finished site or enable paid traffic. Follow `docs/website-blueprint-implementation.md` for the phased delivery and proof contract.

## Architecture decision

The source blueprint defaults to Next.js public web + React owner console + NestJS + PostgreSQL. This repository currently operates React/Vite + FastAPI. In order not to disrupt Chat's existing workflows, this branch introduces Next.js public-web code independently and proposes adapting through versioned FastAPI APIs and the existing durable infrastructure. A NestJS service should only be adopted following a reviewed migration decision, not as a surprise replacement.

## Enquiry storage (disabled by default)

The contact route has an optional enquiry form with PostgreSQL lead+outbox atomic writes. It is **disabled** unless `WEBSITE_LEAD_CAPTURE_ENABLED=true` and the dedicated database and origin values are configured. Never enable before anti-abuse controls, least-privilege credentials, approved privacy text, and durable retry/worker verification. CRM/email deliveries are not implemented. SQL has not been run against a database; see `db/003_lead_capture.sql`.

### Idempotency safety update

`db/004_lead_idempotency.sql` adds a SHA-256 fingerprint of the normalized submission payload. Reusing an idempotency key with different form data now returns HTTP 409 and does not pretend a new enquiry was accepted. Apply migrations in order after backup and privilege review, with a tested deployment backfill. This code remains unverified against live PostgreSQL.

## CMS writing foundation (internal only, not enabled)

`src/lib/cms-editor.ts` provides server-only `saveDraft`, `publishApproved`, and `restorePublished` domain operations, each using one PostgreSQL transaction. They require actor permission objects sourced from a future authenticated server-side owner console. No write endpoint or login/role verification is wired to these functions. Publication requires an already-approved revision and a different publishing actor; an approval workflow is **not yet implemented**. Publication inserts a new published snapshot, updates the live pointer, and writes audit and outbox records atomically. Restoring an older published snapshot preserves all revision history. The database migration, role permissions, cache invalidation worker and cross-instance verification remain outstanding. DO NOT deploy or expose these operations before authentication, migration and role tests.

### Independent editorial approval (not production activated)

`db/005_cms_approvals.sql` introduces attributable approval records. The internal `approveDraft` method now requires `cms:review` permission from a **trusted server session**, excludes self-approval by the revision author, records approval and audit in one transaction, and moves the revision to approved state. Publication requires both approved state and corresponding independent approval evidence. No admin API or trusted user-session adapter has been implemented yet. Approval-state mutation is a workflow status update; content block/title snapshots remain unchanged. Confirm migration, database role grants, concurrency and audit integrity in integration tests before activation.

## CMS page creation checkpoint

Added server-only `createPage` to `src/lib/cms-editor.ts`. It creates a new page and initial draft revision inside one transaction, writes an audit record, and refuses duplicate site/locale/path combinations. `src/lib/cms-path.ts` restricts new routes to `/content/<slug>`, away from existing Chat and website routes. Contract tests cover reserved, malformed and nested routes. This is not a working public admin UI; it has no authenticated caller, applied schema, or validated database permissions. Production activation remains blocked.

## Protected CMS authoring API — NOT enabled for production
The branch now includes an internal owner API for **listing pages**, **creating a page**, **saving drafts**, **approving**, **publishing**, and **restoring**:
- `GET/POST /api/owner/pages`
- `POST /api/owner/pages/:pageId/draft|approve|publish|restore`

All endpoints deny access by default. A protected action requires a verified RS256 Bearer access token with exact issuer/audience, `sub` UUID, matching `site_id` UUID, permitted `permissions` array, and a maximum token age of 15 minutes. They **never trust actor, site or roles from a JSON body**. Write requests require the configured origin and JSON content type. Drafts are not served through public APIs. The identity-provider integration, login UX and JWT issuance are **not** supplied by this repository. Configure `WEBSITE_CMS_OIDC_ISSUER`, `WEBSITE_CMS_OIDC_AUDIENCE` and `WEBSITE_CMS_OIDC_JWKS_URL` only after an identity/security review.

This API also requires `WEBSITE_CMS_OWNER_API_ENABLED=true` **and** `WEBSITE_CMS_OWNER_DB_RLS_VERIFIED=true`; the latter is an explicit operator attestation, **not a tested RLS implementation**. Do not enable until isolated migrations, database permissions/RLS, replay/rate limits, external identity-provider mapping, audience and permissions, audit, CSRF/origin configuration, TLS, and browser integration tests are verified. The two flags alone do not make this safe to deploy. Since no delivery worker exists, publish/restore respond `publication-queued`/`restoration-queued` instead of claiming cache refresh is complete. This is not an owner-operated production CMS yet.
