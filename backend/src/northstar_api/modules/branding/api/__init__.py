"""HTTP routers for workspace white-label capabilities."""

from northstar_api.modules.workspace.branding import router as branding_router
from northstar_api.modules.workspace.domains import router as domains_router
from northstar_api.modules.workspace.email_routes import router as email_router

__all__ = ["branding_router", "domains_router", "email_router"]
