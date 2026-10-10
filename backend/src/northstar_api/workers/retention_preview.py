"""Explicitly scoped read-only retention inventory CLI (NO deletion)."""

from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import asdict
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import text

from northstar_api.config import get_settings
from northstar_api.database import build_engine
from northstar_api.services.retention_preview import preview_conversation_retention


async def run(*, tenant_id: UUID, workspace_id: UUID, limit: int) -> None:
    # Use a fresh DB transaction and deny writes inside PostgreSQL itself.
    engine = build_engine(get_settings())
    try:
        async with engine.connect() as connection:
            if connection.dialect.name == "postgresql":
                await connection.execute(text("SET TRANSACTION READ ONLY"))
                await connection.execute(
                    text("SELECT set_config('app.tenant_id', :tenant_id, true)"),
                    {"tenant_id": str(tenant_id)},
                )
            preview = await preview_conversation_retention(
                connection,
                tenant_id=tenant_id,
                workspace_id=workspace_id,
                as_of=datetime.now(UTC),
                max_rows=limit,
            )
            print(json.dumps(asdict(preview), default=str, sort_keys=True))
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description="Read-only scoped retention candidate preview")
    parser.add_argument("--tenant-id", type=UUID, required=True)
    parser.add_argument("--workspace-id", type=UUID, required=True)
    parser.add_argument("--limit", type=int, default=500)
    args = parser.parse_args()
    if not 1 <= args.limit <= 1_000:
        parser.error("--limit must be in 1..1000")
    asyncio.run(run(tenant_id=args.tenant_id, workspace_id=args.workspace_id, limit=args.limit))


if __name__ == "__main__":
    main()
