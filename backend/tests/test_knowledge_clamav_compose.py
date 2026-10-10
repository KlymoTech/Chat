"""Contract tests for the opt-in local knowledge ClamAV Compose overlay.

These are read-only YAML checks, not evidence that Docker/clamd ran.
"""

from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


def _yaml(path: str) -> dict:
    result = yaml.safe_load((ROOT / path).read_text(encoding="utf-8"))
    assert isinstance(result, dict)
    return result


def test_base_compose_keeps_development_scanning_disabled_by_default() -> None:
    base = _yaml("compose.yaml")
    environment = base["x-api-environment"]
    assert environment["KNOWLEDGE_CLAMAV_ENABLED"] == "${KNOWLEDGE_CLAMAV_ENABLED:-false}"
    assert environment["KNOWLEDGE_CLAMAV_PORT"] == "${KNOWLEDGE_CLAMAV_PORT:-3310}"
    assert (
        environment["KNOWLEDGE_CLAMAV_TIMEOUT_SECONDS"]
        == "${KNOWLEDGE_CLAMAV_TIMEOUT_SECONDS:-120}"
    )
    assert "knowledge-clamav" not in base["services"]


def test_optional_sidecar_enables_api_scanning_without_replacing_api() -> None:
    override = _yaml("compose.knowledge-clamav.yaml")
    api = override["services"]["api"]
    assert set(api) == {"environment"}
    assert api["environment"]["KNOWLEDGE_CLAMAV_ENABLED"] == "true"
    assert api["environment"]["KNOWLEDGE_CLAMAV_PORT"] == "3310"


def test_sidecar_binds_only_to_api_loopback_with_no_exposed_port() -> None:
    override = _yaml("compose.knowledge-clamav.yaml")
    sidecar = override["services"]["knowledge-clamav"]
    assert sidecar["network_mode"] == "service:api"
    assert sidecar["depends_on"]["api"]["condition"] == "service_started"
    assert sidecar["environment"]["CLAMD_CONF_TCPAddr"] == "127.0.0.1"
    assert sidecar["environment"]["CLAMD_CONF_TCPSocket"] == "3310"
    assert not {"ports", "expose", "networks", "privileged"}.intersection(sidecar)
    assert sidecar["security_opt"] == ["no-new-privileges:true"]


def test_sidecar_fails_closed_on_scan_limits_and_persists_signatures() -> None:
    override = _yaml("compose.knowledge-clamav.yaml")
    sidecar = override["services"]["knowledge-clamav"]
    env = sidecar["environment"]
    assert env["CLAMD_CONF_StreamMaxLength"] == "500M"
    assert env["CLAMD_CONF_AlertExceedsMax"] == "yes"
    assert env["CLAMD_CONF_MaxFileSize"] == "500M"
    assert env["CLAMD_CONF_MaxScanSize"] == "550M"
    assert sidecar["volumes"] == ["knowledge_clamav_signatures:/var/lib/clamav"]
    assert "knowledge_clamav_signatures" in override["volumes"]
    assert sidecar["image"].startswith("clamav/clamav:1.5.4_")
    assert sidecar["mem_limit"] == "4g"


def test_env_examples_document_same_scanner_controls() -> None:
    for filename in (".env.example", "backend/.env.example"):
        content = (ROOT / filename).read_text(encoding="utf-8")
        assert "KNOWLEDGE_CLAMAV_ENABLED=false" in content
        assert "KNOWLEDGE_CLAMAV_PORT=3310" in content
        assert "KNOWLEDGE_CLAMAV_TIMEOUT_SECONDS=120" in content
