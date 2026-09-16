from __future__ import annotations

import asyncio
import hashlib
import html
import json
import re
import zipfile
from urllib.parse import urlparse
from uuid import UUID
from typing import Any

import structlog
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from northstar_api.config import get_settings
from northstar_api.models import DocumentChunk, IngestionJob, JobStatus, KnowledgeKind, KnowledgeSource, KnowledgeStatus
from northstar_api.services.crawler import crawl_website, take_screenshot
from northstar_api.services.hybrid_extraction import ExtractionPackage, configuration, encode_page_checkpoint, extract_document
from northstar_api.services.extraction_storage import approved_content, load_archive, recover_checkpoints
from northstar_api.services.llm import nvidia_adapter
from northstar_api.services.object_store import object_store
from northstar_api.services.outbox import enqueue_event
from northstar_api.services.safe_fetch import fetch_public_text
from northstar_api.services.vision import extract_vision_text

logger = structlog.get_logger(__name__)


def semantic_chunks(text: str, target_words: int = 220, overlap_words: int = 35) -> list[str]:
    """Create chunks without crossing PDF page boundaries."""
    normalized = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    if not normalized:
        return []
    pages = re.split(r"\n\s*===PDF_PAGE:\d+===\s*\n", normalized)
    chunks: list[str] = []
    for page in pages:
        page = page.strip()
        if not page:
            continue
        paragraphs = [part.strip() for part in re.split(r"\n\s*\n", page) if part.strip()]
        if not paragraphs:
            continue
        current: list[str] = []
        current_words = 0
        for paragraph in paragraphs:
            paragraph_words = paragraph.split()
            if len(paragraph_words) > target_words * 2:
                if current:
                    chunks.append(" ".join(current).strip())
                    current = []
                    current_words = 0
                step = max(1, target_words - overlap_words)
                for start in range(0, len(paragraph_words), step):
                    part = paragraph_words[start : start + target_words]
                    if part:
                        chunks.append(" ".join(part).strip())
                continue
            if current and current_words + len(paragraph_words) > target_words:
                chunks.append(" ".join(current).strip())
                overlap = current[-overlap_words:] if overlap_words else []
                current = overlap + paragraph_words
                current_words = len(current)
            else:
                current.extend(paragraph_words)
                current_words += len(paragraph_words)
        if current:
            chunks.append(" ".join(current).strip())
    return [chunk for chunk in chunks if chunk]


async def _existing_evidence(source: KnowledgeSource) -> ExtractionPackage | None:
    key = source.extraction_key
    if not key or not key.startswith(f"extractions/{source.tenant_id}/{source.id}/"):
        return None
    blob, _ = await object_store.download(key, limit_bytes=1024 * 1024 * 1024)
    try:
        return load_archive(blob, source.checksum)
    except (ValueError, KeyError, TypeError, UnicodeError, OSError, zipfile.BadZipFile) as exc:
        logger.warning("extraction_evidence_invalid", source_id=str(source.id), error=type(exc).__name__)
        return None


async def _prepare_file(session: AsyncSession, source: KnowledgeSource, job: IngestionJob | None) -> str | None:
    """Return only verified canonical content, otherwise persist a reviewable draft."""
    if not source.object_key:
        raise ValueError("File sources require a preserved uploaded original; supplied text is not evidence")
    settings = get_settings()
    version = source.revision or 1
    previous = await _existing_evidence(source)
    if previous and previous.record.get("extraction_revision") == version:
        try:
            content = approved_content(previous, source.name)
        except ValueError:
            pass
        else:
            # Never use a client-supplied or stale source.content as file approval evidence.
            source.content = content
            return content
    data, _ = await object_store.download(source.object_key)
    source_hash = hashlib.sha256(data).hexdigest()
    if source.checksum != source_hash:
        raise ValueError("Uploaded source checksum does not match the preserved original")
    if job:
        job.step = "extracting"
        job.progress = 30
        await session.commit()
    identity = hashlib.sha256(json.dumps(configuration(settings), sort_keys=True).encode()).hexdigest()
    raw_pages = await object_store.load_extraction_pages(source.tenant_id, source.id, version=version)
    resume_pages, invalid = recover_checkpoints(raw_pages, source_sha256=source_hash,
                                               configuration_identity=identity, revision=version)
    if invalid:
        logger.warning("extraction_checkpoints_reprocessed", source_id=str(source.id), pages=invalid)

    async def checkpoint(page: dict[str, Any], image: bytes, page_issues: list[dict[str, Any]]) -> None:
        number = int(page["number"])
        encoded = encode_page_checkpoint(page, image, page_issues, source_sha256=source_hash,
                                         model=identity, version=version)
        await object_store.put_extraction_page(source.tenant_id, source.id, version=version,
                                               page_number=number, data=encoded)
        if job:
            job.step = f"extracted_page_{number}"
            job.progress = min(90, 30 + number)
            await session.commit()

    package = await extract_document(data, source.name, settings, resume_pages=resume_pages,
                                     on_page=checkpoint, previous_package=previous)
    package.record["extraction_revision"] = version
    source.extraction_key = await object_store.put_extraction(source.tenant_id, source.id, package.archive(), version=version)
    source.content = None
    source.extraction_issue_count = sum(issue.get("status") != "resolved" for issue in package.issues)
    source.status = KnowledgeStatus.NEEDS_REVIEW
    source.size_label = f"{len(package.record['pages'])} source units"
    if job:
        job.status = JobStatus.SUCCEEDED
        job.step = "needs_review"
        job.progress = 100
    await session.commit()
    return None


