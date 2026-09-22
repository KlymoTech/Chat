"""Provider-neutral platform configuration and dependency contracts."""

from .contracts import DeploymentProfile, PlatformSpec, ProviderChangeClass
from .control_plane import ChangePlan, PlanAction, build_change_plan, spec_digest
from .validation import (
    DependencyGraph,
    PlatformSpecError,
    build_dependency_graph,
    classify_provider_change,
    validate_platform_spec,
)

__all__ = [
    "DependencyGraph",
    "ChangePlan",
    "DeploymentProfile",
    "PlatformSpec",
    "PlatformSpecError",
    "PlanAction",
    "ProviderChangeClass",
    "build_dependency_graph",
    "build_change_plan",
    "classify_provider_change",
    "spec_digest",
    "validate_platform_spec",
]
