from __future__ import annotations

import hashlib
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import delete, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import NotFoundError, PermissionDeniedError

from .models import (
    Chunk,
    Conversation,
    Course,
    CourseMembership,
    Deck,
    DeckVersion,
    Feedback,
    IngestionJob,
    Message,
    RetrievalRun,
    Slide,
    SlideBlock,
    VectorOutbox,
)


@dataclass(slots=True)
class ActiveDeckContext:
    deck: Deck
    version: DeckVersion


@dataclass(frozen=True, slots=True)
class ConversationHistoryMessage:
    role: str
    content: str
    slide_number: int | None
    slide_title: str | None
    selected_text: str | None


INDEX_MIGRATION_LOCK_KEY = 5_565_132_050_821_205


async def acquire_index_migration_lock(session: AsyncSession) -> None:
    """Serialize vector activation with global collection alias migrations."""

    bind = session.get_bind()
    if bind.dialect.name == "postgresql":
        await session.execute(
            text("SELECT pg_advisory_xact_lock(:lock_key)"),
            {"lock_key": INDEX_MIGRATION_LOCK_KEY},
        )


def build_manifest_hash(items: Iterable[tuple[UUID | str, str]]) -> str:
    normalized = sorted(f"{item_id}:{content_hash}" for item_id, content_hash in items)
    return hashlib.sha256("\n".join(normalized).encode("utf-8")).hexdigest()


async def require_course_access(
    session: AsyncSession,
    *,
    course_id: UUID,
    user_id: UUID,
    write: bool = False,
) -> CourseMembership:
    membership = await session.scalar(
        select(CourseMembership).where(
            CourseMembership.course_id == course_id,
            CourseMembership.user_id == user_id,
        )
    )
    if membership is None:
        raise NotFoundError("Course not found")
    if write and membership.role not in {"owner", "teacher"}:
        raise PermissionDeniedError("Teacher access is required")
    return membership


async def require_deck_access(
    session: AsyncSession,
    *,
    deck_id: UUID,
    user_id: UUID,
    write: bool = False,
) -> Deck:
    row = (
        await session.execute(
            select(Deck, CourseMembership)
            .join(
                CourseMembership,
                (CourseMembership.course_id == Deck.course_id)
                & (CourseMembership.user_id == user_id),
            )
            .where(Deck.id == deck_id)
        )
    ).first()
    if row is None:
        raise NotFoundError("Deck not found")
    deck, membership = row
    if write and membership.role not in {"owner", "teacher"}:
        raise PermissionDeniedError("Teacher access is required")
    return deck


async def create_development_course(
    session: AsyncSession,
    *,
    user_id: UUID,
    course_id: UUID,
    name: str = "Development course",
) -> Course:
    course = await session.get(Course, course_id)
    if course is None:
        course = Course(id=course_id, name=name, owner_id=user_id)
        session.add(course)
        session.add(CourseMembership(course_id=course_id, user_id=user_id, role="owner"))
        await session.flush()
    return course


async def create_deck_version(
    session: AsyncSession,
    *,
    deck_id: UUID,
    deck_version_id: UUID,
    course_id: UUID,
    title: str,
    source_file_path: str,
    source_type: str,
    content_hash: str,
    settings: Settings,
    existing_deck: Deck | None = None,
) -> tuple[Deck, DeckVersion, IngestionJob]:
    deck = existing_deck
    if deck is None:
        deck = Deck(id=deck_id, course_id=course_id, title=title)
        session.add(deck)
        version_number = 1
    else:
        locked_deck = await session.get(Deck, deck.id, with_for_update=True)
        if locked_deck is None:
            raise NotFoundError("Deck not found")
        deck = locked_deck
        latest = await session.scalar(
            select(func.max(DeckVersion.version_number)).where(DeckVersion.deck_id == deck.id)
        )
        version_number = int(latest or 0) + 1

    version = DeckVersion(
        id=deck_version_id,
        deck_id=deck.id,
        version_number=version_number,
        source_file_path=source_file_path,
        source_type=source_type,
        content_hash=content_hash,
        embedding_model=settings.openai_embedding_model,
        embedding_dimensions=settings.openai_embedding_dimensions,
        embedding_version=settings.embedding_version,
        retrieval_schema_version=settings.retrieval_schema_version,
    )
    job = IngestionJob(deck_version_id=version.id)
    session.add_all([version, job])
    await session.flush()
    return deck, version, job


