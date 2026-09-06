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
    fake_ai: bool = field(default_factory=lambda: (_env("NEUROSEARCH_FAKE_AI", "") or "").lower() in ("1", "true", "yes"))
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
    # politeness: seconds to wait between YouTube fetches (randomised ±50%), and how long to back off after a bot-check
    yt_delay: float = field(default_factory=lambda: float(_env("NEUROSEARCH_YT_DELAY", "4") or 4))
    yt_backoff_minutes: int = field(default_factory=lambda: int(_env("NEUROSEARCH_YT_BACKOFF_MINUTES", "20") or 20))
    # bulk defaults for channels/playlists: only videos newer than this many years, and at most this many
    default_since_years: float = field(default_factory=lambda: float(_env("NEUROSEARCH_SINCE_YEARS", "2") or 2))
    default_max_videos: int = field(default_factory=lambda: int(_env("NEUROSEARCH_MAX_VIDEOS", "20") or 20))
    daily_budget: float = field(default_factory=lambda: float(_env("NEUROSEARCH_DAILY_BUDGET_USD", "5") or 5))
    monthly_budget: float = field(default_factory=lambda: float(_env("NEUROSEARCH_MONTHLY_BUDGET_USD", "50") or 50))
    prices_json: str | None = field(default_factory=lambda: _env("NEUROSEARCH_PRICES"))
    auto_suggest: bool = field(default_factory=lambda: (_env("NEUROSEARCH_AUTO_SUGGEST", "true") or "").lower() == "true")

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
        return self.fake_ai or bool(self.openai_api_key)


settings = Settings()
settings.data_dir.mkdir(parents=True, exist_ok=True)
settings.media_dir.mkdir(parents=True, exist_ok=True)
