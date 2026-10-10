"""Explicit, fail-closed notification worker composition and lifecycle.

Production startup must supply trusted, qualified route/secret/egress
dependencies and a deliberate enablement decision. No worker is started by
importing this module, and no insecure/default transport is created.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from .queue_notification_config import ApprovedTransportFactory, ApprovedRouteRepository, ApprovedTenantTransportResolver
from .queue_notification_dispatch import NotificationDispatcher
from .queue_notification_routing import RoutedAlertNotificationTransport
from .queue_notification_worker import NotificationWorker, NotificationWorkerSettings


class WorkerQualification(Protocol):
    async def verify(self) -> bool: ...


@dataclass(frozen=True)
class NotificationRuntimeConfiguration:
    enabled: bool = False
    qualification_id: str | None = None
    lease_seconds: int = 60
    max_attempts: int = 8
    max_batch: int = 20
    poll_seconds: float = 2.0

    def __post_init__(self) -> None:
        if self.lease_seconds < 2 or self.max_attempts < 1:
            raise ValueError("invalid notification lease/retry limits")
        NotificationWorkerSettings(
            enabled=self.enabled,
            max_batch=self.max_batch,
            poll_seconds=self.poll_seconds,
        )
        if self.enabled and (not self.qualification_id or not self.qualification_id.strip()):
            raise ValueError("enabled notification runtime requires qualification evidence")


class NotificationRuntime:
    def __init__(
        self, *,
        sessions: async_sessionmaker[AsyncSession],
        routes: ApprovedRouteRepository,
        transports: ApprovedTransportFactory,
        qualification: WorkerQualification,
        configuration: NotificationRuntimeConfiguration | None = None,
    ) -> None:
        self.configuration = configuration or NotificationRuntimeConfiguration()
        self._qualification = qualification
        resolver = ApprovedTenantTransportResolver(routes, transports)
        dispatcher = NotificationDispatcher(
            sessions, RoutedAlertNotificationTransport(resolver),
            lease_seconds=self.configuration.lease_seconds,
            max_attempts=self.configuration.max_attempts,
        )
        self.worker = NotificationWorker(
            dispatcher,
            settings=NotificationWorkerSettings(
                enabled=self.configuration.enabled,
                poll_seconds=self.configuration.poll_seconds,
                max_batch=self.configuration.max_batch,
            ),
        )

    async def run(self) -> None:
        """One explicit, blocking lifecycle entry point; never autostarts."""
        if not self.configuration.enabled:
            return
        # A missing/failed independent deployment qualification is fatal,
        # before the worker can claim any outbox record.
        if await self._qualification.verify() is not True:
            raise PermissionError("notification worker qualification failed")
        await self.worker.run()

    def request_stop(self) -> None:
        self.worker.request_stop()
