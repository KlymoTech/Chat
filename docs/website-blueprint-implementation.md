# Website Master Blueprint v1.3 — implementation and evidence register

**Branch:** `feature/website-blueprint-v1-3`  
**Policy:** no merges to `main`; no modifications of existing product service behavior without tested additive compatibility.  
**Source:** Website Master Blueprint v1.3, 7 October 2026, 78 chapters and Appendices A–P.

## Required discovery decisions (OPEN — no fabricated answers)

Owner must confirm legal entity, brand, domain, languages, offers, price/claim evidence, content owners, conversion outcome, traffic/uptime expectations, privacy jurisdictions and lawful bases, consent purposes, integrations, production hosting, budget, RPO/RTO, and release reviewers (chapter 02, Appendix A). Without these the website cannot be declared complete.

## Requirements by verified state

| Area | Blueprint mapping | Status | Acceptance evidence required |
| --- | --- | --- | --- |
| Public route starter, navigation, accessible responsive layout | 04–06, 73 | PARTIAL / UNVERIFIED | Home/static routes and published-only resource index code; approved content, browser QA and build passing still pending |
| Owner CMS, page revisions, preview, publish, rollback, media | 07–09, 44, 73, 76 | PARTIAL / DISABLED / UNVERIFIED | Owner block editor, OIDC/PKCE sign-in and APIs added; media, collections, autosave, live DB/RLS proof, provider integration, worker and acceptance tests outstanding |
| Blog preservation and manual-only deletion | 09, 38–39 | PARTIAL / DISABLED / UNVERIFIED | manual trash/restore draft code, persistent metadata and protected API added; blog taxonomy, independent purge/hold workflow, migration verification and cache-consistency tests pending |
| SEO metadata, crawl controls, redirects and sitemap | 10–11, 49–50, 66, 70 | PARTIAL / UNVERIFIED | sitemap, robots and canonical now implemented behind explicit approval; redirects, crawler and search-route checks remain |
| Lead submission and durable outbox/CRM delivery | 20–23, 40, 69 | PARTIAL / DISABLED / UNVERIFIED | intake, transactional outbox, one-shot CRM worker, HMAC signing and atomic hourly quotas added; live anti-bot hardening, IAM/RLS, migrations, worker integration and crash/retry tests pending |
| Privacy, consent-aware visitor and UTM events | 14–18, 35–37, 59, 72 | PARTIAL / DISABLED / UNVERIFIED | versioned server receipt, withdrawal and minimized event collector added; region rules, retention/erasure operations, full attribution and lawful basis review missing |
| Marketing automation, scoring, experiments, ads | 12–13, 19, 34, 43, 45–56, 67–71, 77 | PARTIAL / DRAFT SIMULATION ONLY | Typed immutable workflow drafts and dry-run added; execution, experiments, segments and provider adapters still absent; real CRM deferred |
| Security, identity, immutable audit, recovery | 24, 28–30, 39, 57–60, 74 | NOT IMPLEMENTED | threat, authorization, backup restore and incident drills |
| Specialized commerce/booking/etc. | 25–26, 54, 61, 75 | NOT ACTIVATED | explicit site brief + complete transaction lifecycle |
| Final launch acceptance | 64, 77–78, Appendices N–P | BLOCKED | requirement-to-test traceability, measured signoff and production evidence |

Status labels distinguish **documented**, **implemented**, **activated** and **verified** as required by Appendix P. No unexecuted check is called passing.

## Work sequence

1. Confirm Appendix A brief and site-specific activation catalogue; preserve Chat baseline commit and existing CI.
2. Complete public templates, real reviewed content, content rendering adapter, navigation, responsive/accessibility tests.
3. Implement PostgreSQL-backed owned CMS with owner/editor approvals, published revisions, audit, media, manual-only trash/purge, and invalidation.
4. Build form builder and reliable lead API with atomic transaction/outbox, idempotency, protected views and integration status.
5. Implement consent policy, privacy rights, events/UTMs/attribution, controlled visitor context, and authorized chatbot handoff.
6. Add SEO sitemap/robots/redirect controls, campaign pages, experimentation, reporting and activated provider adapters.
7. Add operations, protection, end-to-end tests, cost/runbooks, backup/restore drills, and Appendix N/P release evidence.

