from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from fastapi import UploadFile

from app.core.config import Settings, get_settings
from app.core.errors import InvalidUploadError


@dataclass(slots=True)
class StoredFile:
    path: Path
    source_type: str
    content_hash: str
    size_bytes: int


class LocalFileStorage:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def save_upload(
        self,
        *,
        file: UploadFile,
        deck_id: UUID,
        deck_version_id: UUID,
    ) -> StoredFile:
        suffix = Path(file.filename or "").suffix.lower()
        if suffix not in self.settings.allowed_upload_extensions:
            allowed = ", ".join(sorted(self.settings.allowed_upload_extensions))
            raise InvalidUploadError(f"Only {allowed} files are accepted")

        target_dir = self.settings.upload_dir.resolve() / str(deck_id) / str(deck_version_id)
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / f"source{suffix}"
        temporary = target.with_suffix(f"{suffix}.part")

        digest = hashlib.sha256()
        size = 0
        try:
            with temporary.open("wb") as output:
                while chunk := await file.read(1024 * 1024):
                    size += len(chunk)
                    if size > self.settings.max_upload_bytes:
                        raise InvalidUploadError(
                            f"File exceeds {self.settings.max_upload_bytes} bytes",
                            code="upload_too_large",
                        )
                    digest.update(chunk)
                    output.write(chunk)
            if size == 0:
                raise InvalidUploadError("The uploaded file is empty")
            os.replace(temporary, target)
        finally:
            if temporary.exists():
                temporary.unlink()
            await file.close()

        return StoredFile(
            path=target,
            source_type=suffix.removeprefix("."),
            content_hash=digest.hexdigest(),
            size_bytes=size,
        )


def get_file_storage() -> LocalFileStorage:
    return LocalFileStorage(get_settings())
