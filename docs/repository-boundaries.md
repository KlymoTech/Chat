# Repository boundaries and naming

The repository uses capability-owned folders. Administrative scopes are kept
separate from customer-facing website code:

```text
frontend/src/features/
├── admin/             # authenticated tenant/workspace administration boundary
├── platform-admin/    # SaaS-owner / super-admin control plane
├── website/           # public website, login, invitations, and widget entrypoints
├── workspace/         # workspace-owned settings and conversations
├── branding/          # white-label identity, domains, email, widget, and versions
└── whatsapp/          # WhatsApp connection, message, webhook, and status capabilities

backend/src/northstar_api/modules/
├── admin/             # tenant/workspace administration namespace
├── platform_admin/    # platform-owner permissions and control plane
├── website/           # unauthenticated public boundary
├── workspace/         # workspace-owned domain and settings
└── branding/          # white-label domain and publication services
```

Website page implementations live under `frontend/src/features/website/pages`
and the platform control-plane implementation lives under
`frontend/src/features/platform-admin`. The old files in `frontend/src/pages`
and `backend/src/northstar_api/routers` remain thin compatibility adapters
during the staged migration. New production imports should enter via the
feature/module boundary, and files must name one responsibility (for example
`WorkspaceMembersSettings.tsx`, not `helpers.ts` or `service.ts`).

`admin` is not `platform-admin`: tenant administrators operate inside a
workspace/tenant scope, while platform administrators use a separate global
permission boundary and support-session flow.
