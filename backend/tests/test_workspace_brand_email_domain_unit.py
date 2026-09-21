from __future__ import annotations

from uuid import uuid4

from northstar_api.models import Workspace
from northstar_api.modules.workspace.contracts import DomainRecord, ExtendedBranding, WorkspaceSettingsBundle
from northstar_api.modules.workspace.email_branding import render_workspace_email


def test_branded_email_action_uses_only_active_custom_domain() -> None:
    bundle = WorkspaceSettingsBundle()
    published = ExtendedBranding()
    published.identity.company_name = "Acme Academy"
    published.identity.branded_emails = True
    bundle.branding_published = published
    bundle.domains.domains = [
        DomainRecord(
            hostname="portal.acme.example",
            verification_name="_northstar-verify.portal.acme.example",
            verification_value="verified-token",
            status="active",
        )
    ]
    workspace = Workspace(
        tenant_id=uuid4(),
        name="Admissions",
        slug="admissions",
        settings_json={"workspaceSettingsV2": bundle.model_dump(by_alias=True, mode="json")},
    )

    rendered = render_workspace_email(
        workspace,
        "password_reset",
        context={},
        action_url="https://app.northstar.example/reset-password#token=secret",
        fallback_subject="Reset",
        fallback_heading="Reset",
        fallback_body="Reset your password",
        fallback_button_label="Reset password",
    )

    assert "https://portal.acme.example/reset-password#token=secret" in rendered.text
    assert "app.northstar.example" not in rendered.text


def test_branded_email_keeps_platform_url_until_domain_is_active() -> None:
    bundle = WorkspaceSettingsBundle()
    published = ExtendedBranding()
    published.identity.branded_emails = True
    bundle.branding_published = published
    bundle.domains.domains = [
        DomainRecord(
            hostname="portal.acme.example",
            verification_name="_northstar-verify.portal.acme.example",
            verification_value="verified-token",
            status="verified",
        )
    ]
    workspace = Workspace(
        tenant_id=uuid4(),
        name="Admissions",
        slug="admissions",
        settings_json={"workspaceSettingsV2": bundle.model_dump(by_alias=True, mode="json")},
    )

    rendered = render_workspace_email(
        workspace,
        "email_verification",
        context={},
        action_url="https://app.northstar.example/verify-email#token=secret",
        fallback_subject="Verify",
        fallback_heading="Verify",
        fallback_body="Verify your email",
        fallback_button_label="Verify email",
    )

    assert "https://app.northstar.example/verify-email#token=secret" in rendered.text
