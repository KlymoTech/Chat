from fastapi import APIRouter, Depends

from northstar_api.routers import (
    agents,
    analytics,
    auth,
    billing,
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
    education_enrollments,
    education_student_identities,
    education_students,
    email_verification,
    help,
    integration_audit,
    integrations,
    knowledge,
    leads,
    mfa,
    notifications,
    password_reset,
    platform_admin,
    qualification,
    whatsapp,
    widget,
    workspace,
    workspace_api_keys,
    workspace_invitations,
)
from northstar_api.services.entitlement_guard import enforce_plan_entitlements

api_router = APIRouter(dependencies=[Depends(enforce_plan_entitlements)])
api_router.include_router(auth.router)
api_router.include_router(email_verification.router)
api_router.include_router(password_reset.router)
api_router.include_router(mfa.router)
api_router.include_router(agents.router)
api_router.include_router(education.router)
api_router.include_router(education_batches.router)
api_router.include_router(education_students.router)
api_router.include_router(education_student_identities.router)
api_router.include_router(education_enrollments.router)
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
# Preserve the historical integration audit endpoint and add the broader SaaS audit API.
api_router.include_router(integration_audit.router)
api_router.include_router(integration_audit.audit_router)
api_router.include_router(notifications.router)
api_router.include_router(integrations.router)
api_router.include_router(help.router)
api_router.include_router(widget.router)
api_router.include_router(whatsapp.router)
api_router.include_router(chat.router)
api_router.include_router(workspace.router)
api_router.include_router(workspace.collection_router)
api_router.include_router(workspace_invitations.router)
api_router.include_router(workspace_invitations.public_router)
api_router.include_router(workspace_api_keys.router)
api_router.include_router(billing.router)
api_router.include_router(platform_admin.router)