async def get_active_deck_context(
    session: AsyncSession,
    *,
    deck_id: UUID,
    user_id: UUID,
) -> ActiveDeckContext | None:
    deck = await require_deck_access(session, deck_id=deck_id, user_id=user_id)
    if deck.active_version_id is None:
        return None
    version = await session.get(DeckVersion, deck.active_version_id)
    if version is None or version.deck_id != deck.id or version.status != "ready":
        return None
    return ActiveDeckContext(deck=deck, version=version)


async def get_latest_deck_version(
    session: AsyncSession,
    *,
    deck_id: UUID,
) -> DeckVersion:
    version = await session.scalar(
        select(DeckVersion)
        .where(DeckVersion.deck_id == deck_id)
        .order_by(DeckVersion.version_number.desc())
        .limit(1)
    )
    if version is None:
        raise NotFoundError("Deck version not found")
    return version


async def get_slides_for_version(
    session: AsyncSession,
    *,
    deck_version_id: UUID,
) -> list[Slide]:
    return list(
        (
            await session.scalars(
                select(Slide)
                .where(Slide.deck_version_id == deck_version_id)
                .order_by(Slide.slide_number)
            )
        ).all()
    )


async def get_slide_blocks(
    session: AsyncSession,
    *,
    slide_id: UUID,
) -> list[SlideBlock]:
    return list(
        (
            await session.scalars(
                select(SlideBlock)
                .where(SlideBlock.slide_id == slide_id)
                .order_by(SlideBlock.reading_order)
            )
        ).all()
    )


async def get_chunks_for_version(
    session: AsyncSession,
    *,
    deck_version_id: UUID,
) -> list[Chunk]:
    return list(
        (
            await session.scalars(
                select(Chunk)
                .join(Slide, Slide.id == Chunk.slide_id)
                .where(Chunk.deck_version_id == deck_version_id)
                .order_by(Slide.slide_number, Chunk.ordinal)
            )
        ).all()
    )


async def get_chunks_for_slide(
    session: AsyncSession,
    *,
    deck_version_id: UUID,
    slide_id: UUID,
) -> list[Chunk]:
    return list(
        (
            await session.scalars(
                select(Chunk)
                .where(
                    Chunk.deck_version_id == deck_version_id,
                    Chunk.slide_id == slide_id,
                )
                .order_by(Chunk.ordinal)
            )
        ).all()
    )


async def get_chunks_in_slide_range(
    session: AsyncSession,
    *,
    deck_version_id: UUID,
    start: int,
    end: int,
) -> list[Chunk]:
    return list(
        (
            await session.scalars(
                select(Chunk)
                .join(Slide, Slide.id == Chunk.slide_id)
                .where(
                    Chunk.deck_version_id == deck_version_id,
                    Slide.slide_number.between(start, end),
                )
                .order_by(Slide.slide_number, Chunk.ordinal)
            )
        ).all()
    )


async def get_neighbor_chunks(
    session: AsyncSession,
    *,
    deck_version_id: UUID,
    slide_number: int,
) -> list[Chunk]:
    return list(
        (
            await session.scalars(
                select(Chunk)
                .join(Slide, Slide.id == Chunk.slide_id)
                .where(
                    Chunk.deck_version_id == deck_version_id,
                    Slide.slide_number.in_([slide_number - 1, slide_number + 1]),
                )
                .order_by(Slide.slide_number, Chunk.ordinal)
            )
        ).all()
    )


