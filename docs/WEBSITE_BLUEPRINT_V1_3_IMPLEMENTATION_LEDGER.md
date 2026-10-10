# Website v1.3 implementation and acceptance ledger

Source: Website Master Blueprint v1.3, 7 October 2026 (273 pages).
This ledger records only **verified** implementation evidence; presence of a
domain contract does not imply that the UI, API, persistence or end-to-end flow works.

## Branch and scope
- Development branch: `feature/website-blueprint-v1-3-20261010`
- Do not merge into `main` without explicit user instruction.
- Preserve existing CMS, CRM, auth, routing and integrations.
- All blueprint-listed capabilities are requested, including external CRM provider integration and conditional modules. Provider activation still requires authorized credentials, account access, lawful basis and project-specific configuration; do not misrepresent unconfigured integrations as operational.
- Keep the existing Python/FastAPI backend unless an approved architecture
  decision replaces it; blueprint NestJS is a reference default, not evidence
  of a migration being necessary.

## Work packages (implementation evidence required for each)

| ID | Capability | Current verified evidence | Missing acceptance evidence |
|---|---|---|---|
| CMS-01 | Visual builder page contract | Document validator and `frontend/src/pages/WebsiteCMSPage.tsx` with section/block controls | Drag-and-drop editor, full owner journeys, browser/E2E checks |
| CMS-02 | Public rendering and preview | Responsive hashed-CSP HTML, authenticated preview and public-published-revision route | Live host/domain integration, deployment smoke test, cache invalidation proof |
| CMS-03 | Editorial publication | API, revision history/restore, owner UI, admin-only RBAC, audit, transactional outbox | Separate approval roles, scheduling worker, published content indexing/rollback smoke tests |
| WEB-01 | Public pages and navigation | Existing public routes and CMS HTML output partially integrated | Responsive real-business site brief, public navigation, forms, route checks, and accessibility testing remain |
| CMS-04 | Blog, media and preservation | Not audited | Manual-only deletion, restore, rights, authoring, export |
| MKT-01 | Campaign link builder | Protected `site-campaigns/url` API, React owner UI, validation and API tests committed | CI test evidence missing; visual automation, durable campaigns and provider reporting remain |
| EVT-01 | Consent-gated website page events | `website_analytics.py`, `website_page_events` migration, nonce-scoped first-party SDK, owner summary | Event/consent integration tests committed but not passed; broader attribution, destination egress and reconciliation remain |
| PRIV-01 | Website consent choices | Policy engine, public React preference center, append-only receipts migration, GPC and withdrawal, analytics ingestion gate | Full banner, retention/rights, all third-party integrations, legal review, cross-browser/E2E tests remain |
| SEC-01 | Production admin auth | Existing auth routes identified | Admin UI, RBAC, MFA, cookie/CSRF/session E2E security |
| DB-01 | Database integrity | Additive migration `0079_website_cms_pages.py` | Upgrade/downgrade on PostgreSQL, tenant isolation proof, backup/restore |
| QA-01 | End-to-end verification | API integration tests added; branch CI workflow added | All tests unverified: GitHub Actions runs failed before exposing job steps/logs; re-run in accessible CI environment |

## Definition of done for every capability
1. Frontend owner/public journey is usable, accessible and responsive.
2. Backend API validates requests and enforces authorization server-side.
3. Durable database migrations, consistency and rollback behavior are tested.
4. Audit and background delivery are implemented where the blueprint requires.
5. Unit, integration and browser end-to-end tests pass in CI with evidence links.
6. Operational instructions, errors, recovery and monitoring are documented.
7. Mark as verified only when evidence exists; never count a stub as complete.

## Blueprint release blockers
- No falsely acknowledged or lost leads.
- No unauthorized admin access, secret leaks or prohibited tracking.
- No broken primary journeys or untested recovery.
- No automatic deletion of blog/source/trash content.
- No green release sign-off without passing acceptance evidence.

## Scope clarification (2026-10-10)
The owner explicitly requests no deferred blueprint features. Implement all documented capability families and their working frontend/backend/database paths. External provider credentials, approvals, legal decisions, and live payment/ad transactions remain environment-dependent release prerequisites, not reasons to claim implementation completion. Maintain per-capability implementation, activation, and verification status separately.

## Next integration milestone
Implement a real CMS page create/edit/preview/publish workflow with migrations,
admin authorization, immutable revisions, public read model and end-to-end tests.
Do not claim it is complete until frontend, backend and database all work together.

## Implementation checkpoint — 2026-10-10
- Browser-accessible CMS route: `/site-cms` inside existing authenticated React workspace.
- New API family: `/api/v1/site-cms` with tenant-scoped page creation and updating, private revision history, restore, admin preview and public published revision.
- New durable tables: `website_cms_pages`, `website_cms_revisions`, `website_cms_audit`.
- Publication emits `website.page.published` via the existing outbox in the database transaction.
- New frontend page editor supports approved blocks and keyboard-operable reorder controls. It is **not** an advanced drag-and-drop editor yet.
- No new CRM provider credentials or live ad/payment activity have been configured. All remain requested in scope but are not verified.
- Automated branch-check workflows exist but current GitHub runs have no executable job step records; no passing tests or release certification can be claimed.


