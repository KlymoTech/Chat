from __future__ import annotations

import math
import re
import time
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from sqlalchemy import exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from northstar_api.config import Settings, get_settings
from northstar_api.education_knowledge_scope import EducationKnowledgeScope
from northstar_api.metrics import RETRIEVAL_DURATION, RETRIEVAL_EVIDENCE
from northstar_api.models import DocumentChunk, FactStatus, KnowledgeFact, KnowledgeSource
from northstar_api.services.llm import NvidiaModelAdapter, nvidia_adapter


@dataclass(frozen=True, slots=True)
class Evidence:
    kind: str
    entity_id: str
    source_id: str | None
    title: str
    url: str | None
    text: str
    score: float
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class EducationRetrievalScope:
    workspace_id: UUID
    student_id: UUID
    enrollment_id: UUID
    course_id: UUID
    batch_id: UUID


class RetrievalService:
    def __init__(
        self,
        model: NvidiaModelAdapter | None = None,
        settings: Settings | None = None,
    ) -> None:
        self.model = model or nvidia_adapter
        self.settings = settings or get_settings()

    async def retrieve(
        self,
        session: AsyncSession,
        *,
        tenant_id: UUID,
        agent_id: UUID,
        revision: int,
        query: str,
        education_scope: EducationRetrievalScope | None = None,
        rerank_candidates: int | None = None,
        final_context_chunks: int | None = None,
    ) -> list[Evidence]:
        started = time.perf_counter()
        query_embedding = await self.model.embed_query(query)
        if session.bind and session.bind.dialect.name == "postgresql":
            evidence = await self._postgres_retrieve(
                session,
                tenant_id=tenant_id,
                agent_id=agent_id,
                revision=revision,
                query=query,
                vector=query_embedding,
                education_scope=education_scope,
                candidate_limit=rerank_candidates,
            )
        else:
            evidence = await self._portable_retrieve(
                session,
                tenant_id=tenant_id,
                agent_id=agent_id,
                revision=revision,
                query=query,
                vector=query_embedding,
                education_scope=education_scope,
                candidate_limit=rerank_candidates,
            )
        evidence = _rerank(
            evidence,
            query,
            final_context_chunks or self.settings.retrieval_context_limit,
        )
        RETRIEVAL_DURATION.observe(time.perf_counter() - started)
        RETRIEVAL_EVIDENCE.observe(len(evidence))
        return evidence

    @staticmethod
    def _source_scope_filter(
        *,
        tenant_id: UUID,
        agent_id: UUID,
        source_id: Any,
        scope: EducationRetrievalScope,
    ) -> ColumnElement[bool]:
        return exists(
            select(EducationKnowledgeScope.id).where(
                EducationKnowledgeScope.tenant_id == tenant_id,
                EducationKnowledgeScope.workspace_id == scope.workspace_id,
                EducationKnowledgeScope.agent_id == agent_id,
                EducationKnowledgeScope.source_id == source_id,
                EducationKnowledgeScope.course_id == scope.course_id,
                EducationKnowledgeScope.batch_id == scope.batch_id,
            )
        )

    @classmethod
    def _fact_scope_filter(
        cls,
        *,
        tenant_id: UUID,
        agent_id: UUID,
        scope: EducationRetrievalScope,
    ) -> ColumnElement[bool]:
        direct = exists(
            select(EducationKnowledgeScope.id).where(
                EducationKnowledgeScope.tenant_id == tenant_id,
                EducationKnowledgeScope.workspace_id == scope.workspace_id,
                EducationKnowledgeScope.agent_id == agent_id,
                EducationKnowledgeScope.fact_id == KnowledgeFact.id,
                EducationKnowledgeScope.course_id == scope.course_id,
                EducationKnowledgeScope.batch_id == scope.batch_id,
            )
        )
        inherited = cls._source_scope_filter(
            tenant_id=tenant_id,
            agent_id=agent_id,
            source_id=KnowledgeFact.source_id,
            scope=scope,
        )
        return or_(direct, inherited)

    async def _postgres_retrieve(
        self,
        session: AsyncSession,
        *,
        tenant_id: UUID,
        agent_id: UUID,
        revision: int,
        query: str,
        vector: list[float],
        education_scope: EducationRetrievalScope | None,
        candidate_limit: int | None,
    ) -> list[Evidence]:
        limit = candidate_limit or self.settings.retrieval_candidate_limit
        fact_filters = [
            KnowledgeFact.tenant_id == tenant_id,
            KnowledgeFact.agent_id == agent_id,
            KnowledgeFact.status == FactStatus.APPROVED,
            KnowledgeFact.revision <= revision,
        ]
        chunk_filters = [
            DocumentChunk.tenant_id == tenant_id,
            DocumentChunk.agent_id == agent_id,
            DocumentChunk.approved.is_(True),
            DocumentChunk.revision <= revision,
        ]
        if education_scope is not None:
            fact_filters.extend(
                [
                    KnowledgeFact.workspace_id == education_scope.workspace_id,
                    self._fact_scope_filter(
                        tenant_id=tenant_id,
                        agent_id=agent_id,
                        scope=education_scope,
                    ),
                ]
            )
            chunk_filters.extend(
                [
                    DocumentChunk.workspace_id == education_scope.workspace_id,
                    self._source_scope_filter(
                        tenant_id=tenant_id,
                        agent_id=agent_id,
                        source_id=DocumentChunk.source_id,
                        scope=education_scope,
                    ),
                ]
            )

        fact_distance = KnowledgeFact.embedding.cosine_distance(vector)
        fact_dense = (
            select(KnowledgeFact, KnowledgeSource.name, KnowledgeSource.url, fact_distance.label("distance"))
            .outerjoin(KnowledgeSource, KnowledgeSource.id == KnowledgeFact.source_id)
            .where(*fact_filters, KnowledgeFact.embedding.is_not(None))
            .order_by(fact_distance)
            .limit(limit)
        )
        chunk_distance = DocumentChunk.embedding.cosine_distance(vector)
        chunk_dense = (
            select(DocumentChunk, KnowledgeSource.name, KnowledgeSource.url, chunk_distance.label("distance"))
            .join(KnowledgeSource, KnowledgeSource.id == DocumentChunk.source_id)
            .where(*chunk_filters, DocumentChunk.embedding.is_not(None))
            .order_by(chunk_distance)
            .limit(limit)
        )
        rank: dict[tuple[str, str], float] = {}
        candidates: dict[tuple[str, str], Evidence] = {}
        for kind, result in (
            ("fact", await session.execute(fact_dense)),
            ("chunk", await session.execute(chunk_dense)),
        ):
            for position, row in enumerate(result.all(), start=1):
                entity, title, url, distance = row
                key = (kind, str(entity.id))
                rank[key] = rank.get(key, 0) + 1 / (60 + position)
                text = f"Q: {entity.question}\nA: {entity.answer}" if kind == "fact" else entity.content
                candidates[key] = Evidence(
                    kind=kind,
                    entity_id=str(entity.id),
                    source_id=str(entity.source_id) if entity.source_id else None,
                    title=title or ("Verified Q&A" if kind == "fact" else "Knowledge base"),
                    url=url,
                    text=text,
                    score=max(0.0, 1.0 - float(distance)),
                    metadata=(entity.metadata_json if kind == "chunk" else entity.source_span) or {},
                )

        ts_query = func.websearch_to_tsquery("simple", query)
        fact_rank = func.ts_rank_cd(
            func.to_tsvector("simple", KnowledgeFact.question + " " + KnowledgeFact.answer), ts_query
        )
        fact_lexical = (
            select(KnowledgeFact, KnowledgeSource.name, KnowledgeSource.url, fact_rank.label("rank"))
            .outerjoin(KnowledgeSource, KnowledgeSource.id == KnowledgeFact.source_id)
            .where(
                *fact_filters,
                ts_query.op("@@")(
                    func.to_tsvector("simple", KnowledgeFact.question + " " + KnowledgeFact.answer)
                ),
            )
            .order_by(fact_rank.desc())
            .limit(limit)
        )
        chunk_rank = func.ts_rank_cd(func.to_tsvector("simple", DocumentChunk.content), ts_query)
        chunk_lexical = (
            select(DocumentChunk, KnowledgeSource.name, KnowledgeSource.url, chunk_rank.label("rank"))
            .join(KnowledgeSource, KnowledgeSource.id == DocumentChunk.source_id)
            .where(
                *chunk_filters,
                ts_query.op("@@")(func.to_tsvector("simple", DocumentChunk.content)),
            )
            .order_by(chunk_rank.desc())
            .limit(limit)
        )
        for kind, result in (
            ("fact", await session.execute(fact_lexical)),
            ("chunk", await session.execute(chunk_lexical)),
        ):
            for position, row in enumerate(result.all(), start=1):
                entity, title, url, lexical_score = row
                key = (kind, str(entity.id))
                rank[key] = rank.get(key, 0) + 1 / (60 + position)
                if key not in candidates:
                    text = f"Q: {entity.question}\nA: {entity.answer}" if kind == "fact" else entity.content
                    candidates[key] = Evidence(
                        kind=kind,
                        entity_id=str(entity.id),
                        source_id=str(entity.source_id) if entity.source_id else None,
                        title=title or ("Verified Q&A" if kind == "fact" else "Knowledge base"),
                        url=url,
                        text=text,
                        score=float(lexical_score),
                        metadata=(entity.metadata_json if kind == "chunk" else entity.source_span) or {},
                    )
        ordered = sorted(
            candidates.values(),
            key=lambda item: (rank[(item.kind, item.entity_id)], item.score),
            reverse=True,
        )
        if not ordered:
            return []
        return [item for item in ordered if item.score >= self.settings.retrieval_min_score]

    async def _portable_retrieve(
        self,
        session: AsyncSession,
        *,
        tenant_id: UUID,
        agent_id: UUID,
        revision: int,
        query: str,
        vector: list[float],
        education_scope: EducationRetrievalScope | None,
        candidate_limit: int | None,
    ) -> list[Evidence]:
        fact_filters = [
            KnowledgeFact.tenant_id == tenant_id,
            KnowledgeFact.agent_id == agent_id,
            KnowledgeFact.status == FactStatus.APPROVED,
            KnowledgeFact.revision <= revision,
        ]
        chunk_filters = [
            DocumentChunk.tenant_id == tenant_id,
            DocumentChunk.agent_id == agent_id,
            DocumentChunk.approved.is_(True),
            DocumentChunk.revision <= revision,
        ]
        if education_scope is not None:
            fact_filters.extend(
                [
                    KnowledgeFact.workspace_id == education_scope.workspace_id,
                    self._fact_scope_filter(
                        tenant_id=tenant_id,
                        agent_id=agent_id,
                        scope=education_scope,
                    ),
                ]
            )
            chunk_filters.extend(
                [
                    DocumentChunk.workspace_id == education_scope.workspace_id,
                    self._source_scope_filter(
                        tenant_id=tenant_id,
                        agent_id=agent_id,
                        source_id=DocumentChunk.source_id,
                        scope=education_scope,
                    ),
                ]
            )

        candidate_limit = candidate_limit or 500
        fact_rows = (
            await session.execute(
                select(KnowledgeFact, KnowledgeSource.name, KnowledgeSource.url)
                .outerjoin(KnowledgeSource, KnowledgeSource.id == KnowledgeFact.source_id)
                .where(*fact_filters)
                .limit(candidate_limit)
            )
        ).all()
        chunk_rows = (
            await session.execute(
                select(DocumentChunk, KnowledgeSource.name, KnowledgeSource.url)
                .join(KnowledgeSource, KnowledgeSource.id == DocumentChunk.source_id)
                .where(*chunk_filters)
                .limit(candidate_limit)
            )
        ).all()
        query_words = set(re.findall(r"\w+", query.casefold()))
        candidates: list[Evidence] = []
        for kind, rows in (("fact", fact_rows), ("chunk", chunk_rows)):
            for entity, title, url in rows:
                text = f"Q: {entity.question}\nA: {entity.answer}" if kind == "fact" else entity.content
                words = set(re.findall(r"\w+", text.casefold()))
                lexical = len(query_words & words) / max(1, len(query_words | words))
                semantic = _cosine(vector, list(entity.embedding)) if entity.embedding is not None else 0.0
                score = max(lexical, max(0.0, semantic))
                if score >= self.settings.retrieval_min_score:
                    candidates.append(
                        Evidence(
                            kind=kind,
                            entity_id=str(entity.id),
                            source_id=str(entity.source_id) if entity.source_id else None,
                            title=title or ("Verified Q&A" if kind == "fact" else "Knowledge base"),
                            url=url,
                            text=text,
                            score=score,
                            metadata=(entity.metadata_json if kind == "chunk" else entity.source_span) or {},
                        )
                    )
        return sorted(candidates, key=lambda item: item.score, reverse=True)


