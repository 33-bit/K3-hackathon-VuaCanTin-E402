from __future__ import annotations

from app.chat.service import _append_notices, _direct_decision_answer


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
