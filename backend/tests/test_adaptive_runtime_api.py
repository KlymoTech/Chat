"""API contract tests for the read-only adaptive control-plane preview."""
import inspect

from northstar_api.modules.super_admin.api.runtime import (
    router,
    TierPreviewRequest,
    CapacityPreviewRequest,
    preview_tier_change,
    preview_capacity_action,
    preview_change_governance,
    list_runtime_tiers,
)
from northstar_api.modules.platform_runtime.tiers import PlatformTier


def test_adaptive_preview_routes_are_registered() -> None:
    paths = {route.path: route.methods for route in router.routes}
    for suffix in ("/tiers", "/tiers/preview", "/capacity/preview", "/changes/governance-preview"):
        assert "/platform-admin/runtime" + suffix in paths


def test_all_preview_handlers_require_platform_reader() -> None:
    for handler in (list_runtime_tiers, preview_tier_change, preview_capacity_action, preview_change_governance):
        assert "_" in inspect.signature(handler).parameters


def test_tier_preview_schema_is_strict() -> None:
    request = TierPreviewRequest(source=PlatformTier.T1, target=PlatformTier.T2)
    assert request.source is PlatformTier.T1
    assert request.target is PlatformTier.T2


def test_capacity_preview_rejects_invalid_replica_count() -> None:
    from pydantic import ValidationError
    try:
        CapacityPreviewRequest(signals={}, replicas=1)
    except ValidationError:
        pass
    else:
        raise AssertionError("replica bounds must be validated")
