"""Read-only audit of the playbook's 23 hosting rules.

Static checks are intentionally narrower than production qualification.
Unverified dynamic rules are reported as such and fail strict conformance.
"""

from __future__ import annotations

import argparse
import ast
import re
from dataclasses import dataclass
from pathlib import Path

import yaml


@dataclass(frozen=True)
class Finding:
    rule: int
    state: str
    location: str
    detail: str


REQUIRED_TARGETS = (
    "bootstrap", "lint", "typecheck", "test", "conformance", "build",
    "image-push", "migrate", "deploy", "smoke", "local-up", "local-down",
)
PROCESS_KINDS = {"http", "queue", "event", "schedule", "job"}
TOP_LEVEL = {
    "apiVersion", "app", "deployment_status", "owner", "region", "stage", "tier",
    "budget_usd_month", "capability_registry", "images", "web", "processes",
    "resources", "secrets", "slo", "ci", "observability",
}
PROCESS_FIELDS = {
    "name", "kind", "image", "routes", "streaming_routes", "memory_mb",
    "timeout_s", "queue", "runtime", "handler", "topic", "ordered", "rate",
    "activity_gate", "command", "when", "cpu", "min_instances",
}
UNVERIFIED = {
    1: "complete inventory of all processes, dependencies, secrets and routes",
    2: "stage-specific runtime rendering for each process kind",
    3: "live health latency and PORT binding",
    4: "long-request queuing and client status behavior",
    5: "streaming heartbeat and 15-minute termination",
    6: "payload bounds and direct-to-object-storage uploads",
    7: "handler importability and one-message execution contract",
    8: "handler replay idempotency and timeout under load",
    9: "absence of polling inside scheduled job dependencies",
    10: "all database pool and session-lifetime paths",
    11: "all environment reads and startup secret resolution",
    12: "repository-wide secret scan and default cloud credential chain",
    13: "all dependency ports and vendor import boundaries",
    14: "process statelessness and ephemeral-write boundaries",
    15: "image size, browser/OCR isolation and both-platform builds",
    16: "SIGTERM shutdown within 30 seconds",
    17: "single migration head and expand/contract safety",
    18: "complete JSON telemetry and OpenTelemetry instrumentation",
    19: "versioned API contract compatibility",
    20: "tenant data, logs, metrics and PostgreSQL RLS coverage",
    21: "all model calls through capped tenant-budgeted LLM port",
    22: "CI and release tooling use only the standard Make targets",
    23: "nightly whole-app local-adapter Compose qualification",
}


class UniqueKeyLoader(yaml.SafeLoader):
    def construct_mapping(self, node: yaml.MappingNode, deep: bool = False) -> dict[object, object]:
        seen: set[object] = set()
        for key_node, _ in node.value:
            key = self.construct_object(key_node, deep=deep)
            try:
                duplicate = key in seen
                seen.add(key)
            except TypeError as exc:
                raise yaml.constructor.ConstructorError(
                    None, None, "YAML mapping key must be a scalar", key_node.start_mark
                ) from exc
            if duplicate:
                raise yaml.constructor.ConstructorError(
                    None, None, f"duplicate YAML key: {key}", key_node.start_mark
                )
        return super().construct_mapping(node, deep=deep)


def _finding(rule: int, state: str, location: str, detail: str) -> Finding:
    return Finding(rule, state, location, detail)


def _handler_finding(root: Path, value: object, process: str) -> Finding | None:
    if not isinstance(value, str) or not re.fullmatch(r"northstar_api(?:\.[A-Za-z_]\w*)+:[A-Za-z_]\w*", value):
        return _finding(7, "fail", "platform.yaml", f"{process}: invalid handler reference")
    module, function = value.split(":", 1)
    path = root / "backend" / "src" / (module.replace(".", "/") + ".py")
    if not path.resolve().is_relative_to(root.resolve()):
        return _finding(7, "fail", str(path), f"{process}: handler path escapes repository")
    if not path.is_file():
        return _finding(7, "fail", str(path), f"{process}: handler module is missing")
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (OSError, SyntaxError) as exc:
        return _finding(7, "fail", str(path), f"{process}: handler source cannot parse: {exc}")
    if not any(isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == function for node in tree.body):
        return _finding(7, "fail", str(path), f"{process}: callable {function} is not defined")
    return None


