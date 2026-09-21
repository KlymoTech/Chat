# Workspace Settings & Branding — Items 1–22

This document describes the workspace-owned implementation delivered on the `workspace-1-22` branch. It intentionally preserves the existing application pipelines and does not implement the platform-admin / post-22 reorganization owned by the next phase.

## Scope and compatibility

- Existing `/workspace` and `/workspace/white-label` behavior remains available.
- The new settings center lives under `/workspace/settings/:section`.
- Existing invitations, workspace membership, API keys, MFA, billing, audit, channels, CRM/integrations, notifications, widget, email and authentication services are reused rather than replaced.
- Platform-admin code is intentionally not part of this change.
- Workspace settings are additive and are stored under the existing workspace-scoped configuration document (`settings_json.workspaceSettingsV2`) with legacy branding compatibility retained in `branding_json`.
- No existing feature file is intentionally deleted by this implementation.

## Frontend routes

| Route | Purpose |
| --- | --- |
| `/workspace/settings/general` | Workspace identity, locale and business hours |
| `/workspace/settings/members` | Members, invitations and lifecycle |
| `/workspace/settings/roles` | Built-in/custom roles and resource scopes |
| `/workspace/settings/teams` | Workspace team configuration |
| `/workspace/settings/security` | Enforced workspace security policies |
| `/workspace/settings/notifications` | Workspace notification controls |
| `/workspace/settings/channels` | Entry into the existing channel pipeline |
| `/workspace/settings/integrations` | Entry into the existing integrations pipeline |
| `/workspace/settings/developer` | API keys and developer policy |
| `/workspace/settings/audit` | Entry into the existing audit log |
| `/workspace/settings/billing` | Existing workspace billing/usage surface |
| `/workspace/settings/branding` | White-label control center |

Navigation and direct-route rendering are filtered by the active workspace permission set.

## Backend module boundary

Workspace-specific additions live in `backend/src/northstar_api/modules/workspace/`:

- `settings.py` — general/security/notifications/developer settings endpoints
- `general.py` — workspace/organization/owner metadata
- `members.py` / `member_state.py` — lifecycle operations layered over existing membership/invitation services
- `access.py` — custom roles, teams and dashboard configuration validation
- `security_policy.py` — workspace security enforcement helpers
- `api_key_scopes.py` — allowed API-key capability expansion
- `branding.py` — white-label draft/publish/version/domain/runtime endpoints
- `brand_cache.py` — published-brand cache and invalidation
- `domain_resolution.py` — public custom-domain workspace resolution
- `email_branding.py` / `email_routes.py` — workspace template rendering, preview/test and delivery helpers
- `conversation_assignment_model.py` / `conversation_assignments.py` / `conversation_scope.py` — assigned-conversation resource scope
- `contracts.py` — validated workspace-owned contracts
- `store.py` — compatibility storage, auditing and outbox integration

The module is included alongside, not instead of, the legacy workspace routers.

## Core API surface

All authenticated routes below require the existing workspace header/context and normal bearer authentication.

### Settings

- `GET /workspace/settings`
- `GET /workspace/settings/capabilities`
- `GET /workspace/settings/general/metadata`
- `PATCH /workspace/settings/general`
- `PATCH /workspace/settings/security`
- `PATCH /workspace/settings/notifications`
- `PATCH /workspace/settings/developer`
- `PATCH /workspace/settings/roles`
- `PATCH /workspace/settings/teams`
- `PATCH /workspace/settings/dashboard`

### Conversation resource assignment

- `GET /workspace/settings/conversation-assignments/{conversation_id}`
- `PUT /workspace/settings/conversation-assignments/{conversation_id}`
- `DELETE /workspace/settings/conversation-assignments/{conversation_id}`

Assignment writes require `conversations.assign`. User/team references are validated inside the same tenant/workspace. Custom-role conversation scope is enforced as follows:

- `all` — no additional conversation filter beyond existing workspace/agent scope.
- `team` — conversation visibility is narrowed through the agents owned by teams in which the user is a member/manager.
- `assigned` — Conversation ORM reads on that request-scoped SQLAlchemy session are limited to conversations assigned to the current user.

