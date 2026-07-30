from __future__ import annotations

from uuid import UUID

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.api import dependencies
from app.core.config import Settings
from app.main import app
from app.models import ChatRequest


def test_openapi_contains_the_backend_contract() -> None:
    paths = app.openapi()["paths"]

    assert {
        "/api/decks",
        "/api/decks/{deck_id}/status",
        "/api/decks/{deck_id}/reindex",
        "/api/decks/{deck_id}/slides",
        "/api/chat/answer",
        "/api/chat/feedback",
        "/api/debug/retrieval/{retrieval_debug_id}",
        "/api/health",
        "/api/ready",
    }.issubset(paths)


def test_cors_origins_accept_csv_environment_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CORS_ORIGINS", "https://one.example, https://two.example")

    settings = Settings(_env_file=None)

    assert settings.cors_origins == [
        "https://one.example",
        "https://two.example",
    ]


def test_v1_collection_rejects_an_incompatible_embedding_model() -> None:
    with pytest.raises(ValidationError, match="text-embedding-3-large"):
        Settings(
            _env_file=None,
            openai_embedding_model="text-embedding-3-small",
        )


def test_production_identity_requires_the_trusted_proxy_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user_id = UUID("00000000-0000-0000-0000-000000000099")
    settings = Settings(
        _env_file=None,
        app_env="production",
        auth_proxy_shared_secret="server-side-secret",
    )
    monkeypatch.setattr(dependencies, "get_settings", lambda: settings)

    assert (
        dependencies.get_current_user_id(
            str(user_id),
            "server-side-secret",
        )
        == user_id
    )
    with pytest.raises(HTTPException) as error:
        dependencies.get_current_user_id(str(user_id), "wrong")
    assert error.value.status_code == 401


def test_blank_production_proxy_secret_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings(
        _env_file=None,
        app_env="production",
        auth_proxy_shared_secret=" ",
    )
    monkeypatch.setattr(dependencies, "get_settings", lambda: settings)

    with pytest.raises(HTTPException) as error:
        dependencies.get_current_user_id(
            "00000000-0000-0000-0000-000000000099",
            "",
        )
    assert error.value.status_code == 503


def test_chat_question_rejects_whitespace_only_input() -> None:
    with pytest.raises(ValidationError, match="question must not be blank"):
        ChatRequest(
            course_id=UUID(int=1),
            deck_id=UUID(int=2),
            current_slide_id=UUID(int=3),
            question="   ",
        )
