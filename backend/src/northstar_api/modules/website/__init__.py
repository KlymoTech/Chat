"""Public website and unauthenticated customer-facing boundary.

Public branding, login, invitation, and widget routes are migrated gradually;
the existing routers remain compatibility adapters until each capability has
its own tests and explicit route ownership.
"""

WEBSITE_SCOPE = "public"

__all__ = ["WEBSITE_SCOPE"]
