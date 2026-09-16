# Workspace platform consolidation

Branch: `feature/workspace-platform-consolidated-20260917`.
Base: `077a5531402de9fa926eb3660ebf0fe9f2f4c4fa` (the earlier scoped-permission checkpoint).
Original main is not changed by this work. This branch must not be merged or deployed until its acceptance gates pass.

## Recovered source checkpoint

The source previously delivered only in the local review bundle is now being committed to this branch: organization onboarding, institution/business profile validation, required-profile API guard, named bounded Free plan, explicit legacy-plan mapping, approved starter tutorials/templates, persistent owner branding choice, safe raster validation, basic dashboard branding, workspace request/state fencing, and regression tests. The existing signup, invitation, verification, MaterialM frontend, domain APIs and worker topology are reused.

This checkpoint is NOT the full specification. Advanced custom-role/team management, comprehensive resource authorization, organization switching, immutable branding/inheritance, verified domains/senders, full surface rendering, lifecycle/export/deletion, atomic usage budgets and production acceptance are tracked separately and may only be marked complete with code and matching tests.

## Evidence boundaries

382 isolated Python unit/contract/migration tests passed in the working overlay. The original application conftest, full source tree, runtime dependency set, PostgreSQL and brokers were unavailable in that environment. These are not 382 end-to-end application tests. The TypeScript syntax checker does not establish semantic type correctness, a successful frontend build or browser acceptance. Historical GitHub CI failures remain unexplained because job logs were unavailable. No live provider, DNS/TLS, mail-sender, backup or production validation is claimed.

## Migration

Apply migration `0044_workspace_onboarding` after existing `0043_knowledge_training` in a controlled test deployment first. Existing customers receive a profile-completion grace and their known names only; no industry/contact details are invented. Unknown legacy subscription names require explicit `NORTHSTAR_LEGACY_PLAN_ALIASES` mappings to known plans before the migration proceeds. Unknown new plan names grant no capacity. Preserve data backups and review the mapping with the organization owner/operator before production migration.
