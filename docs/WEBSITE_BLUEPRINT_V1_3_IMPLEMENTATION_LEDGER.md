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


## CAP-005 integration increment — 2026-10-10

- Audited Chapter 44 before editing: the existing `WebsiteCMSPage` had manual Save and `site-cms/pages/{page_id}` already implemented optimistic `expected_version` checks. No parallel editor, API, database table or worker was created for autosave.
- Extended `frontend/src/pages/websiteBuilderOperations.ts` with bounded, pure undo/redo history, content-stable draft comparisons and a readable local/server difference summary.
- Extended the **same** `WebsiteCMSPage` with a 3-second debounced save, accurate pending/saved/error status, browser-unload guard, keyboard-accessible Undo/Redo and explicit retry.
- Server acknowledgement updates the saved revision but does not overwrite edits typed while the request was in flight.
- The existing API returns 409 for a stale editor version; autosave pauses and retains local content. The owner can inspect the latest server revision, export their unsaved JSON, load the server copy only after explicit confirmation, or preserve local edits as a **separate unpublished draft** through the existing validated `site-cms/pages/import` endpoint.
- Conflict comparison is a review aid, **not** an automatic merge and never claims a stale write succeeded.
- Existing JSON import/export helper and existing backend transaction are reused, with no duplicate page-persistence subsystem.
- `websiteBuilderOperations.test.ts` now covers undo/redo, branching, limits, reordered JSON properties and readable diff; `WebsiteCMSPage.autosave.test.tsx` adds debounced save, 409 recovery and independent draft tests.
- CI still has not produced trusted passing executions, so CAP-005 stays **not verified**. Offline local persistence with a reviewed device-sharing/expiry/logout-clearing policy and browser accessibility acceptance remain missing.


## No-duplicate gap-closure increment — 2026-10-10, public navigation and redirects

Source requirements: Chapter 04.1 (task-oriented routes and working navigation), Chapter 07.1–07.4 (owner-managed menus and redirects) and Chapter 08.3 (published revision integrity). Reused the **existing** `website_cms.py` router, owner `WebsiteCMSPage.tsx`, page status model, shared ORM metadata, transaction/outbox helpers and public renderer. No parallel CMS, route-service application or duplicate owner console was added.

### First-party public navigation
- Additive migration `0082_website_site_navigation.py` adds a workspace-scoped navigation document, immutable versions and actor-attributed audit records in existing CMS model code.
- GET/PUT `/api/v1/site-cms/menu`; POST `/api/v1/site-cms/menu/publish`; GET `/api/v1/site-cms/menu/revisions`; POST `/api/v1/site-cms/menu/restore/{version}`.
- Validates stable IDs, labels, internal slugs, bounded item counts, unique destinations and optimistic versions. Publication checks every target is a currently published page. Publishing is idempotent and records an outbox event.
- Public page renderer outputs a responsive, semantic primary navigation landmark, escaping text/attributes. It filters destination links which later become unpublished, while keeping the immutable published menu revision.
- Existing CMS owner screen provides published-page selection, editable labels, keyboard-operable ordering/removal, draft save, explicit publish and history-based restore.
- `test_website_navigation_api.py`, `WebsiteCMSPage.navigation.test.tsx` and renderer tests cover authorization, public/draft isolation, stale versions, unsafe inputs and archival safety.

### Controlled URL redirects
- Searched for existing owner website redirect managers and data models before implementation; none were found. Added `0083_website_cms_redirects.py` to the same CMS model family.
- GET/POST `/api/v1/site-cms/redirects` and PUT `/api/v1/site-cms/redirects/{redirect_id}` are role- and tenant-scoped, require published internal targets, preserve revisions and actor history, and reject stale writes.
- Public page resolver may return a same-origin 307 or 308 on an old/archived slug. Active pages and unfinished drafts cannot be displaced, source slug reservation prevents collisions, and redirects to archived targets fail closed.
- Changes emit existing transactional outbox records; the public route returns `Cache-Control: no-store`.
- Existing CMS screen now includes creation, target changes, 307/308 selection, audited disable/enable and visible errors. Disabling never erases the previous rule.
- `test_website_redirects_api.py` and `WebsiteCMSPage.redirects.test.tsx` include recovery, open-redirect rejection, version conflict, retired URL, and active-page protection.

### Release evidence limits
- No live environment migration, frontend compilation, DB integration execution, end-to-end browser run or owner acceptance is certified by this ledger.
- GitHub-hosted workflow jobs still fail without assignment to a runner or execution steps; investigate repository/org Actions billing, availability and policy before a release gate can pass.
- CAP-002, CAP-004, CAP-007, CAP-011 and CAP-012 remain **not verified**. The rest of the 120-capability catalogue remains in scope and cannot be considered delivered solely because adjacent components now exist.

### Additional correctness safeguards
- The existing shared page-creation function and new redirect-creation operation both lock the workspace URL namespace before checking source/target collisions, preventing a concurrent page/redirect claim on separate tables in PostgreSQL.
- Redirect creation, updates and disabling now append existing transactional outbox messages, with tests asserting audit/outbox evidence.
- Tests use the existing **session-scoped** backend workspace fixture. Navigation tests derive their expected versions from the live fixture and check publication retries against previous side-effect counts instead of assuming an empty database.
- The isolated branch workflow now includes Python source and migration syntax checks plus `alembic heads`, and explicitly includes the menu/redirect API test files. These checks remain configured but **not executed successfully** due to the GitHub runner issue.


