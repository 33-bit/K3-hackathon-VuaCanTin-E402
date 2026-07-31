from __future__ import annotations

import json
from dataclasses import dataclass

from app.chat.history import (
    build_conversation_history,
    build_fallback_conversation_summary,
    build_fallback_rolling_summary,
    compact_rolling_summary_input,
)
from app.ingestion.tokenizer import Tokenizer


@dataclass(frozen=True, slots=True)
class _Message:
    role: str
    content: str
    slide_number: int | None = None
    slide_title: str | None = None
    selected_text: str | None = None


def test_history_keeps_only_recent_complete_turns_in_chronological_order() -> None:
    messages: list[_Message] = []
    for number in range(1, 6):
        messages.extend(
            [
                _Message(
                    role="user",
                    content=f"Câu hỏi {number}",
                    slide_number=number,
                    slide_title=f"Slide {number}",
                ),
                _Message(role="assistant", content=f"Câu trả lời {number}"),
            ]
        )

    history = build_conversation_history(
        messages,
        max_turns=4,
        token_budget=2_500,
        tokenizer=Tokenizer(force_fallback=True),
    )

    assert [turn["user_question"] for turn in history] == [
        "Câu hỏi 2",
        "Câu hỏi 3",
        "Câu hỏi 4",
        "Câu hỏi 5",
    ]
    assert history[-1]["assistant_answer"] == "Câu trả lời 5"
    assert history[-1]["slide_number"] == 5


def test_history_is_token_bounded_and_truncates_long_answers() -> None:
    tokenizer = Tokenizer(force_fallback=True)
    messages = [
        _Message(role="user", content="Hãy giải thích attention", slide_number=15),
        _Message(role="assistant", content="attention " * 2_000),
    ]

    history = build_conversation_history(
        messages,
        max_turns=4,
        token_budget=300,
        tokenizer=tokenizer,
    )

    assert len(history) == 1
    assert history[0]["user_question"] == "Hãy giải thích attention"
    assert history[0]["assistant_answer"].endswith("…")
    assert tokenizer.count(json.dumps(history, ensure_ascii=False)) <= 300


def test_orphan_assistant_message_is_not_used_as_history_evidence() -> None:
    history = build_conversation_history(
        [_Message(role="assistant", content="Một câu trả lời không có câu hỏi.")],
        max_turns=4,
        token_budget=500,
        tokenizer=Tokenizer(force_fallback=True),
    )

    assert history == []


def test_fallback_summary_keeps_questions_and_answers_within_budget() -> None:
    tokenizer = Tokenizer(force_fallback=True)
    summary = build_fallback_conversation_summary(
        [
            {
                "user_question": "Attention là gì?",
                "assistant_answer": "Attention giúp mô hình tập trung vào token liên quan.",
                "slide_number": 15,
            },
            {
                "user_question": "Context là gì?",
                "assistant_answer": "Context là lượng thông tin mô hình nhìn thấy.",
                "slide_number": 14,
            },
        ],
        token_budget=120,
        tokenizer=tokenizer,
    )

    assert "Người học hỏi" in summary
    assert "Tutor đã trả lời" in summary
    assert "Context là gì?" in summary
    assert tokenizer.count(summary) <= 120


def test_fallback_rolling_summary_keeps_newest_turn_and_hard_limit() -> None:
    tokenizer = Tokenizer(force_fallback=True)
    summary = build_fallback_rolling_summary(
        "Nội dung cũ " * 500,
        {
            "user_question": "Câu hỏi mới nhất là gì?",
            "assistant_answer": "Đây là câu trả lời mới nhất.",
        },
        token_budget=100,
        tokenizer=tokenizer,
    )

    assert "Câu hỏi mới nhất" in summary
    assert "câu trả lời mới nhất" in summary
    assert tokenizer.count(summary) <= 100


def test_rolling_summary_input_is_bounded_before_provider_call() -> None:
    tokenizer = Tokenizer(force_fallback=True)
    previous, new_turn = compact_rolling_summary_input(
        "memory " * 2_000,
        {
            "user_question": "question " * 2_000,
            "assistant_answer": "answer " * 4_000,
            "selected_text": "selection " * 1_000,
            "citation_slides": list(range(1, 100)),
        },
        token_budget=600,
        tokenizer=tokenizer,
    )
    payload = json.dumps(
        {"previous_summary": previous, "new_turn": new_turn},
        ensure_ascii=False,
    )

    assert tokenizer.count(payload) <= 600
    assert 1 <= len(new_turn["citation_slides"]) <= 50
