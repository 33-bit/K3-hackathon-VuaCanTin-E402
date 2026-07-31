from __future__ import annotations

import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol
from uuid import UUID

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import (
    GenerationProviderUnavailableError,
    StaleSlideContextError,
    VectorIndexInconsistentError,
)
from app.db import repositories
from app.db.models import Chunk, DeckVersion, Slide
from app.services.openai_service import LLMProvider, QueryUnderstanding

from .query_policy import normalize_range_query, route_query
from .selected_text_matcher import SelectedTextMatch, match_selected_text

logger = structlog.get_logger(__name__)


class VectorHitLike(Protocol):
    point_id: UUID
    score: float
    content_hash: str
    slide_id: UUID
    slide_number: int
    embedding_version: str
    retrieval_schema_version: str


class VectorSearchProvider(Protocol):
    async def count_deck_version(self, deck_version_id: UUID) -> int: ...

    async def hybrid_query(
        self,
        *,
        dense_vector: Sequence[float],
        query_text: str,
        course_id: UUID,
        deck_id: UUID,
        deck_version_id: UUID,
        prefetch_limit: int,
        fused_limit: int,
    ) -> Sequence[VectorHitLike]: ...


@dataclass(slots=True)
class RetrievalResult:
    query: QueryUnderstanding
    chunks: list[Chunk]
    slides: dict[UUID, Slide]
    selected_match: SelectedTextMatch | None
    candidates_debug: list[dict[str, Any]]
    filters_debug: dict[str, str]
    timings_ms: dict[str, float] = field(default_factory=dict)