async def ingest_source_async(session: AsyncSession, source_id: UUID) -> None:
    source = await session.scalar(select(KnowledgeSource).where(KnowledgeSource.id == source_id))
    if not source:
        return
    job = await session.scalar(select(IngestionJob).where(IngestionJob.source_id == source.id)
                               .order_by(IngestionJob.created_at.desc()))
    if job:
        if job.status == JobStatus.SUCCEEDED:
            return
        job.status = JobStatus.RUNNING
        job.step = "chunking"
        job.progress = 20
        job.attempts += 1
    source.status = KnowledgeStatus.PROCESSING
    source.error = None
    await session.commit()
    try:
        if source.kind == KnowledgeKind.FILE:
            content = await _prepare_file(session, source, job)
            if content is None:
                return
        else:
            content = await _materialize_text(source)
        if not content:
            raise ValueError("Source has no extracted text")
        settings = get_settings()
        if len(content) > settings.knowledge_max_extracted_characters:
            raise ValueError("Source text exceeds the configured extraction limit")
        chunks = semantic_chunks(content)
        if not chunks:
            raise ValueError("Source produced no usable chunks")
        if len(chunks) > settings.knowledge_max_chunks:
            raise ValueError("Source produced more chunks than the configured limit")
        if job:
            job.step = "embedding"
            job.progress = 55
            await session.commit()
        vectors: list[list[float]] = []
        batch_size = 32
        for start in range(0, len(chunks), batch_size):
            vectors.extend(await nvidia_adapter.embed_documents(chunks[start : start + batch_size]))
        await session.execute(delete(DocumentChunk).where(DocumentChunk.source_id == source.id))
        for ordinal, (content_chunk, vector) in enumerate(zip(chunks, vectors, strict=True)):
            session.add(DocumentChunk(tenant_id=source.tenant_id, workspace_id=source.workspace_id,
                agent_id=source.agent_id, source_id=source.id, ordinal=ordinal, content=content_chunk,
                token_count=max(1, round(len(content_chunk.split()) * 1.35)), approved=True,
                revision=source.revision, embedding_model=get_settings().nvidia_embedding_model,
                embedding=vector, metadata_json={"checksum": hashlib.sha256(content_chunk.encode()).hexdigest()}))
        source.status = KnowledgeStatus.READY
        source.chunk_count = len(chunks)
        source.size_label = f"{len(content.split()):,} words"
        if job:
            job.status = JobStatus.SUCCEEDED
            job.step = "complete"
            job.progress = 100
        enqueue_event(session, tenant_id=source.tenant_id, aggregate_type="knowledge_source", aggregate_id=source.id,
                      event_type="knowledge.source.ingested.v1",
                      payload={"sourceId": str(source.id), "agentId": str(source.agent_id), "chunks": len(chunks)})
        await session.commit()
    except Exception as exc:
        source.status = KnowledgeStatus.FAILED
        source.error = "Ingestion failed; inspect the job log."
        if job:
            job.status = JobStatus.FAILED
            job.step = "failed"
            job.error_json = {"type": type(exc).__name__, "message": str(exc)[:400]}
        await session.commit()
        raise