If multiple custom roles are assigned, the broader `all`/`team` scope prevents an `assigned` role from unexpectedly narrowing a broader role grant.

### Branding

- `GET /workspace/settings/branding`
- `GET /workspace/settings/runtime-branding`
- `PATCH /workspace/settings/branding/draft`
- `POST /workspace/settings/branding/publish`
- `POST /workspace/settings/branding/rollback`
- `POST /workspace/settings/branding/email/preview`
- `POST /workspace/settings/branding/email/test`
- `POST /workspace/settings/domains`
- `POST /workspace/settings/domains/{domain_id}/verification-start`
- `POST /workspace/settings/domains/{domain_id}/activation-check`
- `POST /workspace/settings/domains/{domain_id}/disable`

Public pre-auth brand discovery is exposed separately at `GET /branding/public?hostname=...`; it returns only safe published public brand data and does not require authentication.

## General settings

The new General section preserves the existing workspace name/slug/preferences pipeline and adds validated workspace-owned configuration for:

- industry and country
- 12/24-hour time format
- currency and week start
- description and workspace icon
- enabled business hours, timezone and daily ranges
- read-only workspace ID, organization, status and owner metadata

Business-hour ranges are validated server-side and use explicit timezone configuration.

## Members and invitations

The implementation reuses the existing invitation and membership services. The UI supports:

- invite
- resend invitation
- revoke/cancel invitation
- change built-in workspace role
- all-agent or selected-agent resource access
- remove member
- suspend/reactivate member
- MFA/last-active lifecycle visibility
- ownership transfer

Team membership is managed by the Teams section so there is one team configuration source of truth.

All administrative lifecycle changes remain workspace scoped and audited.

## Roles and permissions

Built-in workspace roles remain backed by the canonical `access_policy.py` grants. Custom roles are additive and may only contain registered workspace permissions. Server validation prevents an administrator from delegating permissions the administrator does not hold.

Custom roles support:

- permission capability selection
- selected-agent restriction
- assigned/team/all conversation scope
- assignment of custom roles to workspace members

Unknown permissions, out-of-workspace members/agents, duplicate role IDs and unknown role references are rejected server-side.

## Teams

Teams are stored in workspace configuration and support:

- members and managers
- custom role references
- queue IDs
- agent ownership
- channel IDs
- business hours/timezone
- routing/escalation description

Server validation enforces unique team IDs/names, workspace-local members/agents, manager membership, and known custom-role references. Team conversation scope reuses team-owned agent boundaries instead of creating a second conversation data model.

## Security

Only security controls with a real backend enforcement path are exposed. Current enforced controls include:

- MFA policy (`optional`, administrators, or all members)
- access/session timeout policy
- workspace minimum password length where workspace-aware password validation is performed
- IPv4/IPv6 allow and deny CIDR lists
- trusted invitation email domains
- suspended member blocking
- sensitive-data masking compatibility setting
- webhook signing/security policy configuration
- security notification configuration

Existing MFA services are reused. SSO/SCIM switches are intentionally not fabricated because this repository does not currently contain a workspace identity-provider/SCIM provisioning model; adding nonfunctional settings would violate the security requirements.

## Notifications

Workspace notification settings are persisted and consumed by the existing notification service category checks for member/security/billing/channel/integration categories and digest recipients.

## Developer settings and API keys

Workspace API keys remain in the existing API-key pipeline and now persist explicit scopes. Service permissions are intersected with the key scopes so keys cannot become unrestricted through the frontend.

Developer settings also store workspace policy for sandbox mode, webhook signing, event subscriptions, rate limit, request-log retention and webhook retry count. OAuth/webhook endpoint management continues through the existing integration pipeline rather than being duplicated under Settings.

## White label

### Draft / publish model

Edits update `brandingDraft` only. Publishing:

