# Leads — user-supplied design export implementation

Branch: `feat/figma-saas-bot-redesign`. Draft PR: #134. Main is not merged or deployed.

## Source and scope

The user supplied `Leads.pdf` and `chat bot.zip`. The ZIP's `lead` directory contains the Leads Overview, contact drawer, Schedule Follow-up, Assign Lead, Change Lead Status, Sync Lead to Connected CRM and conversation-transcript references. Other directories contain Overview, agent-creation, Conversations and Education references. These exports are the visual source; implementation is native React/TypeScript/CSS, not screenshots embedded as UI.

This increment implements the Leads list and contact drawer, status-change, assignment, follow-up and CRM configuration-review dialogs. It retains existing saved column layouts, field editing, Excel export, lifecycle/status services, CRM routing and delivery-attempt evidence. The transcript action opens the existing authorized conversation screen; the separate exported transcript composition is not reconstructed in this increment. Other ZIP surfaces are still pending.

## Real data and preserved behavior

Summary counts come from the selected workspace and permitted agents, not a paginated list or the design's sample numbers. Search, status, agent and channel filters are applied by the server. CSV/Excel exports include all matching rows and preserve saved column layouts. An API outage displays an error and retry, not demo records. Missing contact/source details are explicitly shown as missing. Manual contact consent defaults to false.

The original Leads APIs remain in use. New additive workspace endpoints provide exact summary counts, persistent lead ownership, follow-up records and status-change notes. A dedicated `lead_workspace_operations` table separates operational bookkeeping from custom lead fields sent to external CRM systems. Migration `0079_lead_workspace_operations` follows `0078_source_retrieval_mode`; apply it through the normal deployment migration process before enabling the new UI in a deployed environment.

Writes require the existing `leads.update` permission and scope every lookup to tenant, workspace and permitted agent. Assignment targets must be active, non-suspended workspace members or eligible teams. Assignment and follow-up writes lock the lead and enforce an operation-version check. Follow-up creation has a client request UUID for replay safety and validates future timezone-aware dates. Changes record audit events. The old manual-create route now also enforces the principal's agent restriction.

## Explicit functional boundaries

- Follow-ups are persisted workspace records with a real downloadable calendar reminder. They do not automatically send email/WhatsApp messages or create a CRM activity.
- The CRM dialog previews actual connected CRM mappings. Its sync action uses existing workspace routing and duplicate-handling rules; selecting a preview card does not override routing.
- Queued, provider-acknowledged and read-back-verified delivery are presented as distinct states. No fake external record, uptime, availability or customer-telemetry values are inserted.
- Additional controls absent from the exported default table remain available to preserve existing functionality. Backend-unsupported labels such as automatic reminder dispatch are not represented as implemented features.

## Verification

Before pushing this increment, the local frontend typecheck and production build passed. Fourteen focused Leads tests passed, and targeted frontend lint passed. Local backend execution was unavailable because its full Python dependencies were not installed; backend success is not inferred from frontend tests.

The read-only `Leads design export regression` workflow runs a clean install/build, focused frontend tests, real FastAPI/SQLite tests, records the migration head and opens the non-demo frontend against a disposable local API/database. It exercises login, lead listing, state changes, durable ownership, follow-up persistence/calendar download, manual capture, filtered CSV and workspace isolation. It blocks external browser traffic and does not use production credentials or paid providers.

Review the exact source SHA, job outcomes, JUnit reports and captured screenshots before accepting this increment. A configured check is not a passing result. PostgreSQL migrations, production worker topology, external CRM/provider delivery and the repository's full release/security gates are separate acceptance requirements.
