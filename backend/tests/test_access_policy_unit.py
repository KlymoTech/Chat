from itertools import product

import pytest

from northstar_api.access_policy import (
    ORGANIZATION_GRANTS, ORGANIZATION_PERMISSIONS, WORKSPACE_GRANTS, WORKSPACE_PERMISSIONS,
    effective_permissions, permits, validate_delegated_permissions,
)

@pytest.mark.parametrize("role", WORKSPACE_GRANTS)
@pytest.mark.parametrize("permission", sorted(ORGANIZATION_PERMISSIONS - {"organization.view"}))
def test_workspace_roles_never_grant_organization_authority(role, permission):
    assert not permits(permission, "member", effective_permissions("member", role), has_workspace=True)

@pytest.mark.parametrize("permission", sorted(WORKSPACE_PERMISSIONS))
def test_org_owner_does_not_override_explicit_viewer_role(permission):
    allowed = permits(permission, "owner", effective_permissions("owner", "viewer"), has_workspace=True)
    assert allowed == (permission in WORKSPACE_GRANTS["viewer"])

@pytest.mark.parametrize("permission", sorted(WORKSPACE_PERMISSIONS))
def test_workspace_grants_require_workspace(permission):
    assert not permits(permission, "owner", effective_permissions("owner", "workspace_admin"), has_workspace=False)

@pytest.mark.parametrize("role,permission", list(product(ORGANIZATION_GRANTS, ORGANIZATION_PERMISSIONS)))
def test_organization_authority_does_not_require_fake_workspace(role, permission):
    assert permits(permission, role, effective_permissions(role, None), has_workspace=False) == (
        permission in ORGANIZATION_GRANTS[role]
    )

def test_unknowns_and_wildcards_deny():
    for permission in ("*", "platform.manage", "billing.typo", "agents.typo"):
        assert not permits(permission, "owner", frozenset({"*", permission}), has_workspace=True)
    assert not permits("billing.manage", "member", frozenset({"*", "billing.manage"}), has_workspace=True)
    assert not (WORKSPACE_PERMISSIONS & ORGANIZATION_PERMISSIONS)
    assert all("*" not in value for value in [*WORKSPACE_GRANTS.values(), *ORGANIZATION_GRANTS.values()])

@pytest.mark.parametrize("permissions", [["*"], ["billing.manage"], ["unknown"], [], ["agents.delete"]])
def test_role_delegation_cannot_escalate(permissions):
    with pytest.raises(ValueError):
        validate_delegated_permissions(permissions, WORKSPACE_GRANTS["viewer"])

def test_valid_delegation():
    assert validate_delegated_permissions(["agents.view"], WORKSPACE_GRANTS["viewer"]) == {"agents.view"}