**Prohibited launch states:** falsely acknowledged leads, unauthorized access, prohibited tracking, leaked secrets, broken conversion journeys, untested recovery (chapter 01). Maintain remaining gaps openly.

## Second checkpoint — explicit SEO safety and public error routes

Added website-local `robots.ts`, `sitemap.ts`, `seo.ts`, `not-found.tsx`, `error.tsx`, and `loading.tsx`. Indexing requires **HTTPS, a non-local site URL and NEXT_PUBLIC_SITE_APPROVED=true**. Legal placeholders stay noindex and outside the sitemap. Canonical URLs are provided per public route. These are implementation claims only: a successful production build, crawler validation, keyboard review, browser checks, and live indexability signoff have **not** been established. The company-specific pages are still intentionally placeholders; this is not production launch clearance.

No `main` branch files were modified by this work.

## Third checkpoint — CMS revision and public rendering foundation

Introduced isolated `website/db/001_cms_foundation.sql` for site/page/revision/audit/outbox tables, `website/src/lib/cms.ts` for a validated read-only published-page contract, safe fixed block components, and a `/content/[slug]` public route. This is **not** a functioning owner-operated CMS: the backend public API, editorial console, authorization, publication transaction, and worker have not been created or verified. The SQL was **not applied to any database**. A missing backend returns 404 instead of inventing content, and no success is claimed for unpersisted operations. All additions are isolated to the website folder and the requirements document.

## Fourth checkpoint — database-backed published-page read path

Implemented a `pg`-based server-only data access function reading from a published-only PostgreSQL view and a no-store GET API route. Next.js content routes can render the same view directly, without leaking database credentials to the browser. SQL view, dependency declarations, and configuration example added. No migration, integration test, production database, owner console or authenticated publication workflow has been executed or verified. **Release remains blocked.**

## Fifth checkpoint — fail-closed visitor preferences

Added user-controlled analytics/marketing preferences on all public routes and a discoverable footer control. Unknown or unavailable storage results in denied optional purposes, with no vendor script or tracking activated. Acceptance of future analytics is **not** wired to any provider. The privacy/legal notice is still a placeholder; enforce jurisdiction, withdrawal propagation, server-side consent logs and automated browser tests before release. No tracking consent is implied by viewing a page.

## Sixth checkpoint — lead intake, strictly disabled by default

Added `website/db/003_lead_capture.sql`, a validated lead-input contract, a server-only PostgreSQL transaction committing the lead and one outbox intent, a same-origin POST endpoint, and an accessible contact form shown only when explicitly enabled. Idempotent retries reference the same saved lead. Endpoint acknowledges success only after transaction commit, otherwise responds with failure. The module stays disabled by default pending spam/rate limits, DB privilege isolation, approved privacy copy, operations and integration testing. A worker to actually deliver outbox events to CRM/email is still NOT implemented. No migrations were applied and no automated tests are claimed passing.

## Seventh checkpoint — idempotency replay integrity

Added migration `004_lead_idempotency.sql` and a normalized-payload SHA-256 check. A repeat of the same idempotency key with identical content can return the same durable receipt; a repeat with changed content returns 409 and rolls back. The lead module remains disabled, and DB migration, concurrency, abuse controls, CRM delivery, and end-to-end tests remain release blockers.

## Eighth checkpoint — transactional CMS domain service (internal only)

