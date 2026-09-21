from __future__ import annotations

import secrets
from datetime import UTC, datetime
from typing import Annotated, Any, Literal
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from pydantic import EmailStr, Field, field_validator

from northstar_api.access_policy import WORKSPACE_GRANTS, WORKSPACE_PERMISSIONS
from northstar_api.dependencies import DBSession, require_permissions
from northstar_api.entitlements import entitlement_for_plan
from northstar_api.lead_crm.audit import record_audit_event
from northstar_api.models import Workspace
from northstar_api.onboarding_contract import SetupContract
from northstar_api.routers.workspace import _load_workspace
from northstar_api.security import Principal
from northstar_api.services.outbox import enqueue_event
from northstar_api.workspace_contract import WhiteLabelWrite

router = APIRouter(prefix="/workspace/settings", tags=["workspace-settings"])
SettingsViewPrincipal = Annotated[Principal, Depends(require_permissions("settings.view"))]
SettingsManagePrincipal = Annotated[Principal, Depends(require_permissions("settings.manage"))]
BrandViewPrincipal = Annotated[Principal, Depends(require_permissions("branding.view"))]
BrandEditPrincipal = Annotated[Principal, Depends(require_permissions("branding.edit"))]
BrandPublishPrincipal = Annotated[Principal, Depends(require_permissions("branding.publish"))]
DomainManagePrincipal = Annotated[Principal, Depends(require_permissions("branding.domain.manage"))]
RolesManagePrincipal = Annotated[Principal, Depends(require_permissions("roles.manage"))]
TeamsManagePrincipal = Annotated[Principal, Depends(require_permissions("teams.manage"))]


class BusinessHours(SetupContract):
    enabled: bool = False
    timezone: str = "Asia/Kolkata"
    schedule: dict[str, list[str]] = Field(default_factory=dict)


class GeneralSettings(SetupContract):
    industry: str = Field(default="", max_length=120)
    country: str = Field(default="", max_length=80)
    time_format: Literal["12h", "24h"] = "24h"
    currency: str = Field(default="INR", min_length=3, max_length=3)
    week_start: Literal["monday", "sunday"] = "monday"
    description: str = Field(default="", max_length=1000)
    workspace_icon: str = Field(default="", max_length=500_000)
    business_hours: BusinessHours = Field(default_factory=BusinessHours)


class SecuritySettings(SetupContract):
    sensitive_data_masking: bool = True
    security_contact: EmailStr | None = None
    mfa_enforcement: Literal["optional", "admins", "all"] = "optional"
    session_timeout_minutes: int = Field(default=480, ge=15, le=43200)
    password_min_length: int = Field(default=12, ge=8, le=128)
    ip_allowlist: list[str] = Field(default_factory=list, max_length=100)
    ip_denylist: list[str] = Field(default_factory=list, max_length=100)
    trusted_domains: list[str] = Field(default_factory=list, max_length=100)
    sso_enabled: bool = False
    scim_enabled: bool = False
    webhook_signing_required: bool = True
    security_notifications: bool = True


class NotificationSettings(SetupContract):
    member_changes: bool = True
    security_alerts: bool = True
    billing_alerts: bool = True
    channel_failures: bool = True
    integration_failures: bool = True
    weekly_digest: bool = False
    recipients: list[EmailStr] = Field(default_factory=list, max_length=50)


class DeveloperSettings(SetupContract):
    sandbox_mode: bool = False
    webhook_signing_enabled: bool = True
    webhook_events: list[str] = Field(default_factory=list, max_length=100)
    rate_limit_per_minute: int = Field(default=120, ge=10, le=100000)
    request_log_retention_days: int = Field(default=30, ge=1, le=365)
    webhook_retry_limit: int = Field(default=5, ge=0, le=20)


class ResourceScope(SetupContract):
    selected: dict[str, list[str]] = Field(default_factory=dict)
    conversation_scope: Literal["all", "assigned", "team"] = "all"


