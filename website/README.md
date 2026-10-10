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

## CMS publish/rollback/trash outbox reconciler — disabled by default

A one-shot, site-scoped worker (`npm run cms:revalidate:once`) processes **only** `cms.published`, `cms.restored`, `cms.trashed`, and `cms.restored_from_trash` outbox records. It preserves the original event, locks one due item, loads the page path from the site-scoped database row, and sends an HMAC-SHA256 signed, timestamp-bound, event-ID-bound request to `POST /api/internal/cms-revalidate`. The receiving Next.js handler verifies the signature and allows **only canonical `/content/<slug>` paths**, plus fixed `/resources`, `/blog`, `/sitemap.xml` invalidations; it never accepts an arbitrary cache pathname. Only an HTTP 204 from the receiving service marks the event delivered in PostgreSQL; failure increments attempts and schedules an exponential retry without dropping records. Like other outbox processors this guarantees **at-least-once**, not exactly-once delivery.

Activation requires a verified HTTPS `WEBSITE_CANONICAL_ORIGIN`, `WEBSITE_CMS_SITE_SLUG`, `WEBSITE_CMS_REVALIDATION_ENABLED=true`, the same high-entropy `WEBSITE_CMS_REVALIDATION_SECRET` in both environments, and a **dedicated** `WEBSITE_CMS_OUTBOX_WORKER_DATABASE_URL` with site-scoped SELECT on event/page references plus narrowly scoped outbox UPDATE. Events must be authenticated at the receiving endpoint; neither endpoint nor worker is a public browser API. Migrations 001–010 (including outbox retry 007) and database grants must first pass on an isolated database. Do not enable an untrusted scheduler, bypass secret management, expose worker credentials or add an automatic purge.

**Limitations:** The worker requests Next.js route cache invalidation, not verified eviction from every CDN/edge, third-party search index or separate deployed instance. The public content page is already dynamically resolved, but external caching and multi-instance propagation need separate review. No scheduler, operational dashboard, redrive controls, alert thresholds, CDN API adapter, integration-run proof or passing CI has been confirmed. Unit contract tests exist in `tests/cms-invalidation.test.mjs`; they have not been verified passing on GitHub. Never mark content removal fully propagated just because this worker returns HTTP 204.

## Media quarantine and owner intake (Chapter 8.4, partial)

Added additive `db/011_media_quarantine.sql`, a private `media_assets` metadata manifest with site scope and `media_usages` references, server-side allowlisted image metadata parsing, `cms:media` permission in signed owner claims, `GET/POST /api/owner/media` and an owner UI at `/owner/media`. The UI calculates SHA-256 locally from a selected file and sends **only metadata**, alt text, licence/rights statement and provenance (including AI generation tool when relevant). No image bytes are uploaded by this step. The new record always starts as `state=quarantined`, `blob_status=not_uploaded` and is invisible to public visitors.

The database approval constraint is intentionally strict: `state=approved` requires confirmed uploaded bytes, scanner evidence/checksum/MIME/size agreement, dimensions, review actor/time, alt text and rights. Unknown/active types including SVG and HTML are excluded. Private records are site-scoped, usage references have cross-tenant FK protection, and source records have no automatic purge or expiry. There is **no owner endpoint for bypassing scan evidence**, no public asset read/view and no upload completion/scanner worker yet. This is a safe **metadata foundation**, not a functional media-delivery pipeline.

Feature flags remain OFF by default: `WEBSITE_MEDIA_MANIFEST_ENABLED=false` in addition to the existing owner API/identity and DB isolation gates. Before activation install migration 011 in an isolated backed-up database, provision least-privilege editor grants and RLS, configure tested identity-provider roles, prove the SQL integrity/tenant constraints and run browser/API tests. Before PUBLIC asset use implement quarantined object-storage upload, content-aware file inspection, malware scanning, privacy metadata stripping, responsive derivatives, attribution/provenance retention, scanner identity, review workflow, CDN invalidation, usage impact and signed private downloads. None of those completion steps is claimed here.

