from __future__ import annotations

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session
from app.models import DependencyStatus, HealthResponse, ReadinessResponse
from app.runtime import get_qdrant_store
from app.services.qdrant_store import QdrantStore
from app.services.redis_service import get_redis

router = APIRouter(tags=["system"])


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse()


@router.get(
    "/ready",
    response_model=ReadinessResponse,
    responses={503: {"model": ReadinessResponse}},
)
async def readiness(
    response: Response,
    session: AsyncSession = Depends(get_session),
    qdrant: QdrantStore = Depends(get_qdrant_store),
) -> ReadinessResponse:
    dependencies: dict[str, DependencyStatus] = {}
    try:
        await session.execute(text("SELECT 1"))
        dependencies["postgresql"] = DependencyStatus(status="ok")
    except Exception as exc:
        dependencies["postgresql"] = DependencyStatus(status="error", detail=_safe_detail(exc))
    try:
        await get_redis().ping()
        dependencies["redis"] = DependencyStatus(status="ok")
    except Exception as exc:
        dependencies["redis"] = DependencyStatus(status="error", detail=_safe_detail(exc))
    try:
        readiness_result = await qdrant.validate_readiness()
        dependencies["qdrant"] = DependencyStatus(
            status="ok" if readiness_result.ready else "error"
        )
    except Exception as exc:
        dependencies["qdrant"] = DependencyStatus(status="error", detail=_safe_detail(exc))

    ready = all(item.status == "ok" for item in dependencies.values())
    if not ready:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return ReadinessResponse(
        status="ready" if ready else "not_ready",
        dependencies=dependencies,
    )


def _safe_detail(exc: Exception) -> str:
    return exc.__class__.__name__
