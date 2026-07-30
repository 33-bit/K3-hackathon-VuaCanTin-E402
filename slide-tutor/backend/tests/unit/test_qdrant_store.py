from __future__ import annotations

from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from qdrant_client.http import models

from app.services.qdrant_store import (
    BM25_MODEL,
    BM25_OPTIONS,
    COLLECTION_ALIAS,
    DENSE_VECTOR_NAME,
    DENSE_VECTOR_SIZE,
    PHYSICAL_COLLECTION,
    SEARCH_PAYLOAD_FIELDS,
    SPARSE_VECTOR_NAME,
    QdrantChunk,
    QdrantIndexInconsistentError,
    QdrantSchemaMismatchError,
    QdrantStore,
)


def _payload_schema() -> dict[str, models.PayloadIndexInfo]:
    def info(data_type: models.PayloadSchemaType, params: object) -> models.PayloadIndexInfo:
        return models.PayloadIndexInfo(data_type=data_type, params=params, points=0)

    return {
        "deck_id": info(
            models.PayloadSchemaType.KEYWORD,
            models.KeywordIndexParams(
                type=models.KeywordIndexType.KEYWORD,
                is_tenant=True,
            ),
        ),
        "chunk_id": info(
            models.PayloadSchemaType.UUID,
            models.UuidIndexParams(type=models.UuidIndexType.UUID),
        ),
        "course_id": info(
            models.PayloadSchemaType.UUID,
            models.UuidIndexParams(type=models.UuidIndexType.UUID),
        ),
        "deck_version_id": info(
            models.PayloadSchemaType.UUID,
            models.UuidIndexParams(type=models.UuidIndexType.UUID),
        ),
        "slide_id": info(
            models.PayloadSchemaType.UUID,
            models.UuidIndexParams(type=models.UuidIndexType.UUID),
        ),
        "slide_number": info(
            models.PayloadSchemaType.INTEGER,
            models.IntegerIndexParams(type=models.IntegerIndexType.INTEGER),
        ),
        "chunk_type": info(
            models.PayloadSchemaType.KEYWORD,
            models.KeywordIndexParams(type=models.KeywordIndexType.KEYWORD),
        ),
        "section": info(
            models.PayloadSchemaType.KEYWORD,
            models.KeywordIndexParams(type=models.KeywordIndexType.KEYWORD),
        ),
    }


def _collection_info(
    *,
    payload_schema: dict[str, models.PayloadIndexInfo] | None = None,
    dense_size: int = DENSE_VECTOR_SIZE,
) -> models.CollectionInfo:
    return models.CollectionInfo(
        status=models.CollectionStatus.GREEN,
        optimizer_status=models.OptimizersStatusOneOf.OK,
        indexed_vectors_count=0,
        points_count=0,
        segments_count=1,
        config=models.CollectionConfig(
            params=models.CollectionParams(
                vectors={
                    DENSE_VECTOR_NAME: models.VectorParams(
                        size=dense_size,
                        distance=models.Distance.COSINE,
                    )
                },
                shard_number=1,
                replication_factor=1,
                write_consistency_factor=1,
                on_disk_payload=True,
                sparse_vectors={
                    SPARSE_VECTOR_NAME: models.SparseVectorParams(modifier=models.Modifier.IDF)
                },
            ),
            hnsw_config=models.HnswConfig(
                m=16,
                ef_construct=100,
                full_scan_threshold=10_000,
                max_indexing_threads=0,
                on_disk=False,
            ),
            optimizer_config=models.OptimizersConfig(
                deleted_threshold=0.2,
                vacuum_min_vector_number=1_000,
                default_segment_number=0,
                max_segment_size=None,
                memmap_threshold=None,
                indexing_threshold=20_000,
                flush_interval_sec=5,
                max_optimization_threads=None,
            ),
            wal_config=models.WalConfig(
                wal_capacity_mb=32,
                wal_segments_ahead=0,
                wal_retain_closed=1,
            ),
            quantization_config=None,
            strict_mode_config=models.StrictModeConfigOutput(
                enabled=True,
                unindexed_filtering_retrieve=False,
                unindexed_filtering_update=False,
            ),
        ),
        payload_schema=payload_schema or {},
    )


