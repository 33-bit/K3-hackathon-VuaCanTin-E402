from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import math
import sys
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from qdrant_client import AsyncQdrantClient, models
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.db import repositories
from app.db.models import Chunk, Deck, DeckVersion, Slide
from app.db.session import get_engine, get_session_factory
from app.services.openai_service import OpenAIService
from app.services.qdrant_store import QdrantChunk, QdrantStore


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Backfill all active deck versions into a new physical Qdrant "
            "collection, verify parity, and optionally switch the logical alias."
        )
    )
    parser.add_argument(
        "--new-collection",
        required=True,
        help="New physical collection name, for example slide_chunks_*_v2.",
    )
    parser.add_argument(
        "--verify-only",
        action="store_true",
        help="Do not call OpenAI or upsert; verify an already backfilled collection.",
    )
    parser.add_argument(
        "--switch-alias",
        action="store_true",
        help=(
            "After verification, snapshot the old collection and atomically switch "
            "the configured logical alias."
        ),
    )
    parser.add_argument(
        "--record-dir",
        type=Path,
        default=Path("data/qdrant-migrations"),
        help="Directory for the migration manifest and rollback metadata.",
    )
    return parser.parse_args()


def api_key(settings: Settings) -> str | None:
    if settings.qdrant_api_key is None:
        return None
    return settings.qdrant_api_key.get_secret_value()


def make_store(
    settings: Settings,
    *,
    alias: str,
    physical_collection: str,
) -> QdrantStore:
    return QdrantStore.from_url(
        settings.qdrant_url,
        api_key=api_key(settings),
        timeout_seconds=settings.qdrant_timeout_seconds,
        collection_alias=alias,
        physical_collection=physical_collection,
        upsert_batch_size=settings.qdrant_upsert_batch_size,
    )


def make_raw_client(settings: Settings) -> AsyncQdrantClient:
    return AsyncQdrantClient(
        url=settings.qdrant_url,
        api_key=api_key(settings),
        timeout=max(1, math.ceil(settings.qdrant_timeout_seconds)),
        cloud_inference=True,
    )


async def alias_target(client: AsyncQdrantClient, alias: str) -> str | None:
    aliases = await client.get_aliases()
    targets = {item.collection_name for item in aliases.aliases if item.alias_name == alias}
    if len(targets) > 1:
        raise RuntimeError(f"Alias {alias!r} has multiple targets")
    return next(iter(targets), None)


async def delete_alias_if_present(
    client: AsyncQdrantClient,
    alias: str,
) -> None:
    if await alias_target(client, alias) is None:
        return
    changed = await client.update_collection_aliases(
        change_aliases_operations=[
            models.DeleteAliasOperation(delete_alias=models.DeleteAlias(alias_name=alias))
        ]
    )
    if changed is False:
        raise RuntimeError(f"Qdrant rejected deletion of temporary alias {alias!r}")


async def active_version_ids(session: AsyncSession | None = None) -> tuple[UUID, ...]:
    if session is not None:
        return await _active_version_ids_in_session(session)
    factory = get_session_factory()
    async with factory() as session:
        return await _active_version_ids_in_session(session)


async def _active_version_ids_in_session(
    session: AsyncSession,
) -> tuple[UUID, ...]:
    return tuple(
        (
            await session.scalars(
                select(DeckVersion.id)
                .join(Deck, Deck.active_version_id == DeckVersion.id)
                .where(
                    DeckVersion.status == "ready",
                    DeckVersion.index_status == "in_sync",
                )
                .order_by(DeckVersion.id)
            )
        ).all()
    )


