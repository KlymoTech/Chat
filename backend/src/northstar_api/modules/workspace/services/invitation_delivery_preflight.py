"""Fail closed on invalid Workspace invitation email settings before DB mutations.

Invitation issue/resend read EmailSettings to calculate token expiry *before*
the transactional encrypted-mail staging function runs. Validate at the
protected router boundary so Pydantic configuration errors cannot escape as
500s or disclose SMTP details. Other member routes and public invitations
must retain their existing behavior.
"""
from __future__ import annotations

from fastapi import HTTPException, Request

from northstar_api.dependencies import CurrentPrincipal
from northstar_api.email_config import get_email_settings


async def preflight_workspace_invitation_email(
    request: Request, principal: CurrentPrincipal,
) -> None:
    """Check only protected invitation POST/create and POST/resend routes.

    The normal endpoint remains the authority on ``members.manage``. Return
    early for other permissions so this dependency never reveals mail-service
    configuration to members who cannot manage invitations.
    """
    if request.method != "POST" or "members.manage" not in principal.permissions:
        return
    route = request.scope.get("route")
    route_path = getattr(route, "path", "")
    if not isinstance(route_path, str) or not (
        route_path.endswith("/workspace/invitations")
        or route_path.endswith("/workspace/invitations/{invitation_id}/resend")
    ):
        return
    try:
        get_email_settings()
    except ValueError:
        raise HTTPException(
            status_code=503,
            detail="Workspace invitation SMTP delivery is not configured",
        ) from None
