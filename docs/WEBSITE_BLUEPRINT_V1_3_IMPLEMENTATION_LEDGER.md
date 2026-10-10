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
| WEB-01 | Public pages and navigation | Not audited | Responsive routes, links, content, SEO and accessibility checks |
| CMS-04 | Blog, media and preservation | Not audited | Manual-only deletion, restore, rights, authoring, export |
| MKT-01 | Campaign link builder | `website_campaign_links.py` | Campaign UI, automation worker, scheduling, delivery and analytics |
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
