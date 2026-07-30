from __future__ import annotations

import asyncio
import hashlib
import socket
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import structlog
from sqlalchemy import select

from app.core.config import Settings, get_settings
from app.core.errors import VectorIndexUnavailableError
from app.core.logging import configure_logging
from app.db import repositories
from app.db.base import Base
from app.db.models import (
    Chunk,
    Deck,
    DeckVersion,
    IngestionJob,
    Slide,
    SlideBlock,
    VectorOutbox,
)
from app.db.session import get_engine, get_session_factory
from app.ingestion import (
    IngestionError,
    ParsedSlide,
    TextlessDocumentError,
    chunk_deck,
    normalize_deck,
    parse_document,
)
from app.services.openai_service import OpenAIService
from app.services.qdrant_store import (
    QdrantChunk,
    QdrantIndexInconsistentError,
    QdrantStore,
)

logger = structlog.get_logger(__name__)


def _raw_slide_text(slide: ParsedSlide) -> str:
    """Build source text while removing characters PostgreSQL cannot store."""

    return "\n\n".join(
        [slide.title, *(block.text for block in slide.blocks)]
    ).replace("\x00", "").strip()


class BackgroundWorker:
    def __init__(
        self,
        *,
        settings: Settings,
        qdrant: QdrantStore,
        openai: OpenAIService,
        worker_id: str | None = None,
    ) -> None:
        self.settings = settings
        self.qdrant = qdrant
        self.openai = openai
        self.worker_id = worker_id or f"{socket.gethostname()}:{id(self)}"
        self._last_reconcile = 0.0
        self._qdrant_ready = False
        self._qdrant_bootstrap_attempt = 0
        self._next_qdrant_bootstrap_at = 0.0
        self._prefer_vector_event = False

    async def run_forever(self) -> None:
        await self._recover_stale_work()
        while True:
            did_work = await self.run_once()
            now = asyncio.get_running_loop().time()
            if now - self._last_reconcile >= self.settings.reconcile_interval_seconds:
                await self.reconcile_active_versions()
                self._last_reconcile = now
            if not did_work:
                await asyncio.sleep(self.settings.worker_poll_seconds)

    async def run_once(self) -> bool:
        if self._prefer_vector_event and await self._ensure_qdrant_ready():
            if await self._process_one_vector_event():
                self._prefer_vector_event = False
                return True
        if await self._process_one_ingestion_job():
            self._prefer_vector_event = True
            return True
        if not await self._ensure_qdrant_ready():
            return False
        did_vector_work = await self._process_one_vector_event()
        if did_vector_work:
            self._prefer_vector_event = False
        return did_vector_work

    async def _ensure_qdrant_ready(self) -> bool:
        if self._qdrant_ready:
            return True
        now = asyncio.get_running_loop().time()
        if now < self._next_qdrant_bootstrap_at:
            return False
        try:
            readiness = await self.qdrant.bootstrap()
            self._qdrant_ready = True
            self._qdrant_bootstrap_attempt = 0
            logger.info(
                "qdrant_bootstrapped",
                alias=readiness.alias,
                collection=readiness.physical_collection,
                points=readiness.points_count,
            )
            return True
        except Exception as exc:
            self._qdrant_bootstrap_attempt += 1
            delay = min(30, 2 ** min(self._qdrant_bootstrap_attempt, 5))
            self._next_qdrant_bootstrap_at = now + delay
            logger.warning(
                "qdrant_bootstrap_failed",
                attempt=self._qdrant_bootstrap_attempt,
                retry_seconds=delay,
                error=str(exc),
            )
            return False

    async def _process_one_ingestion_job(self) -> bool:
        factory = get_session_factory()
        async with factory() as session:
            async with session.begin():
                job = await repositories.claim_ingestion_job(session, worker_id=self.worker_id)
            if job is None:
                return False
            job_id = job.id
            version_id = job.deck_version_id

        try:
            await self._ingest_version(version_id)
            async with factory() as session:
                async with session.begin():
                    current = await session.get(IngestionJob, job_id, with_for_update=True)
                    if current is not None:
                        current.status = "completed"
                        current.stage = "vector_outbox_created"
                        current.locked_at = None
                        current.worker_id = None
            logger.info("ingestion_completed", deck_version_id=str(version_id))
        except TextlessDocumentError as exc:
            async with factory() as session:
                async with session.begin():
                    version = await session.get(DeckVersion, version_id, with_for_update=True)
                    current = await session.get(IngestionJob, job_id, with_for_update=True)
                    if version is not None:
                        await repositories.mark_version_failed(
                            session,
                            version=version,
                            code="unsupported_textless_pdf",
                            detail=str(exc),
                            status="unsupported_textless_pdf",
                        )
                    if current is not None:
                        current.status = "failed"
                        current.last_error = str(exc)
                        current.locked_at = None
                        current.worker_id = None
            logger.info("ingestion_textless", deck_version_id=str(version_id))
        except Exception as exc:
            async with factory() as session:
                async with session.begin():
                    current = await session.get(IngestionJob, job_id, with_for_update=True)
                    version = await session.get(DeckVersion, version_id, with_for_update=True)
                    if current is not None:
                        repositories.schedule_retry(
                            current,
                            error=exc,
                            max_attempts=self.settings.max_job_attempts,
                        )
                        if current.status == "failed" and version is not None:
                            await repositories.mark_version_failed(
                                session,
                                version=version,
                                code=_ingestion_error_code(exc),
                                detail=str(exc),
                            )
            logger.exception(
                "ingestion_failed",
                deck_version_id=str(version_id),
                error=str(exc),
            )
        return True

    async def _ingest_version(self, version_id: UUID) -> None:
        factory = get_session_factory()
        async with factory() as session:
            async with session.begin():
                version = await session.get(DeckVersion, version_id, with_for_update=True)
                if version is None:
                    raise RuntimeError(f"Deck version {version_id} no longer exists")
                version.status = "parsing"
                version.stage = "text_extraction"
                source_path = version.source_file_path
                deck = await session.get(Deck, version.deck_id)
                if deck is None:
                    raise RuntimeError(f"Deck {version.deck_id} no longer exists")
                deck_title = deck.title

        parsed = await asyncio.to_thread(
            parse_document,
            Path(source_path),
            filename=source_path,
            deck_title=deck_title,
        )
        normalized = normalize_deck(parsed, version_id)
        chunk_data = chunk_deck(normalized)
        raw_by_number = {slide.number: _raw_slide_text(slide) for slide in parsed.slides}

        slides: list[Slide] = []
        blocks: list[SlideBlock] = []
        for index, slide in enumerate(normalized.slides):
            previous_id = normalized.slides[index - 1].id if index > 0 else None
            next_id = (
                normalized.slides[index + 1].id if index + 1 < len(normalized.slides) else None
            )
            slides.append(
                Slide(
                    id=slide.id,
                    deck_version_id=version_id,
                    slide_number=slide.number,
                    title=slide.title or None,
                    section=slide.section or None,
                    raw_text=raw_by_number.get(slide.number, ""),
                    normalized_text=slide.text,
                    previous_slide_id=previous_id,
                    next_slide_id=next_id,
                    content_hash=hashlib.sha256(slide.text.encode("utf-8")).hexdigest(),
                )
            )
            blocks.extend(
                SlideBlock(
                    id=block.id,
                    slide_id=slide.id,
                    block_type=block.kind.value,
                    reading_order=block.reading_order,
                    bullet_level=None,
                    text=block.text,
                    metadata_json={},
                )
                for block in slide.blocks
            )
        chunks = [
            Chunk(
                id=item.id,
                deck_version_id=item.deck_version_id,
                slide_id=item.slide_id,
                ordinal=item.ordinal,
                chunk_type=item.chunk_type.value,
                text=item.text,
                embedding_text=item.embedding_text,
                token_count=item.token_count,
                content_hash=item.content_hash,
                metadata_json=item.metadata_json,
            )
            for item in chunk_data
        ]
        textless_count = sum(1 for slide in normalized.slides if not slide.text.strip())

        async with factory() as session:
            async with session.begin():
                version = await session.get(DeckVersion, version_id, with_for_update=True)
                if version is None:
                    raise RuntimeError(f"Deck version {version_id} no longer exists")
                version.status = "chunking"
                version.stage = "persisting_chunks"
                await repositories.replace_version_content(
                    session,
                    version=version,
                    slides=slides,
                    blocks=blocks,
                    chunks=chunks,
                    textless_slide_count=textless_count,
                )

    async def _process_one_vector_event(self) -> bool:
        factory = get_session_factory()
        async with factory() as session:
            async with session.begin():
                event = await repositories.claim_vector_event(session, worker_id=self.worker_id)
            if event is None:
                return False
            event_id = event.id
            event_type = event.event_type
            version_id = event.deck_version_id

        try:
            if event_type == "INDEX_DECK_VERSION":
                async with factory() as session:
                    async with session.begin():
                        await repositories.acquire_index_migration_lock(session)
                        indexed_count = await self._index_version(version_id)
                        event = await session.get(VectorOutbox, event_id, with_for_update=True)
                        version = await session.get(DeckVersion, version_id, with_for_update=True)
                        if event is None or version is None:
                            raise RuntimeError("Vector event target was deleted")
                        await repositories.mark_version_ready(
                            session,
                            version=version,
                            indexed_chunk_count=indexed_count,
                            old_vector_retention_seconds=(
                                self.settings.old_vector_retention_seconds
                            ),
                        )
                        event.status = "completed"
                        event.processed_at = datetime.now(UTC)
                        event.locked_at = None
                        event.worker_id = None
            elif event_type == "REBUILD_COLLECTION":
                raise RuntimeError(
                    "Global rebuild events require scripts.rebuild_collection "
                    "with an explicit target physical collection"
                )
            elif event_type == "DELETE_DECK_VERSION":
                async with factory() as session:
                    async with session.begin():
                        await repositories.acquire_index_migration_lock(session)
                        event = await session.get(VectorOutbox, event_id, with_for_update=True)
                        version = await session.get(DeckVersion, version_id)
                        deck = (
                            await session.get(Deck, version.deck_id, with_for_update=True)
                            if version is not None
                            else None
                        )
                        if event is None:
                            return True
                        if deck is None or deck.active_version_id != version_id:
                            await self.qdrant.delete_deck_version(version_id)
                        else:
                            event.last_error = "Cleanup skipped because version is active"
                        event.status = "completed"
                        event.processed_at = datetime.now(UTC)
                        event.locked_at = None
                        event.worker_id = None
            else:
                raise RuntimeError(f"Unknown vector event {event_type}")
            logger.info(
                "vector_event_completed",
                event_type=event_type,
                deck_version_id=str(version_id),
            )
        except Exception as exc:
            if isinstance(exc, VectorIndexUnavailableError):
                self._qdrant_ready = False
            async with factory() as session:
                async with session.begin():
                    event = await session.get(VectorOutbox, event_id, with_for_update=True)
                    version = await session.get(DeckVersion, version_id, with_for_update=True)
                    if event is not None:
                        repositories.schedule_retry(
                            event,
                            error=exc,
                            max_attempts=self.settings.max_job_attempts,
                        )
                        if (
                            event.status == "failed"
                            and version is not None
                            and event_type == "INDEX_DECK_VERSION"
                        ):
                            deck = await session.get(Deck, version.deck_id)
                            if deck is not None and deck.active_version_id == version.id:
                                version.status = "ready"
                                version.stage = "vector_repair_failed"
                                version.index_status = "failed"
                                version.error_code = "vector_index_failed"
                                version.error_detail = str(exc)[:4000]
                            else:
                                await repositories.mark_version_failed(
                                    session,
                                    version=version,
                                    code="vector_index_failed",
                                    detail=str(exc),
                                )
            logger.exception(
                "vector_event_failed",
                event_type=event_type,
                deck_version_id=str(version_id),
                error=str(exc),
            )
        return True

    async def _index_version(self, version_id: UUID) -> int:
        factory = get_session_factory()
        async with factory() as session:
            version = await session.get(DeckVersion, version_id)
            if version is None:
                raise RuntimeError(f"Deck version {version_id} no longer exists")
            deck = await session.get(Deck, version.deck_id)
            if deck is None:
                raise RuntimeError(f"Deck {version.deck_id} no longer exists")
            chunks = await repositories.get_chunks_for_version(session, deck_version_id=version.id)
            slides = await repositories.get_slide_map(
                session, slide_ids=(chunk.slide_id for chunk in chunks)
            )

        # A retry may follow a partial upsert or a parser retry may have changed
        # the deterministic manifest. Replacing this immutable version scope
        # removes orphan points before rebuilding it.
        await self.qdrant.delete_deck_version(version_id)
        qdrant_chunks: list[QdrantChunk] = []
        for start in range(0, len(chunks), self.settings.embedding_batch_size):
            batch = chunks[start : start + self.settings.embedding_batch_size]
            embeddings = await self.openai.embed_texts([chunk.embedding_text for chunk in batch])
            for chunk, dense_vector in zip(batch, embeddings, strict=True):
                slide = slides[chunk.slide_id]
                qdrant_chunks.append(
                    QdrantChunk(
                        point_id=chunk.id,
                        course_id=deck.course_id,
                        deck_id=deck.id,
                        deck_version_id=version.id,
                        slide_id=slide.id,
                        slide_number=slide.slide_number,
                        chunk_type=chunk.chunk_type,
                        section=slide.section or "",
                        content_hash=chunk.content_hash,
                        embedding_version=version.embedding_version,
                        retrieval_schema_version=version.retrieval_schema_version,
                        embedding_text=chunk.embedding_text,
                        dense_vector=dense_vector,
                    )
                )
        indexed_count = await self.qdrant.upsert_chunks(qdrant_chunks)
        manifest = await self.qdrant.read_manifest(version.id)
        expected = {chunk.id: chunk.content_hash for chunk in chunks}
        if (
            indexed_count != len(chunks)
            or manifest.exact_count != len(chunks)
            or not manifest.count_matches
            or manifest.hashes_by_chunk_id != expected
        ):
            raise QdrantIndexInconsistentError(
                f"Expected {len(chunks)} canonical chunks, got {manifest.exact_count} Qdrant points"
            )
        observed_manifest_hash = repositories.build_manifest_hash(
            manifest.hashes_by_chunk_id.items()
        )
        if observed_manifest_hash != version.index_manifest_hash:
            raise QdrantIndexInconsistentError("Qdrant manifest hash does not match PostgreSQL")
        return indexed_count

    async def reconcile_active_versions(self) -> None:
        await self._recover_stale_work()
        if not await self._ensure_qdrant_ready():
            return
        factory = get_session_factory()
        async with factory() as session:
            versions = list(
                (
                    await session.scalars(
                        select(DeckVersion)
                        .join(Deck, Deck.active_version_id == DeckVersion.id)
                        .where(DeckVersion.status == "ready")
                    )
                ).all()
            )
        for version in versions:
            try:
                manifest = await self.qdrant.read_manifest(version.id)
                observed_hash = repositories.build_manifest_hash(
                    manifest.hashes_by_chunk_id.items()
                )
                if (
                    manifest.exact_count != version.expected_chunk_count
                    or not manifest.count_matches
                    or observed_hash != version.index_manifest_hash
                ):
                    raise QdrantIndexInconsistentError("Periodic reconciliation found vector drift")
                if version.index_status != "in_sync":
                    async with factory() as session:
                        async with session.begin():
                            current = await session.get(
                                DeckVersion,
                                version.id,
                                with_for_update=True,
                            )
                            if current is not None:
                                current.index_status = "in_sync"
                                current.stage = "completed"
                                current.error_code = None
                                current.error_detail = None
            except QdrantIndexInconsistentError as exc:
                async with factory() as session:
                    async with session.begin():
                        current = await session.get(DeckVersion, version.id, with_for_update=True)
                        if current is not None:
                            await repositories.flag_index_drift(
                                session, version=current, detail=str(exc)
                            )
                logger.error(
                    "vector_drift_detected",
                    deck_version_id=str(version.id),
                    error=str(exc),
                )
            except Exception as exc:
                if isinstance(exc, VectorIndexUnavailableError):
                    self._qdrant_ready = False
                logger.warning(
                    "vector_reconciliation_unavailable",
                    deck_version_id=str(version.id),
                    error=str(exc),
                )
        await self._reschedule_failed_vector_work()

    async def _recover_stale_work(self) -> None:
        factory = get_session_factory()
        async with factory() as session:
            async with session.begin():
                ingestion_count, vector_count = await repositories.recover_stale_work(
                    session,
                    lock_timeout_seconds=self.settings.worker_lock_timeout_seconds,
                )
        if ingestion_count or vector_count:
            logger.warning(
                "expired_worker_leases_recovered",
                ingestion_jobs=ingestion_count,
                vector_events=vector_count,
            )

    async def _reschedule_failed_vector_work(self) -> None:
        factory = get_session_factory()
        async with factory() as session:
            async with session.begin():
                active_version_ids = set(
                    (
                        await session.scalars(
                            select(Deck.active_version_id).where(
                                Deck.active_version_id.is_not(None)
                            )
                        )
                    ).all()
                )
                failed_events = list(
                    (
                        await session.scalars(
                            select(VectorOutbox)
                            .where(VectorOutbox.status == "failed")
                            .with_for_update(skip_locked=True)
                        )
                    ).all()
                )
                rescheduled = 0
                scheduled_cleanup_versions = set(
                    (
                        await session.scalars(
                            select(VectorOutbox.deck_version_id).where(
                                VectorOutbox.event_type == "DELETE_DECK_VERSION",
                                VectorOutbox.status.in_(["pending", "processing"]),
                            )
                        )
                    ).all()
                )
                for event in failed_events:
                    should_retry = (
                        event.event_type == "DELETE_DECK_VERSION"
                        and event.deck_version_id not in active_version_ids
                        and event.deck_version_id not in scheduled_cleanup_versions
                    )
                    if not should_retry:
                        continue
                    event.status = "pending"
                    event.attempts = 0
                    event.available_at = datetime.now(UTC)
                    event.locked_at = None
                    event.worker_id = None
                    scheduled_cleanup_versions.add(event.deck_version_id)
                    rescheduled += 1
        if rescheduled:
            logger.warning("failed_vector_events_rescheduled", count=rescheduled)


def _ingestion_error_code(exc: Exception) -> str:
    if isinstance(exc, IngestionError):
        return exc.__class__.__name__.removesuffix("Error").lower()
    return "ingestion_failed"


async def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    settings.ensure_runtime_directories()
    if settings.auto_create_schema:
        async with get_engine().begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
    api_key = (
        settings.qdrant_api_key.get_secret_value() if settings.qdrant_api_key is not None else None
    )
    qdrant = QdrantStore.from_url(
        settings.qdrant_url,
        api_key=api_key,
        timeout_seconds=settings.qdrant_timeout_seconds,
        collection_alias=settings.qdrant_collection_alias,
        physical_collection=settings.qdrant_physical_collection,
        upsert_batch_size=settings.qdrant_upsert_batch_size,
    )
    worker = BackgroundWorker(
        settings=settings,
        qdrant=qdrant,
        openai=OpenAIService(settings),
    )
    try:
        await worker.run_forever()
    finally:
        await qdrant.close()


if __name__ == "__main__":
    asyncio.run(main())
