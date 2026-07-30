from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class ApiModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class ErrorBody(ApiModel):
    code: str
    message: str
    details: dict[str, Any] | None = None
    request_id: str | None = None


class ErrorResponse(ApiModel):
    error: ErrorBody


class DeckAcceptedResponse(ApiModel):
    deck_id: UUID
    deck_version_id: UUID
    status: Literal["uploaded"] = "uploaded"
    status_url: str


class DeckStatusResponse(ApiModel):
    deck_id: UUID
    deck_version_id: UUID
    active_version_id: UUID | None
    status: str
    stage: str
    slide_count: int
    textless_slide_count: int
    expected_chunk_count: int
    indexed_chunk_count: int
    index_status: str
    error_code: str | None = None
    error_detail: str | None = None
    created_at: datetime
    ready_at: datetime | None = None


class SlideBlockResponse(ApiModel):
    id: UUID
    block_type: str
    reading_order: int
    bullet_level: int | None
    text: str


class SlideResponse(ApiModel):
    id: UUID
    slide_number: int
    title: str | None
    section: str | None
    normalized_text: str
    blocks: list[SlideBlockResponse] = Field(default_factory=list)


class SlidesResponse(ApiModel):
    deck_id: UUID
    deck_version_id: UUID
    slides: list[SlideResponse]


class SlideRange(ApiModel):
    start: int = Field(ge=1)
    end: int = Field(ge=1)

    @model_validator(mode="after")
    def validate_order(self) -> SlideRange:
        if self.end < self.start:
            raise ValueError("end must be greater than or equal to start")
        return self


class ChatRequest(ApiModel):
    conversation_id: UUID | None = None
    course_id: UUID
    deck_id: UUID
    current_slide_id: UUID
    selected_text: str | None = Field(default=None, max_length=20_000)
    question: str = Field(min_length=1, max_length=8_000)
    language: str = Field(default="vi", min_length=2, max_length=16)
    references: list[SlideRange] = Field(default_factory=list, max_length=20)

    @field_validator("question")
    @classmethod
    def validate_question(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("question must not be blank")
        return value

    @field_validator("language")
    @classmethod
    def normalize_language(cls, value: str) -> str:
        value = value.strip().lower()
        if len(value) < 2:
            raise ValueError("language must contain at least two characters")
        return value

    @field_validator("selected_text")
    @classmethod
    def normalize_selected_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        return value or None


class Citation(ApiModel):
    slide_id: UUID
    slide_number: int
    title: str | None
    chunk_ids: list[UUID]


class ChatResponse(ApiModel):
    conversation_id: UUID
    message_id: UUID
    answer: str
    citations: list[Citation]
    confidence: Literal["high", "medium", "low"]
    insufficient_evidence: bool
    missing_content_types: list[str] = Field(default_factory=list)
    retrieval_debug_id: UUID


class FeedbackRequest(ApiModel):
    message_id: UUID
    rating: Literal["helpful", "incorrect", "incomplete"]
    reason: str | None = Field(default=None, max_length=80)
    comment: str | None = Field(default=None, max_length=4_000)


class FeedbackResponse(ApiModel):
    feedback_id: UUID


class RetrievalDebugResponse(ApiModel):
    retrieval_debug_id: UUID
    deck_id: UUID
    deck_version_id: UUID
    original_query: str
    rewritten_query: str
    selected_text_match: dict[str, Any] | None
    filters: dict[str, Any]
    candidates: list[dict[str, Any]]
    final_chunk_ids: list[str]
    timings_ms: dict[str, Any]
    model_versions: dict[str, Any]
    inconsistency: dict[str, Any] | None
    created_at: datetime


class HealthResponse(ApiModel):
    status: Literal["ok"] = "ok"


class DependencyStatus(ApiModel):
    status: Literal["ok", "error"]
    detail: str | None = None


class ReadinessResponse(ApiModel):
    status: Literal["ready", "not_ready"]
    dependencies: dict[str, DependencyStatus]
