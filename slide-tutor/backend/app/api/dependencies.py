from __future__ import annotations

import secrets
from typing import Annotated
from uuid import UUID

from fastapi import Header, HTTPException

from app.core.config import get_settings


def get_current_user_id(
    x_user_id: Annotated[str | None, Header(alias="X-User-Id")] = None,
    x_auth_proxy_secret: Annotated[
        str | None,
        Header(alias="X-Auth-Proxy-Secret"),
    ] = None,
) -> UUID:
    settings = get_settings()
    if not settings.is_development:
        configured_secret = settings.auth_proxy_shared_secret
        secret_value = (
            configured_secret.get_secret_value() if configured_secret is not None else ""
        ).strip()
        if not secret_value:
            raise HTTPException(status_code=503, detail="Authentication proxy is not configured")
        if x_auth_proxy_secret is None or not secrets.compare_digest(
            x_auth_proxy_secret,
            secret_value,
        ):
            raise HTTPException(status_code=401, detail="Invalid authentication proxy credentials")
    if not x_user_id:
        if settings.is_development:
            return settings.dev_user_id
        raise HTTPException(status_code=401, detail="X-User-Id is required")
    try:
        return UUID(x_user_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="X-User-Id must be a UUID") from exc
