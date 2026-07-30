"""Qdrant-backed, rebuildable retrieval index for slide chunks.

PostgreSQL remains the source of truth.  This module deliberately keeps
canonical chunk text out of Qdrant payloads: ``embedding_text`` is submitted
only as a server-side BM25 ``Document`` and is never persisted as payload.
"""

from __future__ import annotations

import asyncio
import math
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol, TypeVar, runtime_checkable
from uuid import UUID

from qdrant_client import AsyncQdrantClient
from qdrant_client.http import models

from app.core.errors import (
    VectorIndexInconsistentError,
    VectorIndexUnavailableError,
)

COLLECTION_ALIAS = "slide_chunks"
PHYSICAL_COLLECTION = "slide_chunks_te3large_1536_bm25_v1"
DENSE_VECTOR_NAME = "dense_text"
SPARSE_VECTOR_NAME = "bm25_text"
DENSE_VECTOR_SIZE = 1536
BM25_MODEL = "qdrant/bm25"
BM25_OPTIONS: Mapping[str, object] = {
    "language": "none",
    "tokenizer": "multilingual",
    "ascii_folding": False,
}
DEFAULT_UPSERT_BATCH_SIZE = 64
DEFAULT_PREFETCH_LIMIT = 20
DEFAULT_FUSED_LIMIT = 12

# Only the fields needed to hydrate and validate canonical PostgreSQL chunks.
# In particular, neither ``text`` nor ``embedding_text`` belongs here.
SEARCH_PAYLOAD_FIELDS: tuple[str, ...] = (
    "chunk_id",
    "course_id",
    "deck_id",
    "deck_version_id",
    "slide_id",
    "slide_number",
    "chunk_type",
    "section",
    "content_hash",
    "embedding_version",
    "retrieval_schema_version",
)
MANIFEST_PAYLOAD_FIELDS: tuple[str, ...] = ("chunk_id", "content_hash")


class QdrantStoreError(RuntimeError):
    """Base class for typed vector-store failures."""


class QdrantValidationError(QdrantStoreError, ValueError):
    """Caller supplied an invalid point, vector, or scope."""


class QdrantUnavailableError(VectorIndexUnavailableError, QdrantStoreError):
    """The Qdrant service could not complete an operation."""


class QdrantIndexInconsistentError(
    VectorIndexInconsistentError,
    QdrantStoreError,
):
    """Stored point identity/payload cannot be reconciled with PostgreSQL."""


class QdrantSchemaMismatchError(QdrantIndexInconsistentError):
    """The active collection does not match the retrieval schema."""


class QdrantAliasConflictError(QdrantSchemaMismatchError):
    """The logical alias unexpectedly targets another physical collection."""


@runtime_checkable
class AsyncQdrantClientProtocol(Protocol):
    """Subset of ``AsyncQdrantClient`` used by the adapter."""

    async def collection_exists(self, collection_name: str, **kwargs: Any) -> bool: ...

    async def create_collection(self, collection_name: str, **kwargs: Any) -> bool: ...

    async def get_collection(
        self, collection_name: str, **kwargs: Any
    ) -> models.CollectionInfo: ...

    async def create_payload_index(
        self,
        collection_name: str,
        field_name: str,
        field_schema: Any = None,
        **kwargs: Any,
    ) -> models.UpdateResult: ...

    async def get_aliases(self, **kwargs: Any) -> models.CollectionsAliasesResponse: ...

    async def update_collection_aliases(
        self,
        change_aliases_operations: Sequence[models.AliasOperations],
        **kwargs: Any,
    ) -> bool: ...

    async def upsert(
        self,
        collection_name: str,
        points: Sequence[models.PointStruct],
        **kwargs: Any,
    ) -> models.UpdateResult: ...

    async def query_points(self, collection_name: str, **kwargs: Any) -> models.QueryResponse: ...

    async def count(self, collection_name: str, **kwargs: Any) -> models.CountResult: ...

    async def scroll(
        self, collection_name: str, **kwargs: Any
    ) -> tuple[list[models.Record], int | str | UUID | None]: ...

    async def delete(
        self, collection_name: str, points_selector: Any, **kwargs: Any
    ) -> models.UpdateResult: ...

    async def close(self, **kwargs: Any) -> None: ...


