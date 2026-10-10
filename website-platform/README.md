# Website Studio — isolated website platform

This is the separate, incremental implementation of **Website Master Blueprint v1.3** inside the Chat repository. It adds a Next.js public website and owner console with a NestJS business API backed by PostgreSQL/Prisma. It does not modify the existing Northstar React/FastAPI application.

**Current state:** initial work package implemented on a dedicated feature branch. **Not production-ready or complete against all blueprint requirements.** See [implementation register](docs/implementation-register.md) and [architecture decisions](docs/architecture-decisions.md).

## Implemented foundations

- Dynamic published homepage, published pages and articles with mobile-responsive layouts.
- Owner sign-in and cookie-backed sessions; editing pages, articles and brand text.
- Versioned publishing: saved drafts do not immediately overwrite the live snapshot; published versions and audit events are recorded.
- Contact form with server validation and idempotency; lead and outbox event share one PostgreSQL transaction.
- Lead status review, basic audit/outbox monitoring, metadata, sitemap, robots, privacy and cookie preference screens.
- No deletions, tracker pixels, paid-ad integrations or invented customer proof.

## Local development

Prerequisites: Node.js 22+, npm, Docker Engine/Compose and an available 55432/4100/3101 port set.

1. `cd website-platform && docker compose up -d postgres`.
2. `npm install` (creates a lockfile that must be reviewed and committed before release).
3. Copy `apps/api/.env.example` to `apps/api/.env` and `apps/web/.env.example` to `apps/web/.env.local`; set a genuine admin email and **strong, unique password of at least 16 characters**. Never commit populated env files. The local PostgreSQL password is an example and must be changed outside development.
4. `npm run db:generate` then `npm run db:migrate` (use a reviewed migration name such as `init_website_studio` if prompted). Production migrations must be reviewed and committed separately.
5. `npm run db:seed`; this only creates the initial owner and home page if absent. Re-running it does not rotate an existing owner's password.
6. Run `npm run dev:api` in one terminal and `npm run dev:web` in another.
7. Open `http://localhost:3101` for the public site or `http://localhost:3101/admin/login` for the owner console.

If the API is not running, public data routes will fail. If the site database is not seeded, public content will not exist. Backend sessions require the site-origin configuration in the API to exactly match the browser origin.

## Boundaries and next work

Pages and articles are stored as **plain text**, not a visual section builder yet. The delivery queue is **persisted only**; no worker/provider adapter has been activated, so third-party notifications are not sent. No built-in user data deletion endpoint exists, but this does **not** substitute for a proper manual approval/preservation workflow. Live credentials, business-specific content, domains, legal texts, customer claims, target markets and platform integrations require a completed Appendix A site brief.

Run `npm test` and `npm run build` after setup. Tests in this branch are code-level examples and do not establish operational acceptance. Do not merge to main without separate user approval.
