from __future__ import annotations

from typing import Any
from uuid import UUID

import pytest

from app.chat.service import (
    ChatService,
    _answer_contract_violations,
    _append_notices,
    _build_coverage_outline,
    _direct_decision_answer,
    _fallback_if_answer_is_empty,
)
from app.core.config import Settings
from app.services.openai_service import GeneratedAnswer, GroundingResult


class _CoverageRepairLLM:
    def __init__(self) -> None:
        self.validation_calls = 0
        self.repair_missing_topics: list[str] = []

    async def validate_grounding(self, **_: Any) -> GroundingResult:
        self.validation_calls += 1
        if self.validation_calls == 1:
            return GroundingResult(
                valid=False,
                supported_chunk_ids=[],
                missing_topics=["AI agents ở slide 24"],
            )
        return GroundingResult(valid=True, supported_chunk_ids=[])

    async def repair_answer(
        self,
        *,
        missing_topics: list[str],
        **_: Any,
    ) -> GeneratedAnswer:
        self.repair_missing_topics = missing_topics
        return GeneratedAnswer(
            answer="Bản sửa đã bổ sung AI agents.",
            citation_chunk_ids=[UUID("00000000-0000-5000-8000-000000000123")],
            confidence="high",
            insufficient_evidence=False,
        )


class _ReasonlessInvalidLLM:
    repair_called = False

    async def validate_grounding(self, **_: Any) -> GroundingResult:
        return GroundingResult(valid=False, supported_chunk_ids=[])

    async def repair_answer(self, **_: Any) -> GeneratedAnswer:
        self.repair_called = True
        raise AssertionError("A reasonless invalid result must not erase a useful answer")


class _FailedCoverageRepairLLM:
    async def validate_grounding(self, **_: Any) -> GroundingResult:
        return GroundingResult(
            valid=False,
            supported_chunk_ids=[],
            missing_topics=["Một chủ đề phụ"],
        )

    async def repair_answer(self, **_: Any) -> GeneratedAnswer:
        return GeneratedAnswer(
            answer="Không đủ căn cứ để sửa.",
            citation_chunk_ids=[],
            confidence="low",
            insufficient_evidence=True,
        )


def test_refusal_can_be_returned_without_fake_slide_citations() -> None:
    answer = _direct_decision_answer(
        answer="Mình không có quyền sửa điểm.",
        response_mode="refuse",
        force_insufficient=False,
        language="vi",
    )

    assert answer.answer == "Mình không có quyền sửa điểm."
    assert answer.citation_chunk_ids == []
    assert answer.insufficient_evidence is False
    assert answer.confidence == "medium"


def test_clarification_is_marked_as_insufficient_context() -> None:
    answer = _direct_decision_answer(
        answer="Bạn muốn so sánh hai khái niệm nào?",
        response_mode="clarify",
        force_insufficient=False,
        language="vi",
    )

    assert answer.insufficient_evidence is True
    assert answer.confidence == "low"


def test_partial_range_notices_are_deduplicated_and_kept() -> None:
    answer = _append_notices(
        "Tóm tắt phần có sẵn.",
        [
            "Deck chỉ có 29 slide.",
            "Deck chỉ có 29 slide.",
            "Hãy kiểm tra LMS hoặc hỏi TA.",
        ],
    )

    assert answer.count("Deck chỉ có 29 slide.") == 1
    assert answer.endswith("Hãy kiểm tra LMS hoặc hỏi TA.")


def test_coverage_outline_is_ordered_and_contains_no_internal_ids() -> None:
    outline = _build_coverage_outline(
        [
            {
                "chunk_id": "internal-2",
                "slide_number": 2,
                "slide_title": "Agents",
                "section": "Applications",
                "text": "Agents can plan and use tools.",
            },
            {
                "chunk_id": "internal-1",
                "slide_number": 1,
                "slide_title": "Context",
                "section": "LLM",
                "text": "Context and attention determine what the model can use.",
            },
        ]
    )

    assert [item["slide_number"] for item in outline] == [1, 2]
    assert outline[1]["title"] == "Agents"
    assert "chunk_id" not in outline[0]


def test_current_slide_outline_excludes_neighbor_contexts() -> None:
    outline = _build_coverage_outline(
        [
            {
                "slide_id": "current",
                "slide_number": 29,
                "slide_title": "Temperature",
                "text": "Temperature changes token selection.",
            },
            {
                "slide_id": "neighbor",
                "slide_number": 28,
                "slide_title": "Prompt",
                "text": "A prompt has four layers.",
            },
        ],
        slide_ids={"current"},
    )

    assert [item["slide_number"] for item in outline] == [29]


