from fastapi import APIRouter

from .access import router as access_router
from .branding import router as branding_router
from .general import router as general_router
from .members import router as members_router
from .settings import router as settings_router

router = APIRouter(prefix="/workspace/settings", tags=["workspace-settings"])
router.include_router(settings_router)
router.include_router(general_router)
router.include_router(members_router)
router.include_router(access_router)
router.include_router(branding_router)