Added a server-only CMS draft/publish/restore domain service within `website/src/lib/cms-editor.ts`. Operations lock the page row, validate known block shapes, preserve revision history and commit audit and outbox alongside publication/rollback pointer updates. This is **not an owner-operated CMS**: no trusted authenticated owner-console caller, approval endpoint, page-create UI, scheduled publication, media system, or durable invalidation worker exists. Permission inputs must come from verified sessions, not request JSON. No PostgreSQL execution, CI pass or browser test is claimed. The launch gate remains BLOCKED.

## Ninth checkpoint — independent review enforcement

Added migration `005_cms_approvals.sql` and server-only `approveDraft`. Review requires a separate actor from the author, writes attributable approval evidence and audit within a transaction, and publication rejects approved state without matching review evidence. This remains an internal domain implementation, **not** a live authenticated editor: trusted session integration, authorization grants, tests, worker processing, deployments, and UI are absent. The complete website and release acceptance remain blocked.

## Tenth checkpoint — isolated website contract tests

Added Vitest regression tests for lead normalization/rejection, CMS public block validation, deny-by-default optional measurement, and production SEO approval gating. Also corrected email validation to apply to normalized input. The branch-only GitHub Actions workflow now includes `npm test` before typecheck and build. These test definitions are committed but their execution/passing status is NOT confirmed, and they do not replace PostgreSQL integration, authenticated CMS, browser accessibility, worker crash/retry, or release acceptance tests.

## Eleventh checkpoint — bounded public CMS payload validation

The public page contract now validates page IDs, canonical path shapes, locale, revision, title/description sizes, block count and bounded inert text fields before rendering. Added contract assertions covering oversized pages and invalid paths. This reduces malformed published-content exposure but **does not constitute a CMS authentication, approval, or deployment test**. Production readiness remains blocked until live database integration, owner-console authorization, complete outbox recovery, browser tests and acceptance evidence pass.

## Twelfth checkpoint — safe page creation foundation

Added server-only `createPage` for a site-scoped draft page, initial immutable content revision and audit event in a single transaction. The `normalizeCmsPath` guard isolates new content to `/content/<slug>` and refuses reserved/system routes. Added Vitest route-validation tests. These are code changes, not verified runtime behavior: PostgreSQL migrations and integration tests have not run; the authenticated owner-console UI, trusted session adapter, publication invalidation worker and release acceptance remain pending. No merge to `main`.

## Thirteenth checkpoint — disabled owner CMS API and verified-claims boundary

Added protected API routes under `/api/owner/pages` for site-scoped list/create and revision draft/review/publish/restore, using existing transactional CMS methods. Authentication requires cryptographically verified short-lived RS256 bearer tokens, issuer/audience checks and UUID site/user claims; an explicit allowlist determines permissions. The API remains **disabled by default**, also requiring operator-confirmed tenant DB isolation. Added pure claim-validation regression tests. This is NOT complete owner autonomy: token issuance/login, owner UI, real DB/RLS grants, migrations, queue consumer, cache invalidation, end-to-end security and acceptance tests have not been demonstrated. Return `202` for publication work queued for downstream processing, not completed live propagation. No updates to `main`.

## Fourteenth checkpoint — published resources and owner revision history

The resource index now queries the published-only PostgreSQL view and lists validated published pages, with an honest empty state. Added site-scoped owner revision-history listing and `GET /api/owner/pages/:pageId/revisions`, protected by the same verified JWT and `cms:read` permission as the owner page listing. No draft is intentionally exposed through a public route; an unavailable DB yields an empty index rather than fictitious content. No live DB migration, tenant-isolation proof, full owner dashboard, recovery test or CI result has been verified. **No deployment approval; main remains unchanged by these commits.**

## Fifteenth checkpoint — manual-only retained content trash

