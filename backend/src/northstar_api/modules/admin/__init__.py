"""Tenant/workspace administration boundary.

Workspace-owned settings and membership implementations remain under
``modules.workspace`` during the staged migration. This package is the stable
administration namespace; new tenant-admin capabilities must be added here or
under a named child capability rather than the generic routers root.
"""

ADMIN_SCOPE = "workspace"

__all__ = ["ADMIN_SCOPE"]
