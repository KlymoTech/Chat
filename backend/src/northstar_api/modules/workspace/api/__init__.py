"""Canonical HTTP boundary for workspace administration.

The concrete routers still live in the compatibility modules during the staged
migration. New production imports should use this package so those modules can
be moved one capability at a time without changing application registration.
"""

from northstar_api.modules.workspace.access import router as access_router
from northstar_api.modules.workspace.branding import router as branding_router
from northstar_api.modules.workspace.conversation_assignments import router as conversation_assignments_router
from northstar_api.modules.workspace.domains import router as domains_router
from northstar_api.modules.workspace.email_routes import router as email_router
from northstar_api.modules.workspace.general import router as general_router
from northstar_api.modules.workspace.members import router as members_router
from northstar_api.modules.workspace.settings import router as settings_router

__all__ = [
    "access_router",
    "branding_router",
    "conversation_assignments_router",
    "domains_router",
    "email_router",
    "general_router",
    "members_router",
    "settings_router",
]
