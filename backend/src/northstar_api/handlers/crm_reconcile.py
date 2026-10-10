"""Activity-gated Lambda entry point for CRM reconciliation."""

from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime
from typing import Any

import boto3
from sqlalchemy.ext.asyncio import async_sessionmaker

from northstar_api.config import get_settings
from northstar_api.database import build_engine
from northstar_api.modules.platform_runtime.activity_gate import run_if_recently_active
from northstar_api.modules.platform_runtime.dynamodb_activity_marker import DynamoDbActivityMarker
from northstar_api.workers.crm_reconciliation import run_once


async def run() -> dict[str, int] | None:
    table = os.environ.get("PLATFORM_ACTIVITY_TABLE")
    key = os.environ.get("PLATFORM_ACTIVITY_KEY")
    if not table or not key:
        raise ValueError("PLATFORM_ACTIVITY_TABLE and PLATFORM_ACTIVITY_KEY are required")

    marker = DynamoDbActivityMarker(boto3.client("dynamodb"), table)
    # SQLAlchemy engine creation does not connect, but keep even construction
    # inside the gated path to make the no-database-on-idle rule explicit.
    async def gated_operation() -> dict[str, int]:
        engine = build_engine(get_settings())
        try:
            factory = async_sessionmaker(engine, expire_on_commit=False)
            async with factory() as session:
                return await run_once(session)
        finally:
            await engine.dispose()

    ran, result = await run_if_recently_active(marker, key, gated_operation, now=datetime.now(UTC))
    return result if ran else None


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    result = asyncio.run(run())
    return {"status": "ran" if result is not None else "skipped", "result": result}
