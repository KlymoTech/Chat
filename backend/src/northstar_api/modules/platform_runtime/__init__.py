"""Provider-neutral platform configuration and dependency contracts."""

from .capacity import CapacityBudget, build_capacity_budget
from .contracts import DeploymentProfile, PlatformSpec, ProviderChangeClass
from .control_plane import ChangePlan, PlanAction, build_change_plan, spec_digest
from .registry import (
    CapabilityCatalog,
    CapabilityChangeAnalysis,
    CapabilityDefinition,
    CapabilityDependencyGraph,
    CapabilityState,
    analyze_capability_change,
    build_capability_catalog,
    capability_definitions,
)
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
    "CapacityBudget",
    "CapabilityCatalog",
    "CapabilityChangeAnalysis",
    "CapabilityDefinition",
    "CapabilityDependencyGraph",
    "CapabilityState",
    "DeploymentProfile",
    "PlatformSpec",
    "PlatformSpecError",
    "PlanAction",
    "ProviderChangeClass",
    "build_dependency_graph",
    "build_change_plan",
    "build_capacity_budget",
    "build_capability_catalog",
    "analyze_capability_change",
    "capability_definitions",
    "classify_provider_change",
    "spec_digest",
    "validate_platform_spec",
]