class RetrievalService:
    def __init__(
        self,
        *,
        settings: Settings,
        llm: LLMProvider,
        vector_store: VectorSearchProvider,
    ) -> None:
        self.settings = settings
        self.llm = llm
        self.vector_store = vector_store

    async def retrieve(
        self,
        *,
        session: AsyncSession,
        version: DeckVersion,
        course_id: UUID,
        deck_id: UUID,
        current_slide_id: UUID,
        selected_text: str | None,
        question: str,
        language: str,
        explicit_ranges: Sequence[tuple[int, int]] = (),
        deck_title: str = "",
        conversation_history: Sequence[dict[str, Any]] = (),
        conversation_history_turns: int = 0,
    ) -> RetrievalResult:
        total_started = time.perf_counter()
        slides = await repositories.get_slides_for_version(session, deck_version_id=version.id)
        slide_by_id = {slide.id: slide for slide in slides}
        current_slide = slide_by_id.get(current_slide_id)
        if current_slide is None:
            raise StaleSlideContextError()

        blocks = await repositories.get_slide_blocks(session, slide_id=current_slide_id)
        selected_match = match_selected_text(selected_text, blocks)
        first_slide_title = slides[0].title if slides else None
        # End the read transaction before calling external model/vector services.
        await session.commit()

        understanding_started = time.perf_counter()
        query = route_query(
            question=question,
            selected_text=selected_text,
            explicit_ranges=explicit_ranges,
            language=language,
            deck_title=deck_title,
            first_slide_title=first_slide_title,
            current_slide_title=current_slide.title,
            slide_count=len(slides),
        )
        if query is None:
            try:
                query = await self.llm.understand_query(
                    question=question,
                    selected_text=selected_text,
                    current_slide_title=current_slide.title,
                    language=language,
                    deck_title=deck_title,
                    first_slide_title=first_slide_title,
                    slide_count=len(slides),
                    current_slide_number=current_slide.slide_number,
                    conversation_history=conversation_history,
                )
            except GenerationProviderUnavailableError:
                query = QueryUnderstanding(rewritten_query=question)
            query = normalize_range_query(
                query,
                question=question,
                slide_count=len(slides),
                language=language,
            )
        understanding_ms = _elapsed_ms(understanding_started)

        if query.response_mode != "answer":
            logger.info(
                "query_resolved_without_retrieval",
                active_deck_version_id=str(version.id),
                response_mode=query.response_mode,
                reason_code=query.reason_code,
                total_ms=_elapsed_ms(total_started),
            )
            return RetrievalResult(
                query=query,
                chunks=[],
                slides={},
                selected_match=selected_match,
                candidates_debug=[],
                filters_debug={
                    "course_id": str(course_id),
                    "deck_id": str(deck_id),
                    "deck_version_id": str(version.id),
                    "response_mode": query.response_mode,
                    "reason_code": query.reason_code or "",
                    "scope": query.scope,
                    "intent": query.intent,
                    "conversation_history_turns": conversation_history_turns,
                },
                timings_ms={
                    "query_understanding": understanding_ms,
                    "total": _elapsed_ms(total_started),
                },
            )

        if query.scope == "range":
            requested_ranges = list(explicit_ranges) or [
                (query.slide_start or 1, query.slide_end or len(slides))
            ]
            ordered: list[Chunk] = []
            seen_range_chunks: set[UUID] = set()
            for raw_start, raw_end in requested_ranges:
                start = max(1, raw_start)
                end = min(len(slides), raw_end)
                if start > end:
                    continue
                range_chunks = await repositories.get_chunks_in_slide_range(
                    session,
                    deck_version_id=version.id,
                    start=start,
                    end=end,
                )
                for chunk in range_chunks:
                    if chunk.id not in seen_range_chunks:
                        ordered.append(chunk)
                        seen_range_chunks.add(chunk.id)
            preferred = _prefer_slide_chunks(ordered)
            selected = _fit_budget(
                preferred,
                token_budget=self.settings.context_token_budget,
                limit=max(self.settings.retrieval_context_limit, len(preferred)),
            )
            result_slides = {chunk.slide_id: slide_by_id[chunk.slide_id] for chunk in selected}
            await session.commit()
            total_ms = _elapsed_ms(total_started)
            logger.info(
                "ordered_range_retrieval_completed",
                active_deck_version_id=str(version.id),
                filter_fields=["course_id", "deck_id", "deck_version_id"],
                requested_ranges=requested_ranges,
                candidate_count=len(ordered),
                selected_count=len(selected),
                total_ms=total_ms,
            )
            return RetrievalResult(
                query=query,
                chunks=selected,
                slides=result_slides,
                selected_match=selected_match,
                candidates_debug=[
                    {"chunk_id": str(chunk.id), "source": "ordered_range"} for chunk in selected
                ],
                filters_debug={
                    "course_id": str(course_id),
                    "deck_id": str(deck_id),
                    "deck_version_id": str(version.id),
                    "response_mode": query.response_mode,
                    "reason_code": query.reason_code or "",
                    "scope": query.scope,
                    "intent": query.intent,
                    "conversation_history_turns": conversation_history_turns,
                },
                timings_ms={
                    "query_understanding": understanding_ms,
                    "total": total_ms,
                },
            )

        count_started = time.perf_counter()
        indexed_count = await self.vector_store.count_deck_version(version.id)
        count_ms = _elapsed_ms(count_started)
        if indexed_count != version.expected_chunk_count:
            detail = (
                f"expected {version.expected_chunk_count} points for active version, "
                f"observed {indexed_count}"
            )
            await repositories.flag_index_drift(session, version=version, detail=detail)
            await session.commit()
            logger.error(
                "vector_manifest_drift_detected",
                active_deck_version_id=str(version.id),
                expected_chunk_count=version.expected_chunk_count,
                indexed_chunk_count=indexed_count,
            )
            raise VectorIndexInconsistentError(detail)

        embedding_started = time.perf_counter()
        query_vector = (await self.llm.embed_texts([query.rewritten_query]))[0]
        embedding_ms = _elapsed_ms(embedding_started)

        qdrant_started = time.perf_counter()
        hits = await self.vector_store.hybrid_query(
            dense_vector=query_vector,
            query_text=query.rewritten_query,
            course_id=course_id,
            deck_id=deck_id,
            deck_version_id=version.id,
            prefetch_limit=self.settings.retrieval_prefetch_limit,
            fused_limit=self.settings.retrieval_fused_limit,
        )
        qdrant_ms = _elapsed_ms(qdrant_started)

        hit_ids = [hit.point_id for hit in hits]
        hydrated = await repositories.hydrate_chunks(session, chunk_ids=hit_ids)
        hydrated_by_id = {chunk.id: chunk for chunk in hydrated}
        inconsistency: list[str] = []
        for hit in hits:
            chunk = hydrated_by_id.get(hit.point_id)
            if chunk is None:
                inconsistency.append(f"missing:{hit.point_id}")
                continue
            slide = slide_by_id.get(chunk.slide_id)
            if (
                chunk.deck_version_id != version.id
                or chunk.content_hash != hit.content_hash
                or chunk.slide_id != hit.slide_id
                or slide is None
                or slide.slide_number != hit.slide_number
                or hit.embedding_version != version.embedding_version
                or hit.retrieval_schema_version != version.retrieval_schema_version
            ):
                inconsistency.append(f"hash_or_version_mismatch:{hit.point_id}")
        if inconsistency:
            await repositories.flag_index_drift(
                session,
                version=version,
                detail=";".join(inconsistency),
            )
            await session.commit()
            logger.error(
                "vector_hydration_inconsistent",
                active_deck_version_id=str(version.id),
                hydration_misses=len(inconsistency),
            )
            raise VectorIndexInconsistentError("; ".join(inconsistency))

        forced: list[tuple[Chunk, str]] = []
        current_chunks = await repositories.get_chunks_for_slide(
            session,
            deck_version_id=version.id,
            slide_id=current_slide_id,
        )
        if selected_match is not None:
            block_id = str(selected_match.block_id)
            forced.extend(
                (chunk, "selected_block")
                for chunk in current_chunks
                if block_id in {str(item) for item in chunk.metadata_json.get("block_ids", [])}
            )
        force_current_slide = selected_match is not None or query.scope == "current_slide"
        if force_current_slide:
            slide_level = next(
                (chunk for chunk in current_chunks if chunk.chunk_type == "slide"),
                None,
            )
            if slide_level is not None:
                forced.append((slide_level, "current_slide"))
            elif current_chunks:
                forced.append((current_chunks[0], "current_slide"))

        neighbors = (
            _prefer_slide_chunks(
                await repositories.get_neighbor_chunks(
                    session,
                    deck_version_id=version.id,
                    slide_number=current_slide.slide_number,
                )
            )
            if force_current_slide
            else []
        )

        merged: list[tuple[Chunk, str, float | None]] = []
        seen: set[UUID] = set()
        for chunk, source in forced:
            if chunk.id not in seen:
                merged.append((chunk, source, None))
                seen.add(chunk.id)
        for hit in hits:
            chunk = hydrated_by_id[hit.point_id]
            if chunk.id not in seen:
                merged.append((chunk, "qdrant_rrf", hit.score))
                seen.add(chunk.id)
        for chunk in neighbors:
            if chunk.id not in seen:
                merged.append((chunk, "neighbor", None))
                seen.add(chunk.id)

        fused_rank_by_id = {hit.point_id: rank for rank, hit in enumerate(hits, start=1)}
        candidates_debug = [
            {
                "chunk_id": str(chunk.id),
                "source": source,
                "rrf_score": score,
                "fused_rank": fused_rank_by_id.get(chunk.id),
                "slide_id": str(chunk.slide_id),
            }
            for chunk, source, score in merged
        ]

        rerank_started = time.perf_counter()
        candidate_payload = [
            {
                "chunk_id": str(chunk.id),
                "text": chunk.text,
                "chunk_type": chunk.chunk_type,
                "source": source,
            }
            for chunk, source, _ in merged[:20]
        ]
        # Canonical rows are fully hydrated; release PostgreSQL while the
        # reranker runs.
        await session.commit()
        try:
            reranked = await self.llm.rerank(
                query=query.rewritten_query,
                candidates=candidate_payload,
                limit=self.settings.retrieval_context_limit,
            )
            rank_ids = [
                item.chunk_id
                for item in reranked
                if item.relevance >= self.settings.rerank_min_relevance
            ]
        except GenerationProviderUnavailableError:
            rank_ids = [chunk.id for chunk, _, _ in merged]
        rerank_ms = _elapsed_ms(rerank_started)

        by_id = {chunk.id: chunk for chunk, _, _ in merged}
        mandatory_ids = [
            chunk.id for chunk, source, _ in merged if source in {"selected_block", "current_slide"}
        ]
        mandatory_set = set(mandatory_ids)
        optional_ids = [item for item in rank_ids if item in by_id and item not in mandatory_set]
        ordered = [by_id[item] for item in [*mandatory_ids, *optional_ids]]
        selected_chunks = _fit_budget(
            _deduplicate(ordered),
            token_budget=self.settings.context_token_budget,
            limit=self.settings.retrieval_context_limit,
        )
        result_slides = {chunk.slide_id: slide_by_id[chunk.slide_id] for chunk in selected_chunks}
        total_ms = _elapsed_ms(total_started)
        logger.info(
            "hybrid_retrieval_completed",
            active_deck_version_id=str(version.id),
            filter_fields=["course_id", "deck_id", "deck_version_id"],
            qdrant_count_ms=count_ms,
            qdrant_hybrid_ms=qdrant_ms,
            fused_candidate_count=len(hits),
            hydration_misses=0,
            selected_count=len(selected_chunks),
            embedding_model=self.settings.openai_embedding_model,
            retrieval_schema_version=version.retrieval_schema_version,
        )
        return RetrievalResult(
            query=query,
            chunks=selected_chunks,
            slides=result_slides,
            selected_match=selected_match,
            candidates_debug=candidates_debug,
            filters_debug={
                "course_id": str(course_id),
                "deck_id": str(deck_id),
                "deck_version_id": str(version.id),
                "response_mode": query.response_mode,
                "reason_code": query.reason_code or "",
                "scope": query.scope,
                "intent": query.intent,
                "conversation_history_turns": conversation_history_turns,
            },
            timings_ms={
                "query_understanding": understanding_ms,
                "qdrant_count": count_ms,
                "query_embedding": embedding_ms,
                "qdrant_hybrid": qdrant_ms,
                "rerank": rerank_ms,
                "total": total_ms,
            },
        )


