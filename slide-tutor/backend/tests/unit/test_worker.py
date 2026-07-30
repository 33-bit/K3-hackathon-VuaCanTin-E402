from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from app.core.config import Settings
from app.ingestion import BlockKind, ParsedBlock, ParsedSlide
from app.worker import BackgroundWorker, _raw_slide_text


def test_raw_slide_text_removes_postgres_unsupported_null_bytes() -> None:
    slide = ParsedSlide(
        number=1,
        title="Intro\x00",
        blocks=(
            ParsedBlock(
                kind=BlockKind.PARAGRAPH,
                text="Customer\x00 outcome",
                reading_order=0,
            ),
        ),
    )

    assert _raw_slide_text(slide) == "Intro\n\nCustomer outcome"


@pytest.mark.asyncio
async def test_qdrant_outage_does_not_block_canonical_ingestion() -> None:
    qdrant = AsyncMock()
    qdrant.bootstrap.side_effect = RuntimeError("offline")
    worker = BackgroundWorker(
        settings=Settings(_env_file=None),
        qdrant=qdrant,
        openai=AsyncMock(),
    )
    worker._process_one_ingestion_job = AsyncMock(return_value=True)  # type: ignore[method-assign]
    worker._process_one_vector_event = AsyncMock(return_value=False)  # type: ignore[method-assign]

    assert await worker.run_once() is True
    qdrant.bootstrap.assert_not_awaited()
    worker._process_one_vector_event.assert_not_awaited()


@pytest.mark.asyncio
async def test_vector_queue_is_not_claimed_until_qdrant_bootstraps() -> None:
    qdrant = AsyncMock()
    qdrant.bootstrap.side_effect = RuntimeError("offline")
    worker = BackgroundWorker(
        settings=Settings(_env_file=None),
        qdrant=qdrant,
        openai=AsyncMock(),
    )
    worker._process_one_ingestion_job = AsyncMock(return_value=False)  # type: ignore[method-assign]
    worker._process_one_vector_event = AsyncMock(return_value=True)  # type: ignore[method-assign]

    assert await worker.run_once() is False
    qdrant.bootstrap.assert_awaited_once()
    worker._process_one_vector_event.assert_not_awaited()
