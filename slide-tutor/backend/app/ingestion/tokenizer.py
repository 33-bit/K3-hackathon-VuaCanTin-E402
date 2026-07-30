"""Token counting and deterministic windowing for ingestion."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

_FALLBACK_TOKEN_RE = re.compile(
    r"[^\W_]+(?:['’\-][^\W_]+)*|_+|[^\w\s]",
    flags=re.UNICODE,
)


@dataclass(frozen=True, slots=True)
class TokenWindow:
    text: str
    token_start: int
    token_end: int


class Tokenizer:
    """Use ``cl100k_base`` when available and a stable lexical fallback.

    The fallback is intentionally deterministic rather than an estimate based
    on string length.  It keeps ingestion usable in lightweight test and
    recovery environments where ``tiktoken`` has not been installed.
    """

    def __init__(
        self,
        encoding_name: str = "cl100k_base",
        *,
        force_fallback: bool = False,
    ) -> None:
        self.encoding_name = encoding_name
        self._encoding: Any | None = None
        if not force_fallback:
            try:
                import tiktoken

                self._encoding = tiktoken.get_encoding(encoding_name)
            except (ImportError, KeyError):
                self._encoding = None

    @property
    def uses_tiktoken(self) -> bool:
        return self._encoding is not None

    def count(self, text: str) -> int:
        if not text:
            return 0
        if self._encoding is not None:
            return len(self._encoding.encode(text, disallowed_special=()))
        return len(tuple(_FALLBACK_TOKEN_RE.finditer(text)))

    def windows(
        self,
        text: str,
        *,
        max_tokens: int,
        overlap_tokens: int,
    ) -> tuple[TokenWindow, ...]:
        if max_tokens <= 0:
            raise ValueError("max_tokens must be positive")
        if overlap_tokens < 0 or overlap_tokens >= max_tokens:
            raise ValueError("overlap_tokens must be in [0, max_tokens)")
        if not text:
            return ()

        if self._encoding is not None:
            token_ids = self._encoding.encode(text, disallowed_special=())
            if not token_ids:
                return ()
            windows: list[TokenWindow] = []
            step = max_tokens - overlap_tokens
            for start in range(0, len(token_ids), step):
                end = min(start + max_tokens, len(token_ids))
                window_text = self._encoding.decode(token_ids[start:end]).strip()
                if window_text:
                    windows.append(TokenWindow(window_text, start, end))
                if end == len(token_ids):
                    break
            return tuple(windows)

        matches = tuple(_FALLBACK_TOKEN_RE.finditer(text))
        if not matches:
            return ()
        windows = []
        step = max_tokens - overlap_tokens
        for start in range(0, len(matches), step):
            end = min(start + max_tokens, len(matches))
            char_start = matches[start].start()
            char_end = matches[end - 1].end()
            window_text = text[char_start:char_end].strip()
            if window_text:
                windows.append(TokenWindow(window_text, start, end))
            if end == len(matches):
                break
        return tuple(windows)
