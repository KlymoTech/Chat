# Workspace feature module — incremental migration

This directory owns new workspace capabilities without deleting or relocating existing implementation. The public API remains `GET/PATCH /api/v1/workspace` (with the existing `/v1` alias); authentication, workspace selection (`X-Workspace-ID`), permission enforcement, validation, legacy branding, security, members, invitations and API keys continue through the existing routers. This module is **not** a replacement workspace router yet.

## General settings: implemented backend slice

`services/general_settings.py` is called by `northstar_api.routers.workspace.update_workspace` after existing validation and before the existing database commit. It compares the persisted values of `name`, `slug`, `timezone`, `default_language` and `date_format`, and records only genuinely changed field names. It stages a `workspace.settings.updated` audit record (actor, tenant and workspace IDs) and a `workspace.settings.updated.v1` outbox record in the same transaction as the workspace update. On transaction failure, all three writes roll back together. Outbox payload: `{ "workspaceId": "<UUID>", "fields": ["name", "timezone"] }`; **old and new values, access tokens and secrets are not included**. Unchanged general settings do not produce a domain event. Legacy security and branding paths retain their pre-existing events and behavior.

The existing `GET /api/v1/workspace` response and `PATCH /api/v1/workspace` request/response schemas remain unchanged. This slice requires no migration or new external service. No worker has been added: the existing transactional outbox and existing publisher remain responsible for delivering events. The frontend continues to call its current `workspaceApi.update` method.

## Checks before any merge

Run from `backend/`: `uv sync --all-groups --locked`, then `uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy src`, and `uv run pytest tests/test_workspace_general_settings_unit.py tests/test_workspace.py tests/test_workspace_contract_unit.py`. Run the repository-wide backend and frontend CI suites afterwards. Test no-op updates, changed fields, wrong-workspace access, permission denials and persistence before merging.

## Status and boundaries

This is **one backend slice** of sections 22–44, **not** the entire requested Workspace implementation. Remaining workspace settings UI, team/role lifecycle, dashboard composition, branding publication, domains, tenant-isolation hardening and acceptance checks must be implemented and independently verified in sequence. WhatsApp, Super Admin, CRM and non-workspace code are owned by other workstreams. Preserve existing files, endpoint compatibility and the other team's changes. Do not merge the draft PR until every in-scope requirement and CI gate is complete.
