"""Feature-owned white-label/branding boundary.

This package intentionally wraps the existing workspace branding implementation
while the repository is migrated capability-by-capability.
"""

from .api import branding_router, domains_router, email_router

__all__ = ["branding_router", "domains_router", "email_router"]