class CustomRole(SetupContract):
    id: str = Field(default_factory=lambda: str(uuid4()))
    name: str = Field(min_length=2, max_length=80)
    description: str = Field(default="", max_length=500)
    permissions: list[str] = Field(min_length=1, max_length=150)
    resources: ResourceScope = Field(default_factory=ResourceScope)

    @field_validator("permissions")
    @classmethod
    def registered_permissions(cls, value: list[str]) -> list[str]:
        selected = set(value)
        if not selected <= WORKSPACE_PERMISSIONS:
            raise ValueError("Only registered workspace permissions can be assigned")
        return sorted(selected)


class RolesSettings(SetupContract):
    custom_roles: list[CustomRole] = Field(default_factory=list, max_length=100)


class WorkspaceTeam(SetupContract):
    id: str = Field(default_factory=lambda: str(uuid4()))
    name: str = Field(min_length=2, max_length=80)
    description: str = Field(default="", max_length=500)
    member_ids: list[str] = Field(default_factory=list, max_length=500)
    manager_ids: list[str] = Field(default_factory=list, max_length=100)
    role_ids: list[str] = Field(default_factory=list, max_length=50)
    queue_ids: list[str] = Field(default_factory=list, max_length=100)
    agent_ids: list[str] = Field(default_factory=list, max_length=500)
    channel_ids: list[str] = Field(default_factory=list, max_length=100)
    business_hours: BusinessHours = Field(default_factory=BusinessHours)
    escalation_rule: str = Field(default="", max_length=1000)


class TeamsSettings(SetupContract):
    teams: list[WorkspaceTeam] = Field(default_factory=list, max_length=100)


class DashboardWidget(SetupContract):
    id: str = Field(default_factory=lambda: str(uuid4()))
    type: str = Field(min_length=2, max_length=80)
    x: int = Field(default=0, ge=0, le=24)
    y: int = Field(default=0, ge=0, le=1000)
    width: int = Field(default=4, ge=1, le=24)
    height: int = Field(default=2, ge=1, le=24)
    visible: bool = True
    audience: list[str] = Field(default_factory=list, max_length=30)
    config: dict[str, Any] = Field(default_factory=dict)


class DashboardSettings(SetupContract):
    layout_version: int = Field(default=1, ge=1)
    landing_screen: str = Field(default="overview", max_length=80)
    widgets: list[DashboardWidget] = Field(default_factory=list, max_length=100)


class AuthBranding(SetupContract):
    login_logo: str = Field(default="", max_length=500_000)
    login_background: str = Field(default="", max_length=500_000)
    login_title: str = Field(default="", max_length=120)
    login_description: str = Field(default="", max_length=500)
    terms_url: str = Field(default="", max_length=2000)
    privacy_url: str = Field(default="", max_length=2000)
    support_url: str = Field(default="", max_length=2000)
    footer: str = Field(default="", max_length=500)


class EmailBranding(SetupContract):
    logo: str = Field(default="", max_length=500_000)
    sender_name: str = Field(default="", max_length=160)
    reply_to: EmailStr | None = None
    footer: str = Field(default="", max_length=1000)
    enabled_templates: list[str] = Field(
        default_factory=lambda: [
            "invitation",
            "password_reset",
            "email_verification",
            "security_alert",
            "billing_notification",
            "conversation_notification",
            "lead_notification",
            "education_notification",
        ]
    )


class WidgetBranding(SetupContract):
    launcher_icon: str = Field(default="", max_length=500_000)
    launcher_color: str = "#0c0b0b"
    position: Literal["bottom-left", "bottom-right"] = "bottom-right"
    greeting: str = Field(default="How can I help?", max_length=240)
    widget_logo: str = Field(default="", max_length=500_000)
    header: str = Field(default="", max_length=160)
    background: str = "#ffffff"
    user_message_color: str = "#0c0b0b"
    agent_message_color: str = "#f3f4f6"
    font: str = Field(default="Inter", max_length=80)
    privacy_url: str = Field(default="", max_length=2000)
    powered_by_label: str = Field(default="", max_length=120)
    offline_message: str = Field(default="We are currently offline.", max_length=300)