async def hydrate_chunks(
    session: AsyncSession,
    *,
    chunk_ids: Sequence[UUID],
) -> list[Chunk]:
    if not chunk_ids:
        return []
    chunks = list((await session.scalars(select(Chunk).where(Chunk.id.in_(chunk_ids)))).all())
    by_id = {chunk.id: chunk for chunk in chunks}
    return [by_id[chunk_id] for chunk_id in chunk_ids if chunk_id in by_id]


async def get_slide_map(
    session: AsyncSession,
    *,
    slide_ids: Iterable[UUID],
) -> dict[UUID, Slide]:
    unique_ids = set(slide_ids)
    if not unique_ids:
        return {}
    rows = (await session.scalars(select(Slide).where(Slide.id.in_(unique_ids)))).all()
    return {slide.id: slide for slide in rows}


async def replace_version_content(
    session: AsyncSession,
    *,
    version: DeckVersion,
    slides: Sequence[Slide],
    blocks: Sequence[SlideBlock],
    chunks: Sequence[Chunk],
    textless_slide_count: int,
) -> VectorOutbox:
    await session.execute(delete(Slide).where(Slide.deck_version_id == version.id))
    session.add_all(list(slides))
    await session.flush()
    session.add_all(list(blocks))
    session.add_all(list(chunks))

    version.status = "indexing"
    version.stage = "vector_indexing"
    version.slide_count = len(slides)
    version.textless_slide_count = textless_slide_count
    version.expected_chunk_count = len(chunks)
    version.indexed_chunk_count = 0
    version.index_status = "indexing"
    version.index_manifest_hash = build_manifest_hash(
        (chunk.id, chunk.content_hash) for chunk in chunks
    )
    event = await session.scalar(
        select(VectorOutbox)
        .where(
            VectorOutbox.deck_version_id == version.id,
            VectorOutbox.event_type == "INDEX_DECK_VERSION",
            VectorOutbox.status.in_(["pending", "processing"]),
        )
        .order_by(VectorOutbox.created_at.desc())
        .limit(1)
    )
    if event is None:
        event = VectorOutbox(
            deck_version_id=version.id,
            event_type="INDEX_DECK_VERSION",
        )
        session.add(event)
    await session.flush()
    return event


async def claim_ingestion_job(
    session: AsyncSession,
    *,
    worker_id: str,
) -> IngestionJob | None:
    now = datetime.now(UTC)
    job = await session.scalar(
        select(IngestionJob)
        .where(
            IngestionJob.status == "pending",
            IngestionJob.available_at <= now,
        )
        .order_by(IngestionJob.created_at)
        .with_for_update(skip_locked=True)
        .limit(1)
    )
    if job is None:
        return None
    job.status = "processing"
    job.attempts += 1
    job.locked_at = now
    job.worker_id = worker_id
    await session.flush()
    return job


async def claim_vector_event(
    session: AsyncSession,
    *,
    worker_id: str,
) -> VectorOutbox | None:
    now = datetime.now(UTC)
    event = await session.scalar(
        select(VectorOutbox)
        .where(
            VectorOutbox.status == "pending",
            VectorOutbox.available_at <= now,
        )
        .order_by(VectorOutbox.created_at)
        .with_for_update(skip_locked=True)
        .limit(1)
    )
    if event is None:
        return None
    event.status = "processing"
    event.attempts += 1
    event.locked_at = now
    event.worker_id = worker_id
    await session.flush()
    return event


def schedule_retry(
    item: IngestionJob | VectorOutbox,
    *,
    error: Exception,
    max_attempts: int,
) -> None:
    item.last_error = str(error)[:4000]
    item.locked_at = None
    item.worker_id = None
    if item.attempts >= max_attempts:
        item.status = "failed"
        return
    delay_seconds = min(30, 2 ** max(0, item.attempts - 1))
    item.status = "pending"
    item.available_at = datetime.now(UTC) + timedelta(seconds=delay_seconds)