## Private media byte upload checkpoint (not a completed media pipeline)

An opt-in, permissioned `PUT /api/owner/media/:assetId/upload` endpoint now accepts raw `application/octet-stream` image bytes (maximum 10 MiB). The owner must first reserve a quarantine manifest through `POST /api/owner/media`. The server enforces trusted OIDC owner authorization plus `cms:media`, exact same-origin and request-length checks. The server **recalculates SHA-256**, compares actual bytes with the reserved checksum/length and checks JPEG/PNG/WebP/AVIF file signatures; the user's claimed MIME type is never enough. Unknown or already approved/rejected media cannot be silently overwritten. Quarantine uploads use a separate private S3-compatible adapter (usable with self-hosted MinIO) and are acknowledged only after a private PUT, private object HEAD check, database status update and audit event. No public object URLs, ACL grants, media approvals, scan attestations or automatic deletion endpoints exist.

The owner media UI can now upload the selected file to private quarantine after reserving metadata, and offers a retry if object storage is unavailable. When upload is disabled it still reserves metadata only. **A successful upload leaves the asset `quarantined` and `blob_status=uploaded`; it is neither scanned nor public.** This is not an antivirus engine or full image parser, and stored bytes may still contain malicious or sensitive metadata. Configure `WEBSITE_MEDIA_UPLOAD_ENABLED=true`, `WEBSITE_MEDIA_STORAGE_ENDPOINT`, `WEBSITE_MEDIA_STORAGE_BUCKET`, `WEBSITE_MEDIA_STORAGE_REGION`, `WEBSITE_MEDIA_STORAGE_ACCESS_KEY_ID` and `WEBSITE_MEDIA_STORAGE_SECRET_ACCESS_KEY` only after bucket privacy, non-public networking, at-rest encryption, TLS, tenant separation, integrity checks, credential rotation and incident handling have been verified. Development-only loopback HTTP for a local self-hosted store requires `WEBSITE_MEDIA_STORAGE_LOCAL_DEV=true` and a non-production runtime.

Storage writes and SQL transactions are not distributed transactions. If a private object PUT succeeds but the database commit fails, the object can be stranded in quarantine and needs an **operator-controlled reconciliation** procedure; do not auto-delete evidence. This implementation holds a row lock during bounded object-store I/O and has not been load tested. The upload feature remains off by default. Independent scanner/byte-level decoding, EXIF stripping, malware/content checks, derivative generation, reviewer approval, public distribution, rate limiting and browser/database/object-store integration tests are all required before enabling this flow in production. Existing GitHub CI has not provided a passing build.

## Internal image inspection and sanitized derivative (Blueprint 8.4, still not publicly usable)

After additive migration `db/012_media_inspection.sql`, an internal-only inspection service can retrieve **already uploaded private quarantine** bytes from S3-compatible storage. It verifies exact original SHA-256, MIME, and length against the reserved manifest. The service sends the original bytes to a **locally operated ClamAV clamd** daemon over 127.0.0.1 INSTREAM. It then uses Sharp's image decoder, rejects oversized/animated/mismatched images, rotates into the pixels and re-encodes a bounded WebP candidate *without copying source EXIF or other unnecessary source metadata*. It scans the re-encoded candidate again and writes it to a **private processed-object key**, verifies its private storage acknowledgment and records hash, dimensions, scanner engine, inspection timestamp and audit event. The result remains `state=quarantined`: scanning and sanitization do **not** constitute publisher approval, copyright validation, public download access or a guarantee of harmless content.

