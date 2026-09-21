"""Allow the existing service-role dispatcher and worker to process invite mail.

The API writes new encrypted jobs as northstar_app. Compose and Kubernetes
background workers connect as northstar_service and need only to read/update
committed jobs, not create, delete or expose invitation credentials elsewhere.
"""
from __future__ import annotations

from alembic import op

revision = "0058_workspace_email_grants"
down_revision = "0057_workspace_invite_email_jobs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute(
            'GRANT SELECT, UPDATE ON "workspace_invitation_email_jobs" TO "northstar_service"'
        )


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute(
            'REVOKE SELECT, UPDATE ON "workspace_invitation_email_jobs" FROM "northstar_service"'
        )