def _aliases(*pairs: tuple[str, str]) -> models.CollectionsAliasesResponse:
    return models.CollectionsAliasesResponse(
        aliases=[
            models.AliasDescription(alias_name=alias, collection_name=collection)
            for alias, collection in pairs
        ]
    )


def _chunk() -> QdrantChunk:
    return QdrantChunk(
        point_id=uuid4(),
        course_id=uuid4(),
        deck_id=uuid4(),
        deck_version_id=uuid4(),
        slide_id=uuid4(),
        slide_number=3,
        chunk_type="block",
        section="Retrieval",
        content_hash="a" * 64,
        embedding_version="te3large_1536_v1",
        retrieval_schema_version="qdrant_bm25_rrf_v1",
        embedding_text="Deck title\nSlide title\nNội dung truy xuất.",
        dense_vector=[0.01] * DENSE_VECTOR_SIZE,
    )


@pytest.mark.asyncio
async def test_bootstrap_creates_exact_schema_indexes_and_alias() -> None:
    client = AsyncMock()
    client.collection_exists.return_value = False
    client.create_collection.return_value = True
    client.get_collection.side_effect = [
        _collection_info(),
        _collection_info(),
        _collection_info(payload_schema=_payload_schema()),
    ]
    client.get_aliases.side_effect = [
        _aliases(),
        _aliases(),
        _aliases((COLLECTION_ALIAS, PHYSICAL_COLLECTION)),
    ]
    client.update_collection_aliases.return_value = True
    store = QdrantStore(client)

    readiness = await store.bootstrap()

    assert readiness.ready is True
    assert readiness.physical_collection == PHYSICAL_COLLECTION
    create_kwargs = client.create_collection.await_args.kwargs
    dense = create_kwargs["vectors_config"][DENSE_VECTOR_NAME]
    sparse = create_kwargs["sparse_vectors_config"][SPARSE_VECTOR_NAME]
    strict = create_kwargs["strict_mode_config"]
    assert dense.size == DENSE_VECTOR_SIZE
    assert dense.distance == models.Distance.COSINE
    assert sparse.modifier == models.Modifier.IDF
    assert create_kwargs["shard_number"] == 1
    assert create_kwargs["replication_factor"] == 1
    assert create_kwargs["quantization_config"] is None
    assert strict.enabled is True
    assert strict.unindexed_filtering_retrieve is False
    assert strict.unindexed_filtering_update is False

    index_calls = client.create_payload_index.await_args_list
    assert {call.kwargs["field_name"] for call in index_calls} == set(_payload_schema())
    deck_index_call = next(call for call in index_calls if call.kwargs["field_name"] == "deck_id")
    assert deck_index_call.kwargs["field_schema"].is_tenant is True
    assert all(call.kwargs["wait"] is True for call in index_calls)

    alias_operation = client.update_collection_aliases.await_args.kwargs[
        "change_aliases_operations"
    ][0]
    assert alias_operation.create_alias.alias_name == COLLECTION_ALIAS
    assert alias_operation.create_alias.collection_name == PHYSICAL_COLLECTION


@pytest.mark.asyncio
async def test_bootstrap_is_idempotent_when_schema_already_exists() -> None:
    client = AsyncMock()
    client.collection_exists.return_value = True
    client.get_collection.side_effect = [
        _collection_info(payload_schema=_payload_schema()),
        _collection_info(payload_schema=_payload_schema()),
        _collection_info(payload_schema=_payload_schema()),
    ]
    client.get_aliases.side_effect = [
        _aliases((COLLECTION_ALIAS, PHYSICAL_COLLECTION)),
        _aliases((COLLECTION_ALIAS, PHYSICAL_COLLECTION)),
    ]

    await QdrantStore(client).bootstrap()

    client.create_collection.assert_not_awaited()
    client.create_payload_index.assert_not_awaited()
    client.update_collection_aliases.assert_not_awaited()