class ExtendedBranding(SetupContract):
    identity: WhiteLabelWrite = Field(default_factory=WhiteLabelWrite)
    colors: dict[str, str] = Field(default_factory=dict)
    typography: dict[str, str | int | float] = Field(default_factory=dict)
    dashboard: DashboardSettings = Field(default_factory=DashboardSettings)
    authentication: AuthBranding = Field(default_factory=AuthBranding)
    email: EmailBranding = Field(default_factory=EmailBranding)
    widget: WidgetBranding = Field(default_factory=WidgetBranding)
    navigation: dict[str, Any] = Field(default_factory=dict)


class BrandVersion(SetupContract):
    version: int
    created_by: str
    published_at: datetime
    change_note: str = Field(default="", max_length=500)
    branding: ExtendedBranding


class DomainRecord(SetupContract):
    id: str = Field(default_factory=lambda: str(uuid4()))
    hostname: str = Field(min_length=4, max_length=253)
    status: Literal[
        "pending",
        "dns_pending",
        "verifying",
        "verified",
        "certificate_pending",
        "active",
        "failed",
        "disabled",
    ] = "dns_pending"
    verification_name: str
    verification_value: str
    failure_reason: str = ""
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @field_validator("hostname")
    @classmethod
    def normalized_hostname(cls, value: str) -> str:
        normalized = value.strip().lower().rstrip(".")
        if "://" in normalized or "/" in normalized or " " in normalized or "." not in normalized:
            raise ValueError("Enter a hostname such as portal.customer.com")
        return normalized


class DomainsSettings(SetupContract):
    domains: list[DomainRecord] = Field(default_factory=list, max_length=20)


class WorkspaceSettingsBundle(SetupContract):
    general: GeneralSettings = Field(default_factory=GeneralSettings)
    security: SecuritySettings = Field(default_factory=SecuritySettings)
    notifications: NotificationSettings = Field(default_factory=NotificationSettings)
    developer: DeveloperSettings = Field(default_factory=DeveloperSettings)
    roles: RolesSettings = Field(default_factory=RolesSettings)
    teams: TeamsSettings = Field(default_factory=TeamsSettings)
    dashboard: DashboardSettings = Field(default_factory=DashboardSettings)
    branding_draft: ExtendedBranding = Field(default_factory=ExtendedBranding)
    branding_published: ExtendedBranding | None = None
    branding_versions: list[BrandVersion] = Field(default_factory=list, max_length=50)
    domains: DomainsSettings = Field(default_factory=DomainsSettings)


class DomainCreate(SetupContract):
    hostname: str = Field(min_length=4, max_length=253)


class PublishRequest(SetupContract):
    change_note: str = Field(default="", max_length=500)


class RollbackRequest(SetupContract):
    version: int = Field(ge=1)
    change_note: str = Field(default="Rollback", max_length=500)


def _settings_document(workspace: Workspace) -> WorkspaceSettingsBundle:
    raw = dict(workspace.settings_json or {}).get("workspaceSettingsV2", {})
    try:
        document = WorkspaceSettingsBundle.model_validate(raw)
    except Exception:
        document = WorkspaceSettingsBundle()

    legacy_security = dict(workspace.settings_json or {}).get("security", {})
    if legacy_security:
        document.security.sensitive_data_masking = bool(
            legacy_security.get("sensitiveDataMasking", document.security.sensitive_data_masking)
        )
        document.security.security_contact = legacy_security.get(
            "securityContact", document.security.security_contact
        )

    if workspace.branding_json and document.branding_published is None:
        legacy = {
            key: value
            for key, value in workspace.branding_json.items()
            if key not in {"customDomain", "dnsStatus"}
        }
        try:
            identity = WhiteLabelWrite.model_validate(legacy)
            document.branding_published = ExtendedBranding(identity=identity)
            document.branding_draft = document.branding_published.model_copy(deep=True)
        except Exception:
            pass
    return document


def _save_document(workspace: Workspace, document: WorkspaceSettingsBundle) -> None:
    settings = dict(workspace.settings_json or {})
    settings["workspaceSettingsV2"] = document.model_dump(by_alias=True, mode="json")
    workspace.settings_json = settings