A server-only service route `POST /api/internal/media/inspect` requires a short-lived signed body with exact site and asset UUIDs; it does not accept a browser/owner review claim. The bounded `npm run media:inspect:once` dispatcher looks up at most five uploaded, uninspected, quarantined manifests through a separate **read-only dispatch database role**, signs requests and attempts scanning. Errors remain quarantined for later retry and human investigation; no scheduled processing, automatic source deletion or paid third-party service is introduced. Activate only after `WEBSITE_MEDIA_SCAN_ENABLED=true`, `WEBSITE_MEDIA_SCANNER_DB_ROLE_VERIFIED=true`, separate `WEBSITE_MEDIA_SCANNER_DATABASE_URL` (scoped write/audit role) and `WEBSITE_MEDIA_SCAN_DISPATCH_DATABASE_URL` (scoped selection-only role), `WEBSITE_MEDIA_SCANNER_ACTOR_ID` (UUID) and a strong server-only `WEBSITE_MEDIA_SCAN_WORKER_SECRET` are configured. Set `WEBSITE_MEDIA_CLAMD_PORT` to a local daemon with properly configured signature updates and streaming limits. `WEBSITE_MEDIA_UPLOAD_ENABLED` and the existing **private** object store must also be configured and secured. Do not expose clamd directly to the public network.

**Important acceptance blockers:** independent human reviewer and approval UI/service, generated public-asset delivery and CDN rights enforcement, durable job claims/backoff/dead-letter alerts, ClamAV service operation and signature-update monitoring, malicious-file corpus tests, Sharp sandboxing/patch cadence, backup and restore, failed private derivative/DB reconciliation, source-file privacy/legal retention, and a successful production-like PostgreSQL + S3 + clamd + browser test are still required. This feature has **not** been verified against a live scanner or external store; passing GitHub CI is also unavailable. Do not enable it in production until all security and operational gates are met.

## Independent human media review (still private)

An owner with the separate signed `cms:media:review` permission can visit `/owner/media/review`, inspect **only the sanitized private WebP candidate** through authenticated `GET /api/owner/media/review/:assetId/preview`, review the recorded alternative text, scan status and rights declarations, and submit a 10–500-character reason to `POST /api/owner/media/review`. Every decision is site-scoped, locked and audited. Approval is denied when the asset was created by that reviewer, remains unscanned, lacks sanitized-derivative evidence, has mismatching source hash/MIME/size, lacks alt text/rights, or the current sanitized hash differs from the exact hash the reviewer saw. A rejected item stays retained for source-preservation investigation. The private review image is streamed with `Cache-Control: private, no-store`, a strict WebP content type and no public storage URL.

Approval **does not serve the asset to the public**; the scanner/derivative stage and reviewer stage each have independent feature gates and DB credentials. Configure `WEBSITE_MEDIA_REVIEW_ENABLED=true`, `WEBSITE_MEDIA_REVIEW_DB_ROLE_VERIFIED=true`, a separate least-privilege `WEBSITE_MEDIA_REVIEW_DATABASE_URL`, and OIDC `cms:media:review` only after team separation, RLS, audit, rights verification and protected-preview tests are complete. The client checkbox is helpful reviewer acknowledgment but not a replacement for audited server-side separation. Public media publishing/CDN delivery, approvals for legally complex rights, rollback and complete browser integration are still unimplemented; keep both flags disabled for production until tested.

## Approved media publication and public delivery — independently gated

Additive migration `db/013_public_media_delivery.sql` introduces **separate** attribution for publication and withdrawal of already-approved assets. Its security-barrier `website_cms.public_published_media` view exposes rows to a *server-side, least-privilege reader* only when a different authorized owner has published an approved, independently reviewed and sanitized asset and it has not been withdrawn. The view's storage key is server-only, **never** sent to site visitors. Source/quarantine objects cannot be served by the new public route.

An owner holding verified `cms:media:publish` (different permission from `cms:media` and `cms:media:review`) can use `/owner/media/publish` or the private `GET/POST /api/owner/media/publication`. Publishing or withdrawing requires an attributed decision plus 10–500 character reason. The publisher cannot publish their own uploaded asset. Decisions use a PostgreSQL row lock and commit an append-only audit event with each change. Withdrawal removes the asset from the published-only view, without deleting the source, derivative, scanner evidence, prior publication history or usage references. A later authorized re-publication records a new audit event.

