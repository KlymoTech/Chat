"""Canonical scoped grants. This module deliberately has no runtime dependencies.

An organization grant never authorizes workspace data. Workspace administrators
receive an explicit allowlist, never a wildcard. Unknown permissions deny access.
"""
from __future__ import annotations

ORGANIZATION_PERMISSIONS = frozenset({
    "organization.view", "organization.profile.update", "organization.members.invite",
    "organization.roles.manage", "organization.ownership.transfer", "organization.audit.view",
    "workspace.create", "billing.view", "billing.manage", "security.view", "security.manage",
    "usage.view", "organization.branding.edit", "organization.branding.publish",
})
WORKSPACE_PERMISSIONS = frozenset({
    "workspace.view", "workspace.update", "workspace.archive", "workspace.restore",
    "workspace.export", "workspace.delete", "members.view", "members.manage", "members.invite",
    "members.roles.assign", "roles.manage", "teams.manage", "agents.view", "agents.create",
    "agents.update", "agents.test", "agents.deploy", "agents.delete", "knowledge.view",
    "knowledge.manage", "knowledge.upload", "knowledge.approve", "knowledge.reindex",
    "knowledge.delete", "knowledge.export", "conversations.view", "conversations.reply",
    "conversations.resolve", "conversations.assign", "conversations.export", "conversations.delete",
    "leads.view", "leads.update", "leads.export", "integrations.view", "integrations.manage",
    "crm.view", "crm.manage", "crm.connections.manage", "crm.mapping.manage", "crm.deliveries.retry",
    "channels.view", "channels.manage", "channels.connections.manage", "analytics.view",
    "education.view", "education.manage", "education.courses.manage", "education.students.view",
    "education.students.manage", "education.enrollments.manage", "education.recovery.manage",
    "settings.view", "settings.manage", "branding.view", "branding.edit", "branding.publish",
    "branding.domain.manage", "audit.view", "audit.export", "api_keys.view", "api_keys.manage",
    "api_keys.create", "api_keys.rotate", "api_keys.revoke", "starter_content.read", "playground.use",
})

_READ = frozenset({
    "workspace.view", "agents.view", "knowledge.view", "conversations.view", "leads.view",
    "analytics.view", "education.view", "starter_content.read",
})
WORKSPACE_GRANTS: dict[str, frozenset[str]] = {
    "workspace_admin": WORKSPACE_PERMISSIONS,
    "manager": _READ | frozenset({
        "members.view", "agents.create", "agents.update", "agents.test", "agents.deploy",
        "knowledge.manage", "conversations.reply", "conversations.resolve", "conversations.assign",
        "leads.update", "leads.export", "integrations.view", "crm.view", "education.manage",
        "settings.view", "branding.view", "playground.use",
    }),
    "operator": (_READ - {"analytics.view"}) | frozenset({
        "conversations.reply", "conversations.resolve", "conversations.assign", "leads.update",
    }),
    "analyst": _READ | frozenset({"leads.export", "integrations.view", "crm.view"}),
    "viewer": _READ,
}
ORGANIZATION_GRANTS: dict[str, frozenset[str]] = {
    "owner": ORGANIZATION_PERMISSIONS,
    "admin": ORGANIZATION_PERMISSIONS - {"organization.ownership.transfer"},
    "billing_admin": frozenset({"organization.view", "billing.view", "billing.manage", "usage.view"}),
    "security_admin": frozenset({
        "organization.view", "security.view", "security.manage", "organization.audit.view",
    }),
    "member": frozenset({"organization.view"}),
    "analyst": frozenset({"organization.view"}),
}


def effective_permissions(organization_role: str, workspace_role: str | None) -> frozenset[str]:
    return ORGANIZATION_GRANTS.get(organization_role, frozenset()) | WORKSPACE_GRANTS.get(
        workspace_role or "", frozenset()
    )


def permits(permission: str, organization_role: str, grants: frozenset[str], *, has_workspace: bool) -> bool:
    """Validate the namespace as well as the grant; wildcard strings are inert."""
    if permission in ORGANIZATION_PERMISSIONS:
        return permission in ORGANIZATION_GRANTS.get(organization_role, frozenset()) and permission in grants
    return has_workspace and permission in WORKSPACE_PERMISSIONS and permission in grants


def validate_delegated_permissions(requested: list[str], actor_grants: frozenset[str]) -> frozenset[str]:
    selected = frozenset(requested)
    if not selected or not selected <= WORKSPACE_PERMISSIONS:
        raise ValueError("Select known workspace permissions only")
    if not selected <= actor_grants:
        raise ValueError("Cannot delegate a permission you do not hold")
    return selected