async def recover_stale_work(
    session: AsyncSession,
    *,
    lock_timeout_seconds: int,
) -> tuple[int, int]:
    """Release jobs abandoned by a crashed worker after their processing lease expires."""

    stale_before = datetime.now(UTC) - timedelta(seconds=lock_timeout_seconds)
    ingestion_jobs = list(
        (
            await session.scalars(
                select(IngestionJob)
                .where(
                    IngestionJob.status == "processing",
                    IngestionJob.locked_at < stale_before,
                )
                .with_for_update(skip_locked=True)
            )
        ).all()
    )
    vector_events = list(
        (
            await session.scalars(
                select(VectorOutbox)
                .where(
                    VectorOutbox.status == "processing",
                    VectorOutbox.locked_at < stale_before,
                )
                .with_for_update(skip_locked=True)
            )
        ).all()
    )
    now = datetime.now(UTC)
    for item in [*ingestion_jobs, *vector_events]:
        item.status = "pending"
        item.available_at = now
        item.locked_at = None
        item.worker_id = None
        item.last_error = "Recovered an expired worker lease"
    await session.flush()
    return len(ingestion_jobs), len(vector_events)


async def mark_version_ready(
    session: AsyncSession,
    *,
    version: DeckVersion,
    indexed_chunk_count: int,
    old_vector_retention_seconds: int,
) -> VectorOutbox | None:
    await acquire_index_migration_lock(session)
    deck = await session.get(Deck, version.deck_id, with_for_update=True)
    if deck is None:
        raise NotFoundError("Deck not found during activation")
    previous_version_id = deck.active_version_id
    previous_version = (
        await session.get(DeckVersion, previous_version_id)
        if previous_version_id is not None
        else None
    )

    version.status = "ready"
    version.stage = "completed"
    version.index_status = "in_sync"
    version.indexed_chunk_count = indexed_chunk_count
    version.ready_at = datetime.now(UTC)
    version.error_code = None
    version.error_detail = None

    cleanup: VectorOutbox | None = None
    if previous_version_id == version.id:
        await session.flush()
        return None

    candidate_is_newest = (
        previous_version is None or version.version_number > previous_version.version_number
    )
    if candidate_is_newest:
        deck.active_version_id = version.id
        if previous_version_id is not None:
            cleanup = await _schedule_vector_cleanup(
                session,
                deck_version_id=previous_version_id,
                delay_seconds=old_vector_retention_seconds,
            )
    else:
        # A slower, older reindex must never replace or schedule deletion of
        # the newer version that already won activation.
        cleanup = await _schedule_vector_cleanup(
            session,
            deck_version_id=version.id,
            delay_seconds=old_vector_retention_seconds,
        )
    await session.flush()
    return cleanup


async def _schedule_vector_cleanup(
    session: AsyncSession,
    *,
    deck_version_id: UUID,
    delay_seconds: int,
) -> VectorOutbox:
    existing = await session.scalar(
        select(VectorOutbox)
        .where(
            VectorOutbox.deck_version_id == deck_version_id,
            VectorOutbox.event_type == "DELETE_DECK_VERSION",
            VectorOutbox.status.in_(["pending", "processing"]),
        )
        .order_by(VectorOutbox.created_at.desc())
        .limit(1)
    )
    if existing is not None:
        return existing
    cleanup = VectorOutbox(
        deck_version_id=deck_version_id,
        event_type="DELETE_DECK_VERSION",
        available_at=datetime.now(UTC) + timedelta(seconds=delay_seconds),
    )
    session.add(cleanup)
    await session.flush()
    return cleanup


async def mark_version_failed(
    session: AsyncSession,
    *,
    version: DeckVersion,
    code: str,
    detail: str,
    status: str = "failed",
) -> None:
    version.status = status
    version.stage = "failed"
    version.index_status = "failed"
    version.error_code = code
    version.error_detail = detail[:4000]
    await session.flush()


async def flag_index_drift(
    session: AsyncSession,
    *,
    version: DeckVersion,
    detail: str,
) -> None:
    version.index_status = "drifted"
    version.error_code = "vector_index_inconsistent"
    version.error_detail = detail[:4000]
    pending = await session.scalar(
        select(VectorOutbox.id).where(
            VectorOutbox.deck_version_id == version.id,
            VectorOutbox.event_type == "INDEX_DECK_VERSION",
            VectorOutbox.status.in_(["pending", "processing"]),
        )
    )
    if pending is None:
        session.add(
            VectorOutbox(
                deck_version_id=version.id,
                event_type="INDEX_DECK_VERSION",
            )
        )
    await session.flush()


