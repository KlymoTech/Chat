# Workspace platform implementation status

Branch: `feature/workspace-platform-consolidated-20260917`.
Pull request: #114, draft. This is an implementation checkpoint, not a completed release.

## Latest continuation: workspace refresh and editor-state preservation

Based on `c052fe67e2174f7f7ce7fc0a2f28a0cfce9d9eb7`. This is an independent frontend continuation using the existing workspace APIs, provider and setup gate; it does not require new database tables or migrations.

- Ordinary access-token rotation no longer serves as the workspace presentation identity. User/organization, role, credential-version and verification changes still invalidate it. These browser keys only partition UI state; the backend remains authoritative.
- The provider cancels superseded workspace-list requests and retains generation/context fences. Same-context background refreshes no longer replace an already loaded editor with the initial loading screen.
- GET requests may retry once only after an external same-context token refresh, using the original selected workspace. POST/PATCH requests are not replayed; uncertain outcomes require reload.
- Transient same-context background outages show a retry warning without discarding the loaded form. Initial-load errors and authorization/context failures do not fall back to stale private account state.
- The setup gate uses stable context keys and does not turn cancelled bootstrap requests into account errors.

Executed: 31 Node transport checks against actual source with storage/fetch fixtures; strict TypeScript transport/storage checking using TypeScript 5.8.3; syntax checks for five changed TypeScript/TSX source/test files. Six normal transport Vitest regressions and six normal React/Testing Library regressions were added but not executed here. Full project lint/types/build, actual browser/cookie concurrency and current-source CI are still required.

See [workspace refresh operations and verification](operations/workspace-refresh.md).

### Blocked publication implementation

The repository tool blocked a separate attempted branding-model/migration tree write. No branch ref was changed by that blocked operation, and it was not retried through an alternate route. Its locally prepared versioned-branding code passed 44 isolated backend/SQLite checks and 23 Node client-module checks, but those are NOT tests of this branch head. The new publication tables, migration, endpoints, observer and versioned editor are NOT committed. The original basic branding path remains intact. No imports or routes reference the unpushed files.

## Prior continuation: organization chooser and account-level recovery

Implemented in `c052fe67e2174f7f7ce7fc0a2f28a0cfce9d9eb7`, based on `d2ad73382cde96445df85262e9d9571f1504556f`.

- `/organizations` lists real memberships and selects a destination using `GET /me/organizations` and `POST /auth/select-organization`. Current database membership supplies the new role; no workspace membership is fabricated.
- Verified interactive identity and matching refresh-cookie proof are required. API keys, malformed/revoked/stale credentials, unverified users and foreign memberships are denied. A removed old membership does not prevent recovery into a still-authorized organization.
- Redis transfers refresh proof to a new family. Database audit/outbox work is transactional; failure compensates by conditionally revoking the undelivered family. This is not a PostgreSQL/Redis distributed transaction guarantee.
- Organization selection handles duplicate clicks, stale responses and ambiguous network outcomes without replay. Refresh credentials are not stored in browser storage.
- `/organization/billing` remains outside the workspace/profile bootstrap and reuses server-authorized billing endpoints. Recovery links remain on error/waiting screens and the dashboard.

Historical verification for that commit: 22 isolated Python claim/transfer tests; 23 actual-router ASGI checks in a minimal SQLite host with substituted host/Redis adapters; 26 Node module checks; targeted strict TypeScript and seven-file syntax checks. Eight backend API regressions and seven Vitest regressions were added but not executed in the restricted environment. This is not full React/browser, real Redis Lua, PostgreSQL/RLS or broker/provider acceptance. See [organization selection operations](operations/organization-selection.md).

## Earlier committed checkpoints retained

- `0044_merge_workspace_extraction` joins the existing onboarding and hybrid-extraction histories without data-changing junction operations. Future migrations must descend from it; the full historical PostgreSQL chain still requires acceptance.
- Scoped access contracts/resource-grant validators are committed; complete custom-role/team services and UI enforcement are not integrated.
- Billing transport no longer fabricates active subscriptions or unlimited legacy entitlements during an outage. Existing checkout, portal, cancellation and reactivation endpoints remain.
- Earlier onboarding/profile/Free-plan/basic-branding and independent PDF-extraction changes remain preserved.

Historical evidence: 22 access/junction tests and 26 billing module checks passed at their respective checkpoints. Older larger overlays have separate tests but are not wholly committed. Their counts are not evidence for this branch's complete current source.

## Remaining implementation and release gates

The full specification still requires custom-role/team runtime and complete resource authorization; immutable whole-application branding and actual auth/widget/email/report surfaces; organization inheritance and asset storage; verified domains/TLS/senders; workspace archive/export/deletion/retention; authoritative usage reservations/budgets; ownership/security governance; durable signup email; the complete starter catalog/playground; Education/CRM/provider/worker acceptance; production migrations, accessibility, load, backup/restore and all frontend/backend quality gates.

Previously blocked access-model/access-migration operations were not bypassed. This continuation does not modify another branch, main, deployment settings, model providers, production databases or worker topology. Keep PR #114 in draft until implementation and acceptance are complete. No existing CI gate is weakened or skipped, and no merge into main is performed.
