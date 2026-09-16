"""Isolated smoke checks; safe to run without database, network, or credentials."""

import asyncio
import hashlib
import importlib.util
import io
import json
import zipfile
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import fitz
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy import text as sa_text

from northstar_api.config import Settings
from northstar_api.models import JobStatus, KnowledgeKind, KnowledgeSource, KnowledgeStatus
from northstar_api.routers import knowledge as knowledge_router
from northstar_api.schemas import UploadPresignRequest
from northstar_api.services import hybrid_extraction as hybrid
from northstar_api.services import ingestion


async def main() -> None:
    assert knowledge_router.router is not None
    assert ingestion.ingest_source_async is not None
    image_upload = UploadPresignRequest(
        filename="scan.png",
        content_type="image/png",
        size_bytes=100,
        checksum_sha256="0" * 64,
    )
    assert image_upload.content_type == "image/png"
    spec = importlib.util.spec_from_file_location(
        "hybrid_migration", "migrations/versions/0044_hybrid_extraction_review.py"
    )
    assert spec is not None and spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        connection.execute(sa_text("CREATE TABLE knowledge_sources (id TEXT PRIMARY KEY)"))
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
        columns = {row[1] for row in connection.execute(sa_text("PRAGMA table_info(knowledge_sources)"))}
        assert {"extraction_key", "extraction_issue_count"} <= columns
    engine.dispose()
    settings = Settings(_env_file=None)
    original = hybrid._read_image

    async def agrees(_: bytes, __: Settings) -> str:
        return "Value -12.50"

    async def differs(_: bytes, __: Settings) -> str:
        return "Value 12.50"

    pdf = fitz.open()
    page = pdf.new_page()
    page.insert_text((72, 72), "Value -12.50")
    image_payload = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False).tobytes("png")
    payload = pdf.tobytes()
    pdf.close()
    try:
        hybrid._read_image = agrees
        matched = await hybrid.extract_document(payload, "fixture.pdf", settings)
        assert len(matched.record["pages"]) == 1
        assert matched.record["pages"][0]["selected_text"] == "Value -12.50"
        assert not matched.issues
        saved_pages: dict[int, hybrid.PageCheckpoint] = {}

        async def save_page(page: dict, image: bytes, issues: list[dict]) -> None:
            encoded = hybrid.encode_page_checkpoint(
                page,
                image,
                issues,
                source_sha256=hashlib.sha256(payload).hexdigest(),
                model=settings.extraction_vision_model,
                version=1,
            )
            saved_pages[page["number"]] = hybrid.decode_page_checkpoint(
                encoded,
                source_sha256=hashlib.sha256(payload).hexdigest(),
                model=settings.extraction_vision_model,
                version=1,
                page_number=page["number"],
            )

        await hybrid.extract_document(payload, "fixture.pdf", settings, on_page=save_page)

        async def should_not_read(_: bytes, __: Settings) -> str:
            raise AssertionError("A checkpointed page was read again")

        hybrid._read_image = should_not_read
        resumed = await hybrid.extract_document(payload, "fixture.pdf", settings, resume_pages=saved_pages)
        assert resumed.record["pages"][0]["selected_text"] == "Value -12.50"
        hybrid._read_image = agrees
        with zipfile.ZipFile(io.BytesIO(matched.archive())) as archive:
            manifest = json.loads(archive.read("manifest.json"))
            assert (
                hashlib.sha256(archive.read("extracted.json")).hexdigest()
                == manifest["artifacts"]["extracted.json"]
            )
            assert "pages/page_0001.png" in archive.namelist()

        hybrid._read_image = differs
        conflict = await hybrid.extract_document(payload, "fixture.pdf", settings)
        assert conflict.record["pages"][0]["selected_text"] is None
        assert conflict.issues[0]["code"] == "CANDIDATE_CONFLICT"
        assert "Verified release: BLOCKED" in conflict.validation_text()

        hybrid._read_image = agrees
        image_source = await hybrid.extract_document(image_payload, "scan.png", settings)
        assert image_source.record["pages"][0]["source_unit"] == "image_frame"
        assert image_source.record["pages"][0]["visual_text"] == "Value -12.50"
        assert image_source.issues[0]["code"] == "VISUAL_ONLY_REVIEW_REQUIRED"

        text = await hybrid.extract_document(b"\xef\xbb\xbfQuestion?\r\nA. Yes\r\n", "fixture.txt", settings)
        assert text.record["pages"][0]["native_text"] == "Question?\r\nA. Yes\r\n"
        try:
            await hybrid.extract_document(b"broken\xff", "fixture.txt", settings)
        except UnicodeDecodeError:
            pass
        else:
            raise AssertionError("Invalid source encoding was accepted")

        source = KnowledgeSource(
            id=uuid4(),
            tenant_id=uuid4(),
            workspace_id=uuid4(),
            agent_id=uuid4(),
            name="fixture.pdf",
            kind=KnowledgeKind.FILE,
            object_key="knowledge/example/file.pdf",
            checksum=hashlib.sha256(payload).hexdigest(),
        )
        source.extraction_key = f"extractions/{source.tenant_id}/{source.id}/review.zip"
        evidence = conflict.archive()

        class ReadStore:
            async def download(self, *_: object, **__: object) -> tuple[bytes, dict[str, object]]:
                return evidence, {}

        original_review_store = knowledge_router.object_store
        knowledge_router.object_store = ReadStore()
        try:
            loaded = await knowledge_router._load_extraction(source)
            assert loaded.record["source_sha256"] == source.checksum
            damaged = io.BytesIO()
            with zipfile.ZipFile(io.BytesIO(evidence)) as original_zip:
                with zipfile.ZipFile(damaged, "w") as damaged_zip:
                    for name in original_zip.namelist():
                        damaged_zip.writestr(
                            name, b"{}" if name == "extracted.json" else original_zip.read(name)
                        )
            evidence = damaged.getvalue()
            try:
                await knowledge_router._load_extraction(source)
            except HTTPException as exc:
                assert exc.status_code == 409
            else:
                raise AssertionError("Tampered extraction evidence was accepted")
        finally:
            knowledge_router.object_store = original_review_store
        job = SimpleNamespace(status=JobStatus.QUEUED, step="queued", progress=0, attempts=0)

        class FakeSession:
            calls = 0

            async def scalar(self, _: object) -> object:
                self.calls += 1
                return source if self.calls == 1 else job

            async def commit(self) -> None:
                pass

        class FakeStore:
            async def download(self, _: str) -> tuple[bytes, dict[str, object]]:
                return payload, {}

            async def load_extraction_pages(self, *_: object, **__: object) -> dict[int, bytes]:
                return {}

            async def put_extraction_page(self, *_: object, **__: object) -> str:
                return "extractions/example/page_0001.zip"

            async def put_extraction(self, *_: object, **__: object) -> str:
                return "extractions/example/review.zip"

        original_store = ingestion.object_store
        ingestion.object_store = FakeStore()
        hybrid._read_image = differs
        try:
            await ingestion.ingest_source_async(FakeSession(), source.id)
        finally:
            ingestion.object_store = original_store
        assert source.status == KnowledgeStatus.NEEDS_REVIEW
        assert source.chunk_count is None or source.chunk_count == 0
        assert source.extraction_issue_count == 1
        assert job.step == "needs_review"

        source.revision = 1
        source.chunk_count = 0
        source.updated_at = datetime.now(UTC)
        saved_archive: list[bytes] = []

        class ReviewStore:
            async def put_extraction(self, _tenant: object, _source: object, data: bytes, **_: object) -> str:
                saved_archive.append(data)
                return "extractions/example/review.zip"

        async def review_source(*_: object) -> KnowledgeSource:
            return source

        blocked_record = json.loads(json.dumps(conflict.record))
        blocked_record["issues"] = [
            {
                "id": "I0001",
                "page": 1,
                "code": "VISION_UNAVAILABLE",
                "message": "Model failed",
            }
        ]
        package_for_review = hybrid.ExtractionPackage(blocked_record, conflict.images)

        async def load_extraction(*_: object) -> hybrid.ExtractionPackage:
            return package_for_review

        class ReviewSession:
            def __init__(self) -> None:
                self.added: list[object] = []

            def add(self, value: object) -> None:
                self.added.append(value)

            async def commit(self) -> None:
                pass

        review_session = ReviewSession()
        originals = (
            knowledge_router._review_source,
            knowledge_router._load_extraction,
            knowledge_router.object_store,
            knowledge_router.enqueue_event,
            knowledge_router.get_settings,
        )
        knowledge_router._review_source = review_source
        knowledge_router._load_extraction = load_extraction
        knowledge_router.object_store = ReviewStore()
        knowledge_router.enqueue_event = lambda *_args, **_kwargs: None
        knowledge_router.get_settings = lambda: Settings(_env_file=None, background_dispatch_enabled=True)
        approval = knowledge_router.ExtractionApproval(
            pages=[knowledge_router.ReviewedPage(number=1, selected_text="Value -12.50")]
        )
        reviewer = SimpleNamespace(
            user_id=uuid4(), tenant_id=source.tenant_id, workspace_id=source.workspace_id
        )
        try:
            try:
                await knowledge_router.approve_extraction(source.id, approval, reviewer, review_session)
            except HTTPException as exc:
                assert exc.status_code == 409
            else:
                raise AssertionError("A failed vision pass was marked verified")
            assert source.status == KnowledgeStatus.NEEDS_REVIEW
            await knowledge_router.retry_extraction(source.id, reviewer, review_session)
            assert source.status == KnowledgeStatus.PROCESSING
            assert source.revision == 2
            # Simulate the retried worker completing its visual pass.
            source.status = KnowledgeStatus.NEEDS_REVIEW
            package_for_review = conflict
            await knowledge_router.approve_extraction(
                source.id,
                approval,
                reviewer,
                review_session,
            )
        finally:
            (
                knowledge_router._review_source,
                knowledge_router._load_extraction,
                knowledge_router.object_store,
                knowledge_router.enqueue_event,
                knowledge_router.get_settings,
            ) = originals
        assert source.status == KnowledgeStatus.PROCESSING
        assert source.content == "===PDF_PAGE:1===\nValue -12.50"
        assert source.revision == 3
        assert len(review_session.added) == 2
        with zipfile.ZipFile(io.BytesIO(saved_archive[0])) as archive:
            assert "Verified release: APPROVED" in archive.read("validation_report.txt").decode()
    finally:
        hybrid._read_image = original
    print("Hybrid extraction smoke checks passed")


if __name__ == "__main__":
    asyncio.run(main())
