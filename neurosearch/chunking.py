"""Turn timestamped transcript segments into retrieval chunks.

- Short-form (under `short_form_seconds`): one chunk for the whole thing (split only if very long text).
- Long-form: sliding windows of ~`target_seconds`, with `overlap_seconds` of context carried over,
  never crossing a chapter boundary when chapters are known.
Every chunk keeps start/end so answers can deep-link to the moment.
"""
from __future__ import annotations

import re
from typing import Any

from .config import settings

MAX_CHUNK_CHARS = 2400


def normalize_segments(segments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Clean caption text, drop empties, merge exact-duplicate rollovers (YouTube auto-subs repeat lines)."""
    out: list[dict[str, Any]] = []
    last_text = None
    for s in segments:
        text = clean_text(s.get("text", ""))
        if not text:
            continue
        start = float(s["start"])
        end = float(s.get("end", start))
        if end < start:
            end = start
        if text == last_text and out:
            out[-1]["end"] = max(out[-1]["end"], end)
            continue
        out.append({"start": start, "end": end, "text": text})
        last_text = text
    return out


def clean_text(text: str) -> str:
    text = re.sub(r"<[^>]+>", "", text)          # inline timing tags from vtt/srv formats
    text = text.replace("​", " ").replace("\n", " ")
    text = re.sub(r"\[(music|applause|laughter|inaudible)[^\]]*\]", " ", text, flags=re.I)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def build_chunks(
    segments: list[dict[str, Any]],
    duration: float | None = None,
    chapters: list[dict[str, Any]] | None = None,
    target_seconds: int | None = None,
    overlap_seconds: int | None = None,
) -> list[dict[str, Any]]:
    target = target_seconds or settings.chunk_target_seconds
    overlap = overlap_seconds if overlap_seconds is not None else settings.chunk_overlap_seconds
    if not segments:
        return []
    total = duration or (segments[-1]["end"] - segments[0]["start"])

    if total <= settings.short_form_seconds:
        return _split_by_chars(segments, chapter=None)

    # Hard boundaries at chapters (if any), else the whole timeline.
    bounds: list[tuple[float, float, str | None]] = []
    if chapters:
        ch = sorted(chapters, key=lambda c: c.get("start_time", 0))
        for i, c in enumerate(ch):
            s = float(c.get("start_time", 0))
            e = float(ch[i + 1]["start_time"]) if i + 1 < len(ch) else float("inf")
            bounds.append((s, e, c.get("title")))
    else:
        bounds.append((0.0, float("inf"), None))

    chunks: list[dict[str, Any]] = []
    for b_start, b_end, title in bounds:
        segs = [s for s in segments if s["start"] >= b_start and s["start"] < b_end]
        chunks.extend(_window(segs, target, overlap, title))
    return chunks


def _window(segs: list[dict[str, Any]], target: int, overlap: int, chapter: str | None) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    if not segs:
        return out
    i = 0
    n = len(segs)
    while i < n:
        w_start = segs[i]["start"]
        j = i
        while j < n and (segs[j]["end"] - w_start) <= target:
            j += 1
        if j == i:  # single very long segment
            j = i + 1
        window = segs[i:j]
        out.extend(_split_by_chars(window, chapter))
        if j >= n:
            break
        # step back for overlap
        next_start_time = segs[j - 1]["end"] - overlap
        k = j
        while k > i + 1 and segs[k - 1]["start"] > next_start_time:
            k -= 1
        i = max(k, i + 1)
    return out


def _split_by_chars(segs: list[dict[str, Any]], chapter: str | None) -> list[dict[str, Any]]:
    """Join segments into a chunk; if the text is huge, split it into several chunks on segment boundaries."""
    out: list[dict[str, Any]] = []
    cur: list[dict[str, Any]] = []
    cur_len = 0
    for s in segs:
        if cur and cur_len + len(s["text"]) + 1 > MAX_CHUNK_CHARS:
            out.append(_make(cur, chapter))
            cur, cur_len = [], 0
        cur.append(s)
        cur_len += len(s["text"]) + 1
    if cur:
        out.append(_make(cur, chapter))
    return out


def _make(segs: list[dict[str, Any]], chapter: str | None) -> dict[str, Any]:
    text = " ".join(s["text"] for s in segs)
    if chapter:
        text = f"[{chapter}] {text}"
    return {"start": segs[0]["start"], "end": segs[-1]["end"], "text": text}


def build_doc_chunks(pages: list[dict[str, Any]], target_chars: int = 1600, overlap_paras: int = 1) -> list[dict[str, Any]]:
    """Chunk a document. `pages` = [{page:int, text:str}]. Chunks carry start/end = page numbers.

    Paragraphs are packed up to ~target_chars, never splitting a paragraph, with one paragraph of overlap.
    """
    paras: list[tuple[int, str]] = []
    for pg in pages:
        for para in re.split(r"\n\s*\n", pg["text"] or ""):
            t = " ".join(para.split())
            if t:
                # very long paragraphs get split on sentence boundaries
                while len(t) > MAX_CHUNK_CHARS:
                    cut = t.rfind(". ", 0, MAX_CHUNK_CHARS)
                    cut = cut + 1 if cut > 200 else MAX_CHUNK_CHARS
                    paras.append((pg["page"], t[:cut].strip()))
                    t = t[cut:].strip()
                paras.append((pg["page"], t))
    chunks: list[dict[str, Any]] = []
    i = 0
    while i < len(paras):
        j, size = i, 0
        while j < len(paras) and (size == 0 or size + len(paras[j][1]) <= target_chars):
            size += len(paras[j][1]) + 1
            j += 1
        group = paras[i:j]
        chunks.append({"start": float(group[0][0]), "end": float(group[-1][0]), "text": "\n".join(p[1] for p in group)})
        if j >= len(paras):
            break
        i = max(j - overlap_paras, i + 1)
    return chunks


def fmt_locator(platform: str, start: float) -> str:
    """Human label for a position: 'p. 12' for documents, mm:ss for media."""
    if platform == "document":
        return f"p. {int(start)}"
    if platform == "web":
        return f"§ {int(start)}"
    if platform == "spreadsheet":
        return f"sheet {int(start)}"
    if platform == "community":
        return f"post {int(start)}"
    return fmt_ts(start)


def fmt_ts(seconds: float) -> str:
    s = int(round(seconds))
    h, rem = divmod(s, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"
