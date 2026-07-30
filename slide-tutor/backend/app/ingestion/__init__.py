"""Public ingestion boundary for parsers, normalization, and chunking."""

from .chunker import ChunkingConfig, build_embedding_text, chunk_deck
from .errors import (
    DocumentParseError,
    EncryptedDocumentError,
    IngestionError,
    InvalidDeckVersionIdError,
    InvalidDocumentStructureError,
    ParserDependencyError,
    TextlessDocumentError,
    UnsupportedFileTypeError,
)
from .models import (
    BlockKind,
    ChunkData,
    ChunkMetadata,
    ChunkType,
    NormalizedBlock,
    NormalizedDeck,
    NormalizedSlide,
    ParsedBlock,
    ParsedDeck,
    ParsedSlide,
    SourceFormat,
)
from .normalizer import normalize_deck, normalize_text
from .parsers import parse_document, parse_pdf, parse_pptx
from .tokenizer import Tokenizer, TokenWindow

__all__ = [
    "BlockKind",
    "ChunkData",
    "ChunkMetadata",
    "ChunkType",
    "ChunkingConfig",
    "DocumentParseError",
    "EncryptedDocumentError",
    "IngestionError",
    "InvalidDeckVersionIdError",
    "InvalidDocumentStructureError",
    "NormalizedBlock",
    "NormalizedDeck",
    "NormalizedSlide",
    "ParsedBlock",
    "ParsedDeck",
    "ParsedSlide",
    "ParserDependencyError",
    "SourceFormat",
    "TextlessDocumentError",
    "TokenWindow",
    "Tokenizer",
    "UnsupportedFileTypeError",
    "build_embedding_text",
    "chunk_deck",
    "normalize_deck",
    "normalize_text",
    "parse_document",
    "parse_pdf",
    "parse_pptx",
]
