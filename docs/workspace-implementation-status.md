# Workspace platform implementation status

Branch: `feature/workspace-platform-consolidated-20260917`.
Pull request: #114, draft. This is an implementation checkpoint, not a completed release.

## Latest continuation: organization chooser and account-level recovery

Based on `d2ad73382cde96445df85262e9d9571f1504556f`. The frontend and backend organization-selection path is now implemented, not merely an unpushed overlay contract.

- `/organizations` lists real memberships and selects a destination using `GET /me/organizations` and `POST /auth/select-organization` under the existing API prefix. The current database membership supplies the new role; no workspace membership is fabricated.
- Verified interactive identity and matching refresh-cookie proof are required. API keys, malformed/revoked/stale credentials, unverified users and foreign memberships are denied. A removed old-organization membership does not prevent recovery into a still-authorized organization.
- Redis atomically transfers the exact refresh proof to a new family with access-token revocation checking. Losing requests do not revoke the winner. Database audit/outbox work is transactional; failure compensates by conditionally revoking only the undelivered new token family.
- Client selection handles duplicate clicks, stale account responses, invalid output and ambiguous network outcomes without silently replaying the mutation. Refresh credentials are never retained in browser storage. Reopening an organization clears a removed workspace selection.
- `/organization/billing` is outside the workspace/profile bootstrap and reuses existing billing endpoints and server-side authorization. Missing-workspace/error/profile-waiting screens and the normal dashboard expose organization recovery links.
- No new database migration, model-provider change, worker rewrite, deployment or main-branch update is part of this continuation.

See [organization selection operations and evidence](operations/organization-selection.md) for contracts, session behavior, the outbox topic and release requirements.

### Evidence actually executed for this continuation

22 isolated Python claim/transfer tests; 23 actual-router ASGI checks in a minimal SQLAlchemy/SQLite host with substituted host/Redis adapters; 26 Node module checks with actual organization/workspace transport source and in-memory browser primitives; strict TypeScript transport checking with the extracted existing Session contract; syntax checking of seven changed TypeScript/TSX files; Python compilation.

Eight normal backend API regressions and seven normal Vitest regressions were added for the real repository pipeline, but were not executed in the restricted local source environment. None of the isolated counts represents the complete application, real Redis Lua, PostgreSQL/RLS, React browser rendering, real cookies, cross-tab races, broker/provider integration or production acceptance. All existing quality gates remain required.

## Earlier committed checkpoints retained

- `0044_merge_workspace_extraction` joins the existing onboarding and hybrid-extraction histories without data-changing junction operations. Future workspace migrations must descend from it; the historical PostgreSQL chain still requires runtime acceptance.
- Scoped access request contracts and resource-grant validators are committed, but full custom-role/team service and UI enforcement are not yet integrated.
- The existing billing transport no longer fabricates active subscriptions or unlimited legacy entitlements during an outage. It retains the existing checkout, portal, cancellation and reactivation endpoints and rejects unsafe redirects and stale-account responses.
- The earlier onboarding/profile/Free-plan/basic-branding implementation and independent PDF-extraction work remain preserved.

Historical evidence: 22 access/junction tests and 26 billing module checks passed at their respective earlier checkpoint. The larger older local overlay had separate unit/service checks, but it is not wholly committed; those counts are not tests of this branch's complete current source.

## Remaining implementation and release gates

The full specification still requires the larger custom-role/team integration and resource matrix; immutable whole-application branding and its actual auth/widget/email/report surfaces; verified domain/TLS/sender workflows; workspace lifecycle/export/deletion and retention; usage reservations/budgets; organization ownership/security governance; durable signup-email processing; complete Education/CRM and provider/worker acceptance; production-like migrations, accessibility, load, backup/restore and full frontend/backend quality gates.

The previously blocked access-model/access-migration writes were not part of this continuation and were not bypassed. This continuation adds organization recovery using existing identity and membership models.

Keep this PR in draft until the complete implementation and its acceptance gates pass. Do not weaken or skip existing CI gates to obtain a green status. No merge into main has been performed.
