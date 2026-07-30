from __future__ import annotations

import re
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
            deck_title=context.deck.title,
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
        direct_response = retrieval_result.query.response_mode != "answer"
        generation_question = (
            retrieval_result.query.generation_question or request.question
        )
        if retrieval_result.query.scope == "range":
            coverage_outline = _build_coverage_outline(contexts)
        elif retrieval_result.query.scope == "current_slide":
            coverage_outline = _build_coverage_outline(
                contexts,
                slide_ids={str(request.current_slide_id)},
            )
        else:
            coverage_outline = []
        if direct_response:
            generated = _direct_decision_answer(
                answer=retrieval_result.query.direct_answer,
                response_mode=retrieval_result.query.response_mode,
                force_insufficient=retrieval_result.query.force_insufficient,
                language=request.language,
            )
        else:
            generated = await self.llm.generate_answer(
                question=generation_question,
                language=request.language,
                contexts=contexts,
                coverage_outline=coverage_outline,
                intent=retrieval_result.query.intent,
            )
            generated = await self._validate_and_repair(
                question=generation_question,
                language=request.language,
                contexts=contexts,
                coverage_outline=coverage_outline,
                intent=retrieval_result.query.intent,
                generated=generated,
            )
            generated = _fallback_if_answer_is_empty(
                generated=generated,
                language=request.language,
            )

        allowed_ids = {chunk.id for chunk in retrieval_result.chunks}
        cited_ids = [
            chunk_id for chunk_id in generated.citation_chunk_ids if chunk_id in allowed_ids
        ]
        if not direct_response and not cited_ids and not generated.insufficient_evidence:
            generated = _safe_insufficient_answer(request.language)
        if retrieval_result.query.notices:
            generated.answer = _append_notices(
                generated.answer,
                retrieval_result.query.notices,
            )
            if retrieval_result.query.force_insufficient:
                generated.insufficient_evidence = True
                generated.confidence = "low"

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
                "model": self.settings.openai_model,
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
        coverage_outline: list[dict[str, Any]],
        intent: str,
        generated: GeneratedAnswer,
    ) -> GeneratedAnswer:
        if generated.insufficient_evidence:
            generated.citation_chunk_ids = []
            return generated
        contract_violations = _answer_contract_violations(
            intent=intent,
            answer=generated.answer,
        )
        validation = await self.llm.validate_grounding(
            answer=generated.answer,
            contexts=contexts,
            question=question,
            coverage_outline=coverage_outline,
            intent=intent,
        )
        if validation.valid and not contract_violations:
            if validation.supported_chunk_ids:
                supported = set(validation.supported_chunk_ids)
                generated.citation_chunk_ids = [
                    chunk_id
                    for chunk_id in generated.citation_chunk_ids
                    if chunk_id in supported
                ]
            return generated
        missing_topics = list(
            dict.fromkeys([*validation.missing_topics, *contract_violations])
        )
        if not validation.unsupported_claims and not missing_topics:
            generated.confidence = "medium"
            return generated
        repaired = await self.llm.repair_answer(
            question=question,
            language=language,
            contexts=contexts,
            previous_answer=generated.answer,
            unsupported_claims=validation.unsupported_claims,
            missing_topics=missing_topics,
            coverage_outline=coverage_outline,
            intent=intent,
        )
        if repaired.insufficient_evidence:
            repaired.citation_chunk_ids = []
            return repaired
        if _answer_contract_violations(intent=intent, answer=repaired.answer):
            repaired.confidence = "medium"
        return repaired


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


def _direct_decision_answer(
    *,
    answer: str | None,
    response_mode: str,
    force_insufficient: bool,
    language: str,
) -> GeneratedAnswer:
    if not answer:
        return _safe_insufficient_answer(language)
    insufficient = force_insufficient or response_mode in {"clarify", "insufficient"}
    return GeneratedAnswer(
        answer=answer,
        citation_chunk_ids=[],
        confidence="low" if insufficient else "medium",
        insufficient_evidence=insufficient,
        missing_content_types=[],
    )


def _fallback_if_answer_is_empty(
    *,
    generated: GeneratedAnswer,
    language: str,
) -> GeneratedAnswer:
    """Keep a useful, explicit insufficiency explanation; replace only an empty answer."""
    if generated.answer.strip():
        return generated
    fallback = _safe_insufficient_answer(language)
    fallback.missing_content_types = generated.missing_content_types
    return fallback


def _answer_contract_violations(*, intent: str, answer: str) -> list[str]:
    normalized = answer.strip()
    violations: list[str] = []
    if intent == "summary_then_key_takeaways":
        has_summary = bool(
            re.search(r"(?im)^\s*(?:#{1,4}\s*)?(?:tóm tắt|summary)\b", normalized)
        )
        has_key_points = bool(
            re.search(
                r"(?im)^\s*(?:#{1,4}\s*)?"
                r"(?:các\s+)?(?:ý chính|điểm chính|key points?|takeaways?)\b",
                normalized,
            )
        )
        if not has_summary or not has_key_points:
            violations.append(
                "Tách rõ hai phần có tiêu đề: Tóm tắt và Ý chính."
            )
    elif intent == "practice_quiz" and normalized.count("?") < 5:
        violations.append(
            "Tạo ít nhất 5 câu hỏi luyện tập trải trên các chủ đề khác nhau."
        )
    return violations


def _append_notices(answer: str, notices: list[str]) -> str:
    unique_notices = list(dict.fromkeys(item.strip() for item in notices if item.strip()))
    if not unique_notices:
        return answer
    return f"{answer.rstrip()}\n\n" + "\n".join(unique_notices)


def _build_coverage_outline(
    contexts: list[dict[str, Any]],
    *,
    slide_ids: set[str] | None = None,
) -> list[dict[str, Any]]:
    """Build an ordered, ID-free topic checklist from canonical range contexts."""
    by_slide: dict[int, dict[str, Any]] = {}
    for context in contexts:
        if slide_ids is not None and str(context.get("slide_id")) not in slide_ids:
            continue
        try:
            slide_number = int(context["slide_number"])
        except (KeyError, TypeError, ValueError):
            continue
        entry = by_slide.setdefault(
            slide_number,
            {
                "slide_number": slide_number,
                "title": context.get("slide_title"),
                "section": context.get("section"),
                "topic_hint": "",
            },
        )
        if entry["topic_hint"]:
            continue
        text = " ".join(str(context.get("text") or "").split())
        if text:
            entry["topic_hint"] = text[:240]
    return [by_slide[number] for number in sorted(by_slide)]
