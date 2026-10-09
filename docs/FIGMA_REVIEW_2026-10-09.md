# SaaS Bot redesign — 9 October 2026 continuation

Status: draft implementation, not full Figma acceptance or production approval.
PR: #134. Branch: `feat/figma-saas-bot-redesign`. Main remains unchanged at `26b2737335d81213fd0bbb9f0052a85f0eb50576`.

## Implemented in this continuation

- The Overview attention card now asks the existing authenticated API for the newest open and escalated conversations separately, before pagination. It merges and deduplicates those results and displays the newest three. A partial request failure is an error, not an empty or healthy inbox. This fixes unresolved conversations being hidden behind the first page of recently resolved conversations.
- Explicit inbox deep links are preserved even when the requested conversation is outside the first 100 list records. Automatic selection occurs only when no explicit selection exists and preserves unrelated query parameters.
- A retained polling result is displayed only for its matching selected conversation. Loading and retry states are explicit for off-page details. Returning to the mobile list hides the old detail.
- Reply drafts are scoped to the workspace and selected conversation, so switching conversations does not carry a previous recipient's draft into a new recipient's composer.
- Added ten frontend regression tests and nine parametrized real FastAPI/SQLite API contract cases. The API cases cover pre-pagination state filters, detail retrieval, workspace isolation, analytics periods, response shapes, missing authentication and unknown workspaces.
- Added a read-only focused CI workflow alongside the original full frontend, backend, security and topology checks. No original failing gate is disabled or weakened.

The retained React routes, four-step creation modal, authentication transport, workspace permissions and FastAPI implementation remain in place. No production backend service or database migration is modified in this continuation.

## Local evidence

A matched comparison used the same recovered Node 22.23.3 test toolchain against source `2d3ddb6d91a613e0c55088ac27ed4565f27e0cb7` before the changes and the reviewed changes after them.

| Check | Before | After |
| --- | --- | --- |
| Full frontend tests | 508 passed, 67 failed | 518 passed, 67 failed |
| Failing test identities | 67 | Same 67, zero added or removed failures |
| Focused dashboard, queue and selection tests | Not this combined selection | 33 passed |
| New inbox selection tests before fixing implementation | 3 failed, 2 passed | 5 passed |
| Application TypeScript project | Not rerun in this comparison | Passed |

The full application/configuration build is delegated to the locked CI install because the isolated local toolchain lacks the workspace-local Vite React plugin. The three pre-existing `react-hooks/set-state-in-effect` violations in `ConversationsPage.tsx` remain; the newly added TypeScript files and changed dashboard passed targeted lint. This is not a claim that repository-wide lint is green.

Read the CI runs and their JUnit artifacts for the backend contracts, clean-install build and browser checks associated with the final source. A configured check is not recorded here as passed before execution. The prior full backend diagnostic reported 1,561 passed and 67 failed; that historical result is not a fresh test result for this continuation.

## Design and release blockers

Both Figma design-context retrieval and screenshot retrieval returned the connected Starter-plan MCP call-limit error in this continuation. No new Figma frame or original asset could be inspected. The already implemented shared shell and Overview are retained, but this work does not claim to reconstruct unseen designs.

Still outstanding: page-by-page Agents, Conversations, Leads and Education Figma reconstruction; the exact six-step full-page agent-creation design; unexported original illustrations; final visual comparisons; resolving the full-suite/lint/security failures; real browser-to-backend integration and safe provider staging tests. Existing browser-review screenshots are explicitly demo fixtures, not provider-delivery or live-backend proof. Do not merge or deploy merely because the focused contracts or production build pass.
