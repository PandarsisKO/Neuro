"""Rank a channel's/playlist's proposed videos by relevance to the project — from titles and
descriptions only, before anything is downloaded — so the review card can pre-select the best N.

One Claude call per batch of ~120 titles (a few cents for a whole channel).
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any, Callable

from . import db
from .config import settings

log = logging.getLogger(__name__)

POOL = 400          # never rank more than this many (newest first); keeps the cost bounded
BATCH = 120

SYSTEM = """You are a research triage assistant scoring a list of videos for relevance BEFORE they are downloaded.
You only see each video's title, a snippet of its description, its length and view count — judge from that.

Score every video 0-100 for how likely it is to contain material useful for THIS project:
- 85-100: squarely on the project's questions; likely full of usable specifics
- 60-84: relevant angle or adjacent topic; probably worth the download
- 30-59: tangential; might contain a nugget
- 0-29: off-topic, promotional, reaction/vlog filler, or a duplicate of a better-looking item
Prefer depth over breadth: a 40-minute deep dive on the exact question beats a 3-minute clip.
Penalise obvious clickbait/sales pitches and near-duplicate titles (score the best one, mark the rest lower).

Return ONLY JSON: {"scores":[{"i":<index>,"score":<0-100>,"why":"<max 8 words>"}]} with one entry per index given."""


def _call(system: str, user: str, project_id: str | None, collection_id: str) -> dict[str, Any]:
    if not settings.anthropic_api_key:
        raise RuntimeError("ANTHROPIC_API_KEY is not set")
    import anthropic
    from . import usage

    usage.guard(0.02)
    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    resp = client.messages.create(model=settings.answer_model, max_tokens=6000, system=system,
                                  messages=[{"role": "user", "content": user}])
    usage.record_anthropic(resp, "rank", project_id=project_id)
    text = "".join(getattr(b, "text", "") for b in resp.content).strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.S)
    s, e = text.find("{"), text.rfind("}")
    return json.loads(text[s:e + 1]) if s >= 0 else {}


def _line(i: int, s: dict[str, Any]) -> str:
    bits = [f"[{i}] {s.get('title') or s.get('url')}"]
    if s.get("duration"):
        m = int(s["duration"] // 60)
        bits.append(f"({m} min)" if m else "(<1 min)")
    if s.get("view_count"):
        bits.append(f"{int(s['view_count']):,} views")
    d = (s.get("description") or "").strip().replace("\n", " ")
    if d:
        bits.append("— " + d[:220])
    return " ".join(bits)


def rank_collection(collection_id: str, project_id: str | None, want: int | None = None,
                    progress: Callable[[float, str], None] | None = None) -> dict[str, Any]:
    """Score every proposed source in the collection and store relevance/relevance_why on each.
    Sources beyond POOL (oldest) get score 0 so they stay unticked."""
    project = db.get_project(project_id) if project_id else None
    rows = db.proposed_sources(collection_id)
    if not rows:
        return {"ranked": 0}
    if not project or not (project.get("brief") or project.get("goal") or project.get("questions")):
        # nothing to rank against: keep newest-first, mark as ranked so the UI stops waiting
        db.mark_review_ranked(collection_id, note="no brief to rank against — newest first")
        return {"ranked": 0, "skipped": "no brief"}
    rows.sort(key=lambda r: r.get("created_at") or 0)      # listing order (newest first for channels)
    pool, rest = rows[:POOL], rows[POOL:]
    head = (f"PROJECT: {project['name']}\n{db.project_steering(project)}\n"
            + (f"We only need about the best {want} videos.\n" if want else ""))
    scored: dict[str, tuple[int, str]] = {}
    for b in range(0, len(pool), BATCH):
        batch = pool[b:b + BATCH]
        if progress:
            progress(b / len(pool), f"ranking {b + 1}-{min(b + BATCH, len(pool))} of {len(pool)}")
        user = head + "\nVIDEOS:\n" + "\n".join(_line(i, s) for i, s in enumerate(batch)) + "\n\nScore them now."
        res = _call(SYSTEM, user, project_id, collection_id)
        for it in res.get("scores") or []:
            try:
                i = int(it.get("i")); sc = max(0, min(100, int(it.get("score", 0))))
            except (TypeError, ValueError):
                continue
            if 0 <= i < len(batch):
                scored[batch[i]["id"]] = (sc, str(it.get("why") or "")[:80])
    for s in pool:
        sc, why = scored.get(s["id"], (0, "not scored"))
        db.set_relevance(s["id"], sc, why)
    for s in rest:
        db.set_relevance(s["id"], 0, "beyond ranking pool (older)")
    db.mark_review_ranked(collection_id)
    return {"ranked": len(scored), "pool": len(pool), "unranked": len(rest)}