async def load_version_data(
    version_id: UUID,
) -> tuple[DeckVersion, Deck, list[Chunk], dict[UUID, Slide]]:
    factory = get_session_factory()
    async with factory() as session:
        version = await session.get(DeckVersion, version_id)
        if version is None:
            raise RuntimeError(f"Deck version {version_id} was deleted")
        deck = await session.get(Deck, version.deck_id)
        if deck is None:
            raise RuntimeError(f"Deck {version.deck_id} was deleted")
        chunks = await repositories.get_chunks_for_version(
            session,
            deck_version_id=version.id,
        )
        slides = await repositories.get_slide_map(
            session,
            slide_ids=(chunk.slide_id for chunk in chunks),
        )
        return version, deck, list(chunks), dict(slides)


async def backfill_version(
    *,
    settings: Settings,
    store: QdrantStore,
    openai: OpenAIService,
    collection_name: str,
    version_id: UUID,
) -> int:
    version, deck, chunks, slides = await load_version_data(version_id)
    if version.embedding_model != settings.openai_embedding_model:
        raise RuntimeError(
            f"Version {version.id} uses embedding model "
            f"{version.embedding_model!r}, not "
            f"{settings.openai_embedding_model!r}"
        )
    if version.embedding_dimensions != settings.openai_embedding_dimensions:
        raise RuntimeError(
            f"Version {version.id} has {version.embedding_dimensions} dimensions, "
            f"not {settings.openai_embedding_dimensions}"
        )

    await store.delete_deck_version(
        version_id,
        collection_name=collection_name,
    )
    indexed = 0
    batch_size = settings.embedding_batch_size
    for start in range(0, len(chunks), batch_size):
        batch = chunks[start : start + batch_size]
        embeddings = await openai.embed_texts([chunk.embedding_text for chunk in batch])
        points: list[QdrantChunk] = []
        for chunk, dense_vector in zip(batch, embeddings, strict=True):
            slide = slides[chunk.slide_id]
            points.append(
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
        indexed += await store.upsert_chunks(
            points,
            collection_name=collection_name,
        )
    return indexed


async def verify_version(
    *,
    store: QdrantStore,
    collection_name: str,
    version_id: UUID,
) -> dict[str, object]:
    version, _, chunks, _ = await load_version_data(version_id)
    expected = {chunk.id: chunk.content_hash for chunk in chunks}
    expected_hash = repositories.build_manifest_hash(expected.items())
    manifest = await store.read_manifest(
        version.id,
        collection_name=collection_name,
    )
    if expected_hash != version.index_manifest_hash:
        raise RuntimeError(
            f"PostgreSQL manifest for version {version.id} is internally inconsistent"
        )
    if (
        not manifest.count_matches
        or manifest.exact_count != len(expected)
        or manifest.hashes_by_chunk_id != expected
    ):
        raise RuntimeError(
            f"Collection parity failed for version {version.id}: "
            f"expected {len(expected)}, observed {manifest.exact_count}"
        )
    return {
        "deck_version_id": str(version.id),
        "chunk_count": len(expected),
        "manifest_hash": expected_hash,
    }


def migration_record_path(record_dir: Path, new_collection: str) -> Path:
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    safe_name = "".join(
        character if character.isalnum() or character in "-_" else "_"
        for character in new_collection
    )
    return record_dir / f"{timestamp}_{safe_name}.json"


def write_record(path: Path, record: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(record, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


async def run(args: argparse.Namespace) -> int:
    settings = get_settings()
    new_collection = args.new_collection.strip()
    if not new_collection:
        raise ValueError("--new-collection cannot be blank")
    if new_collection == settings.qdrant_collection_alias:
        raise ValueError("The physical collection name must differ from the alias")

    raw_client = make_raw_client(settings)
    source_store: QdrantStore | None = None
    target_store: QdrantStore | None = None
    bootstrap_alias = (
        f"{settings.qdrant_collection_alias}__bootstrap_"
        f"{hashlib.sha256(new_collection.encode()).hexdigest()[:10]}"
    )
    record_path = migration_record_path(args.record_dir, new_collection)
    try:
        previous_collection = await alias_target(
            raw_client,
            settings.qdrant_collection_alias,
        )
        if previous_collection is None:
            raise RuntimeError(f"Required alias {settings.qdrant_collection_alias!r} is missing")
        if previous_collection == new_collection:
            raise RuntimeError("The logical alias already points to the new collection")

        source_store = make_store(
            settings,
            alias=settings.qdrant_collection_alias,
            physical_collection=previous_collection,
        )
        await source_store.validate_readiness()

        if args.verify_only and not await raw_client.collection_exists(new_collection):
            raise RuntimeError(f"Cannot verify missing collection {new_collection!r}")
        target_store = make_store(
            settings,
            alias=bootstrap_alias,
            physical_collection=new_collection,
        )
        await target_store.bootstrap()

        initial_versions = await active_version_ids()
        if not args.verify_only:
            openai = OpenAIService(settings)
            for version_id in initial_versions:
                await backfill_version(
                    settings=settings,
                    store=target_store,
                    openai=openai,
                    collection_name=new_collection,
                    version_id=version_id,
                )

        manifests = [
            await verify_version(
                store=target_store,
                collection_name=new_collection,
                version_id=version_id,
            )
            for version_id in initial_versions
        ]
        readiness = await target_store.validate_readiness()
        expected_total = sum(int(item["chunk_count"]) for item in manifests)
        if readiness.points_count != expected_total:
            raise RuntimeError(
                "New collection contains orphan or unexpected points: "
                f"expected {expected_total}, observed {readiness.points_count}"
            )

        record: dict[str, object] = {
            "created_at": datetime.now(UTC).isoformat(),
            "alias": settings.qdrant_collection_alias,
            "previous_collection": previous_collection,
            "new_collection": new_collection,
            "active_versions": manifests,
            "point_count": expected_total,
            "alias_switched": False,
            "phase": "verified",
            "required_runtime_configuration": {"QDRANT_PHYSICAL_COLLECTION": new_collection},
        }
        write_record(record_path, record)

        if args.switch_alias:
            factory = get_session_factory()
            async with factory() as lock_session:
                async with lock_session.begin():
                    await repositories.acquire_index_migration_lock(lock_session)
                    current_versions = await active_version_ids(lock_session)
                    if current_versions != initial_versions:
                        record["phase"] = "aborted_active_versions_changed"
                        record["observed_active_versions"] = [
                            str(item) for item in current_versions
                        ]
                        write_record(record_path, record)
                        raise RuntimeError(
                            "Active deck versions changed during backfill; rerun before switching"
                        )

                    snapshot = await raw_client.create_snapshot(
                        collection_name=previous_collection,
                        wait=True,
                    )
                    if snapshot is None:
                        raise RuntimeError("Qdrant did not return an old-collection snapshot")
                    record["previous_collection_snapshot"] = snapshot.name
                    record["phase"] = "alias_switch_pending"
                    write_record(record_path, record)

                    switch_result = await source_store.switch_alias(new_collection)
                    record["alias_switched"] = switch_result.changed
                    record["switched_at"] = datetime.now(UTC).isoformat()
                    record["phase"] = "complete"
                    write_record(record_path, record)
        else:
            current_versions = await active_version_ids()
            if current_versions != initial_versions:
                record["phase"] = "verified_active_versions_changed"
                record["observed_active_versions"] = [str(item) for item in current_versions]
            write_record(record_path, record)

        await delete_alias_if_present(raw_client, bootstrap_alias)
        print(
            json.dumps(
                {
                    "status": "complete",
                    "record": str(record_path),
                    **record,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0
    finally:
        try:
            await delete_alias_if_present(raw_client, bootstrap_alias)
        except Exception as cleanup_exc:
            print(
                f"warning: could not remove temporary alias {bootstrap_alias!r}: {cleanup_exc}",
                file=sys.stderr,
            )
        if target_store is not None:
            await target_store.close()
        if source_store is not None:
            await source_store.close()
        await raw_client.close()
        await get_engine().dispose()


def main() -> None:
    raise SystemExit(asyncio.run(run(parse_args())))


if __name__ == "__main__":
    main()
