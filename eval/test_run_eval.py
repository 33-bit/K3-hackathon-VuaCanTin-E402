from __future__ import annotations

import pytest

from finalize_review import (
    immutable_review_hash,
    score_review_packet,
    validate_completed_reviews,
)
from run_eval import build_review_packet, deterministic_checks


def _case() -> dict:
    return {
        "id": "VL-T01",
        "title": "Grounded answer",
        "situation_type": "source_truth",
        "rarity": "common",
        "origin": {"type": "self_test", "basis": "manual"},
        "input": {"current_slide_number": 1, "question": "Nội dung là gì?"},
        "expected": {
            "description": "Trả lời đúng nguồn",
            "expected_http_status": 200,
            "expected_insufficient_evidence": False,
            "min_citation_count": 1,
            "allowed_citation_slides": [1],
        },
    }


def test_deterministic_checks_reject_out_of_scope_citation() -> None:
    case = _case()
    passed, failures = deterministic_checks(
        case=case,
        http_status=200,
        response={
            "answer": "Có căn cứ.",
            "citations": [{"slide_number": 2}],
            "insufficient_evidence": False,
        },
        valid_slide_numbers={1, 2},
    )

    assert passed is False
    assert failures == ["citations outside allowed scope: [2]"]


def test_review_packet_keeps_expected_and_actual_without_model_judge() -> None:
    case = _case()
    packet = build_review_packet(
        golden={
            "name": "test",
            "version": "1",
            "quality_bar": {"minimum_passed_cases": 1, "total_cases": 1},
            "cases": [case],
        },
        coverage={"total": 1},
        results=[
            {
                "case_id": case["id"],
                "title": case["title"],
                "situation_type": case["situation_type"],
                "rarity": case["rarity"],
                "http_status": 200,
                "latency_ms": 10,
                "answer": "Có căn cứ.",
                "citations": [{"slide_number": 1}],
                "confidence": "high",
                "insufficient_evidence": False,
                "deterministic_pass": True,
                "deterministic_failures": [],
            }
        ],
        deck_id="deck",
        run_id="run",
    )

    review_case = packet["cases"][0]
    assert packet["review_method"] == "human_or_codex"
    assert review_case["expected"] == case["expected"]
    assert review_case["actual"]["answer"] == "Có căn cứ."
    assert review_case["review"]["pass"] is None


def test_incomplete_review_cannot_be_scored() -> None:
    packet = {"schema_version": "1.0", "cases": [{"case_id": "VL-T01", "review": {}}]}

    with pytest.raises(ValueError, match="review.reviewer is required"):
        validate_completed_reviews(packet)


def test_final_score_requires_deterministic_and_content_review() -> None:
    cases = []
    for case_id, deterministic_pass, review_pass in (
        ("VL-1", True, True),
        ("VL-2", False, True),
        ("VL-3", True, False),
    ):
        cases.append(
                {
                    "case_id": case_id,
                    "title": case_id,
                    "situation_type": "normal",
                    "input": {"question": "Test"},
                    "expected": {"description": "Expected"},
                    "actual": {"citations": []},
                "deterministic": {
                    "pass": deterministic_pass,
                    "failures": [] if deterministic_pass else ["bad citation"],
                },
                "review": {
                    "reviewer": "Codex",
                    "pass": review_pass,
                    "reason": "Đã đối chiếu expected.",
                },
            }
        )
        cases[-1]["immutable_sha256"] = immutable_review_hash(cases[-1])
    packet = {
        "schema_version": "1.0",
        "coverage": {"total": 3},
        "quality_bar": {"minimum_passed_cases": 2},
        "cases": cases,
    }

    score = score_review_packet(packet)

    assert score["passed"] == 1
    assert [row["final_pass"] for row in score["rows"]] == [True, False, False]
