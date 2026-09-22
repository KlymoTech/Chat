# Repository boundaries and naming

The repository uses capability-owned folders. Administrative scopes are kept
separate from customer-facing website code:

```text
frontend/src/
├── app/                # application shell, routes, and authentication guards
└── features/
    ├── admin/          # authenticated tenant/workspace administration boundary
    ├── super-admin/    # SaaS-owner / global super-admin control plane
    ├── website/        # public website, login, invitations, and widget entrypoints
    ├── workspace/      # workspace-owned settings and conversations
    ├── branding/       # white-label identity, domains, email, widget, and versions
    └── whatsapp/       # WhatsApp connection, message, webhook, and status capabilities

backend/src/northstar_api/modules/
├── admin/             # tenant/workspace administration namespace
├── super_admin/       # global super-admin permissions and control plane
│   └── api/runtime.py  # protected capability catalog and change planning API
├── website/           # unauthenticated public boundary
├── workspace/         # workspace-owned domain and settings
├── branding/          # white-label domain and publication services
└── platform_runtime/  # provider-neutral contracts, registry, and planner
```

Application composition lives under `frontend/src/app`. The root
`frontend/src/App.tsx` is a deprecated compatibility export; new providers,
guards, route composition, and application-level wiring belong in `app/`.

Website page implementations live under `frontend/src/features/website/pages`,
tenant administration is exposed through
`frontend/src/features/admin/WorkspaceSettingsPage.tsx`, and
the global super-admin implementation lives under
`frontend/src/features/super-admin/SuperAdminPage.tsx`. The old `platform-admin` frontend and
`platform_admin` backend namespaces, plus the legacy `pages/` and
`routers/` roots, remain thin compatibility adapters during the staged
migration. New production imports should enter via the feature/module
boundary, and files must name one responsibility (for example
`WorkspaceMembersSettings.tsx`, not `helpers.ts` or `service.ts`).

`admin` is not `super-admin`: tenant administrators operate inside a
workspace/tenant scope, while super-admins use a separate global permission
boundary and support-session flow.
