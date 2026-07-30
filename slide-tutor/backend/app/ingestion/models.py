"""Internal, persistence-agnostic models for parsing and chunking."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from uuid import UUID


class SourceFormat(StrEnum):
    PPTX = "pptx"
    PDF = "pdf"


class BlockKind(StrEnum):
    PARAGRAPH = "paragraph"
    BULLET_GROUP = "bullet_group"
    TABLE_ROW_GROUP = "table_row_group"


class ChunkType(StrEnum):
    SLIDE = "slide"
    BLOCK = "block"


@dataclass(frozen=True, slots=True)
class ParsedBlock:
    kind: BlockKind
    text: str
    reading_order: int


@dataclass(frozen=True, slots=True)
class ParsedSlide:
    number: int
    title: str = ""
    section: str = ""
    blocks: tuple[ParsedBlock, ...] = field(default_factory=tuple)


@dataclass(frozen=True, slots=True)
class ParsedDeck:
    title: str
    source_format: SourceFormat
    slides: tuple[ParsedSlide, ...]


@dataclass(frozen=True, slots=True)
class NormalizedBlock:
    id: UUID
    kind: BlockKind
    text: str
    reading_order: int


@dataclass(frozen=True, slots=True)
class NormalizedSlide:
    id: UUID
    number: int
    title: str
    section: str
    blocks: tuple[NormalizedBlock, ...]

    @property
    def text(self) -> str:
        """Canonical slide text, with its title included exactly once."""

        parts: list[str] = []
        if self.title:
            parts.append(self.title)
        parts.extend(block.text for block in self.blocks if block.text)
        return "\n\n".join(parts)


@dataclass(frozen=True, slots=True)
class NormalizedDeck:
    deck_version_id: UUID
    title: str
    source_format: SourceFormat
    slides: tuple[NormalizedSlide, ...]


@dataclass(frozen=True, slots=True)
class ChunkMetadata:
    """Location data needed to hydrate and order a retrieved chunk."""

    block_ids: tuple[UUID, ...] = field(default_factory=tuple)
    reading_order_start: int | None = None
    reading_order_end: int | None = None
    split_part_index: int | None = None
    split_part_count: int | None = None

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-safe representation for ``Chunk.metadata_json``."""

        return {
            "block_ids": [str(block_id) for block_id in self.block_ids],
            "reading_order_start": self.reading_order_start,
            "reading_order_end": self.reading_order_end,
            "split_part_index": self.split_part_index,
            "split_part_count": self.split_part_count,
        }


@dataclass(frozen=True, slots=True)
class ChunkData:
    """Complete chunk record expected by persistence and vector workers."""

    id: UUID
    deck_version_id: UUID
    slide_id: UUID
    slide_number: int
    ordinal: int
    chunk_type: ChunkType
    text: str
    embedding_text: str
    token_count: int
    content_hash: str
    section: str
    metadata: ChunkMetadata

    @property
    def metadata_json(self) -> dict[str, object]:
        """JSON value ready to assign to the persistence model."""

        return self.metadata.to_dict()
