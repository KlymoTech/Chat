# Workspace platform implementation status

Branch: `feature/workspace-platform-consolidated-20260917`.
Pull request: #114, draft. This is an implementation checkpoint, not a completed release.

## Continuation checkpoint: migration junction, billing truthfulness, access contracts

### Pushed changes

- `0044_merge_workspace_extraction` joins the existing `0044_workspace_onboarding` and `0044_hybrid_extraction_review` histories. It has no data-changing upgrade/downgrade operations. Future workspace migrations must descend from this junction. Neither existing migration was rewritten.
- Workspace access request contracts validate custom-role permissions, exclusive member-role sources, explicit resource selections, conversation visibility and version expectations. Immutable resource-grant helpers keep action-specific restrictions separate and reject delegation that broadens the parent grant. These contracts are NOT yet a complete custom-role service/UI.
- The existing frontend billing API no longer converts server/network failures into fabricated active subscriptions or unlimited legacy entitlements. Compatibility plan arguments do not grant authority.
- Billing requests retain backend checkout/portal/cancellation/reactivation endpoints, use the authenticated organization without an operational workspace header, reject stale-account responses, and never automatically replay a potentially completed billing mutation. Redirects must be HTTPS without embedded credentials.
- Regression tests were updated to require authoritative billing failure behavior, not the removed mock fallback. A separate Node module-check runner is included.

### Verification executed

- 22 targeted Python tests: 20 access-contract/resource-grant cases and two migration-junction cases. These ran in an isolated source snapshot without the full application's conftest.
- 26 Node billing-module tests passed using compiled actual module source with mocked storage/fetch. This is not a React/browser, real-cookie, live-provider or complete frontend test.
- Strict TypeScript checking passed for the changed billing module and actual storage helper, with a minimal Vite environment declaration. This is not a full-project typecheck or Vite production build.
- The 455 older overlay unit cases and 22 isolated overlay service checks were also rerun successfully, but the expanded overlay is not all committed. Those counts must NOT be represented as tests of this PR's current head.
- Updated Vitest tests still require execution in the repository's normal dependency environment. Full source CI, PostgreSQL/RLS, worker/broker and production acceptance remain outstanding.

Reproduce the isolated billing check after installing the repository's frontend dependencies:

```sh
node --test scripts/check_billing_transport.cjs
```

## Blocked write and scope boundary

The repository tool blocked the attempted access-model/access-migration tree write because it could not determine its safety status. The blocked write was not retried through another route. Access model, runtime service, role/team administration UI and expanded versioned-branding integration therefore remain outside this pushed checkpoint. No import of these unpushed model files was introduced by the contract-only checkpoint.

The earlier recovered onboarding/basic-branding implementation remains on this branch. The independently developed PDF-extraction work is preserved. No update to main, merge into main, production deployment or production database migration was performed in this continuation.

## Remaining implementation and release gates

The full specification still requires the larger custom-role/team integration and resource matrix; immutable whole-application branding and its actual auth/widget/email/report surfaces; real domain/TLS/sender verification; workspace lifecycle/export/deletion and retention; usage reservations/budgets; organization ownership/security governance; durable signup-email processing; complete Education/CRM and provider acceptance; and production-like migrations, accessibility, load, backup/restore and full frontend/backend quality gates.

A valid migration junction is not evidence that the entire historical chain was executed against PostgreSQL. Keep this PR in draft until the full implementation and its acceptance gates are complete. Do not weaken or skip existing CI gates to obtain a green status.