Implemented additive migration `006_manual_content_trash.sql`, `trashContentPage` and `restoreTrashedContentPage`, separate signed `cms:trash` and `cms:restore` permissions, and `POST /api/owner/pages/:pageId/preservation`. A human action and 10–500 character reason are required. Trash retains all revisions, clears current publication, logs actor/reason with audit and outbox transaction, and excludes trashed pages through the public published-content view. Restore clears trash state but deliberately leaves the page unpublished. Other content mutations reject trashed pages. `BLOG_AUTO_DELETE_ENABLED=false` is checked fail-closed when mutating trash state. Added contract tests, but not executed here. No automatic blog purge is installed. **This does not complete Chapter 38**: independent privileged purge, legal holds, source media relationships, separate audit-export integrity, tenant/RLS verification, cache invalidation, restore drills, and owner UI remain unimplemented. No SQL migrations applied or CI passed evidence. Main remains untouched.

## Sixteenth checkpoint — functional owner UI and OIDC sign-in code

Added a private `/owner` workspace with responsive page list, block editor, local preview, revision list, create/draft/review/publish/rollback and manual trash/restore controls, connected to the protected owner API. Implemented OIDC authorization-code PKCE, encrypted state and HttpOnly owner session, signed RS256 ID-token nonce verification, re-verified short-lived access tokens and local logout. Endpoints remain disabled until explicit IdP configuration, tenant security approval, production secrets, approved HTTPS origin and migrations. This milestone is **code committed, not live-tested or production-ready**. Cross-tenant integration, role-matrix tests, session revocation, IdP tests, cookie handling, database locks, CSRF, browser accessibility and publishing propagation remain acceptance blockers. No main merge.

### Owner sign-in regression checks added

`website/tests/owner-oidc.test.ts` now covers feature-off defaults, valid callback construction, denial of insecure/cross-origin OAuth endpoints, encrypted owner cookie roundtrip, purpose isolation and tampered cookie rejection. The owner UI defaults to an empty valid block list, and local logout clears session cookies even if the owner API becomes disabled. These are **test definitions and code commits, not passing test evidence**. Execute `npm test`, `npm run typecheck`, and `npm run build` plus configured OIDC, PostgreSQL and browser E2E scenarios before enabling owner access.

## Seventeenth checkpoint — opt-in at-least-once lead outbox worker

Added `db/007_outbox_retries.sql`, HTTPS destination validation, event-id based HMAC-signed `website.lead.accepted.v1` envelope, bounded exponential retry logic, one-shot `lead:deliver:once` worker and contract tests. No custom recurring cost or automatic scheduler. The worker requires both explicit enablement and privacy approval, and handles only `lead.accepted`, not other outbox event types. Uses a PostgreSQL row lock and commits delivery acknowledgement only after a 2xx response, retaining failures without deletion. This is an **unverified integration**: destination signature verification, idempotent receiving, PostgreSQL installation, operational alerting, multi-worker stress, recovery drills and security tests remain blocked. Marketing automation, consent-based ads conversion and publication cache workers are still not implemented. Do not activate until live receiver-side checks and release approval.

### Delivery role separation and sitemap inclusion

