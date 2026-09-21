# Workspace owner recovery — additive endpoint

`POST /api/v1/workspace/owner/recover` (and the application's pre-existing `/v1` API alias). This is **not** ordinary ownership transfer: the latter remains `/workspace/owner/transfer` and requires the existing owner. No original API path or creator record is deleted.

## Request

The authenticated caller must select the workspace with `X-Workspace-ID` and possess the existing `members.manage` workspace capability **and** be the active tenant's `owner`. The request must use an interactive access token, never a workspace API key. The service independently verifies current organization ownership from the database rather than trusting the token role alone.

```json
{
  "targetUserId": "<UUID of a different active workspace administrator>",
  "reason": "recorded_owner_unavailable",
  "confirmation": "RECOVER"
}
```

`reason` is either `recorded_owner_unavailable` (a stored owner ID exists but does not resolve to an eligible owner) or `legacy_owner_unavailable` (an older workspace has no stored owner ID and no eligible owner). The reason must match the actual locked workspace state. A self-appointed target, missing/wrong-workspace/other-tenant target, suspended target, inactive account, non-admin or target without current tenant membership is rejected. An active owner means **409; use normal transfer**, not recovery. `RECOVER` is case-sensitive. Missing/invalid input returns 422. Unauthorized requests return 403.

On success returns `{ "ownerUserId": "<UUID>", "ownerName": "...", "creatorUserId": "<UUID or null>" }`, sets private no-store, and changes only `settings_json.ownerUserId`. No user role or immutable workspace creator changes. All transitions take the workspace row lock, and record exactly one tenant/workspace-scoped `workspace.owner.recovered` audit and `workspace.owner.recovered.v1` outbox event in the same database transaction. Payloads contain target ID, reason code, an existing-record flag and workspace ID; they never copy untrusted original owner strings, invitation tokens, passwords or other secrets. The request that fails validation must not emit a recovery record.

Frontend: the General Settings owner panel only displays recovery to a locally identified organization owner with `members.manage` when GET owner returned null. It loads authoritative member details and offers only other active workspace administrators, requires a reason and typed confirmation, blocks on candidate-fetch error, and uses a context-checked, non-retrying request. **Frontend visibility is not the permission boundary.**

## Acceptance still required

Run `backend/tests/test_workspace_owner_recovery_api.py` on the fully provisioned database, then verify tenant-owner versus workspace-admin authority, suspended targets, legacy and invalid-record cases, old-route compatibility, transaction rollback, simultaneous transfer/recovery locking, frontend component tests and actual PostgreSQL RLS. Locked dependencies and GitHub CI are not green in this session; this code is not authorized for merge or production deployment until the complete section-44 criteria pass.
