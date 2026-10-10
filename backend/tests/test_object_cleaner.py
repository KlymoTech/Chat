from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from unittest.mock import AsyncMock, MagicMock

from northstar_api.workers.event_utils import EventEnvelope
from northstar_api.workers.object_cleaner import cleanup_object_key, process_cleanup_event


def _deletion_event(*, tenant_id: UUID, object_key: object) -> EventEnvelope:
    return EventEnvelope(
        event_id=uuid4(),
        event_type="knowledge.source.deleted.v1",
        tenant_id=tenant_id,
        occurred_at=datetime.now(UTC),
        payload={"sourceId": str(uuid4()), "objectKey": object_key},
    )


def test_cleanup_object_key_accepts_only_its_tenant_prefix() -> None:
    tenant_id = uuid4()
    key = f"knowledge/{tenant_id}/2026/09/source.txt"

    assert cleanup_object_key(_deletion_event(tenant_id=tenant_id, object_key=key)) == key


def test_cleanup_object_key_rejects_a_different_tenant_prefix() -> None:
    event_tenant_id = uuid4()
    foreign_key = f"knowledge/{uuid4()}/2026/09/source.txt"

    with pytest.raises(ValueError, match="outside its tenant prefix"):
        cleanup_object_key(_deletion_event(tenant_id=event_tenant_id, object_key=foreign_key))


def test_cleanup_object_key_accepts_null_for_non_file_sources() -> None:
    assert cleanup_object_key(_deletion_event(tenant_id=uuid4(), object_key=None)) is None


def test_cleanup_object_key_rejects_missing_object_key() -> None:
    event = _deletion_event(tenant_id=uuid4(), object_key=None)
    del event.payload["objectKey"]

    with pytest.raises(ValueError, match="missing a valid sourceId or objectKey"):
        cleanup_object_key(event)



@pytest.mark.parametrize("malformed", [
    "extractions/foreign/source/file.zip",
    123,
    "",
])
def test_invalid_extraction_target_fails_preflight(malformed: object) -> None:
    tenant_id = uuid4()
    event = _deletion_event(
        tenant_id=tenant_id, object_key=f"knowledge/{tenant_id}/file.pdf"
    )
    event.payload["extractionKey"] = malformed
    with pytest.raises(ValueError, match="extractionKey"):
        cleanup_object_key(event)


def test_no_file_still_validates_extraction_target() -> None:
    event = _deletion_event(tenant_id=uuid4(), object_key=None)
    event.payload["extractionKey"] = "extractions/other/source/file.zip"
    with pytest.raises(ValueError, match="extractionKey"):
        cleanup_object_key(event)


@pytest.mark.asyncio
async def test_bad_extraction_target_never_touches_storage_or_database() -> None:
    tenant_id = uuid4()
    key = f"knowledge/{tenant_id}/file.pdf"
    event = _deletion_event(tenant_id=tenant_id, object_key=key)
    event.payload["extractionKey"] = "extractions/another-tenant/file.zip"
    factory = MagicMock()
    store = MagicMock()
    store.purge_exact = AsyncMock()
    store.purge_prefix = AsyncMock()

    with pytest.raises(ValueError, match="extractionKey"):
        await process_cleanup_event(factory, event, key, store)
    factory.assert_not_called()
    store.purge_exact.assert_not_awaited()
    store.purge_prefix.assert_not_awaited()


@pytest.mark.asyncio
async def test_substituted_object_key_never_touches_storage_or_database() -> None:
    tenant_id = uuid4()
    event = _deletion_event(
        tenant_id=tenant_id, object_key=f"knowledge/{tenant_id}/valid.pdf"
    )
    factory = MagicMock()
    store = MagicMock()
    store.purge_exact = AsyncMock()

    with pytest.raises(ValueError, match="differs from event payload"):
        await process_cleanup_event(
            factory, event, f"knowledge/{tenant_id}/different.pdf", store
        )
    factory.assert_not_called()
    store.purge_exact.assert_not_awaited()


@pytest.mark.asyncio
async def test_valid_cleanup_preserves_exact_and_prefix_purge(monkeypatch) -> None:
    from northstar_api.workers import object_cleaner

    tenant_id = uuid4()
    event = _deletion_event(
        tenant_id=tenant_id, object_key=f"knowledge/{tenant_id}/valid.pdf"
    )
    source_id = event.payload["sourceId"]
    prefix = f"extractions/{tenant_id}/{source_id}/"
    event.payload["extractionKey"] = prefix + "v0001.zip"
    session = MagicMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    factory = MagicMock(return_value=session)
    was_processed = AsyncMock(return_value=False)
    mark_processed = AsyncMock()
    monkeypatch.setattr(object_cleaner, "_was_processed", was_processed)
    monkeypatch.setattr(object_cleaner, "_mark_processed", mark_processed)
    store = MagicMock()
    store.purge_exact = AsyncMock(return_value=2)
    store.purge_prefix = AsyncMock(return_value=3)

    assert await process_cleanup_event(factory, event, event.payload["objectKey"], store) == 5
    store.purge_exact.assert_awaited_once_with(event.payload["objectKey"])
    store.purge_prefix.assert_awaited_once_with(prefix)
    mark_processed.assert_awaited_once()
