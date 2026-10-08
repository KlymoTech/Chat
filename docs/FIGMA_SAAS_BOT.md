# SaaS Bot 01 — implementation and review record

Status: **draft implementation; not a production or complete-Figma acceptance**.
Branch: `feat/figma-saas-bot-redesign`. Pull request: #134. Main remains unchanged.
Design file: `opBYcjdIlYRQFAcDFUpCyO`, page `0:1`.

## Scope actually implemented

The existing React/TypeScript application and Python/FastAPI backend are retained. No backend services, database migrations, authentication transport, provider credentials, or deployment configuration were replaced.

| Surface | Implemented | Remaining |
| --- | --- | --- |
| Shared authenticated layout | Off-white navigation, charcoal active states, rounded panels, workspace/search/account pills, mobile drawer, existing routes and commands | Final comparison against every design state |
| Overview, Figma `59:12884` | API-backed metrics, featured-agent navigation, agent filters, weekly/monthly chart, knowledge health, connections, inbox activity, Help Center link | Exact original illustration and final visual acceptance |
| Agent creation, Figma `46:1704` | Existing four-step wizard restyled; `/agents?create=1` deep link; cancellation preserves unrelated query parameters; created agent opens its real builder | The design's six-step full-page composition and additional unsupported avatar/generation/draft controls are NOT implemented |
| Agents list, Conversations, Leads, Education and other existing routes | Existing business pages retained under the shared theme | Bespoke Figma page-by-page reconstruction is NOT complete |
| Fonts | Exact Space Grotesk, JetBrains Mono and Plus Jakarta Sans variable families, pinned Fontsource 5.3.0 packages and lock metadata, bundled locally | No external font CDN is required |

The Figma connector exhausted its plan call limit after the Overview and agent Basics design reads. Other screens were discoverable through metadata, but their complete design contexts and original assets were not retrievable. Metadata alone is not treated as a verified design specification. Original hero node `59:13025` and learning illustration node `59:13355` remain unexported; no unrelated image was substituted, and no expiring MCP asset URL was committed.

## Data and behavior preservation

`SaasBotOverview` calls the existing `api.agents.list`, `api.analytics.summary`, `api.conversations.list`, `api.knowledge.list` and `api.integrations.list` methods. Their bearer/session refresh and workspace headers remain untouched. No design sample statistics replace live responses in a normal build.

The active-agent count is current workspace state. Analytics labels identify the chosen 7/30-day period. Resolution is labelled **Resolved conversations**, not **Resolved by AI**, because the existing summary field does not establish AI attribution. Channel connection state is not represented as a service-uptime guarantee. Knowledge readiness is scoped to the named selected agent, not claimed as workspace-wide health.

Empty, loading, error and retry states are explicit. Failed or reloading analytics do not present the previous period as current data. Changing workspace remounts the dashboard. Explicit workspace permissions take precedence over organization roles for the new dashboard controls; creation, knowledge, analytics, conversations and integrations have separate checks. All authorization remains server-enforced.

The existing `CreateAgentModal` owns creation and validation. Its education draft-provisioning behavior and WhatsApp number rules are preserved. A new route adapter does not duplicate the business logic. Published custom dashboards continue to use `WorkspaceConfiguredDashboard` instead of being overwritten.

## Changed-code map

- `frontend/src/theme/saas-bot.css`: scoped theme, dashboard and responsive layout.
- `frontend/src/features/dashboard/SaasBotOverview.tsx`: live-data Overview composition.
- `frontend/src/features/dashboard/dashboardPermissions.ts`: explicit workspace capability handling.
- `frontend/src/features/dashboard/AgentsRoutePage.tsx`: adapter into the original creation workflow.
- `frontend/src/pages/OverviewPage.tsx`: workspace-keyed wrapper and custom-dashboard preservation.
- `frontend/src/components/materialm/MaterialmAppShell.tsx`: active shell theme, expanded-first preference, existing navigation behavior.
- `frontend/src/app/routes.tsx`: lazy-load the route adapter; all URLs retained.
- `frontend/src/main.tsx`, `frontend/package.json`, `package-lock.json`: local font and theme loading.
- `scripts/figma-redesign/checks.py`: independent diagnostics with per-stage logs and JUnit.
- `scripts/figma-redesign/browser_review.py`: explicitly demo-only browser review and screenshots.
- `.github/workflows/figma-redesign-review.yml`: read-only diagnostic jobs alongside, not in place of, the original CI gates.

## Test evidence and interpretation

