"""Compatibility adapter for the renamed super-admin API boundary."""

from northstar_api.modules.super_admin.api import router

__all__ = ["router"]
