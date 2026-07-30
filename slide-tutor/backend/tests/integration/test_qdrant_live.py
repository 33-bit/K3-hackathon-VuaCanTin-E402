from __future__ import annotations

import os
from uuid import uuid4

import pytest
from qdrant_client import AsyncQdrantClient
from qdrant_client.http import models

from app.core.config import Settings
from app.services.qdrant_store import (
    DENSE_VECTOR_SIZE,
    QdrantChunk,
    QdrantStore,
)

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.getenv("RUN_QDRANT_INTEGRATION") != "1",
        reason="set RUN_QDRANT_INTEGRATION=1 with a live Qdrant 1.18.3",
    ),
]


def _dense(value: float) -> list[float]:
    return [value, *([0.0] * (DENSE_VECTOR_SIZE - 1))]


@pytest.mark.asyncio
async def test_live_bm25_rrf_scope_idempotency_alias_and_snapshot() -> None:
    settings = Settings()
    suffix = uuid4().hex[:12]
    alias = f"it_slide_chunks_{suffix}"
    physical = f"it_slide_chunks_{suffix}_v1"
    target_alias = f"it_slide_chunks_{suffix}_bootstrap"
    target_physical = f"it_slide_chunks_{suffix}_v2"
    api_key = (
        settings.qdrant_api_key.get_secret_value() if settings.qdrant_api_key is not None else None
    )
    raw = AsyncQdrantClient(
        url=settings.qdrant_url,
        api_key=api_key,
        timeout=20,
        cloud_inference=True,
    )
    store = QdrantStore.from_url(
        settings.qdrant_url,
        api_key=api_key,
        timeout_seconds=20,
        collection_alias=alias,
        physical_collection=physical,
    )
    target = QdrantStore.from_url(
        settings.qdrant_url,
        api_key=api_key,
        timeout_seconds=20,
        collection_alias=target_alias,
        physical_collection=target_physical,
    )
    try:
        await store.bootstrap()
        await store.bootstrap()

        course_id = uuid4()
        deck_id = uuid4()
        version_id = uuid4()
        slide_id = uuid4()
        allowed = QdrantChunk(
            point_id=uuid4(),
            course_id=course_id,
            deck_id=deck_id,
            deck_version_id=version_id,
            slide_id=slide_id,
            slide_number=1,
            chunk_type="slide",
            section="Truy xuất",
            content_hash="a" * 64,
            embedding_version="te3large_1536_v1",
            retrieval_schema_version="qdrant_bm25_rrf_v1",
            embedding_text="Giảng viên giải thích truy xuất lai bằng tiếng Việt.",
            dense_vector=_dense(1.0),
        )
        denied = QdrantChunk(
            point_id=uuid4(),
            course_id=uuid4(),
            deck_id=uuid4(),
            deck_version_id=uuid4(),
            slide_id=uuid4(),
            slide_number=1,
            chunk_type="slide",
            section="Private",
            content_hash="b" * 64,
            embedding_version="te3large_1536_v1",
            retrieval_schema_version="qdrant_bm25_rrf_v1",
            embedding_text="Giảng viên giải thích truy xuất lai bằng tiếng Việt.",
            dense_vector=_dense(1.0),
        )

        await store.upsert_chunks([allowed, denied])
        await store.upsert_chunks([allowed, denied])
        assert await store.count_deck_version(version_id) == 1

        hits = await store.hybrid_query(
            query_text="truy xuất lai tiếng Việt",
            dense_vector=_dense(1.0),
            course_id=course_id,
            deck_id=deck_id,
            deck_version_id=version_id,
        )
        assert [hit.point_id for hit in hits] == [allowed.point_id]

        snapshot = await raw.create_snapshot(
            collection_name=physical,
            wait=True,
        )
        assert snapshot is not None

        await target.bootstrap()
        switched = await store.switch_alias(target_physical)
        assert switched.current_collection == target_physical
        rolled_back = await store.switch_alias(physical)
        assert rolled_back.current_collection == physical
    finally:
        aliases = await raw.get_aliases()
        cleanup_aliases = [
            item.alias_name for item in aliases.aliases if item.alias_name in {alias, target_alias}
        ]
        if cleanup_aliases:
            await raw.update_collection_aliases(
                change_aliases_operations=[
                    models.DeleteAliasOperation(delete_alias=models.DeleteAlias(alias_name=item))
                    for item in cleanup_aliases
                ]
            )
        for collection in (physical, target_physical):
            if await raw.collection_exists(collection):
                await raw.delete_collection(collection)
        await target.close()
        await store.close()
        await raw.close()
