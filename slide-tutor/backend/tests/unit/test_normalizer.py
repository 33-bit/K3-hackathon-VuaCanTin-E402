from uuid import UUID

import pytest

from app.ingestion import (
    BlockKind,
    InvalidDeckVersionIdError,
    InvalidDocumentStructureError,
    ParsedBlock,
    ParsedDeck,
    ParsedSlide,
    SourceFormat,
    TextlessDocumentError,
    normalize_deck,
    normalize_text,
)

VERSION_ID = UUID("d5cf9739-42fc-4c32-9de9-659206f598ee")


def test_normalize_text_preserves_vietnamese_and_line_structure() -> None:
    value = "  ＡI\u00a0và\u00a0Tiếng Việt \r\n\r\n\r\n  dòng\t hai  "

    assert normalize_text(value) == "AI và Tiếng Việt\n\ndòng hai"


def test_normalize_deck_assigns_stable_ids_and_reading_order() -> None:
    parsed = ParsedDeck(
        title="  Demo  ",
        source_format=SourceFormat.PPTX,
        slides=(
            ParsedSlide(
                number=1,
                title=" Tổng quan ",
                section=" Phần 1 ",
                blocks=(
                    ParsedBlock(BlockKind.PARAGRAPH, "khối sau", 20),
                    ParsedBlock(BlockKind.BULLET_GROUP, " - mục đầu ", 10),
                ),
            ),
        ),
    )

    first = normalize_deck(parsed, VERSION_ID)
    second = normalize_deck(parsed, str(VERSION_ID))

    assert first == second
    assert first.title == "Demo"
    assert first.slides[0].title == "Tổng quan"
    assert [block.reading_order for block in first.slides[0].blocks] == [0, 1]
    assert [block.text for block in first.slides[0].blocks] == [
        "- mục đầu",
        "khối sau",
    ]
    assert first.slides[0].id.version == 5
    assert all(block.id.version == 5 for block in first.slides[0].blocks)


def test_normalize_deck_rejects_duplicate_slide_numbers() -> None:
    parsed = ParsedDeck(
        title="Demo",
        source_format=SourceFormat.PDF,
        slides=(
            ParsedSlide(number=1, title="Một"),
            ParsedSlide(number=1, title="Hai"),
        ),
    )

    with pytest.raises(InvalidDocumentStructureError):
        normalize_deck(parsed, VERSION_ID)


def test_normalize_deck_rejects_textless_document() -> None:
    parsed = ParsedDeck(
        title="Demo",
        source_format=SourceFormat.PDF,
        slides=(ParsedSlide(number=1, title=" \n ", blocks=()),),
    )

    with pytest.raises(TextlessDocumentError) as exc_info:
        normalize_deck(parsed, VERSION_ID)

    assert exc_info.value.code == "unsupported_textless_document"


def test_normalize_deck_rejects_invalid_version_id() -> None:
    parsed = ParsedDeck(
        title="Demo",
        source_format=SourceFormat.PDF,
        slides=(ParsedSlide(number=1, title="Có chữ"),),
    )

    with pytest.raises(InvalidDeckVersionIdError):
        normalize_deck(parsed, "not-a-uuid")
