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


def int_env(name: str, default: int) -> int:
    """A positive integer ceiling from the environment, or the default.

    0.63.14: several module constants were round numbers with no evidence attached, and a limit that cannot be
    changed without editing code is not a setting — it is a decision nobody can revisit. These read the environment
    so every one of them is reversible from `.env`."""
    try:
        v = int(os.environ.get(name, "") or default)
    except ValueError:
        return default
    return v if v > 0 else default


def float_env(name: str, default: float) -> float:
    """The float twin of `int_env`, added 0.63.35 for a contract TIMEOUT.

    Same contract and same reason: a junk, zero or negative value falls back to the default. Written
    because the first version of the claims timeout used `float(os.environ.get(...) or 480.0)` and a
    typo in `.env` would have raised ValueError at import time — stopping the app from starting over a
    misspelled number, which is a far worse failure than the wrong timeout."""
    try:
        v = float(os.environ.get(name, "") or default)
    except ValueError:
        return default
    return v if v > 0 else default


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
    # Reddit's official API (0.32.2): a 'script' app's client id/secret, app-only OAuth (read-only public data). Reddit refuses
    # every non-browser client since 2026-06-30, so without these the app cannot search subreddits; threads still arrive
    # through the browser extension ("Send this page" on a thread).
    # Scholarly catalogues (scholar.py). The email is Crossref's `mailto` — no account, it only earns the polite
    # pool's higher limits. OpenAlex has REQUIRED a free key since 2026-02-13 (unkeyed callers get 100 credits then
    # HTTP 409), so without it `scholar.available()` reports OpenAlex off rather than failing mid-query.
    scholar_email: str | None = field(default_factory=lambda: _env("NEUROSEARCH_SCHOLAR_EMAIL"))
    openalex_api_key: str | None = field(default_factory=lambda: _env("OPENALEX_API_KEY"))
    reddit_client_id: str | None = field(default_factory=lambda: _env("REDDIT_CLIENT_ID"))
    reddit_client_secret: str | None = field(default_factory=lambda: _env("REDDIT_CLIENT_SECRET"))
    answer_model: str = field(default_factory=lambda: _env("NEUROSEARCH_ANSWER_MODEL", "claude-sonnet-4-6"))
    embedding_model: str = field(default_factory=lambda: _env("NEUROSEARCH_EMBEDDING_MODEL", "text-embedding-3-small"))
    transcribe_model: str = field(default_factory=lambda: _env("NEUROSEARCH_TRANSCRIBE_MODEL", "whisper-1"))
    planner_v3: bool = field(default_factory=lambda: (_env("NEUROSEARCH_PLANNER_V3", "") or "").lower() in ("1", "true", "yes"))   # F4: decomposed planner (temporary flag)
    retrieval_rerank: bool = field(default_factory=lambda: (_env("NEUROSEARCH_RETRIEVAL_RERANK", "") or "").lower() in ("1", "true", "yes"))   # I2: Haiku listwise rerank of the retrieved candidates (experiment, off)
    findings_prefilter: bool = field(default_factory=lambda: (_env("NEUROSEARCH_FINDINGS_PREFILTER", "") or "").lower() in ("1", "true", "yes"))   # H1: cheap window rejection filter before findings.extract (off until proven)

    # Ingest
    caption_langs: list[str] = field(
        default_factory=lambda: [s.strip() for s in (_env("NEUROSEARCH_CAPTION_LANGS", "en,en-US,en-GB") or "").split(",") if s.strip()]
    )
    cookies_file: str | None = field(default_factory=lambda: _env("NEUROSEARCH_COOKIES_FILE"))
    allow_transcription: bool = field(default_factory=lambda: (_env("NEUROSEARCH_ALLOW_TRANSCRIPTION", "true") or "").lower() == "true")
    max_transcribe_minutes: int = field(default_factory=lambda: int(_env("NEUROSEARCH_MAX_TRANSCRIBE_MINUTES", "240") or 240))
    # 0.63.14: 3, was 2. These workers do ingestion — download, transcribe, chunk — and YouTube politeness is
    # already handled by `yt_delay` (4 s, randomised) rather than by how many workers exist, so 2 was throttling
    # his own machine rather than protecting anything. Revert with NEUROSEARCH_WORKERS=2.
    workers: int = field(default_factory=lambda: int_env("NEUROSEARCH_WORKERS", 3))
    # L1 Local-First AI: ai_profile=local routes eligible tasks through Claude Code. Local failure waits locally
    # unless local_api_fallback is explicitly enabled; cloud keeps every call on the API.
    ai_profile: str = field(default_factory=lambda: (_env("NEUROSEARCH_AI_PROFILE", "cloud") or "cloud").lower())
    # Foundation: local transport errors must not silently buy an API retry. Explicit opt-in only.
    local_api_fallback: bool = field(default_factory=lambda: (_env("NEUROSEARCH_LOCAL_API_FALLBACK", "false") or "false").lower() in ("1", "true", "yes"))
    local_ai_workers: int = field(default_factory=lambda: int(_env("NEUROSEARCH_LOCAL_AI_WORKERS", "2") or 2))
    # 0.63.13 — the API analysis pool was ONE hard-coded thread, so work the user PAID to accelerate ran one job at
    # a time. Concurrency is not a rate limit: the spend-rate ceiling, the daily/weekly budgets and the account
    # gates all still hold, and each is a better instrument for "how much" than a thread count.
    api_ai_workers: int = field(default_factory=lambda: int(_env("NEUROSEARCH_API_AI_WORKERS", "3") or 3))
    claude_code_bin: str = field(default_factory=lambda: _env("NEUROSEARCH_CLAUDE_CODE_BIN", "claude") or "claude")
    claude_code_model: str | None = field(default_factory=lambda: _env("NEUROSEARCH_CLAUDE_CODE_MODEL"))
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
    # L-30 (EXECUTION-LADDER.md P2, E7 Nightly Refinery): 0 (the default) means off -- nothing runs
    # unattended until a caller explicitly sets a per-night dollar cap. t4_nightly_hour is a LOCAL hour
    # (0-23); the envelope only fires once it's due AND hasn't already run for today's date (see
    # neurosearch/nightly.py), never "at that hour exactly" -- same host-honesty rule as L-20's CLI.
    t4_nightly_budget: float = field(default_factory=lambda: float(_env("NEUROSEARCH_T4_NIGHTLY_BUDGET_USD", "0") or 0))
    t4_nightly_hour: int = field(default_factory=lambda: int(_env("NEUROSEARCH_T4_NIGHTLY_HOUR", "2") or 2))
    # L-60: a SEPARATE per-night cap for T5 adjudication (each paid adjudication is a Sonnet-tier call, not a
    # Haiku findings read) -- off by default, authorized independently of the findings budget above.
    t5_nightly_budget: float = field(default_factory=lambda: float(_env("NEUROSEARCH_T5_NIGHTLY_BUDGET_USD", "0") or 0))

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
    def images_dir(self) -> Path:
        """Where an ingested image is KEPT so it can be looked at (0.63.0). Named by source id, never by anything
        the user supplied — the serving route then needs no path handling at all, so there is nothing to traverse."""
        return self.data_dir / "images"

    @property
    def embeddings_enabled(self) -> bool:
        return self.fake_ai or bool(self.openai_api_key)


settings = Settings()
settings.data_dir.mkdir(parents=True, exist_ok=True)
settings.media_dir.mkdir(parents=True, exist_ok=True)