def _cosine(left: list[float], right: list[float]) -> float:
    if not left or len(left) != len(right):
        return 0.0
    dot = sum(a * b for a, b in zip(left, right, strict=True))
    norm_left = math.sqrt(sum(value * value for value in left))
    norm_right = math.sqrt(sum(value * value for value in right))
    return dot / (norm_left * norm_right) if norm_left and norm_right else 0.0


def _rerank(evidence: list[Evidence], query: str, limit: int) -> list[Evidence]:
    """Cheap deterministic reranking after vector/lexical fusion.

    Exact terms and critical qualifiers receive a small boost. This improves
    latency versus a second model call while keeping numbers and NOT/EXCEPT
    visible to the ranking decision.
    """
    query_terms = set(re.findall(r"\w+", query.casefold()))
    critical = set(re.findall(r"\b(?:not|except|least|most|incorrect)\b", query.casefold()))
    scored: list[tuple[float, Evidence]] = []
    seen_sources: set[str] = set()
    for item in evidence:
        terms = set(re.findall(r"\w+", item.text.casefold()))
        overlap = len(query_terms & terms) / max(1, len(query_terms))
        critical_overlap = len(critical & terms) / max(1, len(critical)) if critical else 0.0
        diversity_bonus = 0.015 if item.source_id not in seen_sources else 0.0
        score = item.score + (0.08 * overlap) + (0.30 * critical_overlap) + diversity_bonus
        scored.append((score, item))
        if item.source_id:
            seen_sources.add(item.source_id)
    scored.sort(key=lambda value: value[0], reverse=True)
    return [replace_evidence(item, score) for score, item in scored[: max(1, limit)]]


def replace_evidence(item: Evidence, score: float) -> Evidence:
    return Evidence(
        kind=item.kind,
        entity_id=item.entity_id,
        source_id=item.source_id,
        title=item.title,
        url=item.url,
        text=item.text,
        score=score,
        metadata=item.metadata,
    )


retrieval_service = RetrievalService()
