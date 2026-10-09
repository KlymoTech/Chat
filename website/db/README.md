# Website CMS database foundation

This SQL is a **schema-only, additive starting point**, not an authenticated CMS. Do not apply to the existing Chat production database without migration review, tenant mapping, privilege design, backup and rollback rehearsal. The SQL is intentionally isolated from `backend/migrations` so no existing migration head changes.

## Contract

- A page owns immutable revisions with an optional currently published revision pointer; audit and outbox tables are reserved for atomic publication transactions.
- A **future** audited publication service must, in one database transaction, authorize the editor, insert the immutable revision, set the published pointer, insert audit and outbox events, and commit before acknowledging publication.
- No purge job or automatic content deletion is implemented. Retention/trash and multi-approver permanent purge need distinct follow-up implementation.
- No public endpoint may expose unpublished revisions. Do not grant website runtime the ability to write audit rows, revisions or published pointers outside an authorized API.
- The public website can now render safe blocks using an **existing/externally provided** `WEBSITE_CMS_PUBLIC_API_URL` which returns the `PublishedPage` JSON contract. The backend endpoint is not implemented yet; unavailable content returns 404.

## Integration to do before launch

Introduce site-aware authorization, tenant isolation/RLS, media, fully governed CMS API, publish-and-rollback transactions, review queues, durable worker and cache invalidation, acceptance tests and migration provenance. Until implemented and verified, keep launch BLOCKED.

## Read-only API checkpoint

The app now has a `GET /api/public/pages?path=/content/example&locale=en` handler and direct server-rendered content reads using `website_cms.public_published_pages` (created by `002_public_read_role.sql`). Configure a separate SELECT-only database principal with access to **this view alone**. The SQL files have not been applied or tested in a database. No permission is automatically granted. The API returns 404 for unavailable content and 503 for database errors. Owner edits/publishing remain unimplemented. This is not a reviewed authorization boundary until view ownership, grants, and database security are tested.