@dataclass(frozen=True, slots=True)
class QdrantChunk:
    """A canonical chunk projection prepared for vector indexing."""

    point_id: UUID
    course_id: UUID
    deck_id: UUID
    deck_version_id: UUID
    slide_id: UUID
    slide_number: int
    chunk_type: str
    section: str
    content_hash: str
    embedding_version: str
    retrieval_schema_version: str
    embedding_text: str
    dense_vector: Sequence[float]

    def __post_init__(self) -> None:
        for field_name in (
            "point_id",
            "course_id",
            "deck_id",
            "deck_version_id",
            "slide_id",
        ):
            _as_uuid(getattr(self, field_name), field_name)
        if self.slide_number < 1:
            raise QdrantValidationError("slide_number must be positive")
        for field_name in (
            "chunk_type",
            "content_hash",
            "embedding_version",
            "retrieval_schema_version",
            "embedding_text",
        ):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value.strip():
                raise QdrantValidationError(f"{field_name} must not be blank")
        if not isinstance(self.section, str):
            raise QdrantValidationError("section must be a string")
        _validate_dense_vector(self.dense_vector)

    def payload(self) -> dict[str, str | int]:
        payload: dict[str, str | int] = {
            "chunk_id": str(self.point_id),
            "course_id": str(self.course_id),
            "deck_id": str(self.deck_id),
            "deck_version_id": str(self.deck_version_id),
            "slide_id": str(self.slide_id),
            "slide_number": self.slide_number,
            "chunk_type": self.chunk_type,
            "content_hash": self.content_hash,
            "embedding_version": self.embedding_version,
            "retrieval_schema_version": self.retrieval_schema_version,
        }
        if self.section:
            payload["section"] = self.section
        return payload


@dataclass(frozen=True, slots=True)
class QdrantCandidate:
    point_id: UUID
    chunk_id: UUID
    course_id: UUID
    deck_id: UUID
    deck_version_id: UUID
    slide_id: UUID
    slide_number: int
    chunk_type: str
    section: str
    content_hash: str
    embedding_version: str
    retrieval_schema_version: str
    score: float


@dataclass(frozen=True, slots=True)
class ManifestEntry:
    point_id: UUID
    chunk_id: UUID
    content_hash: str


@dataclass(frozen=True, slots=True)
class VectorManifest:
    deck_version_id: UUID
    exact_count: int
    entries: tuple[ManifestEntry, ...]

    @property
    def observed_count(self) -> int:
        return len(self.entries)

    @property
    def count_matches(self) -> bool:
        return self.exact_count == self.observed_count

    @property
    def hashes_by_chunk_id(self) -> dict[UUID, str]:
        return {entry.chunk_id: entry.content_hash for entry in self.entries}


@dataclass(frozen=True, slots=True)
class QdrantReadiness:
    ready: bool
    alias: str
    physical_collection: str
    status: str
    points_count: int


@dataclass(frozen=True, slots=True)
class AliasSwitchResult:
    alias: str
    previous_collection: str | None
    current_collection: str
    changed: bool


_T = TypeVar("_T")


