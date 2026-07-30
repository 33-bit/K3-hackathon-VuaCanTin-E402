"""Unicode, whitespace, ordering, and stable-ID normalization."""

from __future__ import annotations

import hashlib
import re
import unicodedata
from uuid import UUID, uuid5

from .errors import (
    InvalidDeckVersionIdError,
    InvalidDocumentStructureError,
    TextlessDocumentError,
)
from .models import (
    NormalizedBlock,
    NormalizedDeck,
    NormalizedSlide,
    ParsedDeck,
)

_HORIZONTAL_SPACE_RE = re.compile(r"[^\S\r\n]+")
_EXCESS_BLANK_LINES_RE = re.compile(r"\n{3,}")
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def normalize_text(value: str) -> str:
    """Normalize text without stripping Vietnamese diacritics or line shape."""

    text = unicodedata.normalize("NFKC", value or "")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = _CONTROL_RE.sub("", text)
    lines = [_HORIZONTAL_SPACE_RE.sub(" ", line).strip() for line in text.split("\n")]
    text = "\n".join(lines).strip()
    return _EXCESS_BLANK_LINES_RE.sub("\n\n", text)


def normalize_deck(parsed: ParsedDeck, deck_version_id: UUID | str) -> NormalizedDeck:
    """Normalize a parsed deck and assign deterministic slide/block UUIDs."""

    version_id = _coerce_uuid(deck_version_id)
    seen_slide_numbers: set[int] = set()
    normalized_slides: list[NormalizedSlide] = []
    has_text = False

    for parsed_slide in parsed.slides:
        if parsed_slide.number < 1 or parsed_slide.number in seen_slide_numbers:
            raise InvalidDocumentStructureError(
                f"Slide number must be unique and positive: {parsed_slide.number}"
            )
        seen_slide_numbers.add(parsed_slide.number)

        slide_id = uuid5(version_id, f"slide:{parsed_slide.number}")
        title = normalize_text(parsed_slide.title)
        section = normalize_text(parsed_slide.section)
        blocks: list[NormalizedBlock] = []

        ordered_blocks = sorted(
            enumerate(parsed_slide.blocks),
            key=lambda item: (item[1].reading_order, item[0]),
        )
        for reading_order, (_, parsed_block) in enumerate(ordered_blocks):
            text = normalize_text(parsed_block.text)
            if not text:
                continue
            digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
            block_id = uuid5(
                slide_id,
                f"block:{reading_order}:{parsed_block.kind.value}:{digest}",
            )
            blocks.append(
                NormalizedBlock(
                    id=block_id,
                    kind=parsed_block.kind,
                    text=text,
                    reading_order=reading_order,
                )
            )

        if title or blocks:
            has_text = True
        normalized_slides.append(
            NormalizedSlide(
                id=slide_id,
                number=parsed_slide.number,
                title=title,
                section=section,
                blocks=tuple(blocks),
            )
        )

    if not has_text:
        raise TextlessDocumentError(
            f"{parsed.source_format.value.upper()} contains no extractable text; "
            "OCR/vision ingestion is not enabled."
        )

    return NormalizedDeck(
        deck_version_id=version_id,
        title=normalize_text(parsed.title) or "Untitled deck",
        source_format=parsed.source_format,
        slides=tuple(normalized_slides),
    )


def _coerce_uuid(value: UUID | str) -> UUID:
    if isinstance(value, UUID):
        return value
    try:
        return UUID(str(value))
    except (TypeError, ValueError, AttributeError) as exc:
        raise InvalidDeckVersionIdError("deck_version_id must be a valid UUID.") from exc
