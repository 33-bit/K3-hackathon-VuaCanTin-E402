from __future__ import annotations

from pathlib import Path
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, File, Form, UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.errors import DeckNotReadyError
from app.db import repositories
from app.db.models import SlideBlock
from app.db.session import get_session
from app.models import (
    DeckAcceptedResponse,
    DeckStatusResponse,
    SlideBlockResponse,
    SlideResponse,
    SlidesResponse,
)
from app.services.file_storage import LocalFileStorage, get_file_storage

from .dependencies import get_current_user_id

router = APIRouter(prefix="/decks", tags=["decks"])


@router.post("", response_model=DeckAcceptedResponse, status_code=status.HTTP_202_ACCEPTED)
async def upload_deck(
    course_id: Annotated[UUID, Form()],
    file: Annotated[UploadFile, File()],
    title: Annotated[str | None, Form(max_length=500)] = None,
    user_id: UUID = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
    storage: LocalFileStorage = Depends(get_file_storage),
) -> DeckAcceptedResponse:
    original_filename = file.filename or "Untitled deck"
    await repositories.require_course_access(
        session,
        course_id=course_id,
        user_id=user_id,
        write=True,
    )
    await session.commit()
    deck_id = uuid4()
    deck_version_id = uuid4()
    stored = await storage.save_upload(
        file=file,
        deck_id=deck_id,
        deck_version_id=deck_version_id,
    )
    try:
        # Permission is canonical PostgreSQL state and may have changed while
        # the file was being streamed, so recheck inside the write transaction.
        await repositories.require_course_access(
            session,
            course_id=course_id,
            user_id=user_id,
            write=True,
        )
        _, version, _ = await repositories.create_deck_version(
            session,
            deck_id=deck_id,
            deck_version_id=deck_version_id,
            course_id=course_id,
            title=(title or Path(original_filename).stem).strip() or "Untitled deck",
            source_file_path=str(stored.path),
            source_type=stored.source_type,
            content_hash=stored.content_hash,
            settings=settings,
        )
        await session.commit()
    except Exception:
        await session.rollback()
        stored.path.unlink(missing_ok=True)
        raise
    return DeckAcceptedResponse(
        deck_id=deck_id,
        deck_version_id=version.id,
        status_url=f"{settings.api_prefix}/decks/{deck_id}/status",
    )


@router.get("/{deck_id}/status", response_model=DeckStatusResponse)
async def deck_status(
    deck_id: UUID,
    user_id: UUID = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_session),
) -> DeckStatusResponse:
    deck = await repositories.require_deck_access(session, deck_id=deck_id, user_id=user_id)
    version = await repositories.get_latest_deck_version(session, deck_id=deck_id)
    return DeckStatusResponse(
        deck_id=deck.id,
        deck_version_id=version.id,
        active_version_id=deck.active_version_id,
        status=version.status,
        stage=version.stage,
        slide_count=version.slide_count,
        textless_slide_count=version.textless_slide_count,
        expected_chunk_count=version.expected_chunk_count,
        indexed_chunk_count=version.indexed_chunk_count,
        index_status=version.index_status,
        error_code=version.error_code,
        error_detail=version.error_detail,
        created_at=version.created_at,
        ready_at=version.ready_at,
    )


@router.post(
    "/{deck_id}/reindex",
    response_model=DeckAcceptedResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def reindex_deck(
    deck_id: UUID,
    user_id: UUID = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> DeckAcceptedResponse:
    deck = await repositories.require_deck_access(
        session,
        deck_id=deck_id,
        user_id=user_id,
        write=True,
    )
    latest = await repositories.get_latest_deck_version(session, deck_id=deck_id)
    new_version_id = uuid4()
    _, version, _ = await repositories.create_deck_version(
        session,
        deck_id=deck.id,
        deck_version_id=new_version_id,
        course_id=deck.course_id,
        title=deck.title,
        source_file_path=latest.source_file_path,
        source_type=latest.source_type,
        content_hash=latest.content_hash,
        settings=settings,
        existing_deck=deck,
    )
    await session.commit()
    return DeckAcceptedResponse(
        deck_id=deck.id,
        deck_version_id=version.id,
        status_url=f"{settings.api_prefix}/decks/{deck.id}/status",
    )


@router.get("/{deck_id}/slides", response_model=SlidesResponse)
async def list_slides(
    deck_id: UUID,
    user_id: UUID = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_session),
) -> SlidesResponse:
    context = await repositories.get_active_deck_context(session, deck_id=deck_id, user_id=user_id)
    if context is None:
        raise DeckNotReadyError()
    slides = await repositories.get_slides_for_version(session, deck_version_id=context.version.id)
    slide_ids = [slide.id for slide in slides]
    blocks = list(
        (
            await session.scalars(
                select(SlideBlock)
                .where(SlideBlock.slide_id.in_(slide_ids))
                .order_by(SlideBlock.slide_id, SlideBlock.reading_order)
            )
        ).all()
    )
    blocks_by_slide: dict[UUID, list[SlideBlockResponse]] = {}
    for block in blocks:
        blocks_by_slide.setdefault(block.slide_id, []).append(
            SlideBlockResponse.model_validate(block)
        )
    return SlidesResponse(
        deck_id=deck_id,
        deck_version_id=context.version.id,
        slides=[
            SlideResponse(
                id=slide.id,
                slide_number=slide.slide_number,
                title=slide.title,
                section=slide.section,
                normalized_text=slide.normalized_text,
                blocks=blocks_by_slide.get(slide.id, []),
            )
            for slide in slides
        ],
    )
