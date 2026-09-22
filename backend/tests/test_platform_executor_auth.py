from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from pydantic import SecretStr, ValidationError

from northstar_api.config import Settings
from northstar_api.modules.super_admin.api import platform_executor


def test_platform_executor_report_token_is_required_and_compared(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        platform_executor,
        "get_settings",
        lambda: SimpleNamespace(platform_change_report_token=SecretStr("report-secret-value")),
    )

    with pytest.raises(HTTPException) as missing:
        platform_executor._require_executor_token(None)
    assert missing.value.status_code == 401

    with pytest.raises(HTTPException) as wrong:
        platform_executor._require_executor_token("Bearer wrong-secret")
    assert wrong.value.status_code == 401

    platform_executor._require_executor_token("Bearer report-secret-value")


def test_platform_executor_report_endpoint_is_disabled_without_server_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        platform_executor,
        "get_settings",
        lambda: SimpleNamespace(platform_change_report_token=None),
    )
    with pytest.raises(HTTPException) as exc:
        platform_executor._require_executor_token("Bearer any-value")
    assert exc.value.status_code == 503


def test_platform_executor_settings_must_be_configured_as_a_complete_set() -> None:
    with pytest.raises(ValidationError, match="PLATFORM_CHANGE_REPORT_TOKEN"):
        Settings(
            platform_change_executor_url="https://executor.example.com/dispatch",
            platform_change_executor_token=SecretStr("outbound-secret"),
        )

    configured = Settings(
        platform_change_executor_url="https://executor.example.com/dispatch",
        platform_change_executor_token=SecretStr("outbound-secret"),
        platform_change_report_token=SecretStr("callback-secret"),
    )
    assert configured.platform_change_executor_url == "https://executor.example.com/dispatch"


def test_platform_executor_url_rejects_query_or_fragment() -> None:
    with pytest.raises(ValidationError, match="query string or fragment"):
        Settings(
            platform_change_executor_url="https://executor.example.com/dispatch?unsafe=1",
            platform_change_executor_token=SecretStr("outbound-secret"),
            platform_change_report_token=SecretStr("callback-secret"),
        )