def _audit(
    session: DBSession,
    principal: Principal,
    workspace: Workspace,
    action: str,
    fields: list[str] | None = None,
) -> None:
    record_audit_event(
        session,
        tenant_id=principal.tenant_id,
        workspace_id=workspace.id,
        actor_user_id=principal.user_id,
        action=action,
        entity_type="workspace",
        entity_id=str(workspace.id),
        category="workspace",
        metadata={"fields": fields or []},
    )
    enqueue_event(
        session,
        tenant_id=principal.tenant_id,
        aggregate_type="workspace",
        aggregate_id=workspace.id,
        event_type=f"{action}.v1",
        payload={"workspaceId": str(workspace.id)},
    )


async def _workspace(principal: Principal, session: DBSession) -> tuple[Any, Workspace]:
    tenant, workspace, _, _ = await _load_workspace(
        principal.tenant_id,
        principal.workspace_id,
        principal.user_id,
        session,
    )
    return tenant, workspace


@router.get("", response_model=WorkspaceSettingsBundle)
async def get_settings(principal: SettingsViewPrincipal, session: DBSession) -> WorkspaceSettingsBundle:
    _, workspace = await _workspace(principal, session)
    return _settings_document(workspace)


@router.get("/capabilities")
async def get_capabilities(principal: SettingsViewPrincipal) -> dict[str, Any]:
    _ = principal
    return {
        "permissions": sorted(WORKSPACE_PERMISSIONS),
        "builtinRoles": {name: sorted(values) for name, values in WORKSPACE_GRANTS.items()},
        "resourceKinds": [
            "agents",
            "knowledge",
            "conversations",
            "courses",
            "batches",
            "students",
            "leads",
            "channels",
            "crm",
        ],
    }


@router.patch("/general", response_model=GeneralSettings)
async def update_general(
    payload: GeneralSettings,
    principal: SettingsManagePrincipal,
    session: DBSession,
) -> GeneralSettings:
    _, workspace = await _workspace(principal, session)
    document = _settings_document(workspace)
    document.general = payload
    _save_document(workspace, document)
    _audit(
        session,
        principal,
        workspace,
        "workspace.settings.general.updated",
        sorted(payload.model_fields_set),
    )
    await session.commit()
    return payload


@router.patch("/security", response_model=SecuritySettings)
async def update_security(
    payload: SecuritySettings,
    principal: SettingsManagePrincipal,
    session: DBSession,
) -> SecuritySettings:
    _, workspace = await _workspace(principal, session)
    document = _settings_document(workspace)
    document.security = payload
    legacy = dict(workspace.settings_json or {})
    legacy["security"] = {
        "sensitiveDataMasking": payload.sensitive_data_masking,
        "securityContact": str(payload.security_contact) if payload.security_contact else None,
    }
    workspace.settings_json = legacy
    _save_document(workspace, document)
    _audit(
        session,
        principal,
        workspace,
        "workspace.settings.security.updated",
        sorted(payload.model_fields_set),
    )
    await session.commit()
    return payload


@router.patch("/notifications", response_model=NotificationSettings)
async def update_notifications(
    payload: NotificationSettings,
    principal: SettingsManagePrincipal,
    session: DBSession,
) -> NotificationSettings:
    _, workspace = await _workspace(principal, session)
    document = _settings_document(workspace)
    document.notifications = payload
    _save_document(workspace, document)
    _audit(
        session,
        principal,
        workspace,
        "workspace.settings.notifications.updated",
        sorted(payload.model_fields_set),
    )
    await session.commit()
    return payload


@router.patch("/developer", response_model=DeveloperSettings)
async def update_developer(
    payload: DeveloperSettings,
    principal: SettingsManagePrincipal,
    session: DBSession,
) -> DeveloperSettings:
    _, workspace = await _workspace(principal, session)
    document = _settings_document(workspace)
    document.developer = payload
    _save_document(workspace, document)
    _audit(
        session,
        principal,
        workspace,
        "workspace.settings.developer.updated",
        sorted(payload.model_fields_set),
    )
    await session.commit()
    return payload


