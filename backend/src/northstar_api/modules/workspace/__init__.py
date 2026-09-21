"""Workspace-owned feature modules.

These modules extend the legacy workspace routers without replacing them. Existing
routes remain authoritative for backward compatibility while new settings routes
are grouped by business capability.
"""

from northstar_api.modules.workspace.router import router

__all__ = ["router"]
