"""Pure, read-only queue alert classification.

Alerts describe one observation only. No notification is emitted until an
independent worker applies persistence, deduplication, and routing policy.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class QueueAlertThresholds:
    warning_pending_seconds: int = 300
    critical_pending_seconds: int = 900
    warning_overdue: int = 5
    critical_overdue: int = 50
    warning_dead_letters: int = 1
    critical_dead_letters: int = 10

    def __post_init__(self) -> None:
        pairs = (
            (self.warning_pending_seconds, self.critical_pending_seconds),
            (self.warning_overdue, self.critical_overdue),
            (self.warning_dead_letters, self.critical_dead_letters),
        )
        if any(low < 1 or high < low for low, high in pairs):
            raise ValueError("alert thresholds must be positive and ordered")


@dataclass(frozen=True)
class QueueAlert:
    code: str
    severity: str
    scope: str
    observed: int | str | None
    reason: str

    def as_json(self) -> dict[str, object]:
        return asdict(self)


def classify_queue_alerts(
    overview: dict[str, Any],
    *,
    thresholds: QueueAlertThresholds | None = None,
) -> tuple[QueueAlert, ...]:
    """Classify tenant backlog and shared broker observations independently."""
    policy = thresholds or QueueAlertThresholds()
    durable = overview["durable_jobs"]
    tenant = str(overview["tenant_id"])
    if str(durable["tenant_id"]) != tenant:
        raise ValueError("tenant health payload does not match requested scope")
    counts = durable["counts"]
    alerts: list[QueueAlert] = []

    def add_metric(code: str, observed: int, warning: int, critical: int) -> None:
        if observed < warning:
            return
        severity = "critical" if observed >= critical else "warning"
        alerts.append(QueueAlert(code, severity, "tenant", observed, "threshold_exceeded"))

    add_metric("queue_overdue", int(durable["overdue"]), policy.warning_overdue, policy.critical_overdue)
    add_metric("queue_dead_letters", int(counts["dead_letter"]),
               policy.warning_dead_letters, policy.critical_dead_letters)
    add_metric("queue_stale_leases", int(durable["stale_leases"]), 1, 5)
    pending_age = durable.get("oldest_pending_seconds")
    if pending_age is not None:
        add_metric("queue_pending_age", int(pending_age),
                   policy.warning_pending_seconds, policy.critical_pending_seconds)

    for name in ("sqs", "rabbitmq"):
        probe = overview["brokers"].get(name)
        if probe is None or probe.get("status") == "unconfigured":
            # An inactive provider is not an outage and not proven healthy.
            continue
        status = str(probe.get("status", "unknown"))
        if status == "unavailable":
            alerts.append(QueueAlert(f"{name}_probe_failed", "warning", "shared_queue",
                                     status, "broker_probe_unavailable"))
        elif status != "healthy":
            alerts.append(QueueAlert(f"{name}_probe_unknown", "unknown", "shared_queue",
                                     status, "broker_health_unconfirmed"))
    return tuple(alerts)
