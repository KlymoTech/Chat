"""The WhatsApp worker imports audit models without the API router's model imports."""

import subprocess
import sys


def test_audit_turn_foreign_keys_resolve_in_isolated_worker_import() -> None:
    script = (
        "from northstar_api.services.course_whatsapp_audit import CourseWhatsappTurn; "
        "[fk.column for fk in CourseWhatsappTurn.__table__.foreign_keys]"
    )
    result = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True, check=False, timeout=30
    )
    assert result.returncode == 0, result.stderr
