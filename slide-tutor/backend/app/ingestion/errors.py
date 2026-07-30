"""Typed errors raised by the ingestion boundary.

The ingestion package deliberately does not depend on FastAPI.  API and worker
layers can map these stable error codes to HTTP responses or job states.
"""

from __future__ import annotations


class IngestionError(Exception):
    """Base class for expected, user-actionable ingestion failures."""

    code = "ingestion_error"

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class UnsupportedFileTypeError(IngestionError):
    code = "unsupported_file_type"


class ParserDependencyError(IngestionError):
    code = "parser_dependency_missing"


class DocumentParseError(IngestionError):
    code = "document_parse_error"


class EncryptedDocumentError(DocumentParseError):
    code = "encrypted_document"


class TextlessDocumentError(IngestionError):
    code = "unsupported_textless_document"


class InvalidDeckVersionIdError(IngestionError):
    code = "invalid_deck_version_id"


class InvalidDocumentStructureError(IngestionError):
    code = "invalid_document_structure"
