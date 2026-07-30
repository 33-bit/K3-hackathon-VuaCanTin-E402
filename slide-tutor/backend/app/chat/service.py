from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import DeckNotReadyError, NotFoundError, VectorIndexInconsistentError
from app.db import repositories
from app.models import ChatRequest, ChatResponse, Citation
from app.retrieval.service import RetrievalService
from app.services.openai_service import GeneratedAnswer, LLMProvider


@dataclass(slots=True)
class ChatService:
    settings: Settings
    llm: LLMProvider
    retrieval: RetrievalService

    async def answer(
        self,
        *,
        session: AsyncSession,
        user_id: UUID,
        request: ChatRequest,
    ) -> ChatResponse:
        context = await repositories.get_active_deck_context(
            session,
            deck_id=request.deck_id,
            user_id=user_id,
        )
        if context is None:
            raise DeckNotReadyError()
        if context.deck.course_id != request.course_id:
            raise NotFoundError("Deck not found")
        if (
            context.version.index_status != "in_sync"
            or context.version.embedding_model != self.settings.openai_embedding_model
            or context.version.embedding_dimensions != self.settings.openai_embedding_dimensions
            or context.version.embedding_version != self.settings.embedding_version
            or context.version.retrieval_schema_version != self.settings.retrieval_schema_version
        ):
            raise VectorIndexInconsistentError(
                "The active deck version is not compatible with the configured vector index"
            )

        retrieval_result = await self.retrieval.retrieve(
            session=session,
            version=context.version,
            course_id=request.course_id,
            deck_id=request.deck_id,
            current_slide_id=request.current_slide_id,
            selected_text=request.selected_text,
            question=request.question,
            language=request.language,
            explicit_ranges=[(item.start, item.end) for item in request.references],
        )
        contexts = [
            {
                "chunk_id": str(chunk.id),
                "slide_id": str(chunk.slide_id),
                "slide_number": retrieval_result.slides[chunk.slide_id].slide_number,
                "slide_title": retrieval_result.slides[chunk.slide_id].title,
                "section": retrieval_result.slides[chunk.slide_id].section,
                "text": chunk.text,
            }
            for chunk in retrieval_result.chunks
        ]
        generated = await self.llm.generate_answer(
            question=request.question,
            language=request.language,
            contexts=contexts,
        )
        generated = await self._validate_and_repair(
            question=request.question,
            language=request.language,
            contexts=contexts,
            generated=generated,
        )
        if generated.insufficient_evidence or not generated.answer.strip():
            missing_content_types = generated.missing_content_types
            generated = _safe_insufficient_answer(request.language)
            generated.missing_content_types = missing_content_types

        allowed_ids = {chunk.id for chunk in retrieval_result.chunks}
        cited_ids = [
            chunk_id for chunk_id in generated.citation_chunk_ids if chunk_id in allowed_ids
        ]
        if not cited_ids and not generated.insufficient_evidence:
            generated = _safe_insufficient_answer(request.language)

        citations = _build_citations(
            chunk_ids=cited_ids,
            chunks=retrieval_result.chunks,
            slides=retrieval_result.slides,
        )
        conversation = await repositories.create_conversation_if_needed(
            session,
            conversation_id=request.conversation_id,
            user_id=user_id,
            course_id=request.course_id,
            deck_id=request.deck_id,
        )
        retrieval_run = await repositories.create_retrieval_run(
            session,
            conversation_id=conversation.id,
            user_id=user_id,
            course_id=request.course_id,
            deck_id=request.deck_id,
            deck_version_id=context.version.id,
            current_slide_id=request.current_slide_id,
            original_query=request.question,
            rewritten_query=retrieval_result.query.rewritten_query,
            selected_text_match=(
                {
                    "block_id": str(retrieval_result.selected_match.block_id),
                    "score": retrieval_result.selected_match.score,
                    "exact": retrieval_result.selected_match.exact,
                }
                if retrieval_result.selected_match
                else None
            ),
            filters_json=retrieval_result.filters_debug,
            candidates_json=retrieval_result.candidates_debug,
            final_chunk_ids=[str(chunk.id) for chunk in retrieval_result.chunks],
            timings_json=retrieval_result.timings_ms,
            model_config_json={
                "answer_model": self.settings.openai_answer_model,
                "fast_model": self.settings.openai_fast_model,
                "embedding_model": self.settings.openai_embedding_model,
                "embedding_dimensions": self.settings.openai_embedding_dimensions,
                "retrieval_schema_version": context.version.retrieval_schema_version,
            },
            inconsistency_json=None,
        )
        _, assistant_message = await repositories.persist_chat_turn(
            session,
            conversation=conversation,
            question=request.question,
            answer=generated.answer,
            current_slide_id=request.current_slide_id,
            selected_text=request.selected_text,
            retrieved_chunk_ids=[chunk.id for chunk in retrieval_result.chunks],
            citations=[item.model_dump(mode="json") for item in citations],
        )
        await session.commit()
        return ChatResponse(
            conversation_id=conversation.id,
            message_id=assistant_message.id,
            answer=generated.answer,
            citations=citations,
            confidence=generated.confidence,
            insufficient_evidence=generated.insufficient_evidence,
            missing_content_types=generated.missing_content_types,
            retrieval_debug_id=retrieval_run.id,
        )

    async def _validate_and_repair(
        self,
        *,
        question: str,
        language: str,
        contexts: list[dict[str, Any]],
        generated: GeneratedAnswer,
    ) -> GeneratedAnswer:
        if generated.insufficient_evidence:
            return generated
        validation = await self.llm.validate_grounding(
            answer=generated.answer,
            contexts=contexts,
        )
        if validation.valid:
            return generated
        repaired = await self.llm.repair_answer(
            question=question,
            language=language,
            contexts=contexts,
            previous_answer=generated.answer,
            unsupported_claims=validation.unsupported_claims,
        )
        if repaired.insufficient_evidence:
            return repaired
        second_validation = await self.llm.validate_grounding(
            answer=repaired.answer,
            contexts=contexts,
        )
        if second_validation.valid:
            return repaired
        return _safe_insufficient_answer(language)


def _build_citations(
    *,
    chunk_ids: list[UUID],
    chunks: list[Any],
    slides: dict[UUID, Any],
) -> list[Citation]:
    chunks_by_id = {chunk.id: chunk for chunk in chunks}
    grouped: dict[UUID, list[UUID]] = {}
    for chunk_id in chunk_ids:
        chunk = chunks_by_id.get(chunk_id)
        if chunk is not None:
            grouped.setdefault(chunk.slide_id, []).append(chunk_id)
    citations = [
        Citation(
            slide_id=slide_id,
            slide_number=slides[slide_id].slide_number,
            title=slides[slide_id].title,
            chunk_ids=ids,
        )
        for slide_id, ids in grouped.items()
    ]
    citations.sort(key=lambda item: item.slide_number)
    return citations


def _safe_insufficient_answer(language: str) -> GeneratedAnswer:
    if language.lower().startswith("vi"):
        answer = "Không đủ dữ liệu văn bản trong slide để trả lời câu hỏi này một cách chắc chắn."
    else:
        answer = "The slide text does not contain enough evidence to answer this confidently."
    return GeneratedAnswer(
        answer=answer,
        citation_chunk_ids=[],
        confidence="low",
        insufficient_evidence=True,
        missing_content_types=[],
    )
