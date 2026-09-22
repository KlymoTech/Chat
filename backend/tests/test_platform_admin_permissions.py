from northstar_api.routers.platform_admin import (
    PLATFORM_PERMISSIONS,
    platform_admin_permissions,
)


def test_platform_admin_defaults_to_full_access_for_legacy_allowlist() -> None:
    assert platform_admin_permissions("admin@example.com", "") == PLATFORM_PERMISSIONS


def test_platform_admin_permissions_are_server_configured_and_filtered() -> None:
    raw = '{"support@example.com":["platform.tenants.read","platform.support.impersonate","unknown"]}'
    assert platform_admin_permissions("support@example.com", raw) == {
        "platform.tenants.read",
        "platform.support.impersonate",
    }
    assert platform_admin_permissions("other@example.com", raw) == set()