1. validates plan entitlements,
2. creates the next immutable brand version,
3. copies the draft to published state,
4. updates the legacy published identity compatibility payload,
5. commits the workspace transaction,
6. invalidates workspace/domain/version cache entries,
7. records the audit/outbox event.

Rollback copies a historical version into a new draft and publishes it as a new version; historical records are not edited in place.

### Brand surfaces

The control center supports:

- identity assets: company/product identity, primary/secondary identity, logo/favicon/app icon plus extended assets
- extended design-token colors
- typography and font weights
- dashboard appearance and navigation configuration
- dashboard widget layout/builder
- branded public authentication
- editable email templates, preview and test delivery
- website chat-widget branding
- custom domains
- version history and rollback

Arbitrary customer CSS is intentionally not accepted; the product uses validated design tokens.

### Dashboard runtime

Published dashboard layout is configuration data (`x`, `y`, `width`, `height`, visibility, audience and widget config). The published runtime supports the selectable widget catalog, including welcome, KPI cards, conversation summary/trend, lead summary/status trend, channel health, agent activity, CRM, education, quick actions, announcements and usage.

The legacy dashboard remains the fallback when branded-dashboard publication is disabled or no configured widgets are published.

### Public authentication branding

Brand lookup happens before authentication by hostname. Only an active server-verified custom domain can resolve workspace public branding. The public payload contains only safe published brand fields used by login/signup/forgot/reset/MFA surfaces. Normal platform-host behavior remains unchanged.

### Custom-domain lifecycle

1. workspace admin creates a hostname record;
2. server issues a TXT verification name/value;
3. server queries DNS to confirm the TXT value;
4. successful ownership moves the record to `verified`;
5. activation performs a public-address check and a valid HTTPS request to the branding health endpoint;
6. only a successful HTTPS/TLS check moves the domain to `active`;
7. a domain can be explicitly disabled.

The frontend cannot directly mark a domain verified or active.

### Branded email

Published branded email templates support invitation, password-reset, verification, security, billing, conversation, lead and education categories. Templates are HTML-escaped during rendering. Test delivery uses the existing configured mail transport; production log-only mode is rejected instead of silently pretending delivery occurred.

Workspace invitations use the published workspace brand. Password reset/email verification use workspace branding only when the request hostname resolves to an active workspace custom domain, avoiding arbitrary workspace selection for multi-workspace accounts. Action links preserve their path/query/fragment while switching to the active branded host.

### Chat widget

The existing widget bootstrap is extended with published workspace widget configuration while preserving per-agent behavior as the base. Published workspace fields include launcher, colors, logo/avatar, header/greeting, font, privacy URL, powered-by behavior, business hours and offline message. Unconfigured workspaces continue to receive the existing agent/widget presentation.

## Caching and audit

Published brands are cached by workspace/domain/version. Publishing, rollback, domain create/verify/activate/disable invalidate affected keys after the database transaction. Administrative settings writes use the existing audit/outbox pipeline; sensitive audit values are redacted by the shared audit implementation.

## Database migrations

- `0055_workspace_brand_domain_resolver.py` — public active-domain resolver used before authentication.
- `0056_workspace_api_key_scopes.py` — persisted workspace API-key scopes with compatibility defaults.
- `0057_workspace_conversation_assignments.py` — additive tenant/workspace keyed conversation assignment table.

These migrations extend current behavior and do not remove existing workspace data.

## Validation and tests

Focused regression coverage on this branch includes workspace settings API behavior, general settings contracts, policy validation, role/team/assigned conversation semantics, branded email/domain behavior, and public-brand bootstrap behavior.

GitHub Actions should remain the authoritative full lint/type/test/security gate. At the time this branch was prepared, repository Actions jobs were being created but terminated before any workflow step executed; that infrastructure condition must not be interpreted as either a test pass or a code-test failure.

## Explicitly outside this branch

This branch does not implement the next-phase backend module layout beginning at item 23, the WhatsApp domain reorganization that follows it, or platform-admin/super-admin control-plane work. Those remain separate ownership areas and should be integrated independently after this workspace branch.
