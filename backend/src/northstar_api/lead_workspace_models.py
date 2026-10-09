"""Workspace-owned lead operations, separate from externally synchronized lead fields."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import ForeignKey, Index, Integer
from sqlalchemy.orm import Mapped, mapped_column

from northstar_api.database import Base
from northstar_api.models import MutableJSON, TimestampMixin


class LeadWorkspaceOperations(Base, TimestampMixin):
    __tablename__ = "lead_workspace_operations"
    __table_args__ = (Index("ix_lead_workspace_operations_scope", "tenant_id", "workspace_id"),)

    lead_id: Mapped[UUID] = mapped_column(ForeignKey("leads.id", ondelete="CASCADE"), primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"))
    workspace_id: Mapped[UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    document: Mapped[dict[str, Any]] = mapped_column(MutableJSON, nullable=False, default=dict)
