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

`src/lib/cms-editor.ts` provides server-only `saveDraft`, `publishApproved`, and `restorePublished` domain operations, each using one PostgreSQL transaction. They require actor permission objects sourced from a future authenticated server-side owner console. Write API code now exists behind disabled-by-default short-lived signed bearer authentication; login UX and live identity-provider integration remain unavailable. Publication requires an already-approved revision and a different publishing actor; an approval workflow is **not yet implemented**. Publication inserts a new published snapshot, updates the live pointer, and writes audit and outbox records atomically. Rollback now creates a **new compatible published snapshot** from an older published revision and atomically updates the live pointer, audit and outbox without modifying the source snapshot. The database migration, role permissions, cache invalidation worker and cross-instance verification remain outstanding. DO NOT deploy or expose these operations before authentication, migration and role tests.

### Independent editorial approval (not production activated)

`db/005_cms_approvals.sql` introduces attributable approval records. The internal `approveDraft` method now requires `cms:review` permission from a **trusted server session**, excludes self-approval by the revision author, records approval and audit in one transaction, and moves the revision to approved state. Publication requires both approved state and corresponding independent approval evidence. A disabled, JWT-verified admin API is now present, but no login UX or tested live identity-provider integration exists. Approval-state mutation is a workflow status update; content block/title snapshots remain unchanged. Confirm migration, database role grants, concurrency and audit integrity in integration tests before activation.

## CMS page creation checkpoint

Added server-only `createPage` to `src/lib/cms-editor.ts`. It creates a new page and initial draft revision inside one transaction, writes an audit record, and refuses duplicate site/locale/path combinations. `src/lib/cms-path.ts` restricts new routes to `/content/<slug>`, away from existing Chat and website routes. Contract tests cover reserved, malformed and nested routes. This is not a working public admin UI; it has no authenticated caller, applied schema, or validated database permissions. Production activation remains blocked.

## Protected CMS authoring API — NOT enabled for production
The branch now includes an internal owner API for **listing pages**, **creating a page**, **saving drafts**, **approving**, **publishing**, and **restoring**:
- `GET/POST /api/owner/pages`
- `POST /api/owner/pages/:pageId/draft|approve|publish|restore`

All endpoints deny access by default. A protected action requires a verified RS256 Bearer access token with exact issuer/audience, `sub` UUID, matching `site_id` UUID, permitted `permissions` array, and a maximum token age of 15 minutes. They **never trust actor, site or roles from a JSON body**. Write requests require the configured origin and JSON content type. Drafts are not served through public APIs. The identity-provider integration, login UX and JWT issuance are **not** supplied by this repository. Configure `WEBSITE_CMS_OIDC_ISSUER`, `WEBSITE_CMS_OIDC_AUDIENCE` and `WEBSITE_CMS_OIDC_JWKS_URL` only after an identity/security review.

This API also requires `WEBSITE_CMS_OWNER_API_ENABLED=true` **and** `WEBSITE_CMS_OWNER_DB_RLS_VERIFIED=true`; the latter is an explicit operator attestation, **not a tested RLS implementation**. Do not enable until isolated migrations, database permissions/RLS, replay/rate limits, external identity-provider mapping, audience and permissions, audit, CSRF/origin configuration, TLS, and browser integration tests are verified. The two flags alone do not make this safe to deploy. Since no delivery worker exists, publish/restore respond `publication-queued`/`restoration-queued` instead of claiming cache refresh is complete. This is not an owner-operated production CMS yet.

## Published resource index (read-only)

The public `/resources` route reads at most 100 **already published** entries from `website_cms.public_published_pages` using only the public-reader database credentials. It validates public block schemas and links to `/content/<slug>`, showing an empty state when no resources are published or the database is unavailable. The public query does not use owner/editor credentials. The editor-only `GET /api/owner/pages/:pageId/revisions` API exposes private editorial history only after token and `cms:read` checks. Neither route has been tested against live PostgreSQL; content, SEO and owner review remain release blockers.

## Manual-only content trash and restore (Chapter 38; API disabled by default)

Apply reviewed migration `db/006_manual_content_trash.sql` **after migrations 001–005**, with a backup and migration test. It adds no-expiry trash metadata and ensures the public published-content view excludes trashed pages. The owner-only endpoint `POST /api/owner/pages/:pageId/preservation` takes `{"action":"trash"|"restore","reason":"..."}`. Both require a verified JWT, site-specific `cms:trash` or `cms:restore` permission, same-origin JSON request, and `BLOG_AUTO_DELETE_ENABLED=false`. Trashing atomically clears the published pointer, retains every revision and records the human actor, reason, audit and outbox. Restoring leaves the page unpublished; republishing is a distinct reviewed editorial action. Slugs remain reserved by the unique page record. **No permanent purge API or automatic delete job has been implemented.** Public CDN/cache invalidation is not implemented, so the API responds 202 rather than claiming worldwide removal. The stronger, independently approved purge flow and legal-hold protections remain release blockers. No live DB migration, security penetration tests or browser verification have run.

