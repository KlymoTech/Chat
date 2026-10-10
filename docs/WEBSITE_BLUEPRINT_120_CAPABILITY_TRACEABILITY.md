# Website Master Blueprint v1.3 — 120-capability traceability

**Source:** uploaded Website Master Blueprint v1.3 (7 October 2026), Appendix H pages 213–219. CAP-001 through CAP-120 are preserved. This is a tracking artifact, **not an implementation certificate**.

**Branch:** `feature/website-blueprint-v1-3-20261010`; do not merge into main without explicit approval.

## Scope and release rules

- User requests implementation of **all 120 documented capabilities**, including industry-conditional examples and growth capabilities, without silently dropping requirements.
- **Building code, activating a provider, and verifying behavior are separate states.** Live activation may require the owner's credentials, lawful-basis decisions, provider approval, budgets and a site-specific brief. These prerequisites do not make a requirement "done".
- Treat all entries as **not verified** until frontend, backend, persistence, permissions, failures, integration tests, owner operation, and actual evidence have been checked.
- Class labels are copied from the blueprint: **F** universal foundation, **G** comprehensive growth, **B** business-specific, and conditional F/B variants.
- Never use fake testimonials, conversions, ROI, rankings, provider delivery, or test-success claims. Content preservation/manual purge requirements remain release-blocking.
- Record evidence links (CI runs, tests, manual acceptance, configuration, and signed release decisions) per capability before marking verified.