`GET /media/:assetId` has no arbitrary source parameter or redirect. If explicitly enabled, it checks the published-only PostgreSQL view **on every request**, verifies UUID-scoped processed-object key, private read-only object-store HEAD metadata, total length and actual SHA-256 of returned WebP bytes. It uses separate public-media database reader and **read-only S3-compatible object-store credentials**, never the uploader/scanner writer credentials. It sends `Cache-Control: no-store`; withdrawal is not represented as a reliable CDN purge or global invalidation claim. The public route responds 503 when disabled, 404 for missing/unpublished/mismatched/corrupt assets. Do **not** configure an external CDN to override no-store.

The CMS owner block editor now supports typed inert `image` blocks with an approved-media UUID, required accessibility alternative text and optional caption. Server-side publishing and rollback verify every image reference is published, approved, same-site and not withdrawn in the transaction that creates an immutable published revision, then record append-only `media_usages` references. Browser rendering produces only a same-origin `/media/<UUID>` path, never owner-controlled HTML, SVG or an external URL. Existing text, callout, blog and form workflows are preserved.

**All feature switches default OFF.** To activate, independently verify the PostgreSQL migrations 001–013, a separate publisher DB role (`WEBSITE_MEDIA_PUBLICATION_DATABASE_URL`), read-only published-view DB grants (`WEBSITE_MEDIA_PUBLIC_DATABASE_URL`), DNS/TLS and least-privilege S3 credentials (`WEBSITE_MEDIA_PUBLIC_STORAGE_*`), ClamAV signature updates, actual byte scanning/decoding, human reviewer role separation, permissions, retention/legal rights, backup recovery, withdrawal behavior, no-cache rules, concurrency, cross-tenant isolation and E2E tests. Then an authorized operator may set `WEBSITE_MEDIA_PUBLICATION_ENABLED`, `WEBSITE_MEDIA_PUBLISH_DB_ROLE_VERIFIED`, `WEBSITE_MEDIA_PUBLIC_DELIVERY_ENABLED` and `WEBSITE_MEDIA_PUBLIC_READER_GRANTS_VERIFIED` to `true`. This is **committed application code, not a verified production rollout**; GitHub CI and all live dependencies are unverified.

## Media withdrawal impact review

Media withdrawal now counts **currently published, non-trashed CMS pages** that reference the asset via `website_cms.media_usages` and their active `current_published_revision_id` pointers. Historical/archived drafts are not counted as live page impact. The owner media publishing console shows the current count. If at least one live page uses a published image, it presents an explicit broken-image warning and requires the publisher to acknowledge the affected pages before withdrawal. The server independently rechecks those references inside the publication decision transaction; a missing acknowledgement causes refusal, while an acknowledged urgent/legal withdrawal is still allowed. The attributable audit event stores the reason, the live-page count at decision time, and the acknowledgement. No media source or usage history is removed.

This feature **does not automatically replace image blocks** in affected pages. After withdrawal, operators should republish affected pages with approved alternatives, using their existing immutable CMS revision workflow. Public media delivery remains no-store and database-gated per request, but separate proxies/CDNs and previously downloaded assets cannot be forcibly recalled. Verify concurrent CMS publication versus asset withdrawal, tenant isolation, permission grants, CDN behavior and full UI acceptance in a real environment before release.

## Scope checkpoint — visual builder, consented analytics, automation drafts (CRM deferred)

**Website Blueprint v1.3 sections 08, 17, 19, 44–45 and Appendix N:** This is an incremental implementation, not proof of full blueprint completion.

