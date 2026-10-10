"""DynamoDB on-demand activity marker adapter for scheduled jobs.

The supplied client uses the workload IAM role. This adapter does not create
the table and never opens a relational database connection.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any


class DynamoDbActivityMarker:
    def __init__(self, client: Any, table_name: str) -> None:
        if not table_name:
            raise ValueError("activity marker table name is required")
        self.client = client
        self.table_name = table_name

    async def last_activity(self, key: str) -> datetime | None:
        if not key:
            raise ValueError("activity marker key is required")
        response = await asyncio.to_thread(
            self.client.get_item,
            TableName=self.table_name,
            Key={"activity_key": {"S": key}},
            ConsistentRead=True,
        )
        item = response.get("Item")
        if not item:
            return None
        raw = item.get("last_activity_epoch", {}).get("N")
        if raw is None:
            raise ValueError("activity marker is missing last_activity_epoch")
        try:
            return datetime.fromtimestamp(int(raw), UTC)
        except (ValueError, OverflowError, TypeError) as exc:
            raise ValueError("activity marker timestamp is invalid") from exc

    async def mark_activity(self, key: str, *, at: datetime) -> None:
        if not key or at.tzinfo is None:
            raise ValueError("activity marker requires a key and aware timestamp")
        epoch = int(at.timestamp())
        if epoch < 0:
            raise ValueError("activity marker timestamp must be nonnegative")
        await asyncio.to_thread(
            self.client.update_item,
            TableName=self.table_name,
            Key={"activity_key": {"S": key}},
            UpdateExpression="SET last_activity_epoch = :timestamp",
            ConditionExpression="attribute_not_exists(last_activity_epoch) OR last_activity_epoch <= :timestamp",
            ExpressionAttributeValues={":timestamp": {"N": str(epoch)}},
        )
