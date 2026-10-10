"""Static migration graph and retention checks for one-use authorizations."""
from __future__ import annotations

from pathlib import Path

from alembic.script import ScriptDirectory


def test_authorization_revision_extends_signing_claims():
    root = Path(__file__).resolve().parents[1] / "migrations"
    script = ScriptDirectory(str(root))
    revision = script.get_revision("0096_signing_authorization_replay")
    assert revision is not None
    assert revision.down_revision == "0095_notification_custody_signing_claims"
    assert "0096_signing_authorization_replay" in script.get_heads()


def test_authorization_consumption_cannot_be_mutated_or_silently_erased():
    path = (
        Path(__file__).resolve().parents[1]
        / "migrations/versions/0096_signing_authorization_replay.py"
    )
    source = path.read_text(encoding="utf-8")
    assert "BEFORE UPDATE OR DELETE" in source
    assert "Cannot erase consumed signing authorizations" in source
    assert 'sa.Column("authorization_id", sa.String(128), primary_key=True)' in source
    assert 'sa.Column("release_id", sa.String(80), nullable=False, unique=True)' in source
    assert 'sa.Column("run_id", sa.String(40), nullable=False, unique=True)' in source