## CAP-041 lead scoring implementation increment — 2026-10-10

- Repository audit found existing CRM Workflow APIs/UI, Lead/LeadProfile, attribution metadata, qualification status/score, LeadActivityEvent and a deduplicated workspace notification service. None was copied into a competing CRM/lead pipeline.
- Added allowlisted rule validation and a bounded, explainable scoring policy in `lead_crm/website_lead_scoring.py`; rules use only source channel and UTM source/medium/campaign with casefolded exact matching.
- Existing `/api/v1/crm/workflow` router now also exposes `GET/PUT /scoring-policy`, `GET /leads/{id}/score-preview` and `POST /leads/{id}/apply-score`.
- Policy is stored in the **existing Workspace.settings_json**, version checked under a workspace row lock. No new lead, CRM, event, queue or settings table was introduced. The existing integration audit records policy changes.
- Scoring is disabled by default, rejects unknown/withdrawn purpose consent and archived leads, and cannot initiate automatic customer messaging or CRM delivery.
- Preview reports matched rules, bounded proposed score and **human review** recommendation without changing any lead data.
- Explicit apply revalidates current tenant/workspace/agent access, policy version, processing consent and expected lead score, then changes only the existing LeadProfile qualification_score. Human qualification status and explanation/reason are preserved; the scoring explanation is appended to existing LeadActivityEvent.
- Threshold-crossing scores reuse `notify_workspace_admins` to create an idempotent in-app **human review** notification. No outbound emails, WhatsApp messages, CRM upserts or spend are triggered.
- Existing CRM Workflow page now includes the scoring policy editor, rule configuration, preview, and confirmed apply button. The existing CRM API client was extended rather than replaced.
- Committed `test_website_lead_scoring.py`, `test_website_lead_scoring_api.py`, and `LeadScoringPanel.test.tsx`, and updated existing `CRMWorkflowPage.test.tsx` and branch CI gates.
- **Verification is incomplete.** The GitHub Actions branch jobs have been failing without running on a runner; these tests cannot be marked passed. CAP-040 automation timers/simulations and CAP-041 batch scoring/manual overrides remain open.


## CAP-038 first-party forms increment — 2026-10-10

Source: Blueprint v1.3 Chapter 20.1–20.3 and Chapter 21.1–21.3. Audit found an existing authoritative Lead, LeadProfile, LeadConsent, agent-purpose guard, transactional outbox, Redis rate limiter and Website CMS page builder. There was no existing first-party website forms module or published form owner UI. Rather than adding another Lead or CRM store, the implementation reuses those existing services.

### Committed integration
- `services/website_form_contracts.py`: strict field schema, stable keys, label/purpose/required state, allowed choices, retention/sensitivity declarations and server-authoritative checks. Activated controls: text/long answer, email, phone, select, radio, checkbox, date and affirmative processing consent. Unicode names are not restricted to English.
- `website_form_models.py` and additive Alembic migration `0084_website_forms.py`: workspace-scoped form definition, immutable numbered revisions and transactional submission/receipt with a unique form-scoped idempotency key. The shared ORM metadata is extended; no parallel Leads or agent schema created.
- `routers/website_forms.py`: authenticated owner form list/create/update/publish/unpublish and safe submission receipt listing; unauthenticated public same-origin HTML form and native URL-encoded submission. The public page is noindex and includes an accessible error summary, strict CSP, anti-spam honeypot and scoped Redis request budget.
- New public submissions reject unknown inputs and unsupported types, require purpose consent and active lead-generation ownership, and commit submission, existing Lead/LeadProfile, LeadConsent, first-party conversion event and existing CRM-routing outbox messages as one unit. The public receipt contains only opaque IDs. Identical repeated keys return the same receipt; changed bodies under a reused key are rejected.
- Replayed identical receipts remain recoverable after safe form unpublication, while new submissions are blocked. Published form revisions remain live while later drafts are edited.
- `WebsiteFormsPanel.tsx` mounts inside the **existing WebsiteCMSPage**, reuses authenticated `request` and existing agent enumeration, and offers field editing, revision save, explicit publication, accessible public URL, and restricted receipt metadata.
- Existing `BuilderNode` and renderer gained one `form` node kind. The page editor inserts an already-published form with an allowlisted same-origin URL. Page publishing verifies that the form exists, is published and belongs to the same tenant/workspace. Public HTML uses a sandboxed, no-referrer iframe and a constrained `frame-src 'self'` CSP. The private builder preview shows a non-submitting placeholder.
- Tests committed: `test_website_form_contracts.py`, `test_website_forms_api.py`, `WebsiteFormsPanel.test.tsx`, `WebsiteCMSPage.forms.test.tsx`, plus builder document/renderer tests. Existing CMS tests were updated for the new panel's read-only owner load.
- CI branch workflow now includes new form contract/router/model lint and new API tests. The form editor and embed UI are covered by the existing frontend `npm test` command.

### Not claimed complete or verified
- Actual GitHub Actions executions still fail at runner assignment, with no steps/logs. No production database migration, browser end-to-end acceptance, real notification delivery, CRM provider write/read-back or recovery drill has passed for this increment.
- File uploads need the existing upload-quarantine and object-authorization pipeline before field activation; conditional/multi-step forms, retention deletion jobs, abuse false-positive review, advanced contact deduplication and owner acceptance remain incomplete.
- Blueprint CAP-038 and all other 120 traceability IDs remain **not verified** until observable acceptance evidence is recorded.
