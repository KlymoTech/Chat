# Website blueprint: consolidated integration branch (10 October 2026)

## Safety and provenance

**Destination only:** `feature/website-consolidated-20261010`. No commit in this operation was written to `main`; no source branch was deleted or force-moved.

The consolidation commit `3f95819be252c4f3d4abffbb8c78697aa60dd748` has three parents:

1. `feature/website-blueprint-v1-3-20261010` at `24fa6f4bd3156b9dbd9c30f6eeffd8f4251a7677`: existing React/FastAPI integrated website CMS, forms, analytics, privacy and CRM screens.
2. `feature/website-blueprint-v1-3` at `325d64619a8b8d8a6c630e6a2b5deb4a45eaed23`: Next.js website application in `website/`, with its own database scripts, tests and workflows.
3. `feature/website-master-blueprint-v1-3-20261009` at `2a34e22d5aca4b75b24c85f4d09efe7793f0f626`: alternate Next.js + NestJS site implementation in `website-platform/`.

All 328 changed source paths across the three diffs were disjoint (83 + 198 + 47), so no existing path was overwritten to create the consolidation. The resulting tree preserves all three branch histories and their files. This is a **code/history consolidation**, not a claim that the three website implementations now share a runtime, database, or user experience.

## Avoid duplicate live products

- **Current integrated product runtime:** `frontend/` and `backend/` (React and FastAPI, including the existing CRM/Lead models). Continue integrating capabilities here by preference.
- **Other branch deliverables preserved for review:** `website/` and `website-platform/`. Their separate app stacks must not be deployed concurrently as copies of the same product until a documented architecture decision and migration/test plan approves one.
- Preserve those trees and the source branches for provenance. Reuse missing domain logic after a capability-by-capability audit; do not recreate CRM, authentication, billing, user or content tables merely because alternate implementations exist.
- Existing `.github/workflows/website-blueprint-branch.yml`, `website-blueprint.yml`, and `website-platform.yml` are all preserved. Their checks are not proof of success until GitHub runners actually execute and report passing status.

## Verification and release boundaries

- `main` was not changed and **must not be the target** for unfinished website integration.
- The three source branches are contained as ancestors of the consolidated branch. They remain available and unmodified.
- Read the 120-capability register at `docs/WEBSITE_BLUEPRINT_120_CAPABILITY_TRACEABILITY.md`; it is the controlling implementation and acceptance tracker. A registered item is not automatically completed because its code exists in `website/` or `website-platform/`.
- Next steps: select one production runtime, audit duplicate domains across stacks, port missing capabilities additively, resolve CI runner failures, apply migrations in an isolated database, execute unit/integration/browser tests, test consent/recovery/rollback and record acceptance evidence. Do **not** imply this branch is production-ready until all applicable release gates are proven.

## Verification of branch merge

The GitHub compare endpoint reports **0 commits behind** this consolidated branch for each of the three source branches, and `main...feature/website-consolidated-20261010` is ahead with **0 commits behind**. This documents history inclusion, not runtime compatibility.
