# Website Master Blueprint v1.3 — implementation and evidence register

**Branch:** `feature/website-blueprint-v1-3`  
**Policy:** no merges to `main`; no modifications of existing product service behavior without tested additive compatibility.  
**Source:** Website Master Blueprint v1.3, 7 October 2026, 78 chapters and Appendices A–P.

## Required discovery decisions (OPEN — no fabricated answers)

Owner must confirm legal entity, brand, domain, languages, offers, price/claim evidence, content owners, conversion outcome, traffic/uptime expectations, privacy jurisdictions and lawful bases, consent purposes, integrations, production hosting, budget, RPO/RTO, and release reviewers (chapter 02, Appendix A). Without these the website cannot be declared complete.

## Requirements by verified state

| Area | Blueprint mapping | Status | Acceptance evidence required |
| --- | --- | --- | --- |
| Public route starter, navigation, accessible responsive layout | 04–06, 73 | IMPLEMENTED / UNVERIFIED | automated build, mobile/keyboard/zoom/screenshots and content signoff |
| Owner CMS, page revisions, preview, publish, rollback, media | 07–09, 44, 73, 76 | NOT IMPLEMENTED | role-based end-to-end publish/recovery tests |
| Blog preservation and manual-only deletion | 09, 38–39 | NOT IMPLEMENTED | authorized manual purge/restore and protected audit checks |
| SEO metadata, crawl controls, redirects and sitemap | 10–11, 49–50, 66, 70 | PARTIAL / UNVERIFIED | sitemap, robots and canonical now implemented behind explicit approval; redirects, crawler and search-route checks remain |
| Lead submission and durable outbox/CRM delivery | 20–23, 40, 69 | NOT IMPLEMENTED | committed receipt + outbox retry/crash and reconciliation tests |
| Privacy, consent-aware visitor and UTM events | 14–18, 35–37, 59, 72 | NOT IMPLEMENTED | consent-denial, revocation, retention and identity separation tests |
| Marketing automation, scoring, experiments, ads | 12–13, 19, 34, 43, 45–56, 67–71, 77 | NOT IMPLEMENTED | approved-provider sandbox tests + quality/goal reconciliation |
| Security, identity, immutable audit, recovery | 24, 28–30, 39, 57–60, 74 | NOT IMPLEMENTED | threat, authorization, backup restore and incident drills |
| Specialized commerce/booking/etc. | 25–26, 54, 61, 75 | NOT ACTIVATED | explicit site brief + complete transaction lifecycle |
| Final launch acceptance | 64, 77–78, Appendices N–P | BLOCKED | requirement-to-test traceability, measured signoff and production evidence |

Status labels distinguish **documented**, **implemented**, **activated** and **verified** as required by Appendix P. No unexecuted check is called passing.

## Work sequence

1. Confirm Appendix A brief and site-specific activation catalogue; preserve Chat baseline commit and existing CI.
2. Complete public templates, real reviewed content, content rendering adapter, navigation, responsive/accessibility tests.
3. Implement PostgreSQL-backed owned CMS with owner/editor approvals, published revisions, audit, media, manual-only trash/purge, and invalidation.
4. Build form builder and reliable lead API with atomic transaction/outbox, idempotency, protected views and integration status.
5. Implement consent policy, privacy rights, events/UTMs/attribution, controlled visitor context, and authorized chatbot handoff.
6. Add SEO sitemap/robots/redirect controls, campaign pages, experimentation, reporting and activated provider adapters.
7. Add operations, protection, end-to-end tests, cost/runbooks, backup/restore drills, and Appendix N/P release evidence.

**Prohibited launch states:** falsely acknowledged leads, unauthorized access, prohibited tracking, leaked secrets, broken conversion journeys, untested recovery (chapter 01). Maintain remaining gaps openly.

## Second checkpoint — explicit SEO safety and public error routes

Added website-local `robots.ts`, `sitemap.ts`, `seo.ts`, `not-found.tsx`, `error.tsx`, and `loading.tsx`. Indexing requires **HTTPS, a non-local site URL and NEXT_PUBLIC_SITE_APPROVED=true**. Legal placeholders stay noindex and outside the sitemap. Canonical URLs are provided per public route. These are implementation claims only: a successful production build, crawler validation, keyboard review, browser checks, and live indexability signoff have **not** been established. The company-specific pages are still intentionally placeholders; this is not production launch clearance.

No `main` branch files were modified by this work.
