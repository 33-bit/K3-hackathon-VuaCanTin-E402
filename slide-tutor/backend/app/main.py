from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from uuid import uuid4

import structlog
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError
from structlog.contextvars import bind_contextvars, clear_contextvars

from app.api import chat, debug, decks, feedback, system
from app.core.config import get_settings
from app.core.errors import AppError
from app.core.logging import configure_logging
from app.db import repositories
from app.db.base import Base
from app.db.session import get_engine, get_session_factory
from app.models import ErrorBody, ErrorResponse
from app.runtime import get_qdrant_store
from app.services.redis_service import get_redis

settings = get_settings()
configure_logging(settings.log_level)
logger = structlog.get_logger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    settings.ensure_runtime_directories()
    if settings.auto_create_schema:
        async with get_engine().begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
    if settings.is_development:
        try:
            async with get_session_factory()() as session:
                async with session.begin():
                    await repositories.create_development_course(
                        session,
                        user_id=settings.dev_user_id,
                        course_id=settings.dev_course_id,
                    )
        except SQLAlchemyError as exc:
            logger.warning("development_course_bootstrap_failed", error=str(exc))
    yield
    if get_qdrant_store.cache_info().currsize:
        await get_qdrant_store().close()
    await get_redis().aclose()
    await get_engine().dispose()


app = FastAPI(
    title=settings.app_name,
    version="1.0.0",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def request_context(request: Request, call_next):  # type: ignore[no-untyped-def]
    request_id = request.headers.get("X-Request-Id") or uuid4().hex
    clear_contextvars()
    bind_contextvars(request_id=request_id, path=request.url.path)
    request.state.request_id = request_id
    response = await call_next(request)
    response.headers["X-Request-Id"] = request_id
    clear_contextvars()
    return response


@app.exception_handler(AppError)
async def handle_app_error(request: Request, exc: AppError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content=ErrorResponse(
            error=ErrorBody(
                code=exc.code,
                message=exc.message,
                details=exc.details,
                request_id=getattr(request.state, "request_id", None),
            )
        ).model_dump(mode="json"),
    )


@app.exception_handler(SQLAlchemyError)
async def handle_database_error(request: Request, exc: SQLAlchemyError) -> JSONResponse:
    logger.exception("database_error", error=str(exc))
    return JSONResponse(
        status_code=503,
        content=ErrorResponse(
            error=ErrorBody(
                code="database_unavailable",
                message="The canonical database is unavailable",
                request_id=getattr(request.state, "request_id", None),
            )
        ).model_dump(mode="json"),
    )


@app.get("/")
async def root() -> dict[str, str]:
    return {
        "service": settings.app_name,
        "docs": "/docs",
        "health": f"{settings.api_prefix}/health",
        "readiness": f"{settings.api_prefix}/ready",
    }


app.include_router(system.router, prefix=settings.api_prefix)
app.include_router(decks.router, prefix=settings.api_prefix)
app.include_router(chat.router, prefix=settings.api_prefix)
app.include_router(feedback.router, prefix=settings.api_prefix)
app.include_router(debug.router, prefix=settings.api_prefix)
