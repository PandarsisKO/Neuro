"""Audio transcription via the OpenAI audio API (whisper-1, segment timestamps).

Long files are split with ffmpeg into ~15 minute pieces (the API caps uploads at 25 MB),
transcribed one by one, and the timestamps re-offset so they line up with the original.
"""
from __future__ import annotations

import json
import logging
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Callable

from .config import settings

log = logging.getLogger(__name__)

PIECE_SECONDS = 15 * 60


def audio_duration(path: Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", str(path)],
        capture_output=True, text=True, check=True,
    ).stdout
    return float(json.loads(out)["format"]["duration"])


def to_mp3(path: Path, dest: Path, bitrate: str = "64k") -> Path:
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-i", str(path), "-vn", "-ac", "1", "-ar", "16000", "-b:a", bitrate, str(dest)],
        check=True,
    )
    return dest


def split_audio(path: Path, workdir: Path, piece_seconds: int = PIECE_SECONDS) -> list[tuple[float, Path]]:
    """Return [(offset_seconds, piece_path)]."""
    total = audio_duration(path)
    pieces: list[tuple[float, Path]] = []
    if total <= piece_seconds:
        return [(0.0, path)]
    offset = 0.0
    i = 0
    while offset < total:
        dest = workdir / f"piece_{i:03d}.mp3"
        subprocess.run(
            ["ffmpeg", "-y", "-v", "error", "-ss", str(offset), "-t", str(piece_seconds), "-i", str(path),
             "-vn", "-ac", "1", "-ar", "16000", "-b:a", "64k", str(dest)],
            check=True,
        )
        pieces.append((offset, dest))
        offset += piece_seconds
        i += 1
    return pieces


def transcribe_file(
    path: Path,
    language: str | None = None,
    progress: Callable[[float, str], None] | None = None,
) -> tuple[list[dict[str, Any]], str | None]:
    """Transcribe an audio/video file. Returns (segments, detected_language)."""
    if not settings.openai_api_key:
        raise RuntimeError("OPENAI_API_KEY is not set; cannot transcribe audio")
    if not shutil.which("ffmpeg"):
        raise RuntimeError("ffmpeg is not installed")
    from openai import OpenAI

    client = OpenAI(api_key=settings.openai_api_key)
    segments: list[dict[str, Any]] = []
    detected: str | None = None
    with tempfile.TemporaryDirectory(prefix="ns_tx_") as td:
        workdir = Path(td)
        src = path if path.suffix.lower() == ".mp3" and path.stat().st_size < 24 * 1024 * 1024 else to_mp3(path, workdir / "src.mp3")
        pieces = split_audio(src, workdir)
        for n, (offset, piece) in enumerate(pieces):
            if progress:
                progress(n / max(len(pieces), 1), f"transcribing part {n + 1}/{len(pieces)}")
            with open(piece, "rb") as fh:
                kwargs: dict[str, Any] = dict(
                    model=settings.transcribe_model, file=fh, response_format="verbose_json",
                    timestamp_granularities=["segment"],
                )
                if language:
                    kwargs["language"] = language
                res = client.audio.transcriptions.create(**kwargs)
            detected = detected or getattr(res, "language", None)
            for s in getattr(res, "segments", None) or []:
                start = float(getattr(s, "start", 0)) + offset
                end = float(getattr(s, "end", start)) + offset
                text = (getattr(s, "text", "") or "").strip()
                if text:
                    segments.append({"start": start, "end": end, "text": text})
    return segments, detected
