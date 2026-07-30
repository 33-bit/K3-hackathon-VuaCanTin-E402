from __future__ import annotations

import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from uuid import UUID

from app.db.models import SlideBlock


@dataclass(slots=True)
class SelectedTextMatch:
    block_id: UUID
    score: float
    exact: bool
    matched_text: str


def normalize_for_match(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip().casefold()


def match_selected_text(
    selected_text: str | None,
    blocks: list[SlideBlock],
    *,
    threshold: float = 0.72,
) -> SelectedTextMatch | None:
    if not selected_text or not selected_text.strip():
        return None
    needle = normalize_for_match(selected_text)
    if not needle:
        return None

    best: SelectedTextMatch | None = None
    for block in blocks:
        haystack = normalize_for_match(block.text)
        if not haystack:
            continue
        exact = needle in haystack or haystack in needle
        score = 1.0 if exact else SequenceMatcher(None, needle, haystack).ratio()
        if exact or score >= threshold:
            candidate = SelectedTextMatch(
                block_id=block.id,
                score=score,
                exact=exact,
                matched_text=block.text,
            )
            if best is None or candidate.score > best.score:
                best = candidate
    return best
