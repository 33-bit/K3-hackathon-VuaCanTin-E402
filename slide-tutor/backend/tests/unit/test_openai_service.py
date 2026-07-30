from __future__ import annotations

from typing import Any

import pytest

from app.core.config import Settings
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

    async def _json_completion(self, **_: Any) -> dict[str, Any]:
        self.completion_calls += 1
        return {
            "rewritten_query": "hybrid retrieval là gì",
            "scope": "retrieval",
            "intent": "explain",
            "slide_start": None,
            "slide_end": None,
        }


@pytest.mark.asyncio
async def test_query_understanding_uses_redis_as_best_effort_cache() -> None:
    cache = MemoryCache()
    service = QueryStubOpenAIService(
        Settings(_env_file=None),
        cache=cache,
    )

    first = await service.understand_query(
        question="Hybrid retrieval là gì?",
        selected_text=None,
        current_slide_title="RAG",
        language="vi",
    )
    second = await service.understand_query(
        question="Hybrid retrieval là gì?",
        selected_text=None,
        current_slide_title="RAG",
        language="vi",
    )

    assert first == second
    assert service.completion_calls == 1
    assert cache.set_calls == 1
    assert len(cache.values) == 1
    assert next(iter(cache.values)).startswith("slide_tutor:query_understanding:")


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
