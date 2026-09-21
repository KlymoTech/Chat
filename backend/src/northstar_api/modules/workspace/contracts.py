from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal
from uuid import uuid4

from pydantic import EmailStr, Field, field_validator

from northstar_api.access_policy import WORKSPACE_PERMISSIONS
from northstar_api.onboarding_contract import SetupContract
from northstar_api.workspace_contract import WhiteLabelWrite


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
    font: Literal["Inter", "DM Sans", "Manrope", "System UI"] = "Inter"
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
