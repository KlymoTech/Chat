"""Regression: both 0093 custody schemas must remain in one Alembic graph."""
from __future__ import annotations

from pathlib import Path

from alembic.script import ScriptDirectory


def test_junit_custody_migrations_have_one_merged_head() -> None:
    versions = Path(__file__).resolve().parents[1] / "migrations"
    script = ScriptDirectory(str(versions))
    merged = script.get_revision("0094_merge_notification_junit_custody_heads")
    assert merged is not None
    assert set(merged.down_revision) == {
        "0093_notification_jenkins_junit_custody",
        "0093_notification_junit_index_custody",
    }
    assert script.get_revision("0093_notification_jenkins_junit_custody")
    assert script.get_revision("0093_notification_junit_index_custody")
    assert "0094_merge_notification_junit_custody_heads" in script.get_heads()
    assert "0093_notification_jenkins_junit_custody" not in script.get_heads()
    assert "0093_notification_junit_index_custody" not in script.get_heads()