class QdrantStore:
    """Typed async adapter around the Qdrant 1.18 Query API."""

    def __init__(
        self,
        client: AsyncQdrantClientProtocol,
        *,
        collection_alias: str = COLLECTION_ALIAS,
        physical_collection: str = PHYSICAL_COLLECTION,
        upsert_batch_size: int = DEFAULT_UPSERT_BATCH_SIZE,
        max_upsert_attempts: int = 5,
        retry_base_seconds: float = 0.25,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        if not collection_alias.strip() or not physical_collection.strip():
            raise QdrantValidationError("collection names must not be blank")
        if collection_alias == physical_collection:
            raise QdrantValidationError("logical alias and physical collection must differ")
        if not 1 <= upsert_batch_size <= DEFAULT_UPSERT_BATCH_SIZE:
            raise QdrantValidationError("upsert_batch_size must be between 1 and 64")
        if max_upsert_attempts < 1:
            raise QdrantValidationError("max_upsert_attempts must be positive")
        if retry_base_seconds < 0:
            raise QdrantValidationError("retry_base_seconds cannot be negative")

        self._client = client
        self.collection_alias = collection_alias
        self.physical_collection = physical_collection
        self.upsert_batch_size = upsert_batch_size
        self.max_upsert_attempts = max_upsert_attempts
        self.retry_base_seconds = retry_base_seconds
        self._sleep = sleep

    @classmethod
    def from_url(
        cls,
        url: str,
        *,
        api_key: str | None = None,
        timeout_seconds: float = 10.0,
        collection_alias: str = COLLECTION_ALIAS,
        physical_collection: str = PHYSICAL_COLLECTION,
        upsert_batch_size: int = DEFAULT_UPSERT_BATCH_SIZE,
    ) -> QdrantStore:
        """Build a remote client that forwards BM25 Documents to Qdrant.

        ``cloud_inference=True`` is the qdrant-client switch that prevents
        local FastEmbed interception.  It is also required when the Qdrant
        server itself performs the native ``qdrant/bm25`` inference.
        """

        if timeout_seconds <= 0:
            raise QdrantValidationError("timeout_seconds must be positive")
        client = AsyncQdrantClient(
            url=url,
            api_key=api_key,
            timeout=max(1, math.ceil(timeout_seconds)),
            cloud_inference=True,
        )
        return cls(
            client,
            collection_alias=collection_alias,
            physical_collection=physical_collection,
            upsert_batch_size=upsert_batch_size,
        )

    async def close(self) -> None:
        await self._call("close Qdrant client", self._client.close())

    async def bootstrap(self) -> QdrantReadiness:
        """Idempotently create and validate the v1 collection and alias."""

        alias_target = await self.get_alias_target()
        if alias_target is not None:
            await self._validate_collection_schema(
                alias_target,
                require_payload_indexes=False,
            )
            await self._ensure_payload_indexes(alias_target)
            return await self.validate_readiness()

        exists = await self._call(
            "check physical collection",
            self._client.collection_exists(self.physical_collection),
        )
        if not exists:
            created = await self._call(
                "create physical collection",
                self._client.create_collection(
                    collection_name=self.physical_collection,
                    vectors_config={
                        DENSE_VECTOR_NAME: models.VectorParams(
                            size=DENSE_VECTOR_SIZE,
                            distance=models.Distance.COSINE,
                        )
                    },
                    sparse_vectors_config={
                        SPARSE_VECTOR_NAME: models.SparseVectorParams(modifier=models.Modifier.IDF)
                    },
                    shard_number=1,
                    replication_factor=1,
                    quantization_config=None,
                    strict_mode_config=_strict_mode_config(),
                ),
            )
            if created is False:
                raise QdrantUnavailableError("Qdrant rejected collection creation")

        await self._validate_collection_schema(
            self.physical_collection, require_payload_indexes=False
        )
        await self._ensure_payload_indexes(self.physical_collection)
        await self._ensure_alias()
        return await self.validate_readiness()

    async def validate_readiness(self) -> QdrantReadiness:
        """Fail closed unless alias, schema, indexes, and collection status are valid."""

        alias_target = await self.get_alias_target()
        if alias_target is None:
            raise QdrantSchemaMismatchError(
                f"required Qdrant alias {self.collection_alias!r} is missing"
            )
        info = await self._validate_collection_schema(alias_target, require_payload_indexes=True)
        status = _enum_value(info.status)
        if status == models.CollectionStatus.RED.value:
            raise QdrantUnavailableError(
                f"Qdrant collection {alias_target!r} reports status {status!r}"
            )
        return QdrantReadiness(
            ready=True,
            alias=self.collection_alias,
            physical_collection=alias_target,
            status=status,
            points_count=int(info.points_count or 0),
        )

    async def upsert_chunks(
        self,
        chunks: Sequence[QdrantChunk],
        *,
        collection_name: str | None = None,
    ) -> int:
        """Upsert deterministic chunk points in batches, waiting for durability."""

        if not chunks:
            return 0
        target = collection_name or self.collection_alias
        for start in range(0, len(chunks), self.upsert_batch_size):
            batch = chunks[start : start + self.upsert_batch_size]
            points = [
                models.PointStruct(
                    id=chunk.point_id,
                    vector={
                        DENSE_VECTOR_NAME: [float(value) for value in chunk.dense_vector],
                        SPARSE_VECTOR_NAME: _bm25_document(chunk.embedding_text),
                    },
                    payload=chunk.payload(),
                )
                for chunk in batch
            ]
            await self._upsert_with_retry(target, points)
        return len(chunks)

    async def hybrid_query(
        self,
        *,
        query_text: str,
        dense_vector: Sequence[float],
        course_id: UUID,
        deck_id: UUID,
        deck_version_id: UUID,
        prefetch_limit: int = DEFAULT_PREFETCH_LIMIT,
        fused_limit: int = DEFAULT_FUSED_LIMIT,
    ) -> tuple[QdrantCandidate, ...]:
        """Run dense + native BM25 prefetches and fuse with equal-weight RRF."""

        if not query_text.strip():
            raise QdrantValidationError("query_text must not be blank")
        _validate_dense_vector(dense_vector)
        course_uuid = _as_uuid(course_id, "course_id")
        deck_uuid = _as_uuid(deck_id, "deck_id")
        version_uuid = _as_uuid(deck_version_id, "deck_version_id")
        if prefetch_limit < 1 or fused_limit < 1:
            raise QdrantValidationError("query limits must be positive")

        scope_filter = _scope_filter(course_uuid, deck_uuid, version_uuid)
        prefetches = [
            models.Prefetch(
                query=[float(value) for value in dense_vector],
                using=DENSE_VECTOR_NAME,
                filter=scope_filter,
                limit=prefetch_limit,
            ),
            models.Prefetch(
                query=_bm25_document(query_text),
                using=SPARSE_VECTOR_NAME,
                filter=scope_filter,
                limit=prefetch_limit,
            ),
        ]
        response = await self._call(
            "run hybrid retrieval",
            self._client.query_points(
                collection_name=self.collection_alias,
                prefetch=prefetches,
                query=models.FusionQuery(fusion=models.Fusion.RRF),
                query_filter=scope_filter,
                limit=fused_limit,
                with_payload=models.PayloadSelectorInclude(include=list(SEARCH_PAYLOAD_FIELDS)),
                with_vectors=False,
            ),
        )
        return tuple(
            _candidate_from_scored_point(
                point,
                expected_course_id=course_uuid,
                expected_deck_id=deck_uuid,
                expected_version_id=version_uuid,
            )
            for point in response.points
        )

    async def count_deck_version(
        self,
        deck_version_id: UUID,
        *,
        collection_name: str | None = None,
    ) -> int:
        version_uuid = _as_uuid(deck_version_id, "deck_version_id")
        response = await self._call(
            "count deck-version points",
            self._client.count(
                collection_name=collection_name or self.collection_alias,
                count_filter=_deck_version_filter(version_uuid),
                exact=True,
            ),
        )
        return int(response.count)

    async def scroll_manifest(
        self,
        deck_version_id: UUID,
        *,
        collection_name: str | None = None,
        page_size: int = 256,
    ) -> tuple[ManifestEntry, ...]:
        """Scroll all chunk IDs and hashes without loading vectors or canonical text."""

        version_uuid = _as_uuid(deck_version_id, "deck_version_id")
        if page_size < 1:
            raise QdrantValidationError("page_size must be positive")
        target = collection_name or self.collection_alias
        offset: int | str | UUID | None = None
        seen_offsets: set[str] = set()
        entries: list[ManifestEntry] = []
        seen_chunk_ids: set[UUID] = set()

        while True:
            records, next_offset = await self._call(
                "scroll deck-version manifest",
                self._client.scroll(
                    collection_name=target,
                    scroll_filter=_deck_version_filter(version_uuid),
                    limit=page_size,
                    offset=offset,
                    with_payload=models.PayloadSelectorInclude(
                        include=list(MANIFEST_PAYLOAD_FIELDS)
                    ),
                    with_vectors=False,
                ),
            )
            for record in records:
                entry = _manifest_entry_from_record(record)
                if entry.chunk_id in seen_chunk_ids:
                    raise QdrantIndexInconsistentError(
                        f"duplicate Qdrant chunk_id {entry.chunk_id}"
                    )
                seen_chunk_ids.add(entry.chunk_id)
                entries.append(entry)

            if next_offset is None:
                break
            offset_key = str(next_offset)
            if offset_key in seen_offsets:
                raise QdrantIndexInconsistentError(
                    "Qdrant scroll returned a repeated pagination offset"
                )
            seen_offsets.add(offset_key)
            offset = next_offset

        return tuple(entries)

    async def read_manifest(
        self,
        deck_version_id: UUID,
        *,
        collection_name: str | None = None,
        page_size: int = 256,
    ) -> VectorManifest:
        version_uuid = _as_uuid(deck_version_id, "deck_version_id")
        exact_count = await self.count_deck_version(version_uuid, collection_name=collection_name)
        entries = await self.scroll_manifest(
            version_uuid,
            collection_name=collection_name,
            page_size=page_size,
        )
        return VectorManifest(
            deck_version_id=version_uuid,
            exact_count=exact_count,
            entries=entries,
        )

    async def delete_deck_version(
        self,
        deck_version_id: UUID,
        *,
        collection_name: str | None = None,
    ) -> None:
        """Delete only points belonging to one exact immutable deck version."""

        version_uuid = _as_uuid(deck_version_id, "deck_version_id")
        await self._call(
            "delete deck-version points",
            self._client.delete(
                collection_name=collection_name or self.collection_alias,
                points_selector=models.FilterSelector(filter=_deck_version_filter(version_uuid)),
                wait=True,
            ),
        )

    async def get_alias_target(self) -> str | None:
        aliases = await self._call("list Qdrant aliases", self._client.get_aliases())
        targets = {
            item.collection_name
            for item in aliases.aliases
            if item.alias_name == self.collection_alias
        }
        if len(targets) > 1:
            raise QdrantSchemaMismatchError(f"alias {self.collection_alias!r} has multiple targets")
        return next(iter(targets), None)

    async def switch_alias(self, new_collection: str) -> AliasSwitchResult:
        """Atomically switch the logical alias after validating a rebuilt collection."""

        if not new_collection.strip() or new_collection == self.collection_alias:
            raise QdrantValidationError("new_collection must be a physical collection name")
        exists = await self._call(
            "check alias target collection",
            self._client.collection_exists(new_collection),
        )
        if not exists:
            raise QdrantSchemaMismatchError(
                f"alias target collection {new_collection!r} does not exist"
            )
        await self._validate_collection_schema(new_collection, require_payload_indexes=True)

        previous = await self.get_alias_target()
        if previous == new_collection:
            self.physical_collection = new_collection
            return AliasSwitchResult(
                alias=self.collection_alias,
                previous_collection=previous,
                current_collection=new_collection,
                changed=False,
            )

        operations: list[models.AliasOperations] = []
        if previous is not None:
            operations.append(
                models.DeleteAliasOperation(
                    delete_alias=models.DeleteAlias(alias_name=self.collection_alias)
                )
            )
        operations.append(
            models.CreateAliasOperation(
                create_alias=models.CreateAlias(
                    collection_name=new_collection,
                    alias_name=self.collection_alias,
                )
            )
        )
        changed = await self._call(
            "atomically switch Qdrant alias",
            self._client.update_collection_aliases(change_aliases_operations=operations),
        )
        if changed is False:
            raise QdrantUnavailableError("Qdrant rejected the alias switch")

        current = await self.get_alias_target()
        if current != new_collection:
            raise QdrantAliasConflictError(
                f"alias switch verification failed: expected {new_collection!r}, found {current!r}"
            )
        self.physical_collection = new_collection
        return AliasSwitchResult(
            alias=self.collection_alias,
            previous_collection=previous,
            current_collection=current,
            changed=True,
        )

    async def _ensure_payload_indexes(self, collection_name: str) -> None:
        info = await self._get_collection(collection_name)
        for field_name, field_schema in _payload_index_definitions().items():
            existing = info.payload_schema.get(field_name)
            if existing is not None:
                _validate_payload_index(field_name, existing, field_schema)
                continue
            await self._call(
                f"create payload index {field_name}",
                self._client.create_payload_index(
                    collection_name=collection_name,
                    field_name=field_name,
                    field_schema=field_schema,
                    wait=True,
                ),
            )

    async def _ensure_alias(self) -> None:
        target = await self.get_alias_target()
        if target is None:
            created = await self._call(
                "create Qdrant collection alias",
                self._client.update_collection_aliases(
                    change_aliases_operations=[
                        models.CreateAliasOperation(
                            create_alias=models.CreateAlias(
                                collection_name=self.physical_collection,
                                alias_name=self.collection_alias,
                            )
                        )
                    ]
                ),
            )
            if created is False:
                raise QdrantUnavailableError("Qdrant rejected alias creation")
            return
        if target != self.physical_collection:
            raise QdrantAliasConflictError(
                f"alias {self.collection_alias!r} already points to {target!r}"
            )

    async def _validate_collection_schema(
        self,
        collection_name: str,
        *,
        require_payload_indexes: bool,
    ) -> models.CollectionInfo:
        info = await self._get_collection(collection_name)
        errors: list[str] = []
        params = info.config.params

        vectors = params.vectors
        if not isinstance(vectors, dict) or set(vectors) != {DENSE_VECTOR_NAME}:
            errors.append(f"dense vectors must contain only {DENSE_VECTOR_NAME!r}")
        else:
            dense = vectors[DENSE_VECTOR_NAME]
            if dense.size != DENSE_VECTOR_SIZE:
                errors.append(
                    f"{DENSE_VECTOR_NAME} size is {dense.size}, expected {DENSE_VECTOR_SIZE}"
                )
            if _enum_value(dense.distance) != _enum_value(models.Distance.COSINE):
                errors.append(f"{DENSE_VECTOR_NAME} distance must be cosine")

        sparse_vectors = params.sparse_vectors
        if not isinstance(sparse_vectors, dict) or set(sparse_vectors) != {SPARSE_VECTOR_NAME}:
            errors.append(f"sparse vectors must contain only {SPARSE_VECTOR_NAME!r}")
        else:
            sparse = sparse_vectors[SPARSE_VECTOR_NAME]
            if _enum_value(sparse.modifier) != _enum_value(models.Modifier.IDF):
                errors.append(f"{SPARSE_VECTOR_NAME} modifier must be idf")

        if params.shard_number != 1:
            errors.append("collection must use exactly one shard")
        if params.replication_factor != 1:
            errors.append("collection must use replication_factor=1")
        if info.config.quantization_config is not None:
            errors.append("quantization must be disabled for the MVP collection")

        strict = info.config.strict_mode_config
        if strict is None or strict.enabled is not True:
            errors.append("strict mode must be enabled")
        else:
            if strict.unindexed_filtering_retrieve is not False:
                errors.append("strict mode must reject unindexed retrieval filters")
            if strict.unindexed_filtering_update is not False:
                errors.append("strict mode must reject unindexed update filters")

        if require_payload_indexes:
            for field_name, expected in _payload_index_definitions().items():
                actual = info.payload_schema.get(field_name)
                if actual is None:
                    errors.append(f"payload index {field_name!r} is missing")
                    continue
                try:
                    _validate_payload_index(field_name, actual, expected)
                except QdrantSchemaMismatchError as exc:
                    errors.append(str(exc))

        if errors:
            raise QdrantSchemaMismatchError(
                f"Qdrant collection {collection_name!r} schema mismatch: " + "; ".join(errors)
            )
        return info

    async def _get_collection(self, collection_name: str) -> models.CollectionInfo:
        return await self._call(
            f"inspect collection {collection_name!r}",
            self._client.get_collection(collection_name),
        )

    async def _upsert_with_retry(
        self,
        collection_name: str,
        points: Sequence[models.PointStruct],
    ) -> None:
        last_error: Exception | None = None
        for attempt in range(1, self.max_upsert_attempts + 1):
            try:
                await self._client.upsert(
                    collection_name=collection_name,
                    points=points,
                    wait=True,
                )
                return
            except Exception as exc:  # client exceptions vary by HTTP/gRPC transport
                last_error = exc
                if attempt == self.max_upsert_attempts:
                    break
                delay = self.retry_base_seconds * (2 ** (attempt - 1))
                if delay:
                    await self._sleep(delay)
        raise QdrantUnavailableError(
            f"upsert failed after {self.max_upsert_attempts} attempts"
        ) from last_error

    @staticmethod
    async def _call(operation: str, call: Awaitable[_T]) -> _T:
        try:
            return await call
        except QdrantStoreError:
            raise
        except Exception as exc:
            raise QdrantUnavailableError(f"Failed to {operation}") from exc


def _strict_mode_config() -> models.StrictModeConfig:
    return models.StrictModeConfig(
        enabled=True,
        unindexed_filtering_retrieve=False,
        unindexed_filtering_update=False,
        upsert_max_batchsize=DEFAULT_UPSERT_BATCH_SIZE,
    )


def _payload_index_definitions() -> dict[str, Any]:
    return {
        "deck_id": models.KeywordIndexParams(
            type=models.KeywordIndexType.KEYWORD,
            is_tenant=True,
        ),
        "chunk_id": models.UuidIndexParams(type=models.UuidIndexType.UUID),
        "course_id": models.UuidIndexParams(type=models.UuidIndexType.UUID),
        "deck_version_id": models.UuidIndexParams(type=models.UuidIndexType.UUID),
        "slide_id": models.UuidIndexParams(type=models.UuidIndexType.UUID),
        "slide_number": models.IntegerIndexParams(type=models.IntegerIndexType.INTEGER),
        "chunk_type": models.KeywordIndexParams(type=models.KeywordIndexType.KEYWORD),
        "section": models.KeywordIndexParams(type=models.KeywordIndexType.KEYWORD),
    }


def _validate_payload_index(
    field_name: str,
    actual: models.PayloadIndexInfo,
    expected: Any,
) -> None:
    expected_type = _enum_value(expected.type)
    if _enum_value(actual.data_type) != expected_type:
        raise QdrantSchemaMismatchError(
            f"payload index {field_name!r} has type "
            f"{_enum_value(actual.data_type)!r}, expected {expected_type!r}"
        )
    if field_name == "deck_id":
        is_tenant = getattr(actual.params, "is_tenant", None)
        if is_tenant is not True:
            raise QdrantSchemaMismatchError("payload index 'deck_id' must set is_tenant=true")


def _scope_filter(
    course_id: UUID,
    deck_id: UUID,
    deck_version_id: UUID,
) -> models.Filter:
    return models.Filter(
        must=[
            _match_condition("course_id", course_id),
            _match_condition("deck_id", deck_id),
            _match_condition("deck_version_id", deck_version_id),
        ]
    )


def _deck_version_filter(deck_version_id: UUID) -> models.Filter:
    return models.Filter(must=[_match_condition("deck_version_id", deck_version_id)])


def _match_condition(key: str, value: UUID) -> models.FieldCondition:
    return models.FieldCondition(
        key=key,
        match=models.MatchValue(value=str(value)),
    )


def _bm25_document(text: str) -> models.Document:
    return models.Document(
        text=text,
        model=BM25_MODEL,
        options=dict(BM25_OPTIONS),
    )


def _candidate_from_scored_point(
    point: models.ScoredPoint,
    *,
    expected_course_id: UUID,
    expected_deck_id: UUID,
    expected_version_id: UUID,
) -> QdrantCandidate:
    payload = point.payload
    if payload is None:
        raise QdrantIndexInconsistentError(f"Qdrant point {point.id!r} has no payload")

    point_id = _as_uuid(point.id, "point.id", QdrantIndexInconsistentError)
    chunk_id = _payload_uuid(payload, "chunk_id")
    course_id = _payload_uuid(payload, "course_id")
    deck_id = _payload_uuid(payload, "deck_id")
    version_id = _payload_uuid(payload, "deck_version_id")
    slide_id = _payload_uuid(payload, "slide_id")
    if point_id != chunk_id:
        raise QdrantIndexInconsistentError(
            f"Qdrant point id {point_id} differs from payload chunk_id {chunk_id}"
        )
    if course_id != expected_course_id:
        raise QdrantIndexInconsistentError(
            f"Qdrant returned course {course_id}, expected {expected_course_id}"
        )
    if deck_id != expected_deck_id:
        raise QdrantIndexInconsistentError(
            f"Qdrant returned deck {deck_id}, expected {expected_deck_id}"
        )
    if version_id != expected_version_id:
        raise QdrantIndexInconsistentError(
            f"Qdrant returned deck version {version_id}, expected {expected_version_id}"
        )

    slide_number = payload.get("slide_number")
    if isinstance(slide_number, bool) or not isinstance(slide_number, int) or slide_number < 1:
        raise QdrantIndexInconsistentError(f"Qdrant point {point_id} has invalid slide_number")
    score = float(point.score)
    if not math.isfinite(score):
        raise QdrantIndexInconsistentError(f"Qdrant point {point_id} has a non-finite score")

    return QdrantCandidate(
        point_id=point_id,
        chunk_id=chunk_id,
        course_id=course_id,
        deck_id=deck_id,
        deck_version_id=version_id,
        slide_id=slide_id,
        slide_number=slide_number,
        chunk_type=_payload_string(payload, "chunk_type"),
        section=_payload_string(payload, "section", required=False),
        content_hash=_payload_string(payload, "content_hash"),
        embedding_version=_payload_string(payload, "embedding_version"),
        retrieval_schema_version=_payload_string(payload, "retrieval_schema_version"),
        score=score,
    )


def _manifest_entry_from_record(record: models.Record) -> ManifestEntry:
    payload = record.payload
    if payload is None:
        raise QdrantIndexInconsistentError(f"Qdrant manifest point {record.id!r} has no payload")
    point_id = _as_uuid(record.id, "point.id", QdrantIndexInconsistentError)
    chunk_id = _payload_uuid(payload, "chunk_id")
    if point_id != chunk_id:
        raise QdrantIndexInconsistentError(
            f"Qdrant point id {point_id} differs from payload chunk_id {chunk_id}"
        )
    return ManifestEntry(
        point_id=point_id,
        chunk_id=chunk_id,
        content_hash=_payload_string(payload, "content_hash"),
    )


def _payload_uuid(payload: Mapping[str, Any], key: str) -> UUID:
    if key not in payload:
        raise QdrantIndexInconsistentError(f"Qdrant payload is missing {key!r}")
    return _as_uuid(payload[key], key, QdrantIndexInconsistentError)


def _payload_string(
    payload: Mapping[str, Any],
    key: str,
    *,
    required: bool = True,
) -> str:
    value = payload.get(key)
    if value is None and not required:
        return ""
    if not isinstance(value, str) or (required and not value.strip()):
        raise QdrantIndexInconsistentError(
            f"Qdrant payload field {key!r} must be a non-empty string"
        )
    return value


def _validate_dense_vector(vector: Sequence[float]) -> None:
    if isinstance(vector, (str, bytes)):
        raise QdrantValidationError("dense vector must be a numeric sequence")
    if len(vector) != DENSE_VECTOR_SIZE:
        raise QdrantValidationError(
            f"dense vector has {len(vector)} dimensions, expected {DENSE_VECTOR_SIZE}"
        )
    try:
        values = (float(value) for value in vector)
        if not all(math.isfinite(value) for value in values):
            raise QdrantValidationError("dense vector contains a non-finite value")
    except (TypeError, ValueError) as exc:
        raise QdrantValidationError("dense vector must contain only numbers") from exc


def _as_uuid(
    value: object,
    field_name: str,
    error_type: type[QdrantStoreError] = QdrantValidationError,
) -> UUID:
    try:
        return value if isinstance(value, UUID) else UUID(str(value))
    except (TypeError, ValueError, AttributeError) as exc:
        raise error_type(f"{field_name} must be a valid UUID") from exc


def _enum_value(value: object) -> str:
    enum_value = getattr(value, "value", value)
    return str(enum_value).lower()
