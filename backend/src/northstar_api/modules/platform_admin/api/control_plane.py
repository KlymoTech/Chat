"""Compatibility adapter for the renamed super-admin control-plane router."""

from northstar_api.modules.super_admin.api.control_plane import router

__all__ = ["router"]
