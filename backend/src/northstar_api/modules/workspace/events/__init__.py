"""Workspace administrative event/audit boundary."""

from northstar_api.modules.workspace.store import record_workspace_change

__all__ = ["record_workspace_change"]
