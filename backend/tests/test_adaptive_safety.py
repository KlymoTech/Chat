"""Unit tests of advisory capacity decision safety boundaries."""
import pytest

from northstar_api.modules.platform_runtime.adaptive_safety import (
    CapacityAction, CapacitySignals, advise_capacity,
)


def signals(**updates: object) -> CapacitySignals:
    values = dict(cpu_utilization=.5, memory_utilization=.5, request_error_rate=0.,
                  queue_oldest_age_seconds=0., samples_age_seconds=5.)
    values.update(updates)
    return CapacitySignals(**values)


def test_scale_out_allowed_only_with_valid_signal_and_headroom() -> None:
    result = advise_capacity(signals(cpu_utilization=.9), replicas=3)
    assert result.action is CapacityAction.SCALE_OUT
    assert result.permitted_for_automatic_horizontal_scaling
    assert not result.architectural_change_permitted


def test_stale_telemetry_blocks_autoscaling() -> None:
    result = advise_capacity(signals(samples_age_seconds=121, cpu_utilization=.95), replicas=3)
    assert result.action is CapacityAction.INVESTIGATE
    assert not result.permitted_for_automatic_horizontal_scaling


def test_incident_blocks_autoscaling() -> None:
    result = advise_capacity(signals(incident_active=True, cpu_utilization=.95), replicas=3)
    assert result.reason == "incident_guard"


def test_scale_in_requires_additional_sustained_evidence() -> None:
    result = advise_capacity(signals(cpu_utilization=.1, memory_utilization=.1), replicas=3)
    assert result.action is CapacityAction.SCALE_IN
    assert not result.permitted_for_automatic_horizontal_scaling


def test_replica_limit_fails_closed() -> None:
    result = advise_capacity(signals(cpu_utilization=.9), replicas=100)
    assert result.reason == "replica_ceiling_reached"


def test_invalid_signal_rejected() -> None:
    with pytest.raises(ValueError):
        signals(cpu_utilization=1.5)
