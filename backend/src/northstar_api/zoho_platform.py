from __future__ import annotations

import os
from dataclasses import dataclass, field
from urllib.parse import urlparse


class ZohoPlatformConfigurationError(RuntimeError):
    """Raised when the platform-managed Zoho OAuth application is incomplete."""


_DEFAULT_SCOPES = (
    "ZohoCRM.modules.ALL",
    "ZohoCRM.settings.ALL",
    "ZohoCRM.org.READ",
)


@dataclass(frozen=True, slots=True)
class ZohoPlatformConfiguration:
    client_id: str = field(repr=False)
    client_secret: str = field(repr=False)
    accounts_url: str = "https://accounts.zoho.com"
    api_domain: str = "https://www.zohoapis.com"
    api_version: str = "v8"
    scopes: tuple[str, ...] = _DEFAULT_SCOPES
    frontend_return_url: str = "http://localhost:3100/integrations"
    callback_url: str | None = None
    live_certification_enabled: bool = True

    @property
    def configured(self) -> bool:
        return bool(self.client_id and self.client_secret)

    def provider_configuration(self) -> dict[str, object]:
        return {
            "accountsUrl": self.accounts_url,
            "apiDomain": self.api_domain,
            "apiVersion": self.api_version,
            "oauthScopes": list(self.scopes),
            "duplicateCheckFields": ["Email"],
            "trigger": ["workflow"],
            "managedBy": "zoho-one-click",
        }


def _optional(name: str) -> str | None:
    value = os.getenv(name, "").strip()
    return value or None


def _boolean(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    normalized = raw.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ZohoPlatformConfigurationError(f"{name} must be true or false")


def _url(name: str, value: str, *, https_only: bool) -> str:
    parsed = urlparse(value)
    if not parsed.scheme or not parsed.netloc:
        raise ZohoPlatformConfigurationError(f"{name} must be an absolute URL")
    if parsed.username or parsed.password:
        raise ZohoPlatformConfigurationError(f"{name} must not contain URL credentials")
    if https_only and parsed.scheme != "https":
        raise ZohoPlatformConfigurationError(f"{name} must use HTTPS")
    if parsed.scheme not in {"http", "https"}:
        raise ZohoPlatformConfigurationError(f"{name} must use HTTP or HTTPS")
    if parsed.query or parsed.fragment:
        raise ZohoPlatformConfigurationError(f"{name} must not contain a query or fragment")
    return value.rstrip("/")


def load_zoho_platform_configuration(
    *,
    required: bool = False,
) -> ZohoPlatformConfiguration | None:
    client_id = _optional("ZOHO_CLIENT_ID")
    client_secret = _optional("ZOHO_CLIENT_SECRET")
    if bool(client_id) != bool(client_secret):
        raise ZohoPlatformConfigurationError(
            "ZOHO_CLIENT_ID and ZOHO_CLIENT_SECRET must be configured together"
        )
    if not client_id or not client_secret:
        if required:
            raise ZohoPlatformConfigurationError(
                "The platform-managed Zoho OAuth application is not configured"
            )
        return None

    accounts_url = _url(
        "ZOHO_ACCOUNTS_URL",
        _optional("ZOHO_ACCOUNTS_URL") or "https://accounts.zoho.com",
        https_only=True,
    )
    api_domain = _url(
        "ZOHO_API_DOMAIN",
        _optional("ZOHO_API_DOMAIN") or "https://www.zohoapis.com",
        https_only=True,
    )
    frontend_return_url = _url(
        "ZOHO_OAUTH_FRONTEND_URL",
        _optional("ZOHO_OAUTH_FRONTEND_URL") or "http://localhost:3100/integrations",
        https_only=False,
    )
    callback_value = _optional("ZOHO_OAUTH_REDIRECT_URI")
    callback_url = (
        _url("ZOHO_OAUTH_REDIRECT_URI", callback_value, https_only=True)
        if callback_value
        else None
    )
    raw_scopes = _optional("ZOHO_OAUTH_SCOPES")
    scopes = (
        tuple(item.strip() for item in raw_scopes.replace(" ", ",").split(",") if item.strip())
        if raw_scopes
        else _DEFAULT_SCOPES
    )
    if not scopes:
        raise ZohoPlatformConfigurationError("ZOHO_OAUTH_SCOPES must contain at least one scope")

    return ZohoPlatformConfiguration(
        client_id=client_id,
        client_secret=client_secret,
        accounts_url=accounts_url,
        api_domain=api_domain,
        api_version=_optional("ZOHO_API_VERSION") or "v8",
        scopes=scopes,
        frontend_return_url=frontend_return_url,
        callback_url=callback_url,
        live_certification_enabled=_boolean("ZOHO_LIVE_CERTIFICATION_ENABLED", True),
    )