@pytest.mark.asyncio
async def test_bootstrap_accepts_a_valid_alias_migrated_to_a_new_collection() -> None:
    migrated_collection = "slide_chunks_te3large_1536_bm25_v2"
    client = AsyncMock()
    client.get_aliases.return_value = _aliases((COLLECTION_ALIAS, migrated_collection))
    client.get_collection.return_value = _collection_info(payload_schema=_payload_schema())

    readiness = await QdrantStore(client).bootstrap()

    assert readiness.physical_collection == migrated_collection
    client.create_collection.assert_not_awaited()
    client.update_collection_aliases.assert_not_awaited()


@pytest.mark.asyncio
async def test_bootstrap_rejects_wrong_dense_dimension() -> None:
    client = AsyncMock()
    client.collection_exists.return_value = True
    client.get_collection.return_value = _collection_info(dense_size=3072)

    with pytest.raises(QdrantSchemaMismatchError, match="expected 1536"):
        await QdrantStore(client).bootstrap()


@pytest.mark.asyncio
async def test_upsert_batches_dense_and_native_bm25_without_text_payload() -> None:
    client = AsyncMock()
    store = QdrantStore(client, upsert_batch_size=1)
    first = _chunk()
    second = _chunk()

    indexed = await store.upsert_chunks([first, second])

    assert indexed == 2
    assert client.upsert.await_count == 2
    first_call = client.upsert.await_args_list[0]
    assert first_call.kwargs["collection_name"] == COLLECTION_ALIAS
    assert first_call.kwargs["wait"] is True
    point = first_call.kwargs["points"][0]
    assert point.id == first.point_id
    assert len(point.vector[DENSE_VECTOR_NAME]) == DENSE_VECTOR_SIZE
    document = point.vector[SPARSE_VECTOR_NAME]
    assert isinstance(document, models.Document)
    assert document.text == first.embedding_text
    assert document.model == BM25_MODEL
    assert document.options == BM25_OPTIONS
    assert point.payload["chunk_id"] == str(first.point_id)
    assert "text" not in point.payload
    assert "embedding_text" not in point.payload


@pytest.mark.asyncio
async def test_hybrid_query_uses_identical_scope_filters_and_rrf() -> None:
    chunk = _chunk()
    scored = models.ScoredPoint(
        id=chunk.point_id,
        version=1,
        score=0.75,
        payload=chunk.payload(),
        vector=None,
    )
    client = AsyncMock()
    client.query_points.return_value = models.QueryResponse(points=[scored])
    store = QdrantStore(client)

    candidates = await store.hybrid_query(
        query_text="giải thích hybrid retrieval",
        dense_vector=[0.02] * DENSE_VECTOR_SIZE,
        course_id=chunk.course_id,
        deck_id=chunk.deck_id,
        deck_version_id=chunk.deck_version_id,
    )

    assert candidates[0].chunk_id == chunk.point_id
    kwargs = client.query_points.await_args.kwargs
    assert kwargs["collection_name"] == COLLECTION_ALIAS
    assert kwargs["limit"] == 12
    assert kwargs["with_vectors"] is False
    assert set(kwargs["with_payload"].include) == set(SEARCH_PAYLOAD_FIELDS)
    assert kwargs["query"].fusion == models.Fusion.RRF
    dense_prefetch, sparse_prefetch = kwargs["prefetch"]
    assert dense_prefetch.using == DENSE_VECTOR_NAME
    assert sparse_prefetch.using == SPARSE_VECTOR_NAME
    assert dense_prefetch.limit == sparse_prefetch.limit == 20
    assert dense_prefetch.filter is sparse_prefetch.filter
    assert kwargs["query_filter"] is dense_prefetch.filter
    assert sparse_prefetch.query.model == BM25_MODEL
    assert sparse_prefetch.query.options == BM25_OPTIONS

    conditions = dense_prefetch.filter.must
    assert [condition.key for condition in conditions] == [
        "course_id",
        "deck_id",
        "deck_version_id",
    ]
    assert [condition.match.value for condition in conditions] == [
        str(chunk.course_id),
        str(chunk.deck_id),
        str(chunk.deck_version_id),
    ]