The worker now reads `WEBSITE_LEAD_WORKER_DATABASE_URL` instead of reusing public form ingestion credentials. Provision an isolated role with narrowly limited SELECT and outbox UPDATE; verify it cannot delete leads, revisions, audit or published source data. The dynamic sitemap now includes only public-view-validated CMS resources after production indexing approval, and robots discourages owner-console indexing. Tests and crawler results remain unverified. Latest GitHub Actions jobs currently fail within seconds with no runner name or executable job steps; this appears to block test evidence before project commands execute. [Example failed run](https://github.com/ooarchitect92/Chat/actions/runs/37990647752). Investigate Actions runner/repository configuration; do not interpret zero steps as a passing build.

## Eighteenth checkpoint — durable lead admission quotas

Added `008_lead_abuse_buckets.sql`, HMAC-anonymized per-contact and site counters, transactionally enforced quotas for **new** accepted leads (3/contact/hour and 100/site/hour), a dedicated feature switch and secret, HTTP 429/Retry-After handling and pure regression tests. Database `now()` supplies the bucket clock, all increments and outbox/lead writes commit atomically, and matching idempotent retries do not consume additional quota. Unknown/missing abuse configuration prevents accepting leads, rather than bypassing the control. No raw contact details/IPs enter the counter table. No expiry job was introduced.

**Verification is pending**: SQL applied nowhere; counter concurrency, cross-instance clock, rate-limit DoS/exhaustion, email-cycling bot defense, rate policy/retention, accessibility, abuse telemetry, RLS, migration rollback, background worker and full end-to-end scenarios are not proven. GitHub Actions jobs on this branch have failed before step execution; a green code/test/build report cannot be claimed. No merge to main.

## Nineteenth checkpoint — publication visibility and outage correctness

Added explicit request-dynamic server rendering on `/content/[slug]` to prevent accidental build-time snapshots of editorial publication state. Public CMS reads reject mismatched path/locale even if a view or query contract is faulty. A new `readPublishedResources` result distinguishes healthy empty listings from unavailable CMS storage; the resource page now displays an outage message instead of falsely claiming no published content. New `collectPublicResources` policy validates canonical content routes, locale, revision/body shape and unique list entries, keeping navigation free of malformed/private paths. Existing resource list API is backward compatible. Added mocked-DB and pure policy regression test definitions.

No tests were executed via the GitHub workflow in this session: recent Actions runs report failure and did not expose executed job steps. Do not infer PostgreSQL tenant isolation, removal propagation or CDN purges from the local code. Pending: real migrations and privileges, OIDC end-to-end, publisher/reader concurrency, downstream cache invalidation, recovery and the remaining blueprint modules. No updates or merges to `main`.

## Nineteenth checkpoint — immutable editorial history and PostgreSQL smoke acceptance

Added `db/009_editorial_integrity.sql` guards against source revision mutation/deletion and tampering with approval/audit evidence. Marked `/content/<slug>` routes as dynamic to avoid serving stale published/trashed pages from the Next.js static render cache. Added a localhost-only `website_test` PostgreSQL acceptance script covering additive migrations 001–010 and selected publication, trash, audit, lead and quota invariants; GitHub Actions now provisions isolated PostgreSQL 16 and attempts this verification. **Do not treat this as test-passing evidence:** current Actions runs are failing before executable steps/runner allocation, and the suite has not been confirmed to execute successfully.

## Twentieth checkpoint — published-only blog and owner classification

Added `db/010_blog_catalogue.sql`, published-only blog read view, audited site-scoped classification API, server-side reader with bounded search/category filters, public `/blog`, navigation/SEO links, owner category/tag inputs and taxonomy contract tests. A blog entry is still a governed content page: owner writes it as a draft, categorizes before review, obtains separate reviewer approval, and publishes. Published/trashed filtering occurs at the database view, and neither audit evidence nor source revisions expire automatically. Missing capabilities include media assets, scheduled publishing, comprehensive blog management, a reviewed metadata versioning/approval process for post-publication tag changes, real PostgreSQL grants/RLS, a verified production identity provider and acceptance tests. **Full blueprint completion and launch remain BLOCKED.** All commits in this checkpoint remain on `feature/website-blueprint-v1-3`; no merge to `main`.

## Twenty-first checkpoint — fail-closed public CMS runtime observability

Added basic process liveness and opt-in public CMS dependency readiness API routes with bounded database checks and privacy-safe responses, plus unit-test definitions. Readiness is explicitly scoped to the published-only read view, never passed off as production approval or marketing launch safety. The endpoint defaults to HTTP 503 until configuration is intentionally enabled, and never displays SQL credentials or internal errors. No external monitoring scheduler or recurring third-party service was introduced. **Evidence still pending:** passing GitHub CI (current jobs fail before steps), real PostgreSQL grant/tenant isolation, OIDC integration, email/webhook receiver, backup restoration, operational alert routing and full browser E2E acceptance. No merge into `main`.

## Twenty-first checkpoint — rollback as a new immutable publication

Corrected `restorePublished` to honor the blueprint's rollback lifecycle: under a site-scoped row lock it verifies the target published snapshot and current block compatibility, appends a new published revision, atomically advances the live pointer and writes attributable audit and outbox evidence (including source and prior live revision IDs). The owner API returns the newly created publication revision rather than falsely reporting the selected historical source as current. Extended isolated PostgreSQL acceptance definitions to check preserved historical revisions and fresh rollback snapshots. **No live migration, CI-pass or CDN/cache invalidation evidence is claimed.** No merge to `main`.

## Next checkpoint — signed CMS outbox revalidation (partial, disabled)

Implemented `cms-outbox-worker.mjs` and `cms-invalidation-contract.mjs` for an opt-in, bounded, durable retrying publication reconciliation flow, and an HMAC-verified `/api/internal/cms-revalidate` endpoint calling Next.js `revalidatePath` for the validated article plus fixed blog/resource/sitemap routes. Only accepted `cms.published`, `cms.restored`, `cms.trashed` and `cms.restored_from_trash` events are processed. An outbox event is marked delivered only on HTTP 204 acknowledgment; failed events remain retryable without deleting editorial source or audit evidence. Tests cover signature, timestamp, event binding, path scope, origin and retry backoff. A separate site-scoped DB worker connection and a secret are required; no automatic schedule or new paid service is introduced.

**Not completed:** live PostgreSQL migrations and least-privilege grants, fully secured worker deployment, cross-instance invalidation, CDN edge eviction, search engine withdrawal, operational retries/alerts, recovery drills, real authentication/end-to-end tests and successful GitHub Actions evidence. This does not establish production readiness or total blueprint completion. All writes continue on the feature branch; no main merge.

## Media quarantine intake checkpoint — Chapter 8.4 (partial)

Added `011_media_quarantine.sql` with tenant-scoped media manifest and usage records, strict image MIME/size/checksum and approval evidence constraints, no public media view, no delete/expiry path and prevention of cross-site asset usage. Created the internal media manifest service, `cms:media` owner permission, protected site-scoped `GET/POST /api/owner/media`, and `/owner/media` interface with local file hashing and provenance/rights/alt inputs. The owner screen **never uploads file bytes**; it creates an audited, private metadata manifest only, quarantined with `not_uploaded` status. Contract and migration-test definitions were added. The owner feature remains OFF without configured `WEBSITE_MEDIA_MANIFEST_ENABLED=true` and the existing signed identity/DB isolation gates.

**Still missing for complete media support:** quarantine object storage upload, byte sniffing, antivirus where applicable, metadata stripping, verified derivatives and dimensions, scanner attestation, reviewed approval, image references in editable blocks, public/secure download delivery, cache propagation, legal licence evidence, media management UI and non-destructive replacement/deletion controls. No SQL migrations or CI tests have been verified passing, so Chapter 8.4 and the full website are **not complete or production-ready**. No merge to main.

## Private media object intake — follow-on checkpoint

Added `media-bytes.ts` (server-measured hash/size and allowlisted file magic), `media-storage.ts` (private S3-compatible, including self-hosted local MinIO option), an authenticated `PUT /api/owner/media/:assetId/upload` endpoint, site-scoped transactional `uploadQuarantinedMedia`, audit event `cms.media_quarantine_uploaded`, and owner UI byte transfer/retry after manifest reservation. The source remains `quarantined` after upload, with `blob_status=uploaded` only on confirmed private object storage and database commit. Added tests for file signatures, checksum, wrong type and size, safe storage targets and dev-only loopback configuration. No expensive third-party service or scheduling integration is assumed; users can operate their own S3-compatible store.

This work is **not** an approved public media workflow. Signature checks are not malware scanning, file decoding, EXIF stripping, or CDR. No scanner evidence, derivative, reviewer approval, public serving or release acceptance exists. No live S3/PostgreSQL integration, soak/concurrency testing or success from GitHub CI was obtained. A private uploaded object may need human reconciliation if a SQL transaction fails after storage succeeds. Never merge into main or enable feature flags until the documented security and test gates are passed.

## Media inspection checkpoint — source scanning and private derivatives

Added `012_media_inspection.sql` to require sanitized-private-candidate evidence and a different human approval identity before a media asset could be marked approved. Added local ClamAV INSTREAM scanning for original and re-encoded bytes, Sharp pixel decoding and WebP re-encoding (metadata stripped by default), size/type/actual-SHA verification, private S3-compatible candidate storage with HEAD acknowledgement, and atomic audit/inspection database record update. A separate signed short-lived service endpoint and bounded one-shot dispatcher select only uploaded, still-quarantined records. A failed inspection leaves the manifest pending and does not purge evidence. Added HMAC authorization regression checks and migration-012 existence assertions, but **no live tests have passed**.

**Still missing:** an independent, reviewed human approval workflow and public media delivery, scanner infrastructure verification, adversarial image corpus tests, true CDN cache handling, origin/tenant/permissions penetration tests, derived-object orphan reconciliation, retry/alert operations, compliant data retention and rights controls, feature-complete visual media editor, and passing full website CI. Scanning is not an assertion that every hostile image is safe. The code remains OFF by default and was committed only to the separate website branch, with no merge to main.

## Human media-review checkpoint (partial, production disabled)

Added a separate authenticated `cms:media:review` permission, a dedicated owner review database role/feature flag, a site-scoped list-and-decision API, and `/owner/media/review` with authenticated sanitized-only preview (never original bytes or an unprotected public URL). Review records an explicit action and human reason in the audit log. The database action checks that a reviewer differs from the original uploader, ensures complete independent scan and sanitized storage evidence, and binds an approval to the currently inspected WebP SHA-256 to prevent stale-review approval. Rejection retains source and history; approval remains **private** without a public asset-serving route.

Not complete: production IdP/RLS grants, true legal rights verification, reviewer role provisioning, private image browser tests, end-to-end ClamAV and S3 compatibility tests, migration recovery, public-media distribution/derivatives review and accessible media block editor. The implementation is committed to the isolated feature branch only; there is **no claim of passing build, production readiness or 100% website completion**.

## Separate media publication, withdrawal and CMS image blocks — follow-on checkpoint

Added `013_public_media_delivery.sql` with explicit public publication and withdrawal attribution and a published-only SQL view. Added `cms:media:publish`, a distinct owner publisher console at `/owner/media/publish`, and a site-scoped transactional audit-preserving publish/withdraw service. A new public `/media/[assetId]` GET is enabled only via explicit feature flags and a dedicated read-only media reader/HTTPS private-storage role. The endpoint verifies a site-matched published-only row, UUID-bound sanitized WebP object key, actual SHA-256 and full object length per request, serving no unprocessed source or public storage credentials. It returns no-store responses and excludes withdrawn assets on subsequent uncached requests.

Added `image` to approved inert CMS blocks and the owner page editor (UUID, required alt, caption). Public block rendering uses only a same-origin media route. CMS publication and rollback validate site-scoped, approved and currently published image references in the same transaction, adding preserved media usage records; withdrawn/non-public references fail publication. Fixed an earlier duplicate `dynamic` export in `/content/[slug]` that prevented Next.js compilation. Added unit-test definitions for delivery path controls, approval/publish role split, image reference safety and PostgreSQL migration-013 visibility checks.

**Still not verified and not ready for market:** GitHub Actions has failed without executing job steps; no passing local/CI Next.js build, PostgreSQL 001–013 integration, authenticated browser, private S3, ClamAV, scanner-recovery, multi-instance withdrawal, CDN no-store or legal/provenance audit is available. Real identity provider setup, admin security/isolation, public media performance, outstanding full visual builder, marketing/customer workflows and site brief are not complete. Features remain disabled by default. No merge to main.

## Non-destructive published-media withdrawal impact checkpoint

Before withdrawing approved public media, the server now counts active, published, non-trashed CMS revisions referencing the asset. When the count is nonzero, a separate owner UI checkbox and a server-enforced `impactAcknowledged=true` decision are required. The audit record includes the explicit human reason, affected live-page count and acknowledgement; withdrawal still takes precedence when an authorized operator needs to remove an asset urgently. Historical media usage and source records remain intact. Existing CMS publication already performs a shared media-row check so withdrawn assets cannot be newly published in a page revision. The public delivery endpoint continues to query the published-only view and returns no-store responses.

Code and mocked regression tests committed, **not executed in CI**. This is an impact safeguard, not a complete downstream repair workflow or proof of CDN eviction. Outstanding requirements: owner repair tooling, publication/withdrawal concurrency tests against PostgreSQL, live scanner/object-store verification, IdP and browser E2E, rest of visual builder and marketing automation, and production launch acceptance.

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


## Blueprint 44/45/59 follow-on: gated editor recovery, browser opt-out, internal automation persistence

Implemented an opt-in, time-limited CMS session recovery contract (`editor-recovery.ts`) and owner workspace controls. Recovery snapshots last at most two hours, are constrained to authenticated owner/site/page, reject unknown sections, and are cleared on confirmed sign-out. Restored snapshots stay unpublished and old-revision recovery requires manual comparison before new server draft creation. This is deliberately disabled pending storage/privacy approval and remains distinct from an approved, encrypted, server-side draft session system.

Added `privacy-signal.ts` and server/browser GPC gates: a browser's `Sec-GPC: 1` or supported client signal disables optional marketing under the conservative policy; the server response is the source of effective consent. No lawful-basis, data-rights workflow or verified retention implementation is implied.

Added migration `016_internal_automation_runs.sql`: site and version-scoped durable synthetic runs, bounded steps, due times, run-step audit and deduplicated internal tasks. A protected owner API can enroll **synthetic** cases, while a signed, one-shot internal processor advances at most ten due rows via PostgreSQL row locks and transactionally records tasks. The visual automation builder can inspect synthetic run statuses. No real lead or CRM enrollment, customer communication, publisher activation, external campaign/ads effects, scheduler, or fully approved workflow operational control exists. Added pure tests and PostgreSQL fixture expectations. New features are **OFF by default**; the recurring failure to schedule a GitHub Actions runner means no passing test, build, DB isolation, external IdP or browser E2E proof was obtained.

Continue with real Postgres tests, stable-role and RLS policy enforcement, optional data erasure/rights handling, visual releases and custom collections, autonomous internal lead operations after review, and full accessibility, security, load and deployment verification. Preserve all existing code, media, and blog history. Defer external CRM integrations as requested. No merges to `main`.


## Internal task handling and final safety adjustments

The synthetic-only automation owner screen now lists durable internal tasks and permits a manual, audited `pending -> done` decision with a reason. The server validates owner permission, same-site workflow/run binding, current pending state, UUID identity, and never deletes an event or sends a message. Workflow drafts changed locally must be saved and server-acknowledged before a new synthetic run can be queued; this avoids silently testing an earlier saved version. The run engine fails tasks scheduled beyond the 14-day expiry budget. SQL migration 016 uses composite same-site keys for run/task/step relationships and the isolated migration fixture rejects wrong-site tasks and duplicate operations.

The opt-in editor recovery state is now flushed immediately before page switching, in addition to its bounded debounce, to avoid losing an edited page when navigation occurs quickly. All local recovery remains restricted to the current signed-in owner, site, page, browser tab, and two-hour expiry and is disabled by default.

These additions still require real PostgreSQL, IdP/session, CI/Playwright and security/load acceptance. No live automation enrollment or external CRM provider calls were implemented. No updates to `main`.
