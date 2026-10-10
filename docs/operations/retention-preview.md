# Conversation retention: read-only inventory foundation

This is a deliberately conservative first increment, **not a retention deletion
worker**. The backend has a per-agent `security.retentionDays` field (1–3650
days), but no unified legal-hold registry and no complete age-based deletion
executor. The website privacy-rights subsystem has a distinct
`legal_hold` case state.

The inventory uses only conversation identifiers, timestamps, the latest
message timestamp, and the agent's retention policy. It avoids reading
message content, visitor name/email, prompts, attachments, or other PII.
The candidate window is conservatively based on the latest of
conversation creation/activity and the most recent message. Missing,
invalid or non-timezone-aware policy evidence cannot produce a candidate.

Run explicitly for a **single tenant and workspace** (operator access only):

```bash
cd backend
uv run python -m northstar_api.workers.retention_preview \
  --tenant-id <tenant-uuid> --workspace-id <workspace-uuid> --limit 500
```

The command executes read-only SQL, sets PostgreSQL transaction READ ONLY
and tenant RLS context, uses an upper bound of 1,000 rows per invocation,
and outputs JSON identifiers/counts without message content.

**No records are deleted** and no task is scheduled by this feature.
`candidate_ids` are provisional and must **not** be passed directly
to a deletion endpoint. Before an executor is enabled, reconcile website
privacy-rights cases and holds, external backup/object/Kafka retention,
data export/custody approvals, concurrency/revision fencing, audit trails,
and full end-to-end tests.

This implementation intentionally does not claim to satisfy regulatory
retention/deletion obligations by itself.
