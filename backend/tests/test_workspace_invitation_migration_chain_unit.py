"""Catch missing Alembic predecessors before enabling Workspace invitation mail.

The Workspace revisions may coexist with an independently developed main-branch
head; this test intentionally checks this capability's ancestry, not a global
single-head assumption. It does not replace real DB upgrade/downgrade tests.
"""
from __future__ import annotations

from pathlib import Path

from alembic.script import ScriptDirectory


def test_workspace_member_and_invitation_revisions_have_resolvable_ancestry() -> None:
    migrations = Path(__file__).resolve().parents[1] / "migrations"
    scripts = ScriptDirectory(str(migrations))
    revisions = (
        "0058_workspace_email_grants",
        "0057_workspace_invite_email_jobs",
        "0056_workspace_invitation_origin",
        "0055_workspace_member_suspension",
        "0054_knowledge_audit_tables",
    )
    for current, predecessor in zip(revisions, revisions[1:], strict=False):
        script = scripts.get_revision(current)
        assert script is not None, current
        assert script.down_revision == predecessor, current
        assert scripts.get_revision(predecessor) is not None, predecessor
