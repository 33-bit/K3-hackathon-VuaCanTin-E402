from __future__ import annotations

from functools import lru_cache

from app.chat.service import ChatService
from app.core.config import get_settings
from app.retrieval.service import RetrievalService
from app.services.openai_service import OpenAIService, get_openai_service
from app.services.qdrant_store import QdrantStore


@lru_cache(maxsize=1)
def get_qdrant_store() -> QdrantStore:
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


def get_chat_service() -> ChatService:
    settings = get_settings()
    llm: OpenAIService = get_openai_service()
    vector_store = get_qdrant_store()
    retrieval = RetrievalService(
        settings=settings,
        llm=llm,
        vector_store=vector_store,
    )
    return ChatService(settings=settings, llm=llm, retrieval=retrieval)
