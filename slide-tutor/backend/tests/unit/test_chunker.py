import hashlib
from uuid import UUID

from app.ingestion import (
    BlockKind,
    ChunkType,
    ParsedBlock,
    ParsedDeck,
    ParsedSlide,
    SourceFormat,
    Tokenizer,
    chunk_deck,
    normalize_deck,
)

VERSION_ID = UUID("41ab7ae9-f03e-49f4-b0d3-fee34aab74fb")
FALLBACK_TOKENIZER = Tokenizer(force_fallback=True)


def _normalized_deck(*slides: ParsedSlide):
    return normalize_deck(
        ParsedDeck(
            title="Khóa học AI",
            source_format=SourceFormat.PPTX,
            slides=slides,
        ),
        VERSION_ID,
    )


def _words(prefix: str, count: int) -> str:
    return " ".join(f"{prefix}{index}" for index in range(count))


def test_small_slide_has_slide_and_block_chunks_with_worker_metadata() -> None:
    deck = _normalized_deck(
        ParsedSlide(
            number=1,
            title="Vector database",
            section="RAG",
            blocks=(
                ParsedBlock(BlockKind.PARAGRAPH, _words("a", 45), 0),
                ParsedBlock(BlockKind.BULLET_GROUP, _words("b", 45), 1),
            ),
        )
    )

    chunks = chunk_deck(deck, tokenizer=FALLBACK_TOKENIZER)

    assert [chunk.chunk_type for chunk in chunks] == [
        ChunkType.SLIDE,
        ChunkType.BLOCK,
    ]
    assert [chunk.ordinal for chunk in chunks] == [0, 1]
    assert chunks[0].metadata.block_ids == tuple(block.id for block in deck.slides[0].blocks)
    assert chunks[1].metadata.reading_order_start == 0
    assert chunks[1].metadata.reading_order_end == 1
    assert chunks[1].metadata.block_ids == tuple(block.id for block in deck.slides[0].blocks)
    assert chunks[1].metadata_json == {
        "block_ids": [str(block.id) for block in deck.slides[0].blocks],
        "reading_order_start": 0,
        "reading_order_end": 1,
        "split_part_index": None,
        "split_part_count": None,
    }
    assert chunks[1].embedding_text.startswith(
        "Deck: Khóa học AI\nSection: RAG\nSlide 1: Vector database\n"
    )
    assert (
        chunks[1].content_hash
        == hashlib.sha256(chunks[1].embedding_text.encode("utf-8")).hexdigest()
    )


def test_chunk_ids_and_ordinals_are_deterministic() -> None:
    deck = _normalized_deck(
        ParsedSlide(
            number=1,
            title="Ổn định",
            blocks=(ParsedBlock(BlockKind.PARAGRAPH, _words("x", 80), 0),),
        ),
        ParsedSlide(
            number=2,
            title="Lặp lại",
            blocks=(ParsedBlock(BlockKind.PARAGRAPH, _words("y", 80), 0),),
        ),
    )

    first = chunk_deck(deck, tokenizer=FALLBACK_TOKENIZER)
    second = chunk_deck(deck, tokenizer=FALLBACK_TOKENIZER)

    assert first == second
    assert [chunk.ordinal for chunk in first if chunk.slide_number == 1] == [0, 1]
    assert [chunk.ordinal for chunk in first if chunk.slide_number == 2] == [0, 1]
    assert all(chunk.id.version == 5 for chunk in first)


def test_long_block_uses_500_token_windows_with_50_token_overlap() -> None:
    deck = _normalized_deck(
        ParsedSlide(
            number=1,
            title="Khối dài",
            blocks=(ParsedBlock(BlockKind.PARAGRAPH, _words("token", 1050), 0),),
        )
    )

    chunks = chunk_deck(deck, tokenizer=FALLBACK_TOKENIZER)
    block_chunks = [chunk for chunk in chunks if chunk.chunk_type is ChunkType.BLOCK]

    assert len(block_chunks) == 3
    assert [chunk.token_count for chunk in block_chunks] == [500, 500, 150]
    assert all(chunk.token_count <= 500 for chunk in block_chunks)
    assert [chunk.metadata.split_part_index for chunk in block_chunks] == [0, 1, 2]
    assert all(chunk.metadata.split_part_count == 3 for chunk in block_chunks)
    first_tokens = block_chunks[0].text.split()
    second_tokens = block_chunks[1].text.split()
    third_tokens = block_chunks[2].text.split()
    assert first_tokens[-50:] == second_tokens[:50]
    assert second_tokens[-50:] == third_tokens[:50]


def test_slide_over_800_tokens_has_no_slide_level_chunk() -> None:
    deck = _normalized_deck(
        ParsedSlide(
            number=1,
            title="Dài",
            blocks=(ParsedBlock(BlockKind.PARAGRAPH, _words("z", 801), 0),),
        )
    )

    chunks = chunk_deck(deck, tokenizer=FALLBACK_TOKENIZER)

    assert chunks
    assert all(chunk.chunk_type is ChunkType.BLOCK for chunk in chunks)


def test_short_blocks_are_grouped_to_reach_minimum_without_crossing_slides() -> None:
    deck = _normalized_deck(
        ParsedSlide(
            number=1,
            title="Slide A",
            blocks=(
                ParsedBlock(BlockKind.PARAGRAPH, _words("a", 25), 0),
                ParsedBlock(BlockKind.PARAGRAPH, _words("b", 25), 1),
            ),
        ),
        ParsedSlide(
            number=2,
            title="Slide B",
            blocks=(
                ParsedBlock(BlockKind.PARAGRAPH, _words("c", 25), 0),
                ParsedBlock(BlockKind.PARAGRAPH, _words("d", 25), 1),
            ),
        ),
    )

    chunks = chunk_deck(deck, tokenizer=FALLBACK_TOKENIZER)
    block_chunks = [chunk for chunk in chunks if chunk.chunk_type is ChunkType.BLOCK]

    assert len(block_chunks) == 2
    assert {chunk.slide_number for chunk in block_chunks} == {1, 2}
    assert all(chunk.token_count == 50 for chunk in block_chunks)
    assert "c0" not in block_chunks[0].text
    assert "a0" not in block_chunks[1].text