async def create_conversation_if_needed(
    session: AsyncSession,
    *,
    conversation_id: UUID | None,
    user_id: UUID,
    course_id: UUID,
    deck_id: UUID,
) -> Conversation:
    if conversation_id is not None:
        conversation = await session.get(Conversation, conversation_id)
        if (
            conversation is None
            or conversation.user_id != user_id
            or conversation.course_id != course_id
            or conversation.deck_id != deck_id
        ):
            raise NotFoundError("Conversation not found")
        return conversation
    conversation = Conversation(
        user_id=user_id,
        course_id=course_id,
        deck_id=deck_id,
    )
    session.add(conversation)
    await session.flush()
    return conversation


async def get_recent_conversation_messages(
    session: AsyncSession,
    *,
    conversation_id: UUID,
    max_messages: int,
) -> list[ConversationHistoryMessage]:
    """Return recent user/assistant messages in chronological order.

    Conversation ownership and deck/course isolation must be checked with
    ``create_conversation_if_needed`` before this function is called.
    """
    if max_messages <= 0:
        return []
    rows = (
        await session.execute(
            select(Message, Slide.slide_number, Slide.title)
            .outerjoin(Slide, Slide.id == Message.current_slide_id)
            .where(
                Message.conversation_id == conversation_id,
                Message.role.in_(("user", "assistant")),
            )
            .order_by(Message.created_at.desc(), Message.role.asc())
            .limit(max_messages)
        )
    ).all()
    return [
        ConversationHistoryMessage(
            role=message.role,
            content=message.content,
            slide_number=slide_number,
            slide_title=slide_title,
            selected_text=message.selected_text,
        )
        for message, slide_number, slide_title in reversed(rows)
    ]


async def persist_chat_turn(
    session: AsyncSession,
    *,
    conversation: Conversation,
    question: str,
    answer: str,
    current_slide_id: UUID,
    selected_text: str | None,
    retrieved_chunk_ids: Sequence[UUID],
    citations: list[dict[str, Any]],
) -> tuple[Message, Message]:
    user_message = Message(
        conversation_id=conversation.id,
        role="user",
        content=question,
        current_slide_id=current_slide_id,
        selected_text=selected_text,
    )
    assistant_message = Message(
        conversation_id=conversation.id,
        role="assistant",
        content=answer,
        current_slide_id=current_slide_id,
        retrieved_chunk_ids=[str(item) for item in retrieved_chunk_ids],
        citations_json=citations,
    )
    session.add_all([user_message, assistant_message])
    await session.flush()
    return user_message, assistant_message


def set_conversation_summary(
    conversation: Conversation,
    *,
    summary_text: str,
    summarized_turn_count: int,
) -> None:
    conversation.summary_text = summary_text
    conversation.summary_turn_count = summarized_turn_count
    conversation.summary_updated_at = datetime.now(UTC)


async def create_retrieval_run(
    session: AsyncSession,
    **values: Any,
) -> RetrievalRun:
    run = RetrievalRun(**values)
    session.add(run)
    await session.flush()
    return run


async def create_feedback(
    session: AsyncSession,
    *,
    message_id: UUID,
    user_id: UUID,
    rating: str,
    reason: str | None,
    comment: str | None,
) -> Feedback:
    message = await session.get(Message, message_id)
    if message is None:
        raise NotFoundError("Message not found")
    conversation = await session.get(Conversation, message.conversation_id)
    if conversation is None or conversation.user_id != user_id:
        raise NotFoundError("Message not found")
    feedback = Feedback(
        message_id=message_id,
        user_id=user_id,
        rating=rating,
        reason=reason,
        comment=comment,
    )
    session.add(feedback)
    await session.flush()
    return feedback
