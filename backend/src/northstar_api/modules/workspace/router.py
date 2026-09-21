from fastapi import APIRouter

from .api import (
    access_router,
    branding_router,
    conversation_assignments_router,
    dashboard_runtime_router,
    domains_router,
    email_router,
    general_router,
    members_router,
    settings_router,
)

router = APIRouter(prefix="/workspace/settings", tags=["workspace-settings"])
router.include_router(settings_router)
router.include_router(general_router)
router.include_router(members_router)
router.include_router(access_router)
router.include_router(conversation_assignments_router)
router.include_router(dashboard_runtime_router)
router.include_router(branding_router)
router.include_router(domains_router)
router.include_router(email_router)
