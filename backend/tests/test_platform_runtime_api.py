from northstar_api.modules.platform_runtime import build_capacity_budget
from northstar_api.modules.super_admin.api.runtime import _declared_platform_spec, router


def test_runtime_control_plane_exposes_only_read_and_plan_operations() -> None:
    routes = {(route.path, tuple(sorted(route.methods or ()))) for route in router.routes}
    assert ("/platform-admin/runtime/capabilities", ("GET",)) in routes
    assert ("/platform-admin/runtime/dependencies", ("GET",)) in routes
    assert ("/platform-admin/runtime/capacity", ("GET",)) in routes
    assert ("/platform-admin/runtime/changes/plan", ("POST",)) in routes
    assert not any("destroy" in path or path.endswith("/apply") for path, _ in routes)


def test_declared_runtime_spec_is_valid_without_exposing_secrets() -> None:
    spec = _declared_platform_spec()
    assert spec.metadata.environment in {"development", "test", "staging", "production"}
    assert spec.providers.ai in {"none", "nvidia"}
    assert spec.deployment.account_id is None


def test_capacity_budget_is_explicitly_not_a_user_guarantee() -> None:
    budget = build_capacity_budget(api_replicas=3, database_pool_size=10, database_max_overflow=20)
    assert budget.database_connection_budget == 90
    assert budget.model_concurrency_budget == 48
    assert budget.active_user_guarantee is None
    assert budget.measured is False
