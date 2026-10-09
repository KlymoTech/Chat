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
| Lead submission and durable outbox/CRM delivery | 20–23, 40, 69 | PARTIAL / DISABLED | schema, transactional enqueue and form implemented; anti-abuse, IAM/RLS, migration execution, worker, reconciliation and crash/retry tests pending |
| Privacy, consent-aware visitor and UTM events | 14–18, 35–37, 59, 72 | PARTIAL / UNVERIFIED | fail-closed device-local preferences UI added; no CMP, backend consent record, lawful-basis policies, revocation propagation or event tests |
| Marketing automation, scoring, experiments, ads | 12–13, 19, 34, 43, 45–56, 67–71, 77 | NOT IMPLEMENTED | approved-provider sandbox tests + quality/goal reconciliation |
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
