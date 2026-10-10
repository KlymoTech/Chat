"""Gate scheduled work on a cheap activity marker before touching PostgreSQL.

The caller supplies a lazy operation. No database session should be created
until the marker has been checked. Marker read failures propagate so the
scheduler can retry; they never trigger a database wake-up.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Protocol


class ActivityMarker(Protocol):
    async def last_activity(self, key: str) -> datetime | None: ...


async def run_if_recently_active[T](
    marker: ActivityMarker,
    key: str,
    operation: Callable[[], Awaitable[T]],
    *,
    now: datetime,
    window: timedelta = timedelta(hours=2),
) -> tuple[bool, T | None]:
    """Run an operation only when the marker lies in the recent window."""
    if not key or now.tzinfo is None or window <= timedelta(0):
        raise ValueError("activity gate requires a key, aware clock and positive window")
    last = await marker.last_activity(key)
    if last is None:
        return False, None
    if last.tzinfo is None:
        raise ValueError("activity marker timestamp must be timezone-aware")
    age = now.astimezone(UTC) - last.astimezone(UTC)
    if age < timedelta(0):
        raise ValueError("activity marker timestamp cannot be in the future")
    if age > window:
        return False, None
    return True, await operation()
