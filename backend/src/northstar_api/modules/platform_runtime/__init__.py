"""Provider-neutral platform configuration and dependency contracts."""

from .capacity import CapacityBudget, build_capacity_budget
from .contracts import DeploymentProfile, PlatformSpec, ProviderChangeClass
from .control_plane import (
    ChangeLifecycleError,
    ChangePlan,
    ChangeStatus,
    PlanAction,
    approver_is_distinct,
    build_change_plan,
    spec_digest,
    transition_change,
)
from .executor_contract import DeploymentDispatchEvent, DeploymentExecutionReport, ExecutionPhase
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
    "ChangeLifecycleError",
    "ChangeStatus",
    "CapacityBudget",
    "DeploymentDispatchEvent",
    "DeploymentExecutionReport",
    "ExecutionPhase",
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
    "approver_is_distinct",
    "capability_definitions",
    "classify_provider_change",
    "spec_digest",
    "transition_change",
    "validate_platform_spec",
]