## Owner dashboard with OIDC login (feature-gated, NOT deployed)

The `/owner` page now includes an accessible editor for approved paragraph/heading/callout blocks, local non-public preview, page creation, draft versioning, history, separate review/publish/rollback, and manually authorized trash/restore. It connects to protected `/api/owner` endpoints and never places bearer tokens into browser JavaScript or local storage.

`GET /api/owner/auth/login` starts OIDC authorization-code + PKCE using HTTPS endpoints bound to the configured issuer origin. Callback verifies encrypted state, client-specific nonce with an RS256-signed ID token, and the separately signed access token's issuer, API audience, user UUID, site UUID and allowed permissions. A short-lived encrypted `__Host-` HttpOnly Secure SameSite cookie carries the access token; every owner API call still verifies the access token. `POST /api/owner/auth/logout` clears cookies but does **not** revoke an external access token already issued by the IdP. No refresh token is retained.

**Activation requires** `WEBSITE_CMS_OWNER_API_ENABLED=true`, `WEBSITE_CMS_OWNER_DB_RLS_VERIFIED=true`, a valid `WEBSITE_CMS_OWNER_SITE_ID`, HTTPS `WEBSITE_CANONICAL_ORIGIN`, approved `WEBSITE_CMS_OIDC_ISSUER`, `WEBSITE_CMS_OIDC_AUDIENCE`, `WEBSITE_CMS_OIDC_JWKS_URL`, `WEBSITE_CMS_OIDC_CLIENT_ID`, authorization and token endpoint URLs, and a 32-byte base64url `WEBSITE_CMS_SESSION_KEY`. Register `https://YOUR-DOMAIN/api/owner/auth/callback` as the exact redirect URI at the IdP. Configure identity claims `sub` (UUID), `site_id` (UUID), `permissions` (explicit allowlist). This is **not** a tested or approved deployment recipe: verify IdP compatibility, MFA and session-revocation policy, cookie size, tenant/RLS isolation, DB writer privileges, migration installation, same-origin request security, background delivery, rate limiting, availability, audit integrity and integration tests first.

The editor handles approved text blocks only. Rich media, menus, forms, scheduled content, autosave, true visual layout builder, blog collections, backup/restore drills and marketing modules are still unfinished. `BLOG_AUTO_DELETE_ENABLED=false` must remain in place; no automatic source purge is provided.

## Durable CRM lead handoff (still OFF by default)

After DBA-reviewed `db/007_outbox_retries.sql`, an opt-in **one-shot** command is available: `npm run lead:deliver:once`. It processes at most ten due `lead.accepted` events for the configured site. Only an approved HTTPS CRM endpoint is allowed, with signed HMAC-SHA256 envelopes (`X-Website-Event-Id`, `X-Website-Timestamp`, `X-Website-Signature`). The receiver **must verify the signature, check the timestamp tolerance, reject replay, and deduplicate using the stable event ID**. The purpose is responding to an enquiry, *not* advertising or marketing-list enrollment.

A 2xx acknowledgment marks the event delivered only after the database transaction commits. Other HTTP responses, network failures, missing source records and interruptions leave events retained with a bounded exponential retry schedule. An HTTP success followed by a worker/database crash can still result in duplicate delivery: this is **at-least-once, not exactly-once**, and receiver deduplication is required. There is no TTL or destructive dead-letter purge. The worker holds a row lock during its five-second bounded HTTPS request; it is a cautious low-volume starting point, **not yet a benchmarked, operationally supervised production queue**. Schedule it only after acceptance testing, backup/restore and alerting; no schedule or external service is automatically installed.

Enabling requires `WEBSITE_CRM_DELIVERY_ENABLED=true`, `WEBSITE_CRM_PRIVACY_APPROVED=true`, scoped `WEBSITE_CMS_SITE_SLUG`, a **separate** least-privilege `WEBSITE_LEAD_WORKER_DATABASE_URL`, approved `WEBSITE_CRM_WEBHOOK_URL`, and server-only `WEBSITE_CRM_WEBHOOK_SECRET` of at least 32 characters. Protect the environment and never send these as public site settings. Before activation prove CRM webhook mapping, retention/rights, no ads-side sharing, rate limits, dual-run retries, PostgreSQL isolation, operational alerts, and incident recovery. Unit contract tests exist but **live CRM delivery tests have not run**.

## Lead abuse-admission checkpoint (disabled by default)

Additive migration `db/008_lead_abuse_buckets.sql` creates two durable hourly counters per accepted enquiry (whole-site and HMAC-keyed contact). Both quotas update **inside the same PostgreSQL transaction** as new lead insertion and its outbox record. When a quota is exhausted the entire new lead/outbox/counter transaction rolls back, returning HTTP 429 with `Retry-After: 3600` rather than a false acceptance. Exact same-idempotency retries do **not** count again, and changed-content retries still return 409. Default budgets are three accepted enquiries per normalized email per hour and 100 accepted enquiries per site per hour. The database clock determines the hour consistently across instances.