Before frontend changes, workflow-only commit `ca10869b29f90429b5dcd747037ee81f43ae209d` triggered CI run `37814748860`: the frontend lint gate, backend gate and source/dependency security gate failed; deploy configuration passed. Full production topology integration was skipped by its existing dependencies. These failures were not converted to passing results or bypassed.

Independent review run `37816865979`, associated with branch commit `68e5f80bf9d18a7115a3c58411b17f48d02c5e5b`, produced complete diagnostic artifacts:

| Check | Observed result |
| --- | --- |
| Frontend typecheck | Passed |
| Production frontend build | Passed |
| Frontend lint | Existing 54 errors and 2 warnings |
| Backend tests | 1,561 passed; 67 failed |
| Backend Ruff | 163 errors |
| Backend formatting | 309 files would be reformatted |
| Backend mypy | 319 errors in 90 files |

The initial independent frontend test run also contained one transitional Overview mock failure before its test mocks were updated. It is not classified as a baseline defect.

A matched local comparison then ran the same toolchain on unchanged source and the updated dashboard. Baseline: **496 passed, 67 failed, 2 unhandled errors**. Redesign at that comparison point: **502 passed, 67 failed, 2 unhandled errors**. The failing test identities were identical; the six newly added dashboard tests passed. Later targeted testing added explicit owner/viewer and creation-adapter coverage: **34 tests passed across eight files**, including existing agent-purpose, duplicate and WhatsApp-number tests. Touched/new TypeScript files also passed targeted ESLint; the application TypeScript project passed. These are not assertions that the full repository suite is green.

The font-lock validation job at commit `d72ff2b6672e25323595a199df4be78896a79937` passed `npm ci`, typecheck and production build. Its temporary branch-only writer workflow and helper are removed after generating the three font-related files; the retained review workflow has read-only permissions.

The first browser review detected four pixels of horizontal overflow at 390px and a low-contrast sidebar logo. The responsive secondary-column alignment and logo override were corrected. Read the latest browser artifact `summary.json` for the actual rerun outcome; do not treat a configured check as passed before it runs.

Browser artifacts use **explicit offline demo fixtures** and are visual/interaction evidence only. They must not be presented as live tenant statistics, real provider delivery, or end-to-end backend proof. The normal production build must leave `VITE_DEMO_MODE` unset or false.

## Reproduce locally

Use a Node 22 release compatible with the existing lockfile (the review runner used Node 22.23.3), Python 3.12 and the existing backend configuration. Preserve local uncommitted work before changing branches.

```sh
git fetch origin
git switch feat/figma-saas-bot-redesign
npm ci
npm run typecheck
npm run build
npm run dev --workspace @northstar/web
```

Keep the current backend running and use its existing API configuration. The development proxy reads `VITE_DEV_API_URL` and otherwise targets `http://localhost:8000`.

```sh
# Individual diagnostics retain failures but continue collecting evidence.
python scripts/figma-redesign/checks.py frontend
cd backend
uv sync --all-groups --locked
uv run pytest
# Run the remaining backend diagnostics through the review workflow or
# python ../scripts/figma-redesign/checks.py backend with the CI test environment.
```

Focused UI checks:

```sh
npm run test --workspace @northstar/web -- src/features/dashboard src/pages/AcademyDashboards.test.tsx src/components/materialm/MaterialmAppShell.test.tsx src/pages/AgentsPage.test.tsx src/pages/AgentsPage.whatsapp.test.tsx
```

Visual-only review, in an isolated environment with no production credentials:

```sh
python -m pip install playwright==1.57.0
python -m playwright install --with-deps chromium
# POSIX syntax. PowerShell: set $env:VITE_DEMO_MODE='true' for this build only.
VITE_DEMO_MODE=true npm run build
python scripts/figma-redesign/browser_review.py
# Rebuild without VITE_DEMO_MODE before any normal deployment.
```

## Release blockers and next acceptance

The 67 backend failures span authorization expectations, education/channel rules, signup/subscription defaults, password-reset database behavior, branding/domain contracts and route-registration assertions. They require triage against the intended contracts; do not weaken security assertions merely to make tests green. Frontend baseline failures include stale API/provider mocks and contract assertions; confirm intended behavior before changing them. Existing lint, type and security gates also remain release blockers.

Completion requires the remaining Figma screen exports and original assets, page-by-page implementation without removing current functionality, successful focused and full regression suites, the original security/deploy gates, real backend browser integration with seeded test tenants and permissions, and a review of actual channel/provider flows in a safe staging environment. Main must not be merged or deployed on the strength of demo screenshots alone.
