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

## Approved public asset release — migration 013

`013_public_media_delivery.sql` introduces media publication and withdrawal attribution fields plus `public_published_media`, a security-barrier view containing **only** independently reviewed, fully scanned, derivative-backed, explicitly published, not-withdrawn assets. Grant SELECT on this view only to the server-side media read-only service role; avoid any SELECT on raw `media_assets`, source uploads, rights/provenance JSON, edit history or audit events for the public runtime. Provision a distinct publisher writer role with narrowly scoped update/SELECT and audit insert grants. The schema does not create users, alter existing app roles, or add public object storage permissions. `verify-postgres.mjs` now requires migrations 001–013 and defines unapproved publication/visibility regression scenarios; live database verification has **not** passed.

## New privacy and automation migrations 014–015

`014_privacy_analytics.sql` adds versioned optional consent decisions, tightly enumerated non-PII event records and per-anonymous-receipt event-rate windows; no public grants or vendor forwarding. It retains rows pending an approved deletion/retention policy. `015_automation_drafts.sql` adds site-bound workflow definitions and immutable draft versions only, with no outbound provider worker or publish capability. Both require audited, least-privilege PostgreSQL roles and real tenant isolation before enabling their default-OFF flags. The isolated migration script now expects versions 001–015 and includes basic CHECK, FK, withdrawal and immutability fixtures, but these have not executed successfully here. The new `test:security-db` preflight can independently evaluate public CMS reader rights and forced tenant RLS; it must be run against explicitly approved staging credentials and is read-only.


## Migration 016 — synthetic-only automation durability

`016_internal_automation_runs.sql` adds immutable-version-bound, site-scoped `automation_internal_runs`, per-step records and idempotent internal tasks. Composite foreign keys prevent assigning a task or step to a run in another site. Runs are bounded to 14 days and at most 60 executed nodes; a completed/failed/cancelled run must have `finished_at`. No trigger enrolls accepted customers by default; all owner runs carry `subject_type=synthetic`. The one-shot runner uses short transactions and `FOR UPDATE SKIP LOCKED` to avoid duplicate concurrent workers. SQL role grants, tenant isolation, reader restrictions and PostgreSQL 16 integration must be independently verified. This is not a CRM or outbound marketing sender.


## Migration 018 — privacy rights case ledger (not automated fulfilment)

`018_privacy_rights_cases.sql` introduces private site-scoped cases and immutable
append-only history for access, correction, erasure, objection and restriction
requests. It intentionally stores no requester name, email, address, uploaded
identity proof, sensitive free-form text or erasure payload. Sensitive decisions
require an external evidence-reference UUID. Case details and identity checks
remain in an approved separate system and must be independently verified.

The owner API requires a distinct `cms:privacy` IdP permission, a verified DB
grant flag, and operator-approved activation. The domain service checks legal
workflow transitions, revision conflicts, and a different actor for identity
verification, legal hold, approvals, denials, execution and closure.
The isolated PostgreSQL verifier now expects migrations 001–018 and tests
append-only history, evidence constraints, and cross-site FK restrictions.

This does NOT execute deletion/anonymization, propagate rights to processors,
apply legal hold across all systems, verify requester identity, or satisfy
jurisdiction-specific deadlines; those remain release blockers. No new public
database grants or automatic data-purging jobs are created.


## SEO redirect registry — retired content only (migration 019)

The blueprint's owner acceptance exercise includes creating a redirect. This slice adds a separate `cms:redirect` permission, authenticated owner editor `/owner/redirects`, draft creation, independent reviewer approval, auditable suspension and permanent server-side HTTP **308** redirects from retired `/content/<slug>` URLs. It does not redirect arbitrary old URLs, proxy API routes, carry over unverified query parameters, rewrite menus or change existing root routes. Destination values are restricted to known internal public paths or a currently published `/content/<slug>` page. External URLs, protocols, percent escapes, path traversal, fragments, URL queries and same-path redirects are denied. Redirect chains are rejected when approving; the public security-barrier view hides disabled mappings and mappings whose content target is no longer published.

Migration `019_content_redirects.sql` adds a site-scoped redirect registry, checked internal destinations, a security-barrier view, and a page-collision trigger. The page-collision trigger and the approval transaction lock the same site row to prevent concurrent route reuse. No public reader is granted access to the private registry. The administrator must grant only the new public redirect view, with private site-specific editor privileges and tenant isolation separately reviewed. Writer and public-reader features are **off by default** using `WEBSITE_REDIRECT_EDITOR_ENABLED` and `WEBSITE_REDIRECT_PUBLIC_ENABLED`; verified DB-grant flags and distinct credentials are required. The existing public content route applies approved redirects only when the live published page is missing. The 308 status intentionally preserves the destination path but does not preserve UTM or click query strings; policy-specific attribution-preserving redirects require separate testing and approval.

This is an additive isolated implementation. Full redirect inventory, bulk import/export, multisite/locale handling, arbitrary legacy URLs, owner navigation-edit flows, canonical SEO migration, sitemap audits, performance tests and release approval are still outstanding. Unit tests and the isolated migration acceptance script through **001–019** are committed but **not confirmed executed**. CRM integration remains deferred. No changes to `main`.
