import subprocess

import pytest
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


@pytest.mark.parametrize("topic", ["missing", "[invalid]"])
def test_undeclared_event_topic_fails_closed(tmp_path: Path, topic: str) -> None:
    root = fixture_root(tmp_path)
    manifest = root / "platform.yaml"
    original = manifest.read_text(encoding="utf-8")
    updated = original.replace(
        "processes:\n",
        "processes:\n"
        "  - name: event\n"
        "    kind: event\n"
        "    image: api\n"
        f"    topic: {topic}\n"
        "    handler: northstar_api.handlers.job:handle\n",
    ).replace(
        "resources: {queues: []}",
        "resources: {queues: [], topics: [{name: approved}]}",
    )
    manifest.write_text(updated, encoding="utf-8")
    result = run_audit(root)
    assert "event topic resource is undeclared" in result.stdout
    assert "Traceback" not in result.stderr


@pytest.mark.parametrize("invalid_timeout", ["-1", "0", "true", "901"])
def test_invalid_lambda_timeout_fails_closed(
    tmp_path: Path, invalid_timeout: str
) -> None:
    root = fixture_root(tmp_path)
    manifest = root / "platform.yaml"
    original = manifest.read_text(encoding="utf-8")
    manifest.write_text(
        original.replace(
            "    kind: schedule\n",
            "    kind: schedule\n"
            "    runtime: lambda\n"
            f"    timeout_s: {invalid_timeout}\n",
        ),
        encoding="utf-8",
    )
    result = run_audit(root)
    assert (
        "Lambda timeout must be an integer between 1 and 900 seconds"
        in result.stdout
    )
    assert "Traceback" not in result.stderr


def test_non_scalar_image_platform_is_rejected(tmp_path: Path) -> None:
    root = fixture_root(tmp_path)
    manifest = root / "platform.yaml"
    manifest.write_text(
        manifest.read_text(encoding="utf-8").replace(
            "platforms: [linux/arm64, linux/amd64]",
            "platforms: [linux/arm64, {arch: linux/amd64}]",
        ),
        encoding="utf-8",
    )
    result = run_audit(root)
    assert "both Arm64 and x86 platforms must be declared" in result.stdout
    assert "Traceback" not in result.stderr


def test_dockerfile_outside_repository_is_rejected(tmp_path: Path) -> None:
    root = fixture_root(tmp_path)
    outside = tmp_path.parent / f"{tmp_path.name}.Dockerfile"
    outside.write_text(
        "FROM python:3.12 AS builder\nFROM python:3.12\nUSER app\n",
        encoding="utf-8",
    )
    manifest = root / "platform.yaml"
    manifest.write_text(
        manifest.read_text(encoding="utf-8").replace(
            "dockerfile: Dockerfile",
            f"dockerfile: ../{outside.name}",
        ),
        encoding="utf-8",
    )
    result = run_audit(root)
    assert "Dockerfile path escapes repository" in result.stdout
    assert "Traceback" not in result.stderr


def test_scheduled_activity_gate_must_be_a_nonempty_string(tmp_path: Path) -> None:
    root = fixture_root(tmp_path)
    manifest = root / "platform.yaml"
    manifest.write_text(
        manifest.read_text(encoding="utf-8").replace(
            "activity_gate: 2h", "activity_gate: true"
        ),
        encoding="utf-8",
    )
    result = run_audit(root)
    assert "scheduled job requires a nonempty activity gate" in result.stdout
