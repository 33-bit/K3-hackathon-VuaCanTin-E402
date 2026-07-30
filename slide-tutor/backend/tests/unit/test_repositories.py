from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db import repositories
from app.db.base import Base
from app.db.models import (
    Course,
    Deck,
    DeckVersion,
    IngestionJob,
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
