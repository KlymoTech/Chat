# Workspace feature module — incremental migration

This directory owns new workspace capabilities without deleting or relocating existing implementation. The public API remains `GET/PATCH /api/v1/workspace` (with the existing `/v1` alias); authentication, workspace selection (`X-Workspace-ID`), permission enforcement, validation, legacy branding, security, members, invitations and API keys continue through the existing routers. This module is **not** a replacement workspace router yet.

## General settings: implemented slice

`services/general_settings.py` is called by `northstar_api.routers.workspace.update_workspace` after existing validation and before the existing database commit. It compares persisted `name`, `slug`, `timezone`, `default_language` and `date_format` and records only genuinely changed field names. It stages a `workspace.settings.updated` audit record (actor, tenant and workspace IDs) and a `workspace.settings.updated.v1` outbox record (tenant and workspace IDs) in the same transaction. On transaction failure, all three writes roll back together. Outbox payload: `{ "workspaceId": "<UUID>", "fields": ["name", "timezone"] }`; **old and new values, access tokens and secrets are not included**. Unchanged general settings do not produce a domain event. Legacy security and branding paths retain their pre-existing events and behavior.

The existing `GET /api/v1/workspace` response and `PATCH /api/v1/workspace` request/response schemas remain unchanged. This slice requires no migration or new external service. No worker has been added: the existing transactional outbox and existing publisher remain responsible for delivering events.

The frontend form and its education guidance now live in `frontend/src/features/workspace/general/WorkspaceGeneralPanel.tsx`, rendered by the existing `WorkspacePage`. It keeps calling the existing `workspaceApi.update` method. A failed initial workspace request now displays an error and retry action instead of an indefinite loading state. Existing team, developer, security, billing and White Label entries are preserved.

## Checks before any merge

From `backend/`, run `uv sync --all-groups --locked`, then `uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy src`, and `uv run pytest tests/test_workspace_general_settings_unit.py tests/test_workspace_general_settings_api.py tests/test_workspace.py tests/test_workspace_contract_unit.py`. Run frontend lint, typecheck, `WorkspaceGeneralPanel.test.tsx`, the full frontend suite and builds. Check wrong-workspace access, permission denials, transaction rollback and existing feature regressions.

The four focused backend unit tests passed locally against source and test bytes independently verified against the GitHub blob SHAs, with audit and outbox dependencies mocked. **This does not constitute a full backend test run.** GitHub's PR CI has returned failures before accessible job steps/logs could be retrieved, so the root cause and full-suite results are unknown. The integration and frontend tests are committed but **not verified as passing**.

## Status and boundaries

This is **one initial Workspace slice** of sections 22–44, **not** the entire requested implementation. Workspace settings UI expansion, member/team/role lifecycle, dashboard composition, branding publication, domain lifecycle, tenant-isolation hardening and acceptance checks remain outstanding. WhatsApp, Super Admin, CRM and non-workspace code belong to other workstreams. Preserve existing files, API compatibility and teammates' changes. Do not merge the draft PR until every in-scope requirement and CI gate is complete.
