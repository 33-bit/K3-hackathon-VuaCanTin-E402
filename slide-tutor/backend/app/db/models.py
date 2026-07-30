from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class Course(TimestampMixin, Base):
    __tablename__ = "courses"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    owner_id: Mapped[UUID] = mapped_column(Uuid, nullable=False, index=True)


class CourseMembership(Base):
    __tablename__ = "course_memberships"

    course_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("courses.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    role: Mapped[str] = mapped_column(String(32), nullable=False, default="student")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        CheckConstraint(
            "role IN ('owner', 'teacher', 'student')",
            name="valid_role",
        ),
        Index("ix_course_memberships_user_course", "user_id", "course_id"),
    )


class Deck(TimestampMixin, Base):
    __tablename__ = "decks"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    course_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("courses.id", ondelete="CASCADE"), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    active_version_id: Mapped[UUID | None] = mapped_column(
        Uuid,
        ForeignKey(
            "deck_versions.id",
            name="fk_decks_active_version",
            use_alter=True,
            ondelete="SET NULL",
        ),
        nullable=True,
    )


class DeckVersion(Base):
    __tablename__ = "deck_versions"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    deck_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("decks.id", ondelete="CASCADE"), nullable=False, index=True
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    source_file_path: Mapped[str] = mapped_column(Text, nullable=False)
    source_type: Mapped[str] = mapped_column(String(16), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)

    status: Mapped[str] = mapped_column(String(40), nullable=False, default="uploaded")
    stage: Mapped[str] = mapped_column(String(40), nullable=False, default="queued")
    parser_version: Mapped[str] = mapped_column(String(64), nullable=False, default="parser_v1")
    chunking_version: Mapped[str] = mapped_column(String(64), nullable=False, default="chunking_v1")
    embedding_model: Mapped[str] = mapped_column(
        String(128), nullable=False, default="text-embedding-3-large"
    )
    embedding_dimensions: Mapped[int] = mapped_column(Integer, nullable=False, default=1536)
    embedding_version: Mapped[str] = mapped_column(
        String(64), nullable=False, default="te3large_1536_v1"
    )
    retrieval_schema_version: Mapped[str] = mapped_column(
        String(64), nullable=False, default="qdrant_bm25_rrf_v1"
    )

    slide_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    textless_slide_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    expected_chunk_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    indexed_chunk_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    index_manifest_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    index_status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")

    error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    error_detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    ready_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        UniqueConstraint("deck_id", "version_number"),
        CheckConstraint("embedding_dimensions = 1536", name="embedding_dimensions_1536"),
        CheckConstraint(
            "status IN "
            "('uploaded','parsing','chunking','indexing','ready','failed',"
            "'unsupported_textless_pdf')",
            name="valid_status",
        ),
        CheckConstraint(
            "index_status IN ('pending','indexing','in_sync','failed','drifted')",
            name="valid_index_status",
        ),
    )


class Slide(Base):
    __tablename__ = "slides"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    deck_version_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("deck_versions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    slide_number: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str | None] = mapped_column(String(500), nullable=True)
    section: Mapped[str | None] = mapped_column(String(500), nullable=True)
    raw_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    normalized_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    previous_slide_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    next_slide_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("deck_version_id", "slide_number"),
        Index("ix_slides_version_number", "deck_version_id", "slide_number"),
    )


class SlideBlock(Base):
    __tablename__ = "slide_blocks"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    slide_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("slides.id", ondelete="CASCADE"), nullable=False, index=True
    )
    block_type: Mapped[str] = mapped_column(String(40), nullable=False)
    reading_order: Mapped[int] = mapped_column(Integer, nullable=False)
    bullet_level: Mapped[int | None] = mapped_column(Integer, nullable=True)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)

    __table_args__ = (UniqueConstraint("slide_id", "reading_order"),)


class Chunk(Base):
    __tablename__ = "chunks"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    deck_version_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("deck_versions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    slide_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("slides.id", ondelete="CASCADE"), nullable=False, index=True
    )
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    chunk_type: Mapped[str] = mapped_column(String(32), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    embedding_text: Mapped[str] = mapped_column(Text, nullable=False)
    token_count: Mapped[int] = mapped_column(Integer, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("deck_version_id", "slide_id", "ordinal"),
        Index("ix_chunks_version_slide", "deck_version_id", "slide_id"),
    )


class IngestionJob(Base):
    __tablename__ = "ingestion_jobs"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    deck_version_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("deck_versions.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    stage: Mapped[str] = mapped_column(String(40), nullable=False, default="queued")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    available_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    worker_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('pending','processing','completed','failed')",
            name="valid_status",
        ),
    )


class VectorOutbox(Base):
    __tablename__ = "vector_outbox"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    deck_version_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("deck_versions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    event_type: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    available_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    worker_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        CheckConstraint(
            "event_type IN ('INDEX_DECK_VERSION','DELETE_DECK_VERSION','REBUILD_COLLECTION')",
            name="valid_event_type",
        ),
        CheckConstraint(
            "status IN ('pending','processing','completed','failed')",
            name="valid_status",
        ),
        Index("ix_vector_outbox_claim", "status", "available_at"),
    )


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(Uuid, nullable=False, index=True)
    course_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("courses.id", ondelete="CASCADE"), nullable=False
    )
    deck_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("decks.id", ondelete="CASCADE"), nullable=False
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    conversation_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    current_slide_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    selected_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    retrieved_chunk_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    citations_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (CheckConstraint("role IN ('user','assistant','system')", name="valid_role"),)


class RetrievalRun(Base):
    __tablename__ = "retrieval_runs"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    conversation_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("conversations.id", ondelete="SET NULL"), nullable=True
    )
    user_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    course_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    deck_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    deck_version_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    current_slide_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    original_query: Mapped[str] = mapped_column(Text, nullable=False)
    rewritten_query: Mapped[str] = mapped_column(Text, nullable=False)
    selected_text_match: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    filters_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    candidates_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False)
    final_chunk_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    timings_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    model_config_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    inconsistency_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class Feedback(Base):
    __tablename__ = "feedback"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    message_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("messages.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    rating: Mapped[str] = mapped_column(String(32), nullable=False)
    reason: Mapped[str | None] = mapped_column(String(80), nullable=True)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