def _fit_budget(chunks: Sequence[Chunk], *, token_budget: int, limit: int) -> list[Chunk]:
    selected: list[Chunk] = []
    used = 0
    for chunk in chunks:
        if len(selected) >= limit:
            break
        if selected and used + chunk.token_count > token_budget:
            continue
        selected.append(chunk)
        used += chunk.token_count
    return selected


def _prefer_slide_chunks(chunks: Sequence[Chunk]) -> list[Chunk]:
    chunks_by_slide: dict[UUID, list[Chunk]] = {}
    slide_order: list[UUID] = []
    for chunk in chunks:
        if chunk.slide_id not in chunks_by_slide:
            slide_order.append(chunk.slide_id)
            chunks_by_slide[chunk.slide_id] = []
        chunks_by_slide[chunk.slide_id].append(chunk)

    ordered: list[Chunk] = []
    for slide_id in slide_order:
        slide_chunks = chunks_by_slide[slide_id]
        slide_level = next(
            (chunk for chunk in slide_chunks if chunk.chunk_type == "slide"),
            None,
        )
        if slide_level is not None:
            ordered.append(slide_level)
        else:
            ordered.extend(slide_chunks)
    return ordered


def _deduplicate(chunks: Sequence[Chunk]) -> list[Chunk]:
    selected: list[Chunk] = []
    seen_hashes: set[str] = set()
    for chunk in chunks:
        if chunk.content_hash in seen_hashes:
            continue
        duplicate = False
        for existing in selected:
            if existing.slide_id != chunk.slide_id:
                continue
            shorter, longer = sorted((existing.text, chunk.text), key=len)
            if shorter and shorter in longer and len(shorter) / max(1, len(longer)) > 0.85:
                duplicate = True
                break
        if not duplicate:
            selected.append(chunk)
            seen_hashes.add(chunk.content_hash)
    return selected


def _elapsed_ms(started: float) -> float:
    return round((time.perf_counter() - started) * 1000, 3)