| ID | Blueprint capability / control | Class | Chapters | Current evidence locator (not a pass) | Verification |
|---|---|---|---|---|---|
| CAP-001 | Business brief, audience, outcomes, evidence and scope | F | 02, 42, 43 | No capability-specific verification evidence assigned | **Not verified** |
| CAP-002 | Sitemap, navigation, page/route families and customer journeys | F | 04, 50 | No capability-specific verification evidence assigned | **Not verified** |
| CAP-003 | Responsive design, semantic HTML, design tokens and accessible components | F | 05, 06, 44 | No capability-specific verification evidence assigned | **Not verified** |
| CAP-004 | CMS, page/section builder, navigation, forms and media ownership | F | 07–09, 44 | Existing CMS builder/edit/archive/import/export plus article authoring and public index (partial; not tested) | **Not verified** |
| CAP-005 | Autosave, draft recovery, undo/redo and edit conflict resolution | F | 44 | Existing CMS uses 3s version-checked autosave, bounded undo/redo, loss-protection, readable 409 comparison, local export or independent recovery draft via existing import route; tests committed; no verified offline/local-storage policy | **Not verified** |
| CAP-006 | Collection/schema builder with approved fields and templates | G | 44, 63 | No capability-specific verification evidence assigned | **Not verified** |
| CAP-007 | Editorial review, revisions, previews, scheduling and releases | F | 08, 44 | Existing editorial API extended with manual archive, restore, change requests; live revision stays available while draft edited (partial; tests committed) | **Not verified** |
| CAP-008 | Import/export, dry runs, manifests, partial failures and migration | F | 44, 62 | No capability-specific verification evidence assigned | **Not verified** |
| CAP-009 | Manual-only blog retention, no-expiry trash and controlled purge | F | 09, 38 | Blog articles use CMS immutable revisions; manual-only trash and protected purge still absent | **Not verified** |
| CAP-010 | Media rights, quarantine, derivatives, alt text and private downloads | F | 08, 09, 50 | No capability-specific verification evidence assigned | **Not verified** |
| CAP-011 | Technical SEO status/rendering/canonical/index policy | F | 10, 50 | Page SEO schema/editor/HTML metadata (partial) | **Not verified** |
| CAP-012 | Sitemaps, feeds, pagination, faceting and crawl trap controls | F | 10, 50 | Published sitemap, blog pagination and category filter code; feeds/faceting/crawl controls pending | **Not verified** |
| CAP-013 | Structured-data registry and truthful rich-result eligibility | F | 10, 50 | No capability-specific verification evidence assigned | **Not verified** |
| CAP-014 | Search-intent map, editorial calendar and internal linking | G | 11, 43, 49 | No capability-specific verification evidence assigned | **Not verified** |
| CAP-015 | Local profiles, real branch/service-area pages and reputation | B | 11, 49, 57 | No capability-specific verification evidence assigned | **Not verified** |
| CAP-016 | Image/video/news/job/AI search-surface policies | B | 49, 50, 61 | No capability-specific verification evidence assigned | **Not verified** |
| CAP-017 | Locale routes, translations, hreflang and support readiness | B | 10, 26, 49, 61 | No capability-specific verification evidence assigned | **Not verified** |
| CAP-018 | Search Console ownership, data extraction and search diagnostics | G | 10, 49, 55 | No capability-specific verification evidence assigned | **Not verified** |
| CAP-019 | Offer/claim registry, pricing consistency and campaign calendar | G | 43 | No capability-specific verification evidence assigned | **Not verified** |
| CAP-020 | Creative library, asset rights, approved copy and social previews | G | 43, 51, 52 | No capability-specific verification evidence assigned | **Not verified** |
| CAP-021 | Google Ads readiness, ownership, policies and destinations | G | 12, 51 | No capability-specific verification evidence assigned | **Not verified** |
| CAP-022 | Google Ads goals, enhanced/offline feedback and supported ingestion | G | 12, 16, 51 | No capability-specific verification evidence assigned | **Not verified** |
| CAP-023 | Google campaign strategy, keywords/negatives, bidding and experiments | G | 51 | No capability-specific verification evidence assigned | **Not verified** |
| CAP-024 | Automated ad text/URL features with review and exclusions | B | 51, 53 | No capability-specific verification evidence assigned | **Not verified** |
| CAP-025 | Meta account/assets, category review, creative and destinations | G | 13, 52 | No capability-specific verification evidence assigned | **Not verified** |
| CAP-026 | Meta Pixel/CAPI mapping, deduplication and sensitive- data controls | G | 13, 16, 52 | No capability-specific verification evidence assigned | **Not verified** |
| CAP-027 | Google/Meta native lead-form ingestion and honest provenance | B | 51, 52 | No capability-specific verification evidence assigned | **Not verified** |
| CAP-028 | Advertising audience eligibility, synchronization and removal | G | 46, 53 | No capability-specific verification evidence assigned | **Not verified** |
| CAP-029 | Campaign creation/budget/targeting API writes | B | 51–53, 63 | No capability-specific verification evidence assigned | **Not verified** |
| CAP-030 | UTM/click-ID campaign builder and attribution snapshots | G | 18, 35 | Validated UTM API and owner link-builder screen (partial) | **Not verified** |
| CAP-031 | Frontend dataLayer/SDK, page/section/form/resource events | F | 14–16 | Consent-gated page/CTA event collector and client (partial) | **Not verified** |
| CAP-032 | Trusted conversion outbox, retries, correction and reconciliation | F | 16, 18 | No capability-specific verification evidence assigned | **Not verified** |
| CAP-033 | A/B/n assignment, exposure, statistical validity and promotion | G | 19, 34 | No capability-specific verification evidence assigned | **Not verified** |
| CAP-034 | Consent-aware heatmaps and session replay | B | 19, 56 | No capability-specific verification evidence assigned | **Not verified** |
| CAP-035 | Controlled IP/coarse location, trusted proxy handling | G | 36 | No capability-specific verification evidence assigned | **Not verified** |
| CAP-036 | Explicit browser location task, accuracy/provenance and fallback | G | 36, 37 | No capability-specific verification evidence assigned | **Not verified** |
| CAP-037 | Contextual chatbot, explicit capture, knowledge safety and human handoff | G | 26, 37 | No capability-specific verification evidence assigned | **Not verified** |
| CAP-038 | Form builder, server validation, idempotency and accessible errors | F | 20 | No capability-specific verification evidence assigned | **Not verified** |
| CAP-039 | CRM stages, routing, notes, qualification, merge/correction and escalation | G | 18, 20 | Existing CRM modules (not audited) | **Not verified** |
| CAP-040 | Visual marketing automation, timers, dispatch gates and simulations | G | 45 | No capability-specific verification evidence assigned | **Not verified** |
| CAP-041 | Explainable scoring, overrides and qualified-lead separation | G | 46 | No capability-specific verification evidence assigned | **Not verified** |
| CAP-042 | Segment builder and purpose-limited personalization | G | 46 | No capability-specific verification evidence assigned | **Not verified** |
| CAP-043 | Email sender authentication and deliverability monitoring | F when email | 20, 47 | No capability-specific verification evidence assigned | **Not verified** |
| CAP-044 | Subscription preferences, one-click unsubscribe and suppression | F when | 47, 59 | No capability-specific verification evidence assigned | **Not verified** |
| CAP-045 | Unified inbox, agent assignments, channel identity and delivery states | G | 37, 48 | No capability-specific verification evidence assigned | **Not verified** |
| CAP-046 | WhatsApp/SMS/Telegram adapters and channel-specific permissions | B | 48 | No capability-specific verification evidence assigned | **Not verified** |
| CAP-047 | Call outcomes, dynamic-number attribution, recording/transcription | B | 48 | No capability-specific verification evidence assigned | **Not verified** |
| CAP-048 | QR, offline/partner campaigns and declared-source attribution | G | 35, 48 | No capability-specific verification evidence assigned | **Not verified** |
| CAP-049 | Feedback/surveys, calculators/quizzes and governed lead magnets | G | 56 | No capability-specific verification evidence assigned | **Not verified** |
| CAP-050 | Popups/announcements/sticky CTAs with accessibility and frequency controls | G | 05, 56 | No capability-specific verification evidence assigned | **Not verified** |
| CAP-051 | Reporting/warehouse, metrics, spend, freshness and reconciliation | G | 19, 55 | No capability-specific verification evidence assigned | **Not verified** |
| CAP-052 | Scheduled reports and permission-safe exports | G | 55 | No capability-specific verification evidence assigned | **Not verified** |
| CAP-053 | Incrementality, lift, marketing-mix and predictive-value analysis | B | 34, 55 | No capability-specific verification evidence assigned | **Not verified** |
| CAP-054 | Domain/registrar/DNS/TLS ownership, renewal and recovery | F | 28, 32, 57 | No capability-specific verification evidence assigned | **Not verified** |
| CAP-055 | Authentication, staff MFA, scoped roles, sessions and recovery | F | 24, 58 | Existing authentication routes and MFA code (not audited) | **Not verified** |
| CAP-056 | Enterprise SSO/provisioning and organization roles | B | 58, 61 | No capability-specific verification evidence assigned | **Not verified** |
| CAP-057 | API/tenant/object security, uploads, SSRF, CSRF and injection controls | F | 23, 24, 58 | No capability-specific verification evidence assigned | **Not verified** |
| CAP-058 | Third-party scripts/tags/CSP, consent and performance governance | F | 15, 58 | No capability-specific verification evidence assigned | **Not verified** |
| CAP-059 | Supply chain, SBOM, licensing, patching and CI secrets | F | 27, 58 | No capability-specific verification evidence assigned | **Not verified** |
| CAP-060 | Abuse/fake leads, message/OTP budgets, referral/transaction fraud | F | 20, 58 | No capability-specific verification evidence assigned | **Not verified** |
| CAP-061 | Data inventory, purpose/consent policy engine, GPC where applicable | F | 17, 59 | Consent policy/API, preference page, receipts (partial) | **Not verified** |
| CAP-062 | Rights requests, retention, holds, processor deletion and restore reconciliation | F | 17, 38, 59 | No capability-specific verification evidence assigned | **Not verified** |
| CAP-063 | Children/sensitive-business and jurisdiction activation review | F | 02, 59, 61 | No capability-specific verification evidence assigned | **Not verified** |
| CAP-064 | Protected comprehensive audit, actor attribution and integrity | F | 39 | CMS audit for create, import, duplicate, review, publication, archive and restore (partial; integrity not certified) | **Not verified** |
| CAP-065 | PostgreSQL constraints, migrations, pooling, indexes and analytical isolation | F | 22, 60, 63 | Additive migrations 0079–0081 (not migration-tested) | **Not verified** |
| CAP-066 | Object storage/CDN, private media, caching and invalidation | F | 06, 08, 28, 60 | No capability-specific verification evidence assigned | **Not verified** |
| CAP-067 | REST/OpenAPI and versioned events | F | 23, 62, 63 | FastAPI API routers and validation (partial) | **Not verified** |
| CAP-068 | GraphQL, SOAP, streaming and legacy/file adapters | B | 23, 62 | No capability-specific verification evidence assigned | **Not verified** |
| CAP-069 | Durable workers, timers, outbox, retries and idempotent external effects | F | 16, 21, 45, 60 | Publication outbox and worker infrastructure (not verified) | **Not verified** |
| CAP-070 | Native/Docker deployment; optional managed/Kubernetes profiles | F | 28, 60 | No capability-specific verification evidence assigned | **Not verified** |
| CAP-071 | Terraform/state/secrets, protected releases and rollback | F capability | 28, 29, 60 | No capability-specific verification evidence assigned | **Not verified** |
| CAP-072 | Monitoring/alerts, service objectives, incident response and status communication | F | 29, 60 | No capability-specific verification evidence assigned | **Not verified** |
| CAP-073 | Backups/PITR, recovery drills, deletion ledgers and independent copies | F | 29, 38, 60 | No capability-specific verification evidence assigned | **Not verified** |
| CAP-074 | Feature flags, extension manifests, tenant/domain isolation | F for selected | 02, 62 | No capability-specific verification evidence assigned | **Not verified** |
| CAP-075 | Commerce/products/inventory/checkout/payments/ returns/feeds | B | 25, 54, 61 | No capability-specific verification evidence assigned | **Not verified** |
| CAP-076 | Bookings/events/webinars/waitlists and verified attendance | B | 25, 48, 61 | No capability-specific verification evidence assigned | **Not verified** |
| CAP-077 | Courses/memberships/student/guardian workflows | B | 25, 59, 61 | No capability-specific verification evidence assigned | **Not verified** |
| CAP-078 | SaaS/subscriptions/usage/entitlements and customer portal | B | 25, 54, 61 | No capability-specific verification evidence assigned | **Not verified** |
| CAP-079 | B2B quotes/organizations/partners/franchises | B | 61, 62 | No capability-specific verification evidence assigned | **Not verified** |
| CAP-080 | Directories/marketplaces/sellers/payouts/disputes | B | 61 | No capability-specific verification evidence assigned | **Not verified** |
| CAP-081 | Referrals/affiliates/loyalty/gift cards/credits | B | 54, 61 | No capability-specific verification evidence assigned | **Not verified** |
| CAP-082 | News/media/RSS/paywalls/publisher advertising/sponsorship | B | 50, 61 | No capability-specific verification evidence assigned | **Not verified** |
| CAP-083 | Community/comments/reviews/moderation/appeals | B | 09, 43, 61 | No capability-specific verification evidence assigned | **Not verified** |
| CAP-084 | Careers/applications and private candidate records | B | 50, 61 | No capability-specific verification evidence assigned | **Not verified** |
| CAP-085 | Donations/fundraising and recurring cancellation | B | 54, 61 | No capability-specific verification evidence assigned | **Not verified** |
| CAP-086 | Healthcare/finance/legal/housing/travel/public-sector profiles | B | 59, 61 | No capability-specific verification evidence assigned | **Not verified** |
| CAP-087 | PWA/offline/push/device permissions and accessible fallback | B | 26, 61 | No capability-specific verification evidence assigned | **Not verified** |
| CAP-088 | Search relevance and approved AI retrieval/index rebuild | B/G by profile | 26, 37, 62 | No capability-specific verification evidence assigned | **Not verified** |
| CAP-089 | Owner handover, second-team portability and secure account transfer | F | 32, 62, 65 | No capability-specific verification evidence assigned | **Not verified** |
| CAP-090 | Master test evidence, launch gates, costs and living- standard review | F | 30, 42, 64, 65 | Branch CI configured; GitHub checks failing | **Not verified** |
| CAP-091 | Current search-surface eligibility and settings register | G | 66 | No capability-specific verification evidence assigned | **Not verified** |
| CAP-092 | Generative-search reporting and source-grain limitations | G | 66 | No capability-specific verification evidence assigned | **Not verified** |
| CAP-093 | Preferred-source and regional discovery eligibility | B | 66 | No capability-specific verification evidence assigned | **Not verified** |
| CAP-094 | Other-engine change notification and IndexNow adapter | B | 66 | No capability-specific verification evidence assigned | **Not verified** |
| CAP-095 | AI-generated media/data provenance preservation | F when used | 66 | No capability-specific verification evidence assigned | **Not verified** |
| CAP-096 | Agent-compatible and delegated-action interface controls | B | 66, 75 | No capability-specific verification evidence assigned | **Not verified** |
| CAP-097 | Google top/absolute-top visibility and economics | G | 67 | No capability-specific verification evidence assigned | **Not verified** |
| CAP-098 | Effective campaign goal/custom-goal resolution | G | 67, 69 | No capability-specific verification evidence assigned | **Not verified** |
| CAP-099 | Automated ad destination and claim expansion review | G | 67, 68 | No capability-specific verification evidence assigned | **Not verified** |
| CAP-100 | Cross-campaign budget authority and remote uncertainty | G | 67, 77 | No capability-specific verification evidence assigned | **Not verified** |
| CAP-101 | Meta creative concepts, rights, variants and approvals | G | 68 | No capability-specific verification evidence assigned | **Not verified** |
| CAP-102 | Native lead/messaging/web provenance separation | G | 68, 69 | No capability-specific verification evidence assigned | **Not verified** |
| CAP-103 | Provider ingestion and authentication migration register | G | 69 | No capability-specific verification evidence assigned | **Not verified** |
| CAP-104 | Post-SDK serialization data-policy enforcement | F when used | 69 | Strict frontend event allowlist (partial) | **Not verified** |
| CAP-105 | Destination-specific normalization and late-event contracts | G | 69 | No capability-specific verification evidence assigned | **Not verified** |
| CAP-106 | CDN/streamed response status and canonical integrity | F | 70 | No capability-specific verification evidence assigned | **Not verified** |
| CAP-107 | robots and discovery infrastructure failure monitoring | F | 70 | No capability-specific verification evidence assigned | **Not verified** |
| CAP-108 | Complex URL/resource/migration dependency tests | F | 70 | No capability-specific verification evidence assigned | **Not verified** |
| CAP-109 | Cross-channel offers, proof and lifecycle consistency | G | 71 | No capability-specific verification evidence assigned | **Not verified** |
| CAP-110 | Acquisition contribution and mature-cohort decisions | G | 67, 71 | No capability-specific verification evidence assigned | **Not verified** |
| CAP-111 | Prerender/prefetch/activation measurement separation | F when used | 72 | No capability-specific verification evidence assigned | **Not verified** |
| CAP-112 | Back/forward restoration and sensitive-state refresh | F | 72 | No capability-specific verification evidence assigned | **Not verified** |
| CAP-113 | Hidden-tab exposure and engagement timing | F | 72 | No capability-specific verification evidence assigned | **Not verified** |
| CAP-114 | Cross-tab consent and revoked queued context | F | 72 | No capability-specific verification evidence assigned | **Not verified** |
| CAP-115 | Scanner/synthetic/internal traffic classification | F | 72 | No capability-specific verification evidence assigned | **Not verified** |
| CAP-116 | Second-operator CMS/accessibility completion | F | 73 | No capability-specific verification evidence assigned | **Not verified** |
| CAP-117 | Key/account-loss and post-restore external-effect control | F | 74 | No capability-specific verification evidence assigned | **Not verified** |
| CAP-118 | Expanded specialist transaction completion packs | B | 75 | No capability-specific verification evidence assigned | **Not verified** |
| CAP-119 | Paid-traffic preflight and 90-day operating evidence | G | 77 | No capability-specific verification evidence assigned | **Not verified** |
| CAP-120 | Final merge, five-dimensional status and release sign-off | F | 78, M–P | This register and existing release ledger; final sign-off pending | **Not verified** |

## Required workflow for each CAP entry

1. Map the user journey, owner role, and frontend route.
2. Implement server validation, authorization, durability, and idempotency.
3. Configure consent, accessibility, privacy rights, recoverability, and observability.
4. Run unit/integration/browser E2E tests, negative tests and environment checks.
5. Attach measured evidence and assign separate implementation, activation, and verified states.
6. Have a human owner approve activation/sign-off; never quietly label a blocked provider as complete.

Last automated cross-system checks on the dedicated branch were **failing or unavailable**. This table deliberately records no capability as release-verified until trustworthy tests and owner acceptance succeed.
