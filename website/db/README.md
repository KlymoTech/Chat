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

## Editorial integrity and published blog catalogue (additive migrations 009–010)

`009_editorial_integrity.sql` introduces database guards that make source revision snapshots immutable, allowing only the audited draft → approved state transition, and protects audit/approval records against UPDATE/DELETE by the application. This supplements—not replaces—independent audit export and least-privilege grants. DBA-superuser privileges and schema ownership still require separate controls.

`010_blog_catalogue.sql` adds a non-cascading page-to-blog classification table and a `security_barrier`-backed `website_cms.public_published_blog_entries` view. Only revisions pointed to as published and belonging to non-trashed pages appear. The public reader role must be granted SELECT on this view after review; **do not grant it direct access to pages, drafts, audit or blog source tables**. Existing content is never automatically deleted. Metadata is set on an unpublished CMS page via an authenticated, audited, site-scoped endpoint, then locked before independent editorial approval and publication. Category/tag revisions after publication require a future separately governed workflow.

Isolated acceptance script: `npm run test:postgres`, running **only** with `WEBSITE_TEST_DATABASE_ALLOW=true` and a PostgreSQL URL ending in local `/website_test`. It applies migrations 001–010 to a **fresh test database** and checks draft/public separation, publication pointer, immutable revisions, append-only evidence, trash/restore visibility, blog read-only visibility, lead/outbox consistency, idempotency and rate-counter admission. It intentionally rejects all non-local test-database URLs. A passing run is still required and cannot be inferred from the scripts merely existing.

## Media quarantine manifest (additive migration 011)

`011_media_quarantine.sql` adds site-scoped private manifests and immutable-by-reference media usage records for future editor workflows. The media table distinguishes *claimed* MIME/checksum/size from independently *verified* evidence. The default state is quarantined and the blob is not uploaded. A database constraint requires actual upload, matching MIME/size/hash, verified dimensions, scanner receipt, reviewer identity, rights and accessible alternative text before any record can be approved. The normal owner API can only reserve private manifests; it cannot upload, mark approved or publish bytes. No public grants, automatic expiry, delete action or CDN URL are created. DB grants and scan/reviewer service separation must be designed and proven before use.

The isolated database script now expects migrations 001–011 and checks that new manifests remain quarantined, approval without evidence fails and cross-tenant usage fails. PostgreSQL runs have **not** been confirmed passing. Migrations must be applied with backup and DBA review, not directly against the Chat application's database.
