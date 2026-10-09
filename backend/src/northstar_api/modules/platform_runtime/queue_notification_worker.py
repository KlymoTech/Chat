"""Bounded, opt-in notification worker lifecycle.

The deployment composition root supplies the already qualified dispatcher.
No background task is launched on import. A disabled worker cannot claim
outbox records or send messages. Shutdown drains the current dispatch.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Protocol


class DispatchOnce(Protocol):
    async def dispatch_one(self) -> bool: ...


@dataclass(frozen=True)
class NotificationWorkerSettings:
    enabled: bool = False
    poll_seconds: float = 2.0
    max_batch: int = 20

    def __post_init__(self) -> None:
        if not 0.1 <= self.poll_seconds <= 60:
            raise ValueError("poll_seconds must be between 0.1 and 60")
        if not 1 <= self.max_batch <= 100:
            raise ValueError("max_batch must be between 1 and 100")


class NotificationWorker:
    def __init__(
        self, dispatcher: DispatchOnce, *,
        settings: NotificationWorkerSettings | None = None,
    ) -> None:
        self.dispatcher = dispatcher
        self.settings = settings or NotificationWorkerSettings()
        self._stop = asyncio.Event()
        self._running = False

    def request_stop(self) -> None:
        self._stop.set()

    async def run_once(self) -> int:
        """Process at most one configured batch; never loop forever."""
        if not self.settings.enabled or self._stop.is_set():
            return 0
        processed = 0
        for _ in range(self.settings.max_batch):
            if self._stop.is_set():
                break
            # A false result means the queue was empty or no state was
            # committed (including a stale lease). Avoid a tight retry loop.
            if not await self.dispatcher.dispatch_one():
                break
            processed += 1
        return processed

    async def run(self) -> None:
        """Run only when explicitly enabled; stop between deliveries."""
        if not self.settings.enabled:
            return
        if self._running:
            raise RuntimeError("notification worker already running")
        self._running = True
        try:
            while not self._stop.is_set():
                await self.run_once()
                if self._stop.is_set():
                    break
                try:
                    await asyncio.wait_for(self._stop.wait(), timeout=self.settings.poll_seconds)
                except TimeoutError:
                    continue
        finally:
            self._running = False
