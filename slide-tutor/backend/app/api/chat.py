from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.chat.service import ChatService
from app.db.session import get_session
from app.models import ChatRequest, ChatResponse
from app.runtime import get_chat_service

from .dependencies import get_current_user_id

router = APIRouter(prefix="/chat", tags=["chat"])


@router.post("/answer", response_model=ChatResponse)
async def answer_question(
    request: ChatRequest,
    user_id: UUID = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_session),
    service: ChatService = Depends(get_chat_service),
) -> ChatResponse:
    return await service.answer(session=session, user_id=user_id, request=request)
