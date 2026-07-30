from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import asdict, dataclass
from uuid import UUID

from sqlalchemy import select

from app.core.config import get_settings
from app.db import repositories
from app.db.models import Deck, DeckVersion
from app.db.session import get_engine, get_session_factory
from app.services.qdrant_store import QdrantStore


@dataclass(slots=True)
class ReconciliationResult:
    deck_version_id: str
    expected_count: int
    observed_count: int
    count_matches: bool
    hash_matches: bool
    repair_enqueued: bool = False

    @property
    def in_sync(self) -> bool:
        return self.count_matches and self.hash_matches


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Compare active PostgreSQL chunk manifests with Qdrant and optionally "
            "enqueue an idempotent repair."
        )
    )
    parser.add_argument(
        "--deck-version-id",
        type=UUID,
        help="Check one version instead of every active ready version.",
    )
    parser.add_argument(
        "--enqueue-repair",
        action="store_true",
        help="Mark inconsistent versions drifted and enqueue INDEX_DECK_VERSION.",
    )
    return parser.parse_args()


def build_qdrant_store() -> QdrantStore:
    settings = get_settings()
    api_key = (
        settings.qdrant_api_key.get_secret_value() if settings.qdrant_api_key is not None else None
    )
    return QdrantStore.from_url(
        settings.qdrant_url,
        api_key=api_key,
        timeout_seconds=settings.qdrant_timeout_seconds,
        collection_alias=settings.qdrant_collection_alias,
        physical_collection=settings.qdrant_physical_collection,
        upsert_batch_size=settings.qdrant_upsert_batch_size,
    )


async def load_versions(version_id: UUID | None) -> list[DeckVersion]:
    factory = get_session_factory()
    async with factory() as session:
        if version_id is not None:
            version = await session.get(DeckVersion, version_id)
            if version is None:
                raise ValueError(f"Deck version {version_id} does not exist")
            return [version]
        return list(
            (
                await session.scalars(
                    select(DeckVersion)
                    .join(Deck, Deck.active_version_id == DeckVersion.id)
                    .where(DeckVersion.status == "ready")
                    .order_by(DeckVersion.created_at)
                )
            ).all()
        )


async def reconcile_version(
    qdrant: QdrantStore,
    version: DeckVersion,
    *,
    enqueue_repair: bool,
) -> ReconciliationResult:
    manifest = await qdrant.read_manifest(version.id)
    observed_hash = repositories.build_manifest_hash(manifest.hashes_by_chunk_id.items())
    count_matches = manifest.count_matches and manifest.exact_count == version.expected_chunk_count
    hash_matches = (
        version.index_manifest_hash is not None and observed_hash == version.index_manifest_hash
    )
    result = ReconciliationResult(
        deck_version_id=str(version.id),
        expected_count=version.expected_chunk_count,
        observed_count=manifest.exact_count,
        count_matches=count_matches,
        hash_matches=hash_matches,
    )
    if result.in_sync or not enqueue_repair:
        return result

    factory = get_session_factory()
    async with factory() as session, session.begin():
        current = await session.get(DeckVersion, version.id, with_for_update=True)
        if current is None:
            raise ValueError(f"Deck version {version.id} was deleted")
        deck = await session.get(Deck, current.deck_id, with_for_update=True)
        if deck is None or deck.active_version_id != current.id:
            raise ValueError(
                "Repair can only be enqueued for the deck's active version"
            )
        await repositories.flag_index_drift(
            session,
            version=current,
            detail=(
                "Manual reconciliation found vector drift: "
                f"expected_count={version.expected_chunk_count}, "
                f"observed_count={manifest.exact_count}, "
                f"hash_matches={hash_matches}"
            ),
        )
    result.repair_enqueued = True
    return result


async def run(args: argparse.Namespace) -> int:
    qdrant = build_qdrant_store()
    try:
        await qdrant.validate_readiness()
        versions = await load_versions(args.deck_version_id)
        results = [
            await reconcile_version(
                qdrant,
                version,
                enqueue_repair=args.enqueue_repair,
            )
            for version in versions
        ]
        print(
            json.dumps(
                {
                    "checked": len(results),
                    "in_sync": sum(result.in_sync for result in results),
                    "inconsistent": sum(not result.in_sync for result in results),
                    "results": [asdict(result) for result in results],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0 if all(result.in_sync for result in results) else 2
    finally:
        await qdrant.close()
        await get_engine().dispose()


def main() -> None:
    raise SystemExit(asyncio.run(run(parse_args())))


if __name__ == "__main__":
    main()
