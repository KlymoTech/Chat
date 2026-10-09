"""Protect the irreversible signing claim migration topology and controls."""
from __future__ import annotations

from pathlib import Path

from alembic.script import ScriptDirectory


def test_signing_claim_revision_follows_merged_custody_heads():
    script = ScriptDirectory(str(Path(__file__).resolve().parents[1] / "migrations"))
    revision = script.get_revision("0095_notification_custody_signing_claims")
    assert revision is not None
    assert revision.down_revision == "0094_merge_notification_junit_custody_heads"
    assert "0095_notification_custody_signing_claims" in script.get_heads()


def test_signing_claim_schema_requires_uniqueness_and_immutability():
    version = Path(__file__).resolve().parents[1] / (
        "migrations/versions/0095_notification_custody_signing_claims.py"
    )
    content = version.read_text(encoding="utf-8")
    assert 'primary_key=True' in content
    assert content.count("unique=True") >= 2
    assert "BEFORE UPDATE OR DELETE" in content
    assert "Cannot destroy custody signing replay claims" in content
