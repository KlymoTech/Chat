from __future__ import annotations

from dataclasses import dataclass


ALL_CHANNELS = frozenset(
    {
        "whatsapp",
        "instagram",
        "facebook_messenger",
        "telegram",
        "widget",
        "api",
        "slack",
        "custom",
    }
)


@dataclass(frozen=True, slots=True)
class PlanEntitlement:
    workspace_limit: int | None
    agent_limit: int | None
    member_limit: int | None
    conversation_limit_monthly: int | None
    token_limit_monthly: int | None
    storage_limit_bytes: int | None
    allowed_channels: frozenset[str]
    crm_enabled: bool
    api_enabled: bool
    white_label_enabled: bool


# Commercial defaults are intentionally centralized here so product/billing can
# change them later without scattering magic numbers across routers and workers.
# Business preserves the limits that the existing billing UI already presented.
PLAN_ENTITLEMENTS: dict[str, PlanEntitlement] = {
    "starter": PlanEntitlement(
        workspace_limit=1,
        agent_limit=2,
        member_limit=3,
        conversation_limit_monthly=1_000,
        token_limit_monthly=500_000,
        storage_limit_bytes=1 * 1024**3,
        allowed_channels=frozenset({"widget", "api"}),
        crm_enabled=False,
        api_enabled=True,
        white_label_enabled=False,
    ),
    "professional": PlanEntitlement(
        workspace_limit=3,
        agent_limit=5,
        member_limit=10,
        conversation_limit_monthly=3_000,
        token_limit_monthly=2_000_000,
        storage_limit_bytes=5 * 1024**3,
        allowed_channels=frozenset({"widget", "api", "whatsapp", "telegram", "slack"}),
        crm_enabled=True,
        api_enabled=True,
        white_label_enabled=False,
    ),
    "business": PlanEntitlement(
        workspace_limit=10,
        agent_limit=10,
        member_limit=20,
        conversation_limit_monthly=5_000,
        token_limit_monthly=5_000_000,
        storage_limit_bytes=20 * 1024**3,
        allowed_channels=ALL_CHANNELS,
        crm_enabled=True,
        api_enabled=True,
        white_label_enabled=True,
    ),
    "enterprise": PlanEntitlement(
        workspace_limit=None,
        agent_limit=None,
        member_limit=None,
        conversation_limit_monthly=None,
        token_limit_monthly=None,
        storage_limit_bytes=None,
        allowed_channels=ALL_CHANNELS,
        crm_enabled=True,
        api_enabled=True,
        white_label_enabled=True,
    ),
}

# Existing/custom tenant plans may predate this catalog. Fail open for unknown
# plans so introducing entitlements never removes capabilities from legacy
# customers. They can be mapped to a catalog plan explicitly by billing later.
CUSTOM_UNLIMITED_ENTITLEMENT = PlanEntitlement(
    workspace_limit=None,
    agent_limit=None,
    member_limit=None,
    conversation_limit_monthly=None,
    token_limit_monthly=None,
    storage_limit_bytes=None,
    allowed_channels=ALL_CHANNELS,
    crm_enabled=True,
    api_enabled=True,
    white_label_enabled=True,
)


def entitlement_for_plan(plan: str) -> PlanEntitlement:
    return PLAN_ENTITLEMENTS.get(plan.strip().lower(), CUSTOM_UNLIMITED_ENTITLEMENT)