- The owner CMS now supports additional **allowlisted and versioned** hero, CTA and FAQ blocks alongside existing inert heading, paragraph, callout and image blocks. New instances get stable UUID `blockId` values, reordering retains identity, duplication creates a new identity, and the editor has keyboard-accessible order and undo/redo controls. Legacy published snapshots without block IDs remain supported. Unknown types/unsafe CTA destinations are denied by both the private editor and public renderer.
- New first-party optional consent receipt API `POST /api/privacy/choices` stores policy-versioned, 30-day, site-scoped purpose decisions (migration `014_privacy_analytics.sql`) and invalidates the prior receipt on change. Local UI permits optional purposes **only after successful server receipt**, expires choices, and synchronizes same-origin tabs. The collector `POST /api/analytics/events` accepts only five bounded event names, stable action keys and canonical paths, and requires a current, nonwithdrawn server consent receipt. Site-scoped rate windows cap collection to 30 events/minute/receipt. No IP, full query URLs, arbitrary JS payloads, email or form field content enter the analytics table. `/owner/analytics` displays only daily groups of at least five events. There is **no Google/Meta/tag egress, customer identity resolution, qualified-lead reporting or production retention/DSAR processing** yet. This is not lawful-basis signoff.
- Migration `015_automation_drafts.sql` and `/owner/automations` provide permissioned, append-only, site-scoped graph drafts with version-conflict protection, typed trigger/condition/delay/internal task/exit nodes and synthetic-clock simulation. The graph validator checks cycles, unreachable nodes, unknown conditions/actions, expiry-sized delays, and missing exits. **There is no activation, live enrollment, campaign sender, workflow worker or external dispatch. Real CRM integration is intentionally deferred.**
- Added Playwright smoke tests for navigation, default-denied consent, and unconfigured owner routes, plus a browser CI step after the isolated Postgres migration/typecheck/build sequence. Expanded the PostgreSQL verifier through migrations **001–015**, including anonymous consent, analytics exclusions, and immutable workflow drafts. `npm run test:security-db` performs **read-only** checks for superuser/RLS bypass, private-table grants and tenant RLS. It is intentionally fail-closed; feature flags asserting verification are not themselves test evidence.

**Release blockers:** the GitHub Actions job currently fails before producing usable execution logs; there is no passing TypeScript/build, PostgreSQL 001–015, Playwright, external IdP/OIDC, object store/ClamAV, tenant RLS/grants, performance/accessibility, production consent-policy/retention or recovery evidence. Multi-instance publishing, full builder features (autosave/recovery, custom collections, global components, full responsive presets, scheduling and release manifests), actual automation runtime, ad/analytics adapter approval, experiments and attribution remain incomplete. The user deferred **real CRM integration**, which is not being activated or represented as completed. `main` remains unchanged.


## Additional builder and stale-edit safety checkpoint — 2026-10-10

- Added a bounded reusable layout catalogue (services overview, resource article and contact conversion) using only the approved hero, CTA, FAQ, paragraph and heading registry. Instances receive fresh UUID-backed block identities and remain editable drafts requiring independent review and publication. These are content skeletons, not asserted facts, prices, proof or approved marketing copy.
- First-party analytics now accepts only enumerated fixed action keys or stable, versioned builder block UUID actions, rejecting arbitrary free-text identifying keys. Owner aggregates exclude events associated with withdrawn, expired, or non-analytics consent receipts. A consent withdrawal still needs legally approved raw-event retention/erasure handling before production enablement.
- CMS draft saves now require `expectedVersion` and enforce that it matches the latest revision number inside the same row-locked PostgreSQL transaction. A stale editor gets HTTP 409 instead of creating an overlapping draft. The editor shows the expected version and a visible unsaved status, warns on navigation/revision replacement and marks edits acknowledged only after a successful server response. This is optimistic conflict avoidance; comparison/merge and approved time-limited browser draft recovery remain outstanding.
- Added template identity, active-consent aggregate, analytics action key, and stale CMS-save contract tests. **Tests are committed but not confirmed passing.** Browser and Postgres integration results cannot be asserted until GitHub Actions executes jobs and approved staging dependencies are provided. No real CRM integration is enabled. All work stays on `feature/website-blueprint-v1-3`; `main` remains unchanged.


## Visual editor recovery and browser GPC checkpoint

