import subprocess
import sys
from pathlib import Path

AUDIT = Path(__file__).resolve().parents[2] / "scripts" / "audit-platform-conformance.py"


def fixture_root(tmp_path: Path) -> Path:
    (tmp_path / "backend" / "src" / "northstar_api" / "handlers").mkdir(parents=True)
    (tmp_path / "backend" / "src" / "northstar_api" / "handlers" / "job.py").write_text(
        "def handle(event):\n    return event\n", encoding="utf-8"
    )
    (tmp_path / "Dockerfile").write_text(
        "FROM python:3.12 AS builder\nFROM python:3.12\nUSER app\n", encoding="utf-8"
    )
    (tmp_path / "Makefile").write_text(
        "".join(f"{target}:\n\t@true\n" for target in (
            "bootstrap", "lint", "typecheck", "test", "conformance", "build", "image-push",
            "migrate", "deploy", "smoke", "local-up", "local-down",
        )),
        encoding="utf-8",
    )
    (tmp_path / "platform.yaml").write_text(
        """apiVersion: platform/v1
app: test
deployment_status: planned
owner: ops
region: ap-south-1
stage: 0
tier: T0
budget_usd_month: 60
images:
  api:
    dockerfile: Dockerfile
    platforms: [linux/arm64, linux/amd64]
processes:
  - name: job
    kind: schedule
    image: api
    rate: 15 minutes
    activity_gate: 2h
    handler: northstar_api.handlers.job:handle
resources: {queues: []}
secrets: []
""",
        encoding="utf-8",
    )
    return tmp_path


def run_audit(root: Path, *, report_only: bool = True) -> subprocess.CompletedProcess[str]:
    command = [sys.executable, str(AUDIT), "--root", str(root)]
    if report_only:
        command.append("--report-only")
    return subprocess.run(command, capture_output=True, text=True, check=False)  # noqa: S603


def test_static_checks_pass_but_dynamic_rules_remain_unverified(tmp_path: Path) -> None:
    root = fixture_root(tmp_path)
    result = run_audit(root)
    assert result.returncode == 0
    assert "[fail]" not in result.stdout
    assert "rule 23 [unverified]" in result.stdout
    assert run_audit(root, report_only=False).returncode == 1


def test_missing_activity_gate_and_handler_are_reported(tmp_path: Path) -> None:
    root = fixture_root(tmp_path)
    manifest = root / "platform.yaml"
    manifest.write_text(
        manifest.read_text(encoding="utf-8")
        .replace("    activity_gate: 2h\n", "")
        .replace("northstar_api.handlers.job:handle", "northstar_api.handlers.job:missing"),
        encoding="utf-8",
    )
    output = run_audit(root).stdout
    assert "rule 07 [fail]" in output
    assert "rule 09 [fail]" in output


def test_duplicate_yaml_keys_fail_closed(tmp_path: Path) -> None:
    root = fixture_root(tmp_path)
    manifest = root / "platform.yaml"
    manifest.write_text(manifest.read_text(encoding="utf-8") + "app: duplicate\n", encoding="utf-8")
    result = run_audit(root)
    assert result.returncode == 0
    assert "duplicate YAML key" in result.stdout
