from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class AppError(Exception):
    code: str
    message: str
    status_code: int = 400
    details: dict[str, Any] | None = None

    def __str__(self) -> str:
        return self.message


class NotFoundError(AppError):
    def __init__(self, message: str = "Resource not found") -> None:
        super().__init__("not_found", message, 404)


class PermissionDeniedError(AppError):
    def __init__(self, message: str = "You do not have access to this resource") -> None:
        super().__init__("permission_denied", message, 403)


class DeckNotReadyError(AppError):
    def __init__(self) -> None:
        super().__init__("deck_not_ready", "The deck does not have a ready active version", 409)


class StaleSlideContextError(AppError):
    def __init__(self) -> None:
        super().__init__(
            "stale_slide_context",
            "The selected slide does not belong to the active deck version",
            409,
        )


class VectorIndexUnavailableError(AppError):
    def __init__(self, message: str = "The vector index is unavailable") -> None:
        super().__init__("vector_index_unavailable", message, 503)


class VectorIndexInconsistentError(AppError):
    def __init__(
        self,
        message: str = "The vector index is inconsistent with canonical data",
    ) -> None:
        super().__init__("vector_index_inconsistent", message, 503)


class EmbeddingProviderUnavailableError(AppError):
    def __init__(self, message: str = "The embedding provider is unavailable") -> None:
        super().__init__("embedding_provider_unavailable", message, 503)


class GenerationProviderUnavailableError(AppError):
    def __init__(self, message: str = "The answer provider is unavailable") -> None:
        super().__init__("generation_provider_unavailable", message, 503)


class InvalidUploadError(AppError):
    def __init__(self, message: str, *, code: str = "invalid_upload") -> None:
        super().__init__(code, message, 400)
