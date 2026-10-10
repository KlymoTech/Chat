"""Activity-gated bounded recovery for lost outbox nudges."""

from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime
from typing import Any

import boto3

from northstar_api.handlers.outbox_relay import BATCH_SIZE, run_once
from northstar_api.modules.platform_runtime.activity_gate import run_if_recently_active
from northstar_api.modules.platform_runtime.dynamodb_activity_marker import DynamoDbActivityMarker
from northstar_api.services.outbox import send_outbox_nudge


async def run() -> dict[str, int | str]:
    table = os.environ.get("PLATFORM_ACTIVITY_TABLE")
    key = os.environ.get("PLATFORM_ACTIVITY_KEY")
    if not table or not key:
        raise ValueError("PLATFORM_ACTIVITY_TABLE and PLATFORM_ACTIVITY_KEY are required")
    marker = DynamoDbActivityMarker(boto3.client("dynamodb"), table)
    ran, published = await run_if_recently_active(marker, key, run_once, now=datetime.now(UTC))
    if not ran:
        return {"status": "skipped", "published": 0}
    count = published or 0
    # The bounded relay may leave more rows. A follow-up message drains them
    # without requiring another scheduled database wake-up.
    if count == BATCH_SIZE and not send_outbox_nudge():
        raise RuntimeError("outbox recovery could not enqueue continuation")
    return {"status": "ran", "published": count}


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, int | str]:
    return asyncio.run(run())