The bucket's contact identifier is a server-keyed SHA-256 HMAC; neither plaintext email nor IP appears in the rate bucket. `WEBSITE_LEAD_RATE_ENABLED=true` and `WEBSITE_LEAD_RATE_SECRET` of at least 32 high-entropy characters are REQUIRED alongside the existing `WEBSITE_LEAD_CAPTURE_ENABLED` gate. A missing setting fails closed. The ingestion database role needs narrowly scoped insert/update access to these buckets as well as the previously required lead/outbox access. The global site quota can deliberately block legitimate traffic under distributed attack, so alerting, controlled operator adjustment, a rate policy and escalation are required.

This is an **abuse backstop**, NOT complete bot protection: distributed email cycling, spam, abuse at an untrusted ingress, malicious text and real-world availability still need layered controls, abuse monitoring and acceptance testing. Retention/privacy policies for keyed derived counters, GDPR/DSAR applicability, rate-limit tuning, concurrent PostgreSQL tests, accessibility and incident response remain release blockers. No automatic cleanup, live SQL execution or passing CI has been verified.

## Live publication consistency checkpoint

`/content/[slug]` is now explicitly rendered with Next.js `dynamic = "force-dynamic"` and `revalidate = 0`. The public PostgreSQL adapter reads only the published security-barrier view, verifies the returned route and locale against the requested values, and does not read draft or trash tables. `/resources` now distinguishes an *empty, healthy* published library from a failed or unconfigured CMS read; it no longer misrepresents an outage as zero published articles. The existing `loadPublishedResources` signature remains available for sitemap compatibility. A pure publication-policy allowlist filters noncanonical paths, invalid block shapes, locale mismatches and duplicate entries.

Unit tests in `tests/publication-policy.test.ts` and `tests/publication-db.test.ts` cover the allowlist and a mocked database query, including view selection, route match, empty results and database failures. These are **committed test definitions, not execution evidence**. Next.js per-request rendering does **not** purge independently configured CDN caches, external search indexes, SEO previews, RSS feeds or third-party mirrors. Live publication, rollbacks and manual trash operations still require real database tests, CDN invalidation and cross-instance end-to-end verification. No production launch is approved.

## Blog editorial catalogue (feature branch code; unverified)

Public `/blog` lists **only** approved/published, non-trashed CMS pages explicitly classified as blog entries. It supports keyword and category filtering and bounded tag display. Owner CMS now supports assigning a category and up to eight validated tags to unpublished `/content/<slug>` pages, via protected `GET/POST /api/owner/pages/:pageId/blog`. Classification changes are audited, site-scoped and blocked after editorial approval or publication; source content/history remains retained. The existing editorial draft → independent approval → publish flow remains mandatory. No automatic blog cleanup/purge has been introduced.

Requires the reviewed additive `db/010_blog_catalogue.sql`, published-only reader-view SELECT grant, authenticated owner identity integration and verified DB/RLS permissions. The site-specific blog articles and approved categories must be supplied rather than fabricated. Pagination, categories manager, image/media pipeline, rich editor, scheduled posts, canonical redirect migration, comments moderation and standalone blog archive/trash UI are **not complete**. New `website/tests/blog-contract.test.ts` checks input sanitation; `scripts/verify-postgres.mjs` includes published/trashed blog visibility checks, neither has been reported as passing. No production activation.

## Independent liveness vs. public CMS readiness

Added `GET /api/health/live` for a basic process check and `GET /api/health/ready` for an opt-in public CMS view/read-permission check. Both return `Cache-Control: no-store` and never expose database errors or credentials. The readiness endpoint returns HTTP 503 until `WEBSITE_RUNTIME_READINESS_ENABLED=true`, the canonical `WEBSITE_CMS_SITE_SLUG` and an appropriately restricted `WEBSITE_CMS_DATABASE_URL` are configured; it then probes `SELECT 1 FROM website_cms.public_published_pages LIMIT 0` with bounded connection/query timeouts. Readiness 200 means **only the public published-only DB view is reachable**. It does not attest to business signoff, owner auth, lead ingestion, background queues, CDN invalidation, backup/restore, legal text, or overall production suitability. Deploy safely with restricted public-reader DB privileges; do not use editor or superuser credentials. Unit tests cover disabled/configured states, view probe and suppressed DB errors; live DB probe still unverified.

### Rollback publication semantics

`restorePublished` accepts an existing compatible published revision, validates its current block schema, appends a **new** published revision with the next revision number, and atomically records the prior source revision and previous live revision in the audit/outbox. No historic revision is overwritten and no original publication is deleted. The owner API returns both the new `revisionId` and `sourceRevisionId`, with HTTP 202 for pending downstream propagation. Incompatible older revisions fail safely until an approved migration exists. Actual CDN invalidation remains pending and still blocks production readiness.