@pytest.mark.asyncio
async def test_hybrid_query_fails_closed_on_point_payload_identity_mismatch() -> None:
    chunk = _chunk()
    wrong_payload = chunk.payload()
    wrong_payload["chunk_id"] = str(uuid4())
    client = AsyncMock()
    client.query_points.return_value = models.QueryResponse(
        points=[
            models.ScoredPoint(
                id=chunk.point_id,
                version=1,
                score=0.5,
                payload=wrong_payload,
                vector=None,
            )
        ]
    )

    with pytest.raises(QdrantIndexInconsistentError, match="differs"):
        await QdrantStore(client).hybrid_query(
            query_text="query",
            dense_vector=[0.01] * DENSE_VECTOR_SIZE,
            course_id=chunk.course_id,
            deck_id=chunk.deck_id,
            deck_version_id=chunk.deck_version_id,
        )


@pytest.mark.asyncio
async def test_hybrid_query_fails_closed_on_scope_payload_mismatch() -> None:
    chunk = _chunk()
    wrong_payload = chunk.payload()
    wrong_payload["course_id"] = str(uuid4())
    client = AsyncMock()
    client.query_points.return_value = models.QueryResponse(
        points=[
            models.ScoredPoint(
                id=chunk.point_id,
                version=1,
                score=0.5,
                payload=wrong_payload,
                vector=None,
            )
        ]
    )

    with pytest.raises(QdrantIndexInconsistentError, match="course"):
        await QdrantStore(client).hybrid_query(
            query_text="query",
            dense_vector=[0.01] * DENSE_VECTOR_SIZE,
            course_id=chunk.course_id,
            deck_id=chunk.deck_id,
            deck_version_id=chunk.deck_version_id,
        )


@pytest.mark.asyncio
async def test_manifest_count_scroll_and_filtered_delete() -> None:
    chunk = _chunk()
    client = AsyncMock()
    client.count.return_value = models.CountResult(count=1)
    client.scroll.return_value = (
        [
            models.Record(
                id=chunk.point_id,
                payload={
                    "chunk_id": str(chunk.point_id),
                    "content_hash": chunk.content_hash,
                },
                vector=None,
            )
        ],
        None,
    )
    store = QdrantStore(client)

    manifest = await store.read_manifest(chunk.deck_version_id)
    await store.delete_deck_version(chunk.deck_version_id)

    assert manifest.exact_count == manifest.observed_count == 1
    assert manifest.count_matches is True
    assert manifest.hashes_by_chunk_id == {chunk.point_id: chunk.content_hash}
    assert client.count.await_args.kwargs["exact"] is True
    assert client.scroll.await_args.kwargs["with_vectors"] is False

    selector = client.delete.await_args.kwargs["points_selector"]
    assert client.delete.await_args.kwargs["wait"] is True
    condition = selector.filter.must[0]
    assert condition.key == "deck_version_id"
    assert condition.match.value == str(chunk.deck_version_id)


@pytest.mark.asyncio
async def test_alias_switch_is_atomic_and_verified() -> None:
    new_collection = "slide_chunks_te3large_1536_bm25_v2"
    client = AsyncMock()
    client.collection_exists.return_value = True
    client.get_collection.return_value = _collection_info(payload_schema=_payload_schema())
    client.get_aliases.side_effect = [
        _aliases((COLLECTION_ALIAS, PHYSICAL_COLLECTION)),
        _aliases((COLLECTION_ALIAS, new_collection)),
    ]
    client.update_collection_aliases.return_value = True
    store = QdrantStore(client)

    result = await store.switch_alias(new_collection)

    assert result.changed is True
    assert result.previous_collection == PHYSICAL_COLLECTION
    assert result.current_collection == new_collection
    operations = client.update_collection_aliases.await_args.kwargs["change_aliases_operations"]
    assert isinstance(operations[0], models.DeleteAliasOperation)
    assert isinstance(operations[1], models.CreateAliasOperation)
    assert operations[1].create_alias.collection_name == new_collection
