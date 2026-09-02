"""Runtime configuration, read from environment / .env."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


def _env(name: str, default: str | None = None) -> str | None:
    v = os.environ.get(name)
    return v if v not in (None, "") else default


@dataclass
class Settings:
    # Storage
    data_dir: Path = field(default_factory=lambda: Path(_env("NEUROSEARCH_DATA_DIR", "./data")).resolve())

    # Auth: a single shared secret. Web UI login + Bearer token for API/MCP.
    app_token: str | None = field(default_factory=lambda: _env("NEUROSEARCH_APP_TOKEN"))

    # Models
    anthropic_api_key: str | None = field(default_factory=lambda: _env("ANTHROPIC_API_KEY"))
    openai_api_key: str | None = field(default_factory=lambda: _env("OPENAI_API_KEY"))
    answer_model: str = field(default_factory=lambda: _env("NEUROSEARCH_ANSWER_MODEL", "claude-sonnet-4-6"))
    embedding_model: str = field(default_factory=lambda: _env("NEUROSEARCH_EMBEDDING_MODEL", "text-embedding-3-small"))
    transcribe_model: str = field(default_factory=lambda: _env("NEUROSEARCH_TRANSCRIBE_MODEL", "whisper-1"))

    # Ingest
    caption_langs: list[str] = field(
        default_factory=lambda: [s.strip() for s in (_env("NEUROSEARCH_CAPTION_LANGS", "en,en-US,en-GB") or "").split(",") if s.strip()]
    )
    cookies_file: str | None = field(default_factory=lambda: _env("NEUROSEARCH_COOKIES_FILE"))
    allow_transcription: bool = field(default_factory=lambda: (_env("NEUROSEARCH_ALLOW_TRANSCRIPTION", "true") or "").lower() == "true")
    max_transcribe_minutes: int = field(default_factory=lambda: int(_env("NEUROSEARCH_MAX_TRANSCRIBE_MINUTES", "240") or 240))
    workers: int = field(default_factory=lambda: int(_env("NEUROSEARCH_WORKERS", "2") or 2))

    # Chunking (seconds)
    chunk_target_seconds: int = field(default_factory=lambda: int(_env("NEUROSEARCH_CHUNK_SECONDS", "60") or 60))
    chunk_overlap_seconds: int = field(default_factory=lambda: int(_env("NEUROSEARCH_CHUNK_OVERLAP", "10") or 10))
    short_form_seconds: int = field(default_factory=lambda: int(_env("NEUROSEARCH_SHORT_FORM_SECONDS", "150") or 150))

    @property
    def db_path(self) -> Path:
        return self.data_dir / "neurosearch.db"

    @property
    def media_dir(self) -> Path:
        return self.data_dir / "media"

    @property
    def embeddings_enabled(self) -> bool:
        return bool(self.openai_api_key)


settings = Settings()
settings.data_dir.mkdir(parents=True, exist_ok=True)
settings.media_dir.mkdir(parents=True, exist_ok=True)