@router.patch("/roles", response_model=RolesSettings)
async def update_roles(
    payload: RolesSettings,
    principal: RolesManagePrincipal,
    session: DBSession,
) -> RolesSettings:
    _, workspace = await _workspace(principal, session)
    document = _settings_document(workspace)
    document.roles = payload
    _save_document(workspace, document)
    _audit(
        session,
        principal,
        workspace,
        "workspace.roles.updated",
        [role.id for role in payload.custom_roles],
    )
    await session.commit()
    return payload


@router.patch("/teams", response_model=TeamsSettings)
async def update_teams(
    payload: TeamsSettings,
    principal: TeamsManagePrincipal,
    session: DBSession,
) -> TeamsSettings:
    _, workspace = await _workspace(principal, session)
    document = _settings_document(workspace)
    document.teams = payload
    _save_document(workspace, document)
    _audit(
        session,
        principal,
        workspace,
        "workspace.teams.updated",
        [team.id for team in payload.teams],
    )
    await session.commit()
    return payload


@router.patch("/dashboard", response_model=DashboardSettings)
async def update_dashboard(
    payload: DashboardSettings,
    principal: BrandEditPrincipal,
    session: DBSession,
) -> DashboardSettings:
    _, workspace = await _workspace(principal, session)
    document = _settings_document(workspace)
    document.dashboard = payload
    document.branding_draft.dashboard = payload
    _save_document(workspace, document)
    _audit(
        session,
        principal,
        workspace,
        "workspace.dashboard.updated",
        [widget.id for widget in payload.widgets],
    )
    await session.commit()
    return payload


@router.get("/branding", response_model=WorkspaceSettingsBundle)
async def get_branding(
    principal: BrandViewPrincipal,
    session: DBSession,
) -> WorkspaceSettingsBundle:
    _, workspace = await _workspace(principal, session)
    return _settings_document(workspace)


@router.patch("/branding/draft", response_model=ExtendedBranding)
async def save_branding_draft(
    payload: ExtendedBranding,
    principal: BrandEditPrincipal,
    session: DBSession,
) -> ExtendedBranding:
    if principal.token_id.startswith("api_key:"):
        raise HTTPException(status_code=403, detail="Interactive branding editing required")
    _, workspace = await _workspace(principal, session)
    document = _settings_document(workspace)
    document.branding_draft = payload
    _save_document(workspace, document)
    _audit(session, principal, workspace, "workspace.brand.draft.updated", ["brandingDraft"])
    await session.commit()
    return payload


def _check_brand_entitlements(plan: str, branding: ExtendedBranding) -> None:
    entitlement = entitlement_for_plan(plan)
    if not entitlement.white_label_enabled:
        raise HTTPException(status_code=403, detail="Your plan does not include white label")
    if branding.identity.branded_emails and not entitlement.branded_email_enabled:
        raise HTTPException(status_code=403, detail="Your plan does not include branded email")
    if branding.identity.remove_platform_branding and not entitlement.remove_platform_mark_enabled:
        raise HTTPException(status_code=403, detail="Your plan does not include platform-brand removal")


async def _publish(
    document: WorkspaceSettingsBundle,
    principal: Principal,
    session: DBSession,
    workspace: Workspace,
    plan: str,
    change_note: str,
) -> BrandVersion:
    _check_brand_entitlements(plan, document.branding_draft)
    version_number = max((item.version for item in document.branding_versions), default=0) + 1
    version = BrandVersion(
        version=version_number,
        created_by=str(principal.user_id),
        published_at=datetime.now(UTC),
        change_note=change_note,
        branding=document.branding_draft.model_copy(deep=True),
    )
    document.branding_published = version.branding.model_copy(deep=True)
    document.branding_versions = (document.branding_versions + [version])[-50:]
    active_domain = next(
        (item.hostname for item in document.domains.domains if item.status == "active"),
        "",
    )
    workspace.branding_json = {
        **version.branding.identity.model_dump(by_alias=True, mode="json"),
        "customDomain": active_domain,
        "dnsStatus": "verified" if active_domain else "not-configured",
    }
    _save_document(workspace, document)
    _audit(
        session,
        principal,
        workspace,
        "workspace.brand.published",
        [f"version:{version_number}"],
    )
    await session.commit()
    return version


