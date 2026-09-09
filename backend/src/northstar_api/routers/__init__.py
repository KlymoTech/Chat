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
    crm_route_admin,
    crm_schema,
    crm_scoped,
    crm_webhooks,
    education,
    education_batches,
    education_student_identities,
    education_students,
    help,
    integration_audit,
    integrations,
    knowledge,
    leads,
    qualification,
    whatsapp,
    widget,
    workspace,
)

api_router = APIRouter()
api_router.include_router(auth.router)
api_router.include_router(agents.router)
api_router.include_router(education.router)
api_router.include_router(education_batches.router)
api_router.include_router(education_students.router)
api_router.include_router(education_student_identities.router)
api_router.include_router(knowledge.router)
api_router.include_router(conversations.router)
api_router.include_router(leads.router)
api_router.include_router(qualification.router)
# Workspace-aware CRM routes are registered before their legacy-compatible
# implementations so identical HTTP paths enforce the active workspace boundary.
api_router.include_router(crm_scoped.router)
api_router.include_router(crm.router)
api_router.include_router(crm_route_admin.router)
api_router.include_router(crm_oauth.router)
api_router.include_router(crm_schema.router)
api_router.include_router(crm_webhooks.router)
api_router.include_router(channels.router)
api_router.include_router(analytics.router)
api_router.include_router(integration_audit.router)
api_router.include_router(integrations.router)
api_router.include_router(help.router)
api_router.include_router(widget.router)
api_router.include_router(whatsapp.router)
api_router.include_router(chat.router)
api_router.include_router(workspace.router)
api_router.include_router(workspace.collection_router)
