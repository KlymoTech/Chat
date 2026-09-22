"""Compatibility namespace for the renamed ``modules.super_admin`` package."""

from northstar_api.modules.super_admin import (
    PLATFORM_PERMISSIONS,
    platform_admin_emails,
    platform_admin_permissions,
)

__all__ = ["PLATFORM_PERMISSIONS", "platform_admin_emails", "platform_admin_permissions"]
