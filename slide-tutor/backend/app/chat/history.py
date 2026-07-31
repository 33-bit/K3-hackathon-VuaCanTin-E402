from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any, Protocol

from app.ingestion.tokenizer import Tokenizer


class HistoryMessage(Protocol):
    role: str
    content: str
    slide_number: int | None
    slide_title: str | None
    selected_text: str | None


def build_conversation_history(
    messages: Sequence[HistoryMessage],
    *,
    max_turns: int,
    token_budget: int,
    tokenizer: Tokenizer | None = None,
) -> list[dict[str, Any]]:
    """Build a bounded, structured history payload from persisted messages.

    Newest turns are preferred. Each turn keeps the prior user question,
    assistant answer and UI slide context together so a follow-up can resolve
    phrases such as "cái trước" without treating an old answer as evidence.
    """
    if max_turns <= 0 or token_budget <= 0 or not messages:
        return []
    tokenizer = tokenizer or Tokenizer()
    turns = _group_turns(messages)[-max_turns:]
    if not turns:
        return []

    per_turn_budget = max(128, token_budget // max_turns)
    selected_newest_first: list[dict[str, Any]] = []
    remaining = token_budget
    for turn in reversed(turns):
        if remaining < 64:
            break
        compact = _compact_turn(
            turn,
            tokenizer=tokenizer,
            token_budget=min(per_turn_budget, remaining),
        )
        token_count = tokenizer.count(json.dumps(compact, ensure_ascii=False))
        if token_count > remaining:
            continue
        selected_newest_first.append(compact)
        remaining -= token_count
    return list(reversed(selected_newest_first))


def build_fallback_conversation_summary(
    history: Sequence[dict[str, Any]],
    *,
    token_budget: int,
    tokenizer: Tokenizer | None = None,
) -> str:
    """Create an extractive summary when the model summary is unavailable."""
    if not history or token_budget <= 0:
        return ""
    tokenizer = tokenizer or Tokenizer()
    lines_newest_first: list[str] = []
    remaining = token_budget
    for turn in reversed(history):
        slide = (
            f" (slide {turn['slide_number']})"
            if turn.get("slide_number") is not None
            else ""
        )
        line = (
            f"Người học hỏi{slide}: {turn.get('user_question', '')}\n"
            f"Tutor đã trả lời: {turn.get('assistant_answer', '')}"
        ).strip()
        line = _truncate(line, remaining, tokenizer)
        count = tokenizer.count(line)
        if not line or count > remaining:
            continue
        lines_newest_first.append(line)
        remaining -= count
        if remaining < 32:
            break
    return "\n\n".join(reversed(lines_newest_first))


def build_fallback_rolling_summary(
    previous_summary: str,
    new_turn: dict[str, Any],
    *,
    token_budget: int,
    tokenizer: Tokenizer | None = None,
) -> str:
    """Merge old memory and the newest turn without exceeding the hard limit."""
    if token_budget <= 0:
        return ""
    tokenizer = tokenizer or Tokenizer()
    new_turn_budget = max(64, token_budget // 2)
    newest = _truncate(
        (
            f"Lượt mới — người học hỏi: {new_turn.get('user_question', '')}\n"
            f"Tutor trả lời: {new_turn.get('assistant_answer', '')}"
        ),
        new_turn_budget,
        tokenizer,
    )
    older_prefix = "\n\nTóm tắt trước: "
    remaining = max(
        0,
        token_budget - tokenizer.count(newest) - tokenizer.count(older_prefix),
    )
    older = _truncate(previous_summary, remaining, tokenizer)
    merged = newest
    if older:
        merged = f"{newest}{older_prefix}{older}"
    return _truncate(merged, token_budget, tokenizer)


def compact_rolling_summary_input(
    previous_summary: str,
    new_turn: dict[str, Any],
    *,
    token_budget: int,
    tokenizer: Tokenizer | None = None,
) -> tuple[str, dict[str, Any]]:
    """Bound the old-memory + new-turn input sent to the summary model."""
    if token_budget <= 0:
        return "", {}
    tokenizer = tokenizer or Tokenizer()
    previous = _truncate(
        previous_summary,
        min(1_000, max(64, token_budget // 3)),
        tokenizer,
    )
    fixed_turn = {
        "user_question": _truncate(
            new_turn.get("user_question"),
            min(1_000, max(64, token_budget // 4)),
            tokenizer,
        ),
        "selected_text": _truncate(
            new_turn.get("selected_text"),
            min(500, max(32, token_budget // 8)),
            tokenizer,
        ),
        "citation_slides": list(new_turn.get("citation_slides") or [])[:50],
    }
    base_tokens = tokenizer.count(
        json.dumps(
            {"previous_summary": previous, "new_turn": fixed_turn},
            ensure_ascii=False,
        )
    )
    answer_budget = max(32, token_budget - base_tokens - 16)
    fixed_turn["assistant_answer"] = _truncate(
        new_turn.get("assistant_answer"),
        answer_budget,
        tokenizer,
    )
    while (
        _rolling_input_token_count(previous, fixed_turn, tokenizer)
        > token_budget
        and answer_budget > 32
    ):
        answer_budget = max(32, answer_budget - 32)
        fixed_turn["assistant_answer"] = _truncate(
            new_turn.get("assistant_answer"),
            answer_budget,
            tokenizer,
        )
    if _rolling_input_token_count(previous, fixed_turn, tokenizer) > token_budget:
        fixed_turn["citation_slides"] = fixed_turn["citation_slides"][:10]
        fixed_turn["selected_text"] = ""
    for field_name in ("assistant_answer", "user_question"):
        while _rolling_input_token_count(previous, fixed_turn, tokenizer) > token_budget:
            current = str(fixed_turn.get(field_name) or "")
            current_tokens = tokenizer.count(current)
            if current_tokens <= 32:
                break
            excess = _rolling_input_token_count(previous, fixed_turn, tokenizer) - token_budget
            fixed_turn[field_name] = _truncate(
                current,
                max(32, current_tokens - excess - 4),
                tokenizer,
            )
    while _rolling_input_token_count(previous, fixed_turn, tokenizer) > token_budget:
        previous_tokens = tokenizer.count(previous)
        if previous_tokens <= 16:
            previous = ""
            break
        excess = _rolling_input_token_count(previous, fixed_turn, tokenizer) - token_budget
        previous = _truncate(previous, max(16, previous_tokens - excess - 4), tokenizer)
    return previous, fixed_turn


def _rolling_input_token_count(
    previous_summary: str,
    new_turn: dict[str, Any],
    tokenizer: Tokenizer,
) -> int:
    return tokenizer.count(
        json.dumps(
            {"previous_summary": previous_summary, "new_turn": new_turn},
            ensure_ascii=False,
        )
    )


def _group_turns(messages: Sequence[HistoryMessage]) -> list[dict[str, Any]]:
    turns: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for message in messages:
        if message.role == "user":
            current = {
                "user_question": message.content,
                "assistant_answer": "",
                "slide_number": message.slide_number,
                "slide_title": message.slide_title,
                "selected_text": message.selected_text,
            }
            turns.append(current)
        elif message.role == "assistant":
            if current is None or current["assistant_answer"]:
                continue
            current["assistant_answer"] = message.content
    return turns


def _compact_turn(
    turn: dict[str, Any],
    *,
    tokenizer: Tokenizer,
    token_budget: int,
) -> dict[str, Any]:
    question_budget = min(240, max(64, token_budget // 3))
    selection_budget = min(180, max(32, token_budget // 5))
    fixed = {
        "user_question": _truncate(turn.get("user_question"), question_budget, tokenizer),
        "slide_number": turn.get("slide_number"),
        "slide_title": _truncate(turn.get("slide_title"), 80, tokenizer),
    }
    selected_text = _truncate(turn.get("selected_text"), selection_budget, tokenizer)
    if selected_text:
        fixed["selected_text"] = selected_text
    fixed_tokens = tokenizer.count(json.dumps(fixed, ensure_ascii=False))
    answer_budget = max(32, token_budget - fixed_tokens - 16)
    assistant_answer = _truncate(
        turn.get("assistant_answer"),
        answer_budget,
        tokenizer,
    )
    if assistant_answer:
        fixed["assistant_answer"] = assistant_answer
    return fixed


def _truncate(value: object, max_tokens: int, tokenizer: Tokenizer) -> str:
    text = str(value or "").strip()
    if not text or max_tokens <= 0:
        return ""
    if tokenizer.count(text) <= max_tokens:
        return text
    marker = "…"
    content_budget = max_tokens - tokenizer.count(marker)
    if content_budget <= 0:
        return marker if tokenizer.count(marker) <= max_tokens else ""
    windows = tokenizer.windows(text, max_tokens=content_budget, overlap_tokens=0)
    return f"{windows[0].text.rstrip()}…" if windows else ""