The owner CMS includes an optional, **explicit opt-in** two-hour recovery snapshot stored only in `sessionStorage` within the current browser tab. The snapshot is bounded at 100 KB, structurally validated, tied to authenticated site ID + owner ID + page ID, and never automatically becomes an approved or published revision. The editor offers **Restore** and **Discard**, preserves local edits after stale-editor conflicts, warns before leaving, and clears the current owner's snapshots after acknowledged sign-out. Restoring an outdated snapshot requires explicit comparison with the latest server revision before saving. The feature is disabled until `NEXT_PUBLIC_EDITOR_RECOVERY_ENABLED=true` is approved; device sharing, XSS, browser extension threats and sensitive unpublished copy require a formal storage decision. Session storage is not encrypted by this application and is not a replacement for a real server draft.

Privacy choices are now filtered through `Sec-GPC: 1` at the server and the supported browser GPC property on the client, conservatively disabling optional marketing measurement while leaving essential processing unchanged. The backend always returns the effective permission decision; the client no longer assumes the originally requested consent was accepted. GPC is **not** interpreted as a universal demand to erase operational, transactional or legally retained records. Legal applicability and final policy signoff remain pending. Browser opt-out failures and server receipt failures must remain visible, not silently grant tracking.

## Durable internal automation runs — migration 016 (not live customer dispatch)

`db/016_internal_automation_runs.sql` adds tenant-bound, version-pinned `automation_internal_runs`, `automation_run_steps` and deduplicated `automation_internal_tasks`. Cross-tenant task/step references are blocked by composite FKs; synthetic enrollment carries only source category and a synthetic permission Boolean, never names, emails or contact destinations. Owners with `cms:automation` can enqueue **synthetic-only** runs at `POST /api/owner/automations/:id/test-run` and list their status with `GET /api/owner/automations/:id/runs`. The workflow screen shows those states. This does not activate any live draft or enroll accepted production leads.

The separate `POST /api/internal/automations/tick` service route requires an authenticated short-lived HMAC command and explicitly enabled verified DB roles. A bounded batch of ten due, synthetic-only runs is selected using `FOR UPDATE SKIP LOCKED`. Node transitions, due times, step records and internal task creation occur within one PostgreSQL transaction. Task IDs are unique per run/node; retries cannot silently duplicate internal task records. Delays are persisted as `due_at` and completed runs remain available for owner audit. This is not a queue-only timer or third-party paid workflow engine. The explicit `npm run automation:internal:once` CLI can invoke the signed endpoint; no recurring scheduler or provider request is installed. The worker does not read any customer contact fields and cannot email, send SMS/WhatsApp, export CRM data or trigger ad spend.

**Still required for production:** independently reviewed/published workflow versions; genuine accepted-event enrollment and re-entry eligibility; current consent/suppression checks at every effect; approved purpose, quiet hours, cost budgets, emergency stop, durable alerts and retries; owner run/task inspection; external dispatch adapters after approval; scanner, IdP, tenant RLS and data restore integration. The synthetic service remains `WEBSITE_AUTOMATION_INTERNAL_RUNS_ENABLED=false` and `WEBSITE_AUTOMATION_RUNNER_ENABLED=false` by default; `WEBSITE_AUTOMATION_RUN_DB_ROLE_VERIFIED` must be operator-verified, not inferred from a green test stub. Never enable against live customers or equate the synthetic worker with a completed marketing automation system. The PostgreSQL acceptance script now covers additive migrations 001–016, including run state, task deduplication and cross-tenant references, but the live test has **not passed in this environment**.


## Internal task handling and final safety adjustments

The synthetic-only automation owner screen now lists durable internal tasks and permits a manual, audited `pending -> done` decision with a reason. The server validates owner permission, same-site workflow/run binding, current pending state, UUID identity, and never deletes an event or sends a message. Workflow drafts changed locally must be saved and server-acknowledged before a new synthetic run can be queued; this avoids silently testing an earlier saved version. The run engine fails tasks scheduled beyond the 14-day expiry budget. SQL migration 016 uses composite same-site keys for run/task/step relationships and the isolated migration fixture rejects wrong-site tasks and duplicate operations.

