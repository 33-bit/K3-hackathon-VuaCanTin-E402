from __future__ import annotations

import json
from typing import Any
from uuid import UUID

import pytest

from app.core.config import Settings
from app.ingestion.tokenizer import Tokenizer
from app.services.openai_service import OpenAIService


class MemoryCache:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.set_calls = 0

    async def get(self, name: str) -> str | None:
        return self.values.get(name)

    async def set(
        self,
        name: str,
        value: str,
        *,
        ex: int,
    ) -> None:
        assert ex > 0
        self.values[name] = value
        self.set_calls += 1


class QueryStubOpenAIService(OpenAIService):
    completion_calls = 0
    last_completion_kwargs: dict[str, Any] = {}

    async def _json_completion(self, **kwargs: Any) -> dict[str, Any]:
        self.completion_calls += 1
        self.last_completion_kwargs = kwargs
        return {
            "rewritten_query": "hybrid retrieval là gì",
            "scope": "retrieval",
            "intent": "explain",
            "slide_start": None,
            "slide_end": None,
        }


class NullOptionalListsOpenAIService(OpenAIService):
    async def _json_completion(self, **_: Any) -> dict[str, Any]:
        return {
            "answer": "Grounded answer",
            "citation_chunk_ids": ["00000000-0000-0000-0000-000000000123"],
            "confidence": "high",
            "insufficient_evidence": False,
            "missing_content_types": None,
        }


class UUIDLeakingOpenAIService(OpenAIService):
    async def _json_completion(self, **_: Any) -> dict[str, Any]:
        chunk_id = "00000000-0000-5000-8000-000000000123"
        return {
            "answer": (
                f"Nội dung có căn cứ. [{chunk_id}] "
                f"Chi tiết thứ hai (chunk_id: {chunk_id})."
            ),
            "citation_chunk_ids": [chunk_id],
            "confidence": "high",
            "insufficient_evidence": False,
            "missing_content_types": [],
        }


class SummaryStubOpenAIService(OpenAIService):
    completion_calls = 0
    last_completion_kwargs: dict[str, Any] = {}

    async def _json_completion(self, **kwargs: Any) -> dict[str, Any]:
        self.completion_calls += 1
        self.last_completion_kwargs = kwargs
        return {"summary": "attention " * 500}


@pytest.mark.asyncio
async def test_query_understanding_uses_redis_as_best_effort_cache() -> None:
    cache = MemoryCache()
    service = QueryStubOpenAIService(
        Settings(_env_file=None),
        cache=cache,
    )
    history = [
        {
            "user_question": "Attention là gì?",
            "assistant_answer": "Attention giúp model tập trung.",
            "slide_number": 15,
        }
    ]

    first = await service.understand_query(
        question="Giải thích kỹ hơn",
        selected_text=None,
        current_slide_title="RAG",
        language="vi",
        conversation_history=history,
    )
    second = await service.understand_query(
        question="Giải thích kỹ hơn",
        selected_text=None,
        current_slide_title="RAG",
        language="vi",
        conversation_history=history,
    )

    assert first == second
    assert service.completion_calls == 1
    assert cache.set_calls == 1
    assert len(cache.values) == 1
    assert next(iter(cache.values)).startswith("slide_tutor:query_understanding:")
    assert service.last_completion_kwargs["schema_name"] == "query_understanding"
    assert service.last_completion_kwargs["response_schema"]["additionalProperties"] is False
    request_payload = json.loads(service.last_completion_kwargs["user"])
    assert request_payload["conversation_history"] == history


@pytest.mark.asyncio
async def test_query_cache_is_isolated_by_conversation_history() -> None:
    cache = MemoryCache()
    service = QueryStubOpenAIService(Settings(_env_file=None), cache=cache)

    for topic in ("attention", "agent"):
        await service.understand_query(
            question="Giải thích kỹ hơn",
            selected_text=None,
            current_slide_title="RAG",
            language="vi",
            conversation_history=[{"user_question": f"{topic} là gì?"}],
        )

    assert service.completion_calls == 2
    assert cache.set_calls == 2
    assert len(cache.values) == 2


@pytest.mark.asyncio
async def test_conversation_summary_is_cached_and_token_bounded() -> None:
    cache = MemoryCache()
    service = SummaryStubOpenAIService(Settings(_env_file=None), cache=cache)
    history = [
        {
            "user_question": "Attention là gì?",
            "assistant_answer": "Attention giúp model tập trung.",
            "slide_number": 15,
        }
    ]

    first = await service.summarize_conversation(
        conversation_history=history,
        language="vi",
        token_budget=40,
    )
    second = await service.summarize_conversation(
        conversation_history=history,
        language="vi",
        token_budget=40,
    )

    assert first == second
    assert service.completion_calls == 1
    assert cache.set_calls == 1
    assert next(iter(cache.values)).startswith("slide_tutor:conversation_summary:")
    assert Tokenizer(force_fallback=True).count(first) <= 40


@pytest.mark.asyncio
async def test_rolling_summary_receives_old_memory_and_new_turn() -> None:
    service = SummaryStubOpenAIService(Settings(_env_file=None), cache=MemoryCache())
    new_turn = {
        "user_question": "Giải thích kỹ hơn",
        "assistant_answer": "Giải thích mới có citation.",
        "citation_slides": [15],
    }

    summary = await service.update_conversation_summary(
        previous_summary="Người học đã hỏi về attention.",
        new_turn=new_turn,
        language="vi",
        token_budget=80,
    )

    request = json.loads(service.last_completion_kwargs["user"])
    assert request["previous_summary"] == "Người học đã hỏi về attention."
    assert request["new_turn"] == new_turn
    assert service.last_completion_kwargs["schema_name"] == "rolling_conversation_summary"
    assert Tokenizer(force_fallback=True).count(summary) <= 80


@pytest.mark.asyncio
async def test_empty_context_answer_respects_requested_language() -> None:
    service = OpenAIService(Settings(_env_file=None))

    answer = await service.generate_answer(
        question="What is this?",
        language="en",
        contexts=[],
    )

    assert answer.insufficient_evidence is True
    assert answer.confidence == "low"
    assert answer.citation_chunk_ids == []
    assert answer.answer.startswith("The slide text")


@pytest.mark.asyncio
async def test_null_optional_lists_do_not_crash_structured_answer_parsing() -> None:
    chunk_id = UUID("00000000-0000-0000-0000-000000000123")
    service = NullOptionalListsOpenAIService(Settings(_env_file=None))

    answer = await service.generate_answer(
        question="Explain this",
        language="en",
        contexts=[
            {
                "chunk_id": str(chunk_id),
                "slide_number": 1,
                "text": "Grounded evidence",
            }
        ],
    )

    assert answer.answer == "Grounded answer"
    assert answer.citation_chunk_ids == [chunk_id]
    assert answer.missing_content_types == []


@pytest.mark.asyncio
async def test_internal_uuid_citations_are_removed_from_answer_text() -> None:
    chunk_id = UUID("00000000-0000-5000-8000-000000000123")
    service = UUIDLeakingOpenAIService(Settings(_env_file=None))

    answer = await service.generate_answer(
        question="Tóm tắt slide",
        language="vi",
        contexts=[
            {
                "chunk_id": str(chunk_id),
                "slide_number": 1,
                "text": "Nội dung có căn cứ.",
            }
        ],
    )

    assert answer.answer == "Nội dung có căn cứ. Chi tiết thứ hai."
    assert answer.citation_chunk_ids == [chunk_id]
