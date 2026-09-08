from fastapi import APIRouter

from northstar_api.routers import (
    agents,
    analytics,
    auth,
    channels,
    chat,
    conversations,
    crm,
    crm_oauth,
    crm_routes,
    crm_schema,
    crm_webhooks,
    integrations,
    knowledge,
    leads,
    qualification,
    whatsapp,
    widget,
)

api_router = APIRouter()
api_router.include_router(auth.router)
api_router.include_router(agents.router)
api_router.include_router(knowledge.router)
api_router.include_router(conversations.router)
api_router.include_router(leads.router)
api_router.include_router(qualification.router)
api_router.include_router(crm.router)
api_router.include_router(crm_routes.router)
api_router.include_router(crm_oauth.router)
api_router.include_router(crm_schema.router)
api_router.include_router(crm_webhooks.router)
api_router.include_router(channels.router)
api_router.include_router(analytics.router)
api_router.include_router(integrations.router)
api_router.include_router(widget.router)
api_router.include_router(whatsapp.router)
api_router.include_router(chat.router)
