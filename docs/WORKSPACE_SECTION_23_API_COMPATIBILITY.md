# Workspace section 23 — API and model boundaries and compatibility

This document covers only Workspace/branding feature boundaries. It describes committed code on the corrective branch of draft PR #132, based on the Workspace implementation branch of draft PR #131. Sections 24–26 (WhatsApp), 31 (Super Admin), and teammate sections 1–22 are excluded.

## Registration and compatibility rule

`northstar_api.routers` registers `modules.workspace.router` under the application's existing API prefix and global entitlement dependency. The Workspace aggregate keeps its `/workspace/settings` prefix. An existing path must be registered **exactly once** in the application's aggregate router. New canonical capability routers reuse the *same existing endpoint function*, FastAPI dependency annotations, HTTP method, response model and status code. The combined routers remain importable for legacy callers but are not additionally registered.

| Capability | Canonical API module | Existing path suffix / HTTP method |
| --- | --- | --- |
| Read settings and capabilities | `modules/workspace/api/workspace_settings_core.py` | `GET /`; `GET /capabilities` |
| Update general settings | `modules/workspace/api/workspace_general_settings.py` | `PATCH /general` |
| Workspace general metadata | `modules/workspace/general.py` | `GET /general/metadata` |
| Security settings | `modules/workspace/api/workspace_security.py` | `PATCH /security` |
| Notification settings | `modules/workspace/api/workspace_notifications.py` | `PATCH /notifications` |
| Developer settings | `modules/workspace/api/workspace_developer.py` | `PATCH /developer` |
| Member lifecycle | `modules/workspace/api/workspace_members.py` | Existing member routes (unchanged) |
| Roles | `modules/workspace/api/workspace_roles.py` | `PATCH /roles` |
| Teams | `modules/workspace/api/workspace_teams.py` | `PATCH /teams` |
| Dashboard settings | `modules/workspace/api/workspace_dashboard.py` | `PATCH /dashboard` |
| Brand read, runtime and draft | `modules/branding/api/brand_draft.py` | `GET /branding`; `GET /runtime-branding`; `PATCH /branding/draft` |
| Brand publication and rollback | `modules/branding/api/brand_versions.py` | `POST /branding/publish`; `POST /branding/rollback` |
| Custom domains | Existing `modules/workspace/domains.py`, exported by `modules/branding/api` | Existing `/domains` operations (unchanged) |
| Branded email preview and test | Existing `modules/workspace/email_routes.py`, exported by `modules/branding/api` | `POST /branding/email/preview`; `POST /branding/email/test` |

All suffixes above are relative to `/workspace/settings` and the existing application-wide API prefix. `modules/workspace/api/workspace_invitations.py` is an **opt-in import adapter**: invitation routes remain registered once by their existing owner; this branch does not change their handlers or teammate-owned files.

## Model boundaries without a schema change

The canonical `modules/workspace/models/` package now exposes these feature-owned modules, all of which **re-export the existing Python class objects** rather than declaring new SQLAlchemy mappings:

| Canonical module | Original types | Existing persistence |
| --- | --- | --- |
| `models/workspace.py` | `Workspace`, `WorkspaceStatus` | `northstar_api.models` / existing `workspaces` table |
| `models/workspace_member.py` | `WorkspaceMembership`, `WorkspaceMemberAgentAccess` | Existing membership and agent-access tables |
| `models/workspace_role.py` | `WorkspaceRole`, `CustomRole`, `RolesSettings` | Original role enum and validated custom-role settings document; **no new role table** |
| `models/workspace_team.py` | `WorkspaceTeam`, `TeamsSettings` | Original validated team settings document; **no new team table** |
| `models/workspace_invitation.py` | `WorkspaceInvitation`, `WorkspaceInvitationAgentAccess`, `WorkspaceInvitationStatus` | Existing teammate-owned invitation ORM tables; no behavioral changes |

`models/__init__.py` preserves the original `WorkspaceConversationAssignment` export and exposes the additional types lazily to avoid importing contracts and invitations prematurely. Existing model and contract imports remain valid. The added identity regression test checks the canonical exports are the *same objects*, the original ORM mappers remain the same, and no extra SQLAlchemy metadata tables appear. It does **not** assert that standalone role/team ORM persistence has been implemented. That requires a separate, tested database migration and must not be inferred from this additive import boundary.

## Import compatibility

The combined `modules.workspace.settings.router`, `modules.workspace.access.router`, and `modules.workspace.branding.router` remain importable. The `modules.branding` package resolves its established public router exports lazily to avoid re-entering the partially initialized legacy branding module. `brand_draft_router` and `brand_versions_router` are additional canonical exports; existing `branding_router`, `domains_router` and `email_router` exports remain available.

## Required verification before closing section 23

These commands are a verification procedure, **not a claim that checks have passed**:

```bash
cd backend
uv sync --all-groups --locked
uv run ruff check src tests
uv run ruff format --check src tests
uv run mypy src
uv run pytest tests/test_workspace_module_boundaries.py tests/test_workspace_canonical_api_routes_unit.py tests/test_workspace_settings_split_routes_unit.py tests/test_workspace_branding_split_routes_unit.py tests/test_workspace_branding_import_order_unit.py tests/test_workspace_production_router_registration_unit.py tests/test_workspace_legacy_loader_import_order_unit.py tests/test_workspace_canonical_model_boundaries_unit.py
```

Additionally run the entire backend/frontend quality gates and verify authenticated and unauthorized calls to every migrated route against the previous API contract. Confirm tenant and workspace isolation, no duplicate operation IDs or mapped tables, preserved global entitlement enforcement, and no import-order regressions. Section 23 remains **OPEN** until these checks produce successful executable results; section 44 requires further database, security, UI and integration verification before either draft PR can merge into `main`.
