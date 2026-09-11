from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import Field

from northstar_api.schemas import APIModel


class PlatformAdminAccessOut(APIModel):
    authorized: bool = True
    email: str


class PlatformOperationsOut(APIModel):
    status: str
    failed_ingestion_jobs: int
    unpublished_outbox_events: int
    oldest_unpublished_event_at: datetime | None = None
    quarantined_events: int
    channel_issues: int
    crm_connection_issues: int
    crm_delivery_issues: int
    open_crm_dead_letters: int
    critical_audit_events_24h: int


class PlatformSubscriptionBreakdownOut(APIModel):
    trial: int = 0
    active: int = 0
    past_due: int = 0
    suspended: int = 0
    cancelled: int = 0


class PlatformOverviewOut(APIModel):
    tenants: int
    workspaces: int
    users: int
    agents: int
    conversations: int
    leads: int
    subscriptions: PlatformSubscriptionBreakdownOut
    operations: PlatformOperationsOut


class PlatformTenantSummaryOut(APIModel):
    id: UUID
    name: str
    slug: str
    plan: str
    subscription_status: str
    workspace_count: int
    member_count: int
    agent_count: int
    conversation_count: int
    lead_count: int
    channel_issues: int
    crm_issues: int
    created_at: datetime


class PlatformTenantListOut(APIModel):
    items: list[PlatformTenantSummaryOut]
    total: int
    limit: int
    offset: int


class PlatformWorkspaceSummaryOut(APIModel):
    id: UUID
    name: str
    slug: str
    status: str
    member_count: int
    agent_count: int
    conversation_count: int
    lead_count: int
    created_at: datetime


class PlatformAuditSummaryOut(APIModel):
    id: UUID
    action: str
    entity_type: str
    entity_id: str
    category: str
    severity: str
    outcome: str
    workspace_id: UUID | None = None
    created_at: datetime


class PlatformTenantDetailOut(PlatformTenantSummaryOut):
    provider: str | None = None
    current_period_end: datetime | None = None
    cancel_at_period_end: bool = False
    workspaces: list[PlatformWorkspaceSummaryOut] = Field(default_factory=list)
    recent_audit: list[PlatformAuditSummaryOut] = Field(default_factory=list)
