"""Compatibility adapter; super-admin access lives in ``modules.super_admin``."""

from northstar_api.modules.super_admin.access import (
    PLATFORM_PERMISSIONS,
    platform_admin_emails,
    platform_admin_permissions,
)

__all__ = ["PLATFORM_PERMISSIONS", "platform_admin_emails", "platform_admin_permissions"]
