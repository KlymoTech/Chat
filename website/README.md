# Website Blueprint v1.3 implementation

This independent Next.js public-site scaffold is isolated from the existing React/Vite control plane and FastAPI product API. It does **not** replace, rewrite, or deploy either existing service.

## Run

From the `website` directory: `npm install`, `npm run dev`; browse http://localhost:3000. Set variables from `.env.example` in `.env.local` after confirming all public claims. Run `npm run typecheck` and `npm run build` before considering a deployment.

## What is currently implemented

- Responsive semantic HTML, keyboard skip link, primary and legal navigation, focus indicators, reduced-motion handling.
- Accessible home, services, about, resources, contact, privacy and terms **starter** routes.
- Per-route titles, global metadata, and configurable site identity. Search indexing is withheld until an explicit site URL is configured.
- Contact uses a configured mailto address; it **does not claim to store a lead**.\n- Schema-only revision/audit/outbox tables and a read-only published-content renderer are introduced; no CMS service or database installation has occurred.

## Release blocking gaps

These pages contain conspicuous placeholders, not approved business claims or legal policies. No functioning CMS, owner console, durable form ingestion, transactional outbox, authentication, audit trail, blog publishing, media storage, consent manager, analytics, paid-media conversion delivery, rollback, backups, or production acceptance exists in this starter. Do **not** advertise it as a finished site or enable paid traffic. Follow `docs/website-blueprint-implementation.md` for the phased delivery and proof contract.

## Architecture decision

The source blueprint defaults to Next.js public web + React owner console + NestJS + PostgreSQL. This repository currently operates React/Vite + FastAPI. In order not to disrupt Chat's existing workflows, this branch introduces Next.js public-web code independently and proposes adapting through versioned FastAPI APIs and the existing durable infrastructure. A NestJS service should only be adopted following a reviewed migration decision, not as a surprise replacement.

## Enquiry storage (disabled by default)

The contact route has an optional enquiry form with PostgreSQL lead+outbox atomic writes. It is **disabled** unless `WEBSITE_LEAD_CAPTURE_ENABLED=true` and the dedicated database and origin values are configured. Never enable before anti-abuse controls, least-privilege credentials, approved privacy text, and durable retry/worker verification. CRM/email deliveries are not implemented. SQL has not been run against a database; see `db/003_lead_capture.sql`.

### Idempotency safety update

`db/004_lead_idempotency.sql` adds a SHA-256 fingerprint of the normalized submission payload. Reusing an idempotency key with different form data now returns HTTP 409 and does not pretend a new enquiry was accepted. Apply migrations in order after backup and privilege review, with a tested deployment backfill. This code remains unverified against live PostgreSQL.
