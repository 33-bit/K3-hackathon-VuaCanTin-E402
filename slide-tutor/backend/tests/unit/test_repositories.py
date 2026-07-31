from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.errors import NotFoundError
from app.db import repositories
from app.db.base import Base
from app.db.models import (
    Conversation,
    Course,
    Deck,
    DeckVersion,
    IngestionJob,
    Message,
    Slide,
    VectorOutbox,
)


def _version(*, deck_id, number: int) -> DeckVersion:  # type: ignore[no-untyped-def]
    return DeckVersion(
        id=uuid4(),
        deck_id=deck_id,
        version_number=number,
        source_file_path=f"/tmp/v{number}.pdf",
        source_type="pdf",
        content_hash=f"{number:064d}",
        status="ready",
        stage="completed",
        index_status="in_sync",
        expected_chunk_count=1,
        indexed_chunk_count=1,
    )


@pytest.mark.asyncio
async def test_older_index_completion_cannot_replace_newer_active_version() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with factory() as session:
            course = Course(id=uuid4(), name="Course", owner_id=uuid4())
            deck = Deck(id=uuid4(), course_id=course.id, title="Deck")
            older = _version(deck_id=deck.id, number=2)
            newer = _version(deck_id=deck.id, number=3)
            session.add_all([course, deck, older, newer])
            await session.flush()
            deck.active_version_id = newer.id
            await session.commit()

            cleanup = await repositories.mark_version_ready(
                session,
                version=older,
                indexed_chunk_count=1,
                old_vector_retention_seconds=3600,
            )
            await session.commit()

            assert deck.active_version_id == newer.id
            assert cleanup is not None
            assert cleanup.deck_version_id == older.id
            assert cleanup.event_type == "DELETE_DECK_VERSION"
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_recover_stale_work_releases_expired_leases() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with factory() as session:
            course = Course(id=uuid4(), name="Course", owner_id=uuid4())
            deck = Deck(id=uuid4(), course_id=course.id, title="Deck")
            version = _version(deck_id=deck.id, number=1)
            stale_at = datetime.now(UTC) - timedelta(hours=2)
            job = IngestionJob(
                deck_version_id=version.id,
                status="processing",
                attempts=1,
                locked_at=stale_at,
                worker_id="dead-worker",
            )
            event = VectorOutbox(
                deck_version_id=version.id,
                event_type="INDEX_DECK_VERSION",
                status="processing",
                attempts=1,
                locked_at=stale_at,
                worker_id="dead-worker",
            )
            session.add_all([course, deck, version, job, event])
            await session.commit()

            recovered = await repositories.recover_stale_work(
                session,
                lock_timeout_seconds=1800,
            )
            await session.commit()

            assert recovered == (1, 1)
            rows = (
                await session.scalars(select(VectorOutbox).where(VectorOutbox.id == event.id))
            ).all()
            assert rows[0].status == "pending"
            assert rows[0].locked_at is None
            assert job.status == "pending"
            assert job.locked_at is None
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_recent_conversation_history_is_ordered_scoped_and_bounded() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with factory() as session:
            owner_id = uuid4()
            course = Course(id=uuid4(), name="Course", owner_id=owner_id)
            deck = Deck(id=uuid4(), course_id=course.id, title="Deck")
            version = _version(deck_id=deck.id, number=1)
            slide = Slide(
                id=uuid4(),
                deck_version_id=version.id,
                slide_number=15,
                title="Attention",
                raw_text="Attention",
                normalized_text="Attention",
                content_hash="a" * 64,
            )
            conversation = Conversation(
                id=uuid4(),
                user_id=owner_id,
                course_id=course.id,
                deck_id=deck.id,
            )
            session.add_all([course, deck, version, slide, conversation])
            await session.flush()
            started = datetime.now(UTC)
            session.add_all(
                [
                    Message(
                        conversation_id=conversation.id,
                        role="user",
                        content="Attention là gì?",
                        current_slide_id=slide.id,
                        created_at=started,
                    ),
                    Message(
                        conversation_id=conversation.id,
                        role="assistant",
                        content="Attention giúp mô hình chú ý.",
                        current_slide_id=slide.id,
                        created_at=started,
                    ),
                    Message(
                        conversation_id=conversation.id,
                        role="user",
                        content="Giải thích kỹ hơn",
                        current_slide_id=slide.id,
                        created_at=started + timedelta(seconds=1),
                    ),
                    Message(
                        conversation_id=conversation.id,
                        role="assistant",
                        content="Giải thích chi tiết hơn.",
                        current_slide_id=slide.id,
                        created_at=started + timedelta(seconds=1),
                    ),
                ]
            )
            await session.commit()

            checked = await repositories.create_conversation_if_needed(
                session,
                conversation_id=conversation.id,
                user_id=owner_id,
                course_id=course.id,
                deck_id=deck.id,
            )
            history = await repositories.get_recent_conversation_messages(
                session,
                conversation_id=checked.id,
                max_messages=2,
            )

            assert [item.role for item in history] == ["user", "assistant"]
            assert history[0].content == "Giải thích kỹ hơn"
            assert history[0].slide_number == 15
            assert history[0].slide_title == "Attention"

            repositories.set_conversation_summary(
                conversation,
                summary_text="Rolling memory",
                summarized_turn_count=2,
            )
            await session.commit()
            assert conversation.summary_text == "Rolling memory"
            assert conversation.summary_turn_count == 2
            assert conversation.summary_updated_at is not None

            with pytest.raises(NotFoundError):
                await repositories.create_conversation_if_needed(
                    session,
                    conversation_id=conversation.id,
                    user_id=uuid4(),
                    course_id=course.id,
                    deck_id=deck.id,
                )
    finally:
        await engine.dispose()
