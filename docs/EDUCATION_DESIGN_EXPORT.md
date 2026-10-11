# Education — uploaded design bundle implementation

Source: user upload `chat bot(1).zip`, folder `chat bot/Education/` (ten PNG exports).
Branch: `feat/figma-saas-bot-redesign`; draft PR #134. Main is not a deployment target.

## Implemented surfaces

| Export | Native application surface |
| --- | --- |
| Education Overview | Education Hub: dark hero, five workflow links, real-data summary cards, featured course/agent, course filters, chart period/metric controls, enrollment distribution, agent state, access requests, import and knowledge links |
| Screen 01 — COURSES / Screen 02 —Courses | Course catalog: export-style toolbar, search, status filtering, linked course names, live batch/student counts, existing CRUD and destructive-action confirmations |
| Add course | Existing validated course creation form restyled under the shared visual system and opened by `?create=1`; no duplicate mutation implementation |
| view courses | Course detail: durable course fields, linked batches, student enrollments, assigned agents and knowledge navigation |
| Batches List / Batches List-1 | Batch catalog: course and status filtering, live enrollment counts, deep-linked details and existing archive/reactivate operations |
| Create Batch / Edit Batch | Full-page two-column editor with baseline details, schedule/date validation, live preview, existing save API and fixed parent course when editing |
| Batch Details | Batch record detail, associated course, dates, roster, enrollment and assigned-agent data |

The Education subnavigation is reused in the desktop sidebar and mobile drawer. A compact-shell navigation fallback retains access to every existing Education route, including course knowledge. Workspace changes remount child views before new data is displayed. Explicit workspace permissions control new management/agent/knowledge actions; the backend remains authoritative.

## Data and behavior mapping

All normal builds retain `VITE_DEMO_MODE=false` or unset. The source export's sample values are not production fixtures. Courses, batches, students, enrollments, access requests and agents come from the existing authenticated clients. No production backend service or migration is modified by this Education increment.

An active enrollment is counted in the validity summary only when the current UTC date lies within its inclusive start/end dates. Student counts are deduplicated by student ID. This is a display calculation, not a substitute for the server's complete authorization checks. Loading or failed requests display unavailable values and retry controls, not invented zero totals. The chart is explicitly labeled as newly created enrollment/course records, not tutoring attendance or AI resolution performance.

Creation links retain unrelated query parameters on cancellation/completion. Existing student and enrollment managers are reused. Course/batch detail links are resolved against the active workspace's records. Batch creation validates code, name, course and date ordering; editing preserves the immutable parent course.

## Deliberate boundaries

The current backend does not supply weekly active learners, faculty counts, attendance, grading, saved import-job history, course tuition/duration metadata, instructor allocation, batch seat limits, delivery modes or recurring class schedules. These are not fabricated or silently stored in unrelated fields. The export's operational compositions and supported actions are implemented; unsupported sample values/controls are replaced by accurate labels or capability explanations.

The small knowledge illustration is not available as an independent asset in the supplied bundle. The current knowledge callout uses a native book icon; this is not claimed as an exact original artwork match. Authored desktop references do not define mobile layouts; responsive adaptations are separately tested.

The rest of the supplied bundle (six-step agent creation, all conversation states and original artwork) remains separate work. Existing Leads/Overview/agent flows are preserved. This increment is not a claim that the entire bundle has been reconstructed or that pre-existing global release gates are green.

## Verification

`education-design-review.yml` is read-only and adds focused frontend tests, existing real course/batch/student/dashboard API contracts, and a normal production frontend against an isolated real FastAPI with disposable SQLite. The browser runner whitelists runtime environment variables, uses random credentials and synthetic records, blocks external browser requests, and cannot target a deployed service. Its screenshots represent seeded test data, not actual customer activity. No paid AI provider or real message delivery is exercised.

Use the workflow's JUnit and `review-results/education-browser/summary.json` for executed outcomes; a configured check is not evidence that it passed. The original full frontend/backend/security/deployment workflows are retained unchanged.