The opt-in editor recovery state is now flushed immediately before page switching, in addition to its bounded debounce, to avoid losing an edited page when navigation occurs quickly. All local recovery remains restricted to the current signed-in owner, site, page, browser tab, and two-hour expiry and is disabled by default.

These additions still require real PostgreSQL, IdP/session, CI/Playwright and security/load acceptance. No live automation enrollment or external CRM provider calls were implemented. No updates to `main`.


## Blueprint follow-on: OIDC trust, responsive previews and first-party event integrity (2026-10-10)

- The owner access-token verifier now uses the same strict issuer-origin rule as the OAuth callback: HTTPS JWKS URLs must share the configured issuer's origin and cannot include credentials, query strings or URL fragments. A standalone unit contract covers wrong-domain keys and malformed URLs. This closes a previously inconsistent API authentication trust check. It is **not** a substitute for real OIDC provider enrollment, MFA, role provisioning, signed-token/browser acceptance or verified database RLS.
- The CMS visual editor now provides desktop (1200px), tablet (768px) and mobile (390px) layout preview modes, with accessible pressed-state controls and horizontal scrolling. Preview layout is a local unpublished approximation, not a real-device Lighthouse, WCAG or viewport-screenshot test. Existing publication and approval contracts are unchanged.
- The optional analytics adapter now suppresses database failures even when the connection or consent DB configuration fails **before a client can be acquired**. Regression tests cover missing configuration, refused connections and a revoked receipt. The first-party event contract pairs each event type with exactly its approved action type to prevent fake FAQ/CTA/navigation metrics and arbitrary identifying action names.
- Additive migration **017_analytics_integrity.sql** adds a PostgreSQL event/action CHECK constraint, marked `NOT VALID` to preserve historical rows while immediately checking all new writes. PostgreSQL fixture expectations now require contiguous migrations 001–017 and verify acceptance of matching actions and rejection of mismatched ones. Old data must be reviewed before a DBA separately validates the constraint. No analytics data or existing feature is deleted.
- `npm run test:imports` now checks relative imports across the app, scripts and unit tests without network access; it runs before Vitest in the dedicated website CI workflow. Isolated fixture tests verify that missing imports cause a non-zero exit. These checks are additive, not a substitute for TypeScript, Next build, PostgreSQL or Playwright verification.
  
**Not production-ready:** the last GitHub Actions jobs failed before executing any steps; no successful automated build or integration tests can currently be asserted. Complete visual-builder releases and collections, approved campaign runtime, consent/data rights, accountable marketing analytics, actual OIDC provider, least-privilege RLS and end-to-end/load/security acceptance still need completion. External CRM integration remains explicitly deferred. All commits are on `feature/website-blueprint-v1-3`; no merge into `main`.


## Private privacy-rights case workflow — blueprint Chapter 59 (partial)

Added a **disabled-by-default** owner workspace at `/owner/privacy/rights`
with authenticated `cms:privacy` role, owner-only intake and controlled
status transitions, revision-conflict handling and immutable evidence-minimal
history (migration `018_privacy_rights_cases.sql`). Owner agents may record
only opaque request identifiers and types. Sensitive decisions require a
separate reviewer and an external evidence-reference UUID when appropriate.
All mutations remain site-bound, transactional and audited. Public reading is
not granted; private rights-case grant and tenant-RLS preflight coverage is
added to the security script.

**No deletion or data export is performed by the workflow.** The website does
not yet provide verified requester identity matching, lawful processing
assessments, approved deadline calculation, processor suppression/notification,
data download packages, deletion across data stores, hold execution or evidence
of legal completion. A status change is an operator assertion, **not proof**
that requested access/erasure has actually been fulfilled. Do not enable
`WEBSITE_PRIVACY_RIGHTS_ENABLED` or issue production promises until real
IdP, DB-grants/RLS, legal review, operational evidence links, security tests and
external processor mapping have passed.


## SEO redirect registry — retired content only (migration 019)

