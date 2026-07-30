"""Deterministic slide/block chunking for dense and sparse retrieval."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from uuid import UUID, uuid5

from .models import (
    ChunkData,
    ChunkMetadata,
    ChunkType,
    NormalizedBlock,
    NormalizedDeck,
    NormalizedSlide,
)
from .tokenizer import Tokenizer


@dataclass(frozen=True, slots=True)
class ChunkingConfig:
    slide_max_tokens: int = 800
    block_target_tokens: int = 300
    block_max_tokens: int = 500
    block_min_tokens: int = 40
    long_block_overlap_tokens: int = 50

    def __post_init__(self) -> None:
        if self.slide_max_tokens < 1:
            raise ValueError("slide_max_tokens must be positive")
        if not 0 < self.block_min_tokens <= self.block_target_tokens:
            raise ValueError("block_min_tokens must be <= block_target_tokens")
        if not self.block_target_tokens <= self.block_max_tokens:
            raise ValueError("block_target_tokens must be <= block_max_tokens")
        if not 0 <= self.long_block_overlap_tokens < self.block_max_tokens:
            raise ValueError("long_block_overlap_tokens must be below block_max_tokens")


@dataclass(frozen=True, slots=True)
class _BlockChunk:
    text: str
    block_ids: tuple[UUID, ...]
    reading_order_start: int
    reading_order_end: int
    split_part_index: int | None = None
    split_part_count: int | None = None


def chunk_deck(
    deck: NormalizedDeck,
    *,
    tokenizer: Tokenizer | None = None,
    config: ChunkingConfig | None = None,
) -> tuple[ChunkData, ...]:
    """Build deterministic chunks ordered globally by slide and granularity."""

    tokenizer = tokenizer or Tokenizer()
    config = config or ChunkingConfig()
    chunks: list[ChunkData] = []

    for slide in deck.slides:
        slide_ordinal = 0
        slide_text = slide.text
        slide_token_count = tokenizer.count(slide_text)
        has_slide_chunk = bool(slide_text and slide_token_count <= config.slide_max_tokens)

        if has_slide_chunk:
            chunks.append(
                _make_chunk(
                    deck=deck,
                    slide=slide,
                    ordinal=slide_ordinal,
                    chunk_type=ChunkType.SLIDE,
                    text=slide_text,
                    tokenizer=tokenizer,
                    metadata=_slide_metadata(slide),
                )
            )
            slide_ordinal += 1

        for block_chunk in _make_block_chunks(slide, tokenizer, config):
            token_count = tokenizer.count(block_chunk.text)
            # Very small block chunks add no retrieval value when the complete
            # slide is already indexed.  Never drop them from a long slide,
            # where no slide-level fallback exists.
            if token_count < config.block_min_tokens and has_slide_chunk:
                continue
            chunks.append(
                _make_chunk(
                    deck=deck,
                    slide=slide,
                    ordinal=slide_ordinal,
                    chunk_type=ChunkType.BLOCK,
                    text=block_chunk.text,
                    tokenizer=tokenizer,
                    metadata=ChunkMetadata(
                        block_ids=block_chunk.block_ids,
                        reading_order_start=block_chunk.reading_order_start,
                        reading_order_end=block_chunk.reading_order_end,
                        split_part_index=block_chunk.split_part_index,
                        split_part_count=block_chunk.split_part_count,
                    ),
                )
            )
            slide_ordinal += 1

    return tuple(chunks)


def build_embedding_text(
    *,
    deck_title: str,
    section: str,
    slide_number: int,
    slide_title: str,
    text: str,
) -> str:
    """Add stable retrieval context without mutating canonical chunk text."""

    context = [f"Deck: {deck_title}"]
    if section:
        context.append(f"Section: {section}")
    slide_label = f"Slide {slide_number}"
    if slide_title:
        slide_label = f"{slide_label}: {slide_title}"
    context.append(slide_label)
    context.append(text)
    return "\n".join(context)


def _make_chunk(
    *,
    deck: NormalizedDeck,
    slide: NormalizedSlide,
    ordinal: int,
    chunk_type: ChunkType,
    text: str,
    tokenizer: Tokenizer,
    metadata: ChunkMetadata,
) -> ChunkData:
    embedding_text = build_embedding_text(
        deck_title=deck.title,
        section=slide.section,
        slide_number=slide.number,
        slide_title=slide.title,
        text=text,
    )
    content_hash = hashlib.sha256(embedding_text.encode("utf-8")).hexdigest()
    location = (
        f"{metadata.reading_order_start}:{metadata.reading_order_end}:"
        f"{metadata.split_part_index}:{metadata.split_part_count}"
    )
    chunk_id = uuid5(
        slide.id,
        f"chunk:{chunk_type.value}:{location}:{content_hash}",
    )
    return ChunkData(
        id=chunk_id,
        deck_version_id=deck.deck_version_id,
        slide_id=slide.id,
        slide_number=slide.number,
        ordinal=ordinal,
        chunk_type=chunk_type,
        text=text,
        embedding_text=embedding_text,
        token_count=tokenizer.count(text),
        content_hash=content_hash,
        section=slide.section,
        metadata=metadata,
    )


def _slide_metadata(slide: NormalizedSlide) -> ChunkMetadata:
    if not slide.blocks:
        return ChunkMetadata()
    return ChunkMetadata(
        block_ids=tuple(block.id for block in slide.blocks),
        reading_order_start=slide.blocks[0].reading_order,
        reading_order_end=slide.blocks[-1].reading_order,
    )


def _make_block_chunks(
    slide: NormalizedSlide,
    tokenizer: Tokenizer,
    config: ChunkingConfig,
) -> tuple[_BlockChunk, ...]:
    results: list[_BlockChunk] = []
    regular_run: list[NormalizedBlock] = []

    def flush_regular_run() -> None:
        if regular_run:
            results.extend(_pack_regular_blocks(tuple(regular_run), tokenizer, config))
            regular_run.clear()

    for block in slide.blocks:
        if tokenizer.count(block.text) <= config.block_max_tokens:
            regular_run.append(block)
            continue

        flush_regular_run()
        windows = tokenizer.windows(
            block.text,
            max_tokens=config.block_max_tokens,
            overlap_tokens=config.long_block_overlap_tokens,
        )
        part_count = len(windows)
        for part_index, window in enumerate(windows):
            results.append(
                _BlockChunk(
                    text=window.text,
                    block_ids=(block.id,),
                    reading_order_start=block.reading_order,
                    reading_order_end=block.reading_order,
                    split_part_index=part_index,
                    split_part_count=part_count,
                )
            )

    flush_regular_run()
    return tuple(results)


def _pack_regular_blocks(
    blocks: tuple[NormalizedBlock, ...],
    tokenizer: Tokenizer,
    config: ChunkingConfig,
) -> tuple[_BlockChunk, ...]:
    groups: list[list[NormalizedBlock]] = []
    current: list[NormalizedBlock] = []

    for index, block in enumerate(blocks):
        proposed = [*current, block]
        proposed_count = tokenizer.count(_join_blocks(proposed))
        if current and proposed_count > config.block_max_tokens:
            groups.append(current)
            current = [block]
        else:
            current = proposed

        if tokenizer.count(_join_blocks(current)) >= config.block_target_tokens:
            remaining = blocks[index + 1 :]
            remaining_count = tokenizer.count(_join_blocks(list(remaining)))
            if not remaining or remaining_count >= config.block_min_tokens:
                groups.append(current)
                current = []

    if current:
        if (
            groups
            and tokenizer.count(_join_blocks(current)) < config.block_min_tokens
            and tokenizer.count(_join_blocks([*groups[-1], *current])) <= config.block_max_tokens
        ):
            groups[-1].extend(current)
        else:
            groups.append(current)

    return tuple(
        _BlockChunk(
            text=_join_blocks(group),
            block_ids=tuple(block.id for block in group),
            reading_order_start=group[0].reading_order,
            reading_order_end=group[-1].reading_order,
        )
        for group in groups
        if group
    )


def _join_blocks(blocks: list[NormalizedBlock]) -> str:
    return "\n\n".join(block.text for block in blocks)
