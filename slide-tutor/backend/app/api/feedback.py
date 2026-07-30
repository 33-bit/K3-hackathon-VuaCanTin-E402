from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import repositories
from app.db.session import get_session
from app.models import FeedbackRequest, FeedbackResponse

from .dependencies import get_current_user_id

router = APIRouter(prefix="/chat/feedback", tags=["feedback"])


@router.post("", response_model=FeedbackResponse, status_code=status.HTTP_201_CREATED)
async def submit_feedback(
    request: FeedbackRequest,
    user_id: UUID = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_session),
) -> FeedbackResponse:
    feedback = await repositories.create_feedback(
        session,
        message_id=request.message_id,
        user_id=user_id,
        rating=request.rating,
        reason=request.reason,
        comment=request.comment,
    )
    await session.commit()
    return FeedbackResponse(feedback_id=feedback.id)