The blueprint's owner acceptance exercise includes creating a redirect. This slice adds a separate `cms:redirect` permission, authenticated owner editor `/owner/redirects`, draft creation, independent reviewer approval, auditable suspension and permanent server-side HTTP **308** redirects from retired `/content/<slug>` URLs. It does not redirect arbitrary old URLs, proxy API routes, carry over unverified query parameters, rewrite menus or change existing root routes. Destination values are restricted to known internal public paths or a currently published `/content/<slug>` page. External URLs, protocols, percent escapes, path traversal, fragments, URL queries and same-path redirects are denied. Redirect chains are rejected when approving; the public security-barrier view hides disabled mappings and mappings whose content target is no longer published.

Migration `019_content_redirects.sql` adds a site-scoped redirect registry, checked internal destinations, a security-barrier view, and a page-collision trigger. The page-collision trigger and the approval transaction lock the same site row to prevent concurrent route reuse. No public reader is granted access to the private registry. The administrator must grant only the new public redirect view, with private site-specific editor privileges and tenant isolation separately reviewed. Writer and public-reader features are **off by default** using `WEBSITE_REDIRECT_EDITOR_ENABLED` and `WEBSITE_REDIRECT_PUBLIC_ENABLED`; verified DB-grant flags and distinct credentials are required. The existing public content route applies approved redirects only when the live published page is missing. The 308 status intentionally preserves the destination path but does not preserve UTM or click query strings; policy-specific attribution-preserving redirects require separate testing and approval.

This is an additive isolated implementation. Full redirect inventory, bulk import/export, multisite/locale handling, arbitrary legacy URLs, owner navigation-edit flows, canonical SEO migration, sitemap audits, performance tests and release approval are still outstanding. Unit tests and the isolated migration acceptance script through **001–019** are committed but **not confirmed executed**. CRM integration remains deferred. No changes to `main`.


## Privacy-rights dual review and redacted audit timeline

The private Chapter 59 workflow now explicitly blocks a reviewer from making two
consecutive sensitive case decisions: the case creator remains excluded from
sensitive approvals, and the actor of the immediately preceding history entry
must differ from the new sensitive reviewer. This is enforced inside the
transaction holding the case lock, and includes a regression test. Operators
still need actual independent reviewers provisioned in the IdP; no legal
compliance is inferred from the transition log.

Added `GET /api/owner/privacy/rights/:id/history` and a status timeline in
the owner rights case screen. The handler requires verified `cms:privacy`
claims and returns only site-scoped revision, status, reason, time and an
evidence-present Boolean. It does **not** return actor identity, evidence UUID,
requester details, or source records. A service regression test checks scope
and response field exclusion. The evidence-entry form now requires a valid
UUID before enabling sensitive actions. This is not an automated erasure
or data-access fulfilment path.

Production blockers remain: functioning GitHub CI runners, a passing Next.js
build, 001–018 PostgreSQL migration and tenant RLS/grants verification,
a configured real identity provider with independent reviewers, privacy policy
and processor mapping, advanced builder orchestration, and production
automation plus browser E2E. Real CRM integration remains deferred. Changes
are committed only to `feature/website-blueprint-v1-3`; do not merge main.


## Owner authentication: recent MFA evidence gate

The owner JWT verification path now offers a fail-closed optional
`WEBSITE_CMS_REQUIRE_MFA=true` setting. When enabled, the **verified**
RS256 access token must contain a recent (within 12 hours) `auth_time`
and a strong MFA `amr` value (`mfa`, `otp`, `hwk`, `swk`,
`fido`, or `webauthn`), or an exact operator-approved
`WEBSITE_CMS_MFA_ACCEPTED_ACR` value. The policy is evaluated before
creating a trusted CMS actor context, including privileged privacy,
publishing, redirects and automation routes. Bad or missing proofs fail closed.
The gate defaults OFF for backward compatibility until the external IdP
claim semantics and enforced MFA enrollment are verified.

This is **not** a substitute for real provider-side MFA enforcement,
role provisioning, key rotation, OIDC integration tests, audited recovery,
or independent release security sign-off.
