"""Release WhatsApp numbers assigned to soft-deleted agents.

Revision ID: 0072_release_deleted_agent_whatsapp_assignments
Revises: 0071_whatsapp_turn_review_link
"""

from alembic import op


revision = "0072_release_deleted_agent_whatsapp_assignments"
down_revision = "0071_whatsapp_turn_review_link"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Agent deletion is a soft delete, so the FK remains valid.  A stale
    # assignment must not make the connected number unavailable forever.
    op.execute(
        "UPDATE whatsapp_connections SET agent_id = NULL "
        "WHERE agent_id IN (SELECT id FROM agents WHERE deleted_at IS NOT NULL)"
    )


def downgrade() -> None:
    # The former assignee is intentionally not restored: it was deleted.
    pass