def audit(root: Path) -> list[Finding]:
    findings: list[Finding] = []
    manifest = root / "platform.yaml"
    try:
        data = yaml.load(manifest.read_text(encoding="utf-8"), Loader=UniqueKeyLoader)
    except (OSError, yaml.YAMLError) as exc:
        return [_finding(1, "fail", str(manifest), f"cannot load manifest: {exc}")]
    if not isinstance(data, dict):
        return [_finding(1, "fail", str(manifest), "manifest must be a mapping")]
    missing = {"apiVersion", "app", "owner", "region", "stage", "images", "processes", "resources", "secrets"} - data.keys()
    extra = data.keys() - TOP_LEVEL
    for key in sorted(missing):
        findings.append(_finding(1, "fail", "platform.yaml", f"required field missing: {key}"))
    for key in sorted(extra):
        findings.append(_finding(1, "fail", "platform.yaml", f"unknown field: {key}"))
    if data.get("apiVersion") != "platform/v1":
        findings.append(_finding(1, "fail", "platform.yaml", "unsupported apiVersion"))
    if data.get("deployment_status") != "planned":
        findings.append(_finding(1, "fail", "platform.yaml", "uncertified deployment must remain planned"))
    stage = data.get("stage")
    if type(stage) is not int or stage not in range(5) or data.get("tier") != f"T{stage}":
        findings.append(_finding(1, "fail", "platform.yaml", "stage and tier must agree in the 0-4 ladder"))
    budget = data.get("budget_usd_month")
    if type(budget) is not int or budget <= 0:
        findings.append(_finding(1, "fail", "platform.yaml", "monthly budget must be a positive integer"))

    images = data.get("images")
    processes = data.get("processes")
    resources = data.get("resources")
    if not isinstance(images, dict) or not isinstance(processes, list) or not isinstance(resources, dict):
        findings.append(_finding(1, "fail", "platform.yaml", "images, processes and resources need their declared types"))
        return findings
    if not processes:
        findings.append(_finding(1, "fail", "platform.yaml", "at least one process is required"))
    if not isinstance(data.get("secrets"), list):
        findings.append(_finding(1, "fail", "platform.yaml", "secrets must be a list"))
    queues = resources.get("queues")
    if not isinstance(queues, list):
        findings.append(_finding(1, "fail", "platform.yaml", "resources.queues must be a list"))
        queues = []
    elif any(not isinstance(queue, str) or not queue for queue in queues):
        findings.append(_finding(1, "fail", "platform.yaml", "resources.queues must contain nonempty names"))
    elif len(set(queues)) != len(queues):
        findings.append(_finding(1, "fail", "platform.yaml", "resources.queues names must be unique"))
    raw_topics = resources.get("topics", [])
    if not isinstance(raw_topics, list):
        findings.append(_finding(1, "fail", "platform.yaml", "resources.topics must be a list"))
        raw_topics = []
    topics: set[str] = set()
    for topic in raw_topics:
        name = topic.get("name") if isinstance(topic, dict) else topic
        if not isinstance(name, str) or not name or name in topics:
            findings.append(_finding(1, "fail", "platform.yaml", "resources.topics has an invalid or duplicate name"))
        else:
            topics.add(name)
    names: set[str] = set()
    for index, process in enumerate(processes):
        location = f"platform.yaml:processes[{index}]"
        if not isinstance(process, dict):
            findings.append(_finding(2, "fail", location, "process must be a mapping"))
            continue
        name = process.get("name")
        kind = process.get("kind")
        if not isinstance(name, str) or not name or name in names:
            findings.append(_finding(1, "fail", location, "process name missing or duplicate"))
        names.add(str(name))
        if not isinstance(kind, str) or kind not in PROCESS_KINDS:
            findings.append(_finding(2, "fail", location, f"unknown process kind: {kind}"))
        for field in sorted(process.keys() - PROCESS_FIELDS):
            findings.append(_finding(1, "fail", location, f"unknown process field: {field}"))
        image_name = process.get("image")
        if not isinstance(image_name, str) or image_name not in images:
            findings.append(_finding(1, "fail", location, "process image is undeclared"))
        if kind == "http" and not process.get("routes"):
            findings.append(_finding(1, "fail", location, "HTTP routes missing"))
        if kind == "queue" and process.get("queue") not in queues:
            findings.append(_finding(1, "fail", location, "queue resource is undeclared"))
        if kind == "event" and process.get("topic") not in topics:
            findings.append(_finding(1, "fail", location, "event topic resource is undeclared"))
        if kind == "schedule" and (not isinstance(process.get("activity_gate"), str) or not process["activity_gate"].strip()):
            findings.append(_finding(9, "fail", location, "scheduled job requires a nonempty activity gate"))
        if kind in {"queue", "event", "schedule"}:
            issue = _handler_finding(root, process.get("handler"), str(name))
            if issue:
                findings.append(issue)
        if process.get("runtime") == "lambda" and (type(process.get("timeout_s")) is not int or not 1 <= process["timeout_s"] <= 900):
            findings.append(_finding(8, "fail", location, "Lambda timeout must be an integer between 1 and 900 seconds"))

    makefile = root / "Makefile"
    make_text = makefile.read_text(encoding="utf-8") if makefile.is_file() else ""
    targets = set(re.findall(r"(?m)^([a-z][a-z-]*):", make_text))
    for target in REQUIRED_TARGETS:
        if target not in targets:
            findings.append(_finding(22 if target not in {"local-up", "local-down"} else 23,
                                     "fail", "Makefile", f"required target missing: {target}"))

    for name, image in images.items():
        if not isinstance(image, dict) or not isinstance(image.get("dockerfile"), str):
            findings.append(_finding(15, "fail", "platform.yaml", f"{name}: Dockerfile missing"))
            continue
        declared_path = Path(image["dockerfile"])
        dockerfile = (root / declared_path).resolve()
        if declared_path.is_absolute() or not dockerfile.is_relative_to(root.resolve()):
            findings.append(_finding(15, "fail", "platform.yaml", f"{name}: Dockerfile path escapes repository"))
            continue
        if not dockerfile.is_file():
            findings.append(_finding(15, "fail", str(dockerfile), f"{name}: Dockerfile not found"))
            continue
        try:
            source = dockerfile.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            findings.append(_finding(15, "fail", str(dockerfile), f"{name}: Dockerfile unreadable: {exc}"))
            continue
        if not re.search(r"(?im)^USER\s+(?!root\b)\S+", source):
            findings.append(_finding(15, "fail", str(dockerfile), f"{name}: non-root runtime user not declared"))
        if len(re.findall(r"(?im)^FROM\s+", source)) < 2:
            findings.append(_finding(15, "fail", str(dockerfile), f"{name}: multi-stage build missing"))
        platforms = image.get("platforms", [])
        if (not isinstance(platforms, list) or
                any(not isinstance(platform, str) for platform in platforms) or
                not {"linux/arm64", "linux/amd64"}.issubset(platforms)):
            findings.append(_finding(15, "fail", "platform.yaml", f"{name}: both Arm64 and x86 platforms must be declared"))

    for rule, detail in UNVERIFIED.items():
        findings.append(_finding(rule, "unverified", "qualification", detail))
    return sorted(findings, key=lambda item: (item.rule, item.state, item.location, item.detail))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--report-only", action="store_true", help="print gaps without failing")
    args = parser.parse_args()
    findings = audit(args.root.resolve())
    for finding in findings:
        print(f"rule {finding.rule:02d} [{finding.state}] {finding.location}: {finding.detail}")
    print(f"conformance: {len(findings)} unresolved findings; no production qualification implied")
    return 0 if args.report_only or not findings else 1


if __name__ == "__main__":
    raise SystemExit(main())