## Privacy and analytics integration checkpoint — 2026-10-10
- Public consent page: \`/privacy/site/:workspaceId\`; preference API: \`/api/v1/site-consent/:workspaceId\`.
- Consent choices are denied by default and saved as append-only, pseudonymous workspace-scoped receipts; no names/emails/IPs are stored in these receipts.
- Explicit opt-in/opt-out/withdrawal and conservative Global Privacy Control suppression are supported for the new website module; the UI does not claim jurisdictional legal certification.
- Public site renderer offers a permanent preference-entry link and a nonce-authorized, server-owned JavaScript SDK.
- The SDK asks the consent API first. It only collects allowlisted page views and CTA clicks when analytics is allowed, with no free-text event parameters.
- Website event collector enforces the latest consent again server-side, validates slugs, block IDs, event IDs, origin and scope, rate limits writes and deduplicates event IDs.
- CMS owner dashboard shows 30-day counts from consent-eligible website events, separate from business conversions.
- New migrations: \`0080_website_consent_receipts\`, \`0081_website_page_events\`. New API regression tests and CI workflow gates have been committed.
- This is not full site measurement, ad-platform conversion delivery, privacy rights automation, or complete cross-module consent enforcement. Those are **unverified and remaining**.
- CI workflow executions currently report failure without job step evidence. Do not classify any of these tests as passed until actual results are obtainable.


## Implementation checkpoint — 2026-10-10, continued

- The newest uploaded blueprint file matches the prior v1.3 document by SHA-256; its CAP-001–CAP-120 register is preserved in \`docs/WEBSITE_BLUEPRINT_120_CAPABILITY_TRACEABILITY.md\`.
- Corrected a consent cookie path that prevented first-party analytics requests from receiving the consent token. Corrected the published-page CSP to allow same-origin event requests. Regression assertions added.
- Added role-protected campaign-link API \`POST /api/v1/site-campaigns/url\` and owner React route \`/site-campaigns\`. This validates/encodes UTM parameters, provides copy/preview actions, and preserves non-UTM query parameters.
- Extended CMS revision JSON with explicit search metadata: meta description, approved HTTPS canonical URL and indexability flag. Missing approval defaults to \`noindex\`.
- Published-page HTML emits escaped description/canonical/robots metadata. A public sitemap at \`/api/v1/site-discovery/sitemap/{workspace_id}.xml\` includes only current published revisions with explicit indexing enabled; the owner dashboard links to it.
- Added backend regression tests for campaign links, SEO metadata, and sitemap published/draft isolation. These tests are **committed but not yet demonstrated passing**.
- Still unverified: a complete deployable public website with approved business content, CI, browser E2E, worker processing, full marketing automation, advanced builder, data/privacy rights, specialist transactions, live provider integrations, audits, backup/restore and production owner sign-off.
- Github Actions branch jobs were failing before usable test logs/steps were available in this environment. Do not label this implementation release-ready.


## No-duplicate implementation checkpoint — 2026-10-10

Scope rule: audit existing routes, components and services before adding anything. Prefer modifying the established module over implementing a competing subsystem. The blueprint's native page-duplication operation is not a duplicate architectural implementation; it creates a separate draft on explicit owner request.

- Reused `backend/src/northstar_api/routers/website_cms.py` for authenticated page duplication, owner JSON export/import, editorial change requests, safe archiving and restoration. No parallel CMS router was introduced.
- Refactored the shared draft create/duplicate/import operation through `_create_draft_page` so page metadata, immutable first revision, audit attribution, rollback and conflict handling use **one** transaction implementation.
- Reused the existing React CMS editor instead of adding an alternative admin dashboard. It now exposes copying, exporting, importing, approval changes and manual archive/restore controls.
- Extended existing `WebsitePage` and `WebsiteRevision` storage. No new tables or migrations were required for these operations.
- Manual archive makes the page unavailable publicly and emits a transactional `website.page.unpublished` event; original revisions and audit entries remain stored. Restoration requires authenticated owner/admin action and routes through editorial review before public publishing.
- The **last published revision remains live while a new draft is edited**. Do not require editorial status `published` in public/sitemap/analytics reads: use `published_version` as the authority; archive clears that pointer.
- Added backend tests for duplication identity, import validation/authorization, archival, restoration, changed-content review and published/draft separation. They are **committed, not demonstrated passing**.
- No existing CRM, lead-management, auth or media modules were replaced or removed.
- CI/runner remains a release blocker. GitHub Actions reported jobs failing without assignment to runners and without execution steps; user/repository Actions policy or billing may need investigation. Do not count this as a passed code or deployment validation.
- All 120 capability IDs remain in scope and **not verified** until repeatable acceptance evidence exists.

## Implementation checkpoint — blog and visual-builder integration (2026-10-10)

- Audited existing page CRUD, revisions, import/export, duplication, archive/restore, and CMS editor before extending them; no second CMS/page model was introduced.
- Existing editor now has section/block rearrangement, duplication, removal, and cross-section moves; editor regression tests have been committed. Drag-and-drop is an enhancement to the same page document API, not a new source of truth.
- Extended versioned `BuilderPageDocument` with `content_type=article` and validated `BlogMetadata` (real author, category, summary, reviewer, locale).
- Updated the existing CMS owner screen to create/edit article metadata. No fictitious author is silently assigned; the owner must enter author, category, and summary.
- Updated the existing duplication/import helper to preserve article metadata, while regenerating node IDs and resetting search-indexing approval.
- Added a public, tenant-isolated blog resource index using the existing published revision table, with server rendering, category-filtered paginated JSON, HTML pagination, and escaped output. This does not invent a separate blogging database.
- Public CMS renderer now displays article byline, category, summary and locale with escaped metadata; unpublished revisions remain private.
- Added backend regression tests covering blog validation, copy behavior, draft exclusion, published-revision isolation and pagination, plus a React authoring test. CI was updated to include the new API tests.
- **Not yet verified passing:** full browser E2E, database migration exercise, production auth, publisher/approval role separation, manual trash/purge controls, SEO edge cases, 120-capability acceptance.
- GitHub Actions may fail before job steps; a passing release certificate is not available. Existing core website and CRM functionality must continue to be regression-tested before release.
