from __future__ import annotations

import pytest

from northstar_api.lead_crm.connectors import CRMFieldDefinition
from northstar_api.services.zoho_one_click import build_default_zoho_mapping
from northstar_api.zoho_platform import (
    ZohoPlatformConfigurationError,
    load_zoho_platform_configuration,
)


def test_platform_configuration_is_optional_and_never_contains_login_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("ZOHO_CLIENT_ID", raising=False)
    monkeypatch.delenv("ZOHO_CLIENT_SECRET", raising=False)
    assert load_zoho_platform_configuration(required=False) is None


def test_platform_configuration_requires_client_pair(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ZOHO_CLIENT_ID", "client-id")
    monkeypatch.delenv("ZOHO_CLIENT_SECRET", raising=False)
    with pytest.raises(ZohoPlatformConfigurationError, match="configured together"):
        load_zoho_platform_configuration(required=True)


def test_platform_configuration_redacts_secret_and_builds_provider_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ZOHO_CLIENT_ID", "client-id")
    monkeypatch.setenv("ZOHO_CLIENT_SECRET", "super-secret-value")
    monkeypatch.setenv("ZOHO_ACCOUNTS_URL", "https://accounts.zoho.in")
    monkeypatch.setenv("ZOHO_API_DOMAIN", "https://www.zohoapis.in")
    monkeypatch.setenv("ZOHO_OAUTH_FRONTEND_URL", "https://app.example.com/integrations")
    configuration = load_zoho_platform_configuration(required=True)
    assert configuration is not None
    assert "super-secret-value" not in repr(configuration)
    assert configuration.provider_configuration() == {
        "accountsUrl": "https://accounts.zoho.in",
        "apiDomain": "https://www.zohoapis.in",
        "apiVersion": "v8",
        "oauthScopes": [
            "ZohoCRM.modules.ALL",
            "ZohoCRM.settings.ALL",
            "ZohoCRM.org.READ",
        ],
        "duplicateCheckFields": ["Email"],
        "trigger": ["workflow"],
        "managedBy": "zoho-one-click",
    }


def test_default_mapping_covers_standard_leads_and_required_custom_fields() -> None:
    fields = [
        CRMFieldDefinition("First_Name", "First Name", "text"),
        CRMFieldDefinition("Last_Name", "Last Name", "text", required=True, nullable=False),
        CRMFieldDefinition("Email", "Email", "email", unique=True),
        CRMFieldDefinition("Mobile", "Mobile", "phone"),
        CRMFieldDefinition("Company", "Company", "text", required=True, nullable=False),
        CRMFieldDefinition("Description", "Description", "textarea"),
        CRMFieldDefinition(
            "Territory_Type",
            "Territory Type",
            "picklist",
            required=True,
            nullable=False,
            custom=True,
            picklist_values=("Domestic", "International"),
        ),
        CRMFieldDefinition(
            "External_Lookup",
            "External Lookup",
            "lookup",
            required=True,
            nullable=False,
            custom=True,
        ),
    ]
    definition, unsupported = build_default_zoho_mapping(
        fields,
        certification_email="northstar@example.com",
    )
    assert definition["fields"] == {
        "firstName": "First_Name",
        "lastName": "Last_Name",
        "email": "Email",
        "phone": "Mobile",
        "company": "Company",
        "qualificationReason": "Description",
    }
    assert definition["constants"] == {"Territory_Type": "Domestic"}
    assert unsupported == ["External_Lookup"]