@router.post("/branding/publish", response_model=BrandVersion)
async def publish_branding(
    payload: PublishRequest,
    principal: BrandPublishPrincipal,
    session: DBSession,
) -> BrandVersion:
    if principal.token_id.startswith("api_key:"):
        raise HTTPException(status_code=403, detail="Interactive branding publication required")
    tenant, workspace = await _workspace(principal, session)
    document = _settings_document(workspace)
    return await _publish(document, principal, session, workspace, tenant.plan, payload.change_note)


@router.post("/branding/rollback", response_model=BrandVersion)
async def rollback_branding(
    payload: RollbackRequest,
    principal: BrandPublishPrincipal,
    session: DBSession,
) -> BrandVersion:
    tenant, workspace = await _workspace(principal, session)
    document = _settings_document(workspace)
    source = next(
        (item for item in document.branding_versions if item.version == payload.version),
        None,
    )
    if source is None:
        raise HTTPException(status_code=404, detail="Brand version not found")
    document.branding_draft = source.branding.model_copy(deep=True)
    return await _publish(document, principal, session, workspace, tenant.plan, payload.change_note)


@router.post("/domains", response_model=DomainRecord, status_code=201)
async def create_domain(
    payload: DomainCreate,
    principal: DomainManagePrincipal,
    session: DBSession,
) -> DomainRecord:
    tenant, workspace = await _workspace(principal, session)
    if not entitlement_for_plan(tenant.plan).custom_domain_enabled:
        raise HTTPException(status_code=403, detail="Your plan does not include custom domains")
    document = _settings_document(workspace)
    normalized = DomainRecord.normalized_hostname(payload.hostname)
    if any(
        item.hostname == normalized and item.status != "disabled"
        for item in document.domains.domains
    ):
        raise HTTPException(status_code=409, detail="Domain is already configured")
    domain = DomainRecord(
        hostname=normalized,
        verification_name=f"_northstar-verify.{normalized}",
        verification_value=secrets.token_urlsafe(24),
    )
    document.domains.domains.append(domain)
    _save_document(workspace, document)
    _audit(session, principal, workspace, "workspace.domain.created", [normalized])
    await session.commit()
    return domain


@router.post("/domains/{domain_id}/verification-start", response_model=DomainRecord)
async def start_domain_verification(
    domain_id: str,
    principal: DomainManagePrincipal,
    session: DBSession,
) -> DomainRecord:
    _, workspace = await _workspace(principal, session)
    document = _settings_document(workspace)
    domain = next((item for item in document.domains.domains if item.id == domain_id), None)
    if domain is None:
        raise HTTPException(status_code=404, detail="Domain not found")
    if domain.status in {"disabled", "active"}:
        raise HTTPException(status_code=409, detail="Domain cannot be verified in its current state")
    domain.status = "verifying"
    domain.failure_reason = ""
    _save_document(workspace, document)
    _audit(
        session,
        principal,
        workspace,
        "workspace.domain.verification.started",
        [domain.hostname],
    )
    await session.commit()
    return domain


@router.post("/domains/{domain_id}/disable", response_model=DomainRecord)
async def disable_domain(
    domain_id: str,
    principal: DomainManagePrincipal,
    session: DBSession,
) -> DomainRecord:
    _, workspace = await _workspace(principal, session)
    document = _settings_document(workspace)
    domain = next((item for item in document.domains.domains if item.id == domain_id), None)
    if domain is None:
        raise HTTPException(status_code=404, detail="Domain not found")
    domain.status = "disabled"
    _save_document(workspace, document)
    _audit(session, principal, workspace, "workspace.domain.disabled", [domain.hostname])
    await session.commit()
    return domain
