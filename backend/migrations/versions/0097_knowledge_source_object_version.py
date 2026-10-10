"""Retain the approved S3 version of promoted knowledge source objects."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0097_knowledge_source_object_version"
down_revision = "0096_signing_authorization_replay"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("knowledge_sources", sa.Column("object_version_id", sa.String(1024), nullable=True))


def downgrade() -> None:
    op.drop_column("knowledge_sources", "object_version_id")