def test_specific_insufficient_answer_is_not_replaced_by_generic_text() -> None:
    generated = GeneratedAnswer(
        answer="Deck không cung cấp con số benchmark MMLU được hỏi.",
        citation_chunk_ids=[],
        confidence="low",
        insufficient_evidence=True,
    )

    result = _fallback_if_answer_is_empty(generated=generated, language="vi")

    assert result is generated
    assert "MMLU" in result.answer


@pytest.mark.asyncio
async def test_specific_insufficient_answer_does_not_cite_an_unrelated_slide() -> None:
    service = ChatService(
        settings=Settings(_env_file=None),
        llm=_ReasonlessInvalidLLM(),  # type: ignore[arg-type]
        retrieval=None,  # type: ignore[arg-type]
    )
    generated = GeneratedAnswer(
        answer="Deck không cung cấp con số benchmark được hỏi.",
        citation_chunk_ids=[UUID("00000000-0000-5000-8000-000000000123")],
        confidence="low",
        insufficient_evidence=True,
    )

    result = await service._validate_and_repair(
        question="Deck có con số benchmark không?",
        language="vi",
        contexts=[],
        coverage_outline=[],
        intent="fact_lookup",
        generated=generated,
    )

    assert result.answer == generated.answer
    assert result.citation_chunk_ids == []


@pytest.mark.asyncio
async def test_missing_coverage_topics_trigger_one_repair() -> None:
    llm = _CoverageRepairLLM()
    service = ChatService(
        settings=Settings(_env_file=None),
        llm=llm,  # type: ignore[arg-type]
        retrieval=None,  # type: ignore[arg-type]
    )
    generated = GeneratedAnswer(
        answer="Bản đầu chưa nói về agents.",
        citation_chunk_ids=[UUID("00000000-0000-5000-8000-000000000123")],
        confidence="medium",
        insufficient_evidence=False,
    )

    result = await service._validate_and_repair(
        question="Tóm tắt toàn bộ deck",
        language="vi",
        contexts=[],
        coverage_outline=[{"slide_number": 24, "title": "Agents"}],
        intent="all_deck_summary",
        generated=generated,
    )

    assert result.answer == "Bản sửa đã bổ sung AI agents."
    assert llm.repair_missing_topics == ["AI agents ở slide 24"]
    assert llm.validation_calls == 1


@pytest.mark.asyncio
async def test_reasonless_validator_failure_does_not_erase_grounded_answer() -> None:
    llm = _ReasonlessInvalidLLM()
    service = ChatService(
        settings=Settings(_env_file=None),
        llm=llm,  # type: ignore[arg-type]
        retrieval=None,  # type: ignore[arg-type]
    )
    generated = GeneratedAnswer(
        answer="Tóm tắt hữu ích có nguồn.",
        citation_chunk_ids=[UUID("00000000-0000-5000-8000-000000000123")],
        confidence="high",
        insufficient_evidence=False,
    )

    result = await service._validate_and_repair(
        question="Tóm tắt deck",
        language="vi",
        contexts=[],
        coverage_outline=[],
        intent="all_deck_summary",
        generated=generated,
    )

    assert result is generated
    assert result.confidence == "medium"
    assert llm.repair_called is False


@pytest.mark.asyncio
async def test_insufficient_repair_clears_unrelated_citations() -> None:
    service = ChatService(
        settings=Settings(_env_file=None),
        llm=_FailedCoverageRepairLLM(),  # type: ignore[arg-type]
        retrieval=None,  # type: ignore[arg-type]
    )
    generated = GeneratedAnswer(
        answer="Tóm tắt chính vẫn hữu ích và có nguồn.",
        citation_chunk_ids=[UUID("00000000-0000-5000-8000-000000000123")],
        confidence="high",
        insufficient_evidence=False,
    )

    result = await service._validate_and_repair(
        question="Tóm tắt toàn bộ deck",
        language="vi",
        contexts=[],
        coverage_outline=[{"slide_number": 24, "title": "Agent"}],
        intent="all_deck_summary",
        generated=generated,
    )

    assert result.insufficient_evidence is True
    assert result.citation_chunk_ids == []


def test_summary_then_takeaways_contract_requires_two_visible_sections() -> None:
    assert _answer_contract_violations(
        intent="summary_then_key_takeaways",
        answer="## Tóm tắt\nNội dung.\n\n## Ý chính\n- Một ý.",
    ) == []
    assert _answer_contract_violations(
        intent="summary_then_key_takeaways",
        answer="Dưới đây là một danh sách nội dung chung.",
    )


def test_practice_quiz_contract_counts_questions_without_case_specific_rules() -> None:
    answer = "\n".join(f"{number}. Câu hỏi {number}?" for number in range(1, 6))

    assert _answer_contract_violations(
        intent="practice_quiz",
        answer=answer,
    ) == []
    assert _answer_contract_violations(
        intent="practice_quiz",
        answer="1. Một câu?\n2. Hai câu?",
    )
