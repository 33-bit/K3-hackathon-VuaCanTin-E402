from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFoundError
from app.db import repositories
from app.db.models import RetrievalRun
from app.db.session import get_session
from app.models import RetrievalDebugResponse

from .dependencies import get_current_user_id

router = APIRouter(prefix="/debug/retrieval", tags=["debug"])


@router.get("/{retrieval_debug_id}", response_model=RetrievalDebugResponse)
async def retrieval_debug(
    retrieval_debug_id: UUID,
    user_id: UUID = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_session),
) -> RetrievalDebugResponse:
    run = await session.get(RetrievalRun, retrieval_debug_id)
    if run is None or run.user_id != user_id:
        raise NotFoundError("Retrieval run not found")
    await repositories.require_deck_access(
        session,
        deck_id=run.deck_id,
        user_id=user_id,
    )
    return RetrievalDebugResponse(
        retrieval_debug_id=run.id,
        deck_id=run.deck_id,
        deck_version_id=run.deck_version_id,
        original_query=run.original_query,
        rewritten_query=run.rewritten_query,
        selected_text_match=run.selected_text_match,
        filters=run.filters_json,
        candidates=run.candidates_json,
        final_chunk_ids=run.final_chunk_ids,
        timings_ms=run.timings_json,
        model_versions=run.model_config_json,
        inconsistency=run.inconsistency_json,
        created_at=run.created_at,
    )
