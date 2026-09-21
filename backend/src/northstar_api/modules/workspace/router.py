from fastapi import APIRouter

from .api import (
    branding_router,
    conversation_assignments_router,
    dashboard_runtime_router,
    dashboard_settings_router,
    domains_router,
    email_router,
    general_router,
    members_router,
    roles_router,
    settings_router,
    teams_router,
)

router = APIRouter(prefix="/workspace/settings", tags=["workspace-settings"])
router.include_router(settings_router)
router.include_router(general_router)
router.include_router(members_router)
# Register each existing access capability once through its canonical boundary.
# The combined access_router remains exported for legacy callers.
router.include_router(roles_router)
router.include_router(teams_router)
router.include_router(dashboard_settings_router)
router.include_router(conversation_assignments_router)
router.include_router(dashboard_runtime_router)
router.include_router(branding_router)
router.include_router(domains_router)
router.include_router(email_router)