async def _materialize_text(source: KnowledgeSource) -> str:
    if source.kind == KnowledgeKind.FILE:
        package = await _existing_evidence(source)
        if not package or package.record.get("extraction_revision") != source.revision:
            raise ValueError("Uploaded files require current verified extraction evidence")
        return approved_content(package, source.name)
    if source.content:
        return source.content.strip()
    if source.url:
        if source.kind == KnowledgeKind.SITEMAP:
            return await _materialize_sitemap(source)
        if source.kind == KnowledgeKind.URL:
            return await _materialize_webpage_with_vision(source)
        text, final_url = await fetch_public_text(source.url)
        source.url = final_url
        return text.strip()
    return ""


async def _materialize_webpage_with_vision(source: KnowledgeSource) -> str:
    """Existing website crawler and NVIDIA vision behavior; outside file extraction scope."""
    assert source.url is not None
    settings = get_settings()
    initial_text, final_url = await fetch_public_text(source.url)
    source.url = final_url
    try:
        pages = await asyncio.to_thread(crawl_website, final_url, 20)
    except Exception as exc:
        logger.warning("website_crawl_failed", source_id=str(source.id), error=type(exc).__name__)
        return initial_text.strip()
    sections: list[str] = []
    for page_number, page in enumerate(pages, start=1):
        page_url = str(page.get("url") or "")
        page_text = str(page.get("text") or "").strip()
        if not page_url:
            continue
        section_parts: list[str] = []
        if page_text:
            section_parts.append(page_text)
        try:
            screenshot_path = await asyncio.to_thread(take_screenshot, page_url, f"web_{source.id}_{page_number:03d}.png")
            vision_text = await asyncio.to_thread(extract_vision_text, screenshot_path)
            if vision_text.strip():
                section_parts.append(f"VISUAL CONTENT FROM WEB PAGE:\n{vision_text.strip()}")
        except Exception as exc:
            logger.warning("website_vision_extraction_failed", source_id=str(source.id), page_url=page_url,
                           error=type(exc).__name__)
        if section_parts:
            sections.append(f"Source page: {page_url}\n\n" + "\n\n".join(section_parts))
    if not sections:
        return initial_text.strip()
    return "\n\n---\n\n".join(sections)[:settings.knowledge_max_extracted_characters].strip()


async def _materialize_sitemap(source: KnowledgeSource) -> str:
    assert source.url is not None
    settings = get_settings()
    sitemap, final_sitemap_url = await fetch_public_text(source.url, max_bytes=1_000_000)
    source.url = final_sitemap_url
    sitemap_host = (urlparse(final_sitemap_url).hostname or "").lower()
    raw_locations = re.findall(r"<(?:[A-Za-z0-9_-]+:)?loc\b[^>]*>(.*?)</(?:[A-Za-z0-9_-]+:)?loc>",
                               sitemap, flags=re.IGNORECASE | re.DOTALL)
    locations: list[str] = []
    for raw_location in raw_locations:
        location = html.unescape(raw_location).strip()
        parsed = urlparse(location)
        if (parsed.scheme.lower() not in {"http", "https"}
                or (parsed.hostname or "").lower() != sitemap_host or location in locations):
            continue
        locations.append(location)
        if len(locations) >= settings.knowledge_sitemap_max_urls:
            break
    if not locations:
        raise ValueError("Sitemap did not contain same-host HTTP(S) page URLs")
    semaphore = asyncio.Semaphore(5)

    async def fetch_page(page_url: str) -> tuple[str, str] | None:
        try:
            async with semaphore:
                page_text, final_url = await fetch_public_text(page_url, max_bytes=500_000)
            return final_url, page_text
        except Exception as exc:
            logger.warning("sitemap_page_fetch_failed", host=(urlparse(page_url).hostname or "")[:255],
                           error=type(exc).__name__)
            return None

    pages = await asyncio.gather(*(fetch_page(location) for location in locations))
    sections: list[str] = []
    remaining = settings.knowledge_max_extracted_characters
    for page in pages:
        if not page or not page[1].strip() or remaining <= 0:
            continue
        final_url, page_text = page
        section = f"Source page: {final_url}\n\n{page_text.strip()}"[:remaining]
        sections.append(section)
        remaining -= len(section)
    if not sections:
        raise ValueError("Sitemap pages did not yield usable text")
    return "\n\n---\n\n".join(sections)
