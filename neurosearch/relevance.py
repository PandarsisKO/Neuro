"""Rank a channel's/playlist's proposed videos by relevance to the project — from titles and
descriptions only, before anything is downloaded — so the review card can pre-select the best N.

One Claude call per batch of ~80 titles (a few cents for a whole channel).
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
BATCH = 80

SYSTEM = """You are a research triage assistant scoring a list of videos for relevance BEFORE they are downloaded.
You only see each video's title, a snippet of its description, its length and view count — judge from that.

Score every video 0-100 for how likely it is to contain material useful for THIS project:
- 85-100: squarely on the project's questions; likely full of usable specifics
- 60-84: relevant angle or adjacent topic; probably worth the download
- 30-59: tangential; might contain a nugget
- 0-29: off-topic, promotional, reaction/vlog filler, or a duplicate of a better-looking item
Prefer depth over breadth: a 40-minute deep dive on the exact question beats a 3-minute clip.
Penalise obvious clickbait/sales pitches and near-duplicate titles (score the best one, mark the rest lower).

Return ONLY JSON: {"scores":[{"i":<index>,"score":<0-100>,"why":"<max 8 words>"}]} with one entry per index given.
Never use double quotes or backslashes inside "why" (write Boring not "Boring")."""


def _system_blocks(system: str, head: str) -> Any:
    from . import usage
    return [{"type": "text", "text": system}, usage.cached_block(head, min_chars=len(system))] if head else system


def _call(system: str, user: str, project_id: str | None, collection_id: str, head: str = "") -> dict[str, Any]:
    from . import providers, usage

    from .contracts import contract
    sys_blocks = _system_blocks(system, head)
    c = contract("rank.relevance")
    messages = [{"role": "user", "content": user}]
    if c.schema:
        # Mission F path: schema-enforced result, fully validated locally; typed failures propagate (a failed batch is
        # visible as failed_batches, never a silently "repaired" one)
        return providers.invoke_structured("rank.relevance", system=sys_blocks, messages=messages, usage_kind="rank", project_id=project_id,
                                           guard_estimate=0.02, legacy=parse_scores)
    usage.guard(0.02)
    resp = providers.invoke("rank.relevance", system=sys_blocks, messages=messages)
    usage.record_anthropic(resp, "rank", project_id=project_id)
    return parse_scores(providers.text_of(resp).strip())


ITEM_RE = re.compile(r'\{\s*"i"\s*:\s*(\d+)\s*,\s*"score"\s*:\s*(\d+)\s*,\s*"why"\s*:\s*"(.*?)"\s*\}', re.S)


def parse_scores(text: str) -> dict[str, Any]:
    """Tolerant parse: strict JSON first, otherwise pull out every {"i":..,"score":..,"why":".."} object we can
    (the model occasionally puts a stray quote inside a reason or gets cut off, and one bad item should not
    sink a batch of 120)."""
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(), flags=re.S)
    s, e = text.find("{"), text.rfind("}")
    if s >= 0:
        try:
            data = json.loads(text[s:e + 1])
            if isinstance(data, dict) and isinstance(data.get("scores"), list):
                return data
        except ValueError:
            pass
    items = [{"i": int(i), "score": int(sc), "why": why.replace('\\"', '"').strip()} for i, sc, why in ITEM_RE.findall(text)]
    if not items:   # last resort: objects without a why
        items = [{"i": int(i), "score": int(sc)} for i, sc in re.findall(r'"i"\s*:\s*(\d+)\s*,\s*"score"\s*:\s*(\d+)', text)]
    return {"scores": items, "repaired": True}


def prompt_version() -> str:
    import hashlib
    return "rank-" + hashlib.sha1(SYSTEM.encode()).hexdigest()[:8]


def schema_version() -> str | None:
    from .contracts import contract
    return contract("rank.relevance").schema


def input_hash(project: dict[str, Any] | str, s: dict[str, Any]) -> str:
    """What the ranking actually judged: title, description snippet, length (to the minute), the brief, the prompt and
    the output schema. View count is deliberately left out — it changes on every metadata refresh and should not
    make a ranking stale."""
    return db._sha("relevance", s.get("title"), (s.get("description") or "")[:220], int((s.get("duration") or 0) // 60), db.brief_revision(project), prompt_version(),
                   schema_version() or "text")


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


def _pool(rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    rows.sort(key=lambda r: r.get("created_at") or 0)      # listing order (newest first for channels)
    pool, rest = rows[:POOL], rows[POOL:]
    # re-rank only what is still unscored when a previous pass partially failed
    unscored = [r for r in pool if r.get("relevance") is None]
    if unscored and len(unscored) < len(pool):
        pool = unscored
    return pool, rest


def _head(project: dict[str, Any], want: int | None) -> str:
    return (f"PROJECT: {project['name']}\n{db.project_steering(project)}\n"
            + (f"We only need about the best {want} videos.\n" if want else ""))


def _user(batch: list[dict[str, Any]]) -> str:
    return "VIDEOS:\n" + "\n".join(_line(i, s) for i, s in enumerate(batch)) + "\n\nScore them now."


def canonical_requests(collection_id: str, project_id: str, want: int | None = None) -> list[dict[str, Any]]:
    """The exact request content rank_collection would send right now — one {system, messages} per batch — built from
    the same helpers, so a token count over these is a token count over the real requests (E2 tokenizer deltas)."""
    project = db.get_project(project_id)
    rows = db.proposed_sources(collection_id, project_id)
    if not rows or not project:
        return []
    pool, _ = _pool(rows)
    head = _head(project, want)
    return [{"system": _system_blocks(SYSTEM, head), "messages": [{"role": "user", "content": _user(pool[b:b + BATCH])}]}
            for b in range(0, len(pool), BATCH)]


def rank_collection(collection_id: str, project_id: str | None, want: int | None = None,
                    progress: Callable[[float, str], None] | None = None) -> dict[str, Any]:
    """Score every proposed source in the collection and store relevance/relevance_why on each.
    Sources beyond POOL (oldest) get score 0 so they stay unticked."""
    project = db.get_project(project_id) if project_id else None
    rows = db.proposed_sources(collection_id, project_id)
    if not rows:
        return {"ranked": 0}
    if not project or not (project.get("brief") or project.get("goal") or project.get("questions")):
        # nothing to rank against: keep newest-first, mark as ranked so the UI stops waiting
        db.mark_review_ranked(collection_id, note="no brief to rank against — newest first")
        return {"ranked": 0, "skipped": "no brief"}
    pool, rest = _pool(rows)
    head = _head(project, want)
    scored: dict[str, tuple[int, str]] = {}
    failed_batches = repaired_batches = batches = 0
    for b in range(0, len(pool), BATCH):
        batches += 1
        batch = pool[b:b + BATCH]
        if progress:
            progress(b / len(pool), f"ranking {b + 1}-{min(b + BATCH, len(pool))} of {len(pool)}")
        user = _user(batch)
        try:
            res = _call(SYSTEM, user, project_id, collection_id, head=head)
        except Exception as e:  # noqa: BLE001
            from .breakers import ProviderUnavailable
            from .usage import BudgetPaused
            if isinstance(e, (BudgetPaused, ProviderUnavailable)):
                raise
            log.warning("rank batch %d failed: %s", b // BATCH, e)
            failed_batches += 1
            continue
        repaired_batches += 1 if res.get("repaired") else 0
        for it in res.get("scores") or []:
            try:
                i = int(it.get("i")); sc = max(0, min(100, int(it.get("score", 0))))
            except (TypeError, ValueError):
                continue
            if 0 <= i < len(batch):
                scored[batch[i]["id"]] = (sc, str(it.get("why") or "")[:80])
    from . import contracts, providers
    prov = {"model": "fake" if providers.fake() else contracts.contract("rank.relevance").model, "provider": "fake" if providers.fake() else "anthropic",
            "prompt_version": prompt_version(), "schema_version": schema_version() or "rank-v1", "brief_revision": db.brief_revision(project),
            "routing": providers.routing_json("rank.relevance", getattr(providers.last_response(), "model", None))}
    with db.batch():
        for s in pool:
            if s["id"] in scored:
                sc, why = scored[s["id"]]
                db.set_relevance(s["id"], sc, why, project_id=project_id, input_hash=input_hash(project, s), **prov)
            elif failed_batches:
                db.set_relevance(s["id"], None, None, project_id=project_id)      # leave unscored rather than pretend it's a 0
            else:
                db.set_relevance(s["id"], 0, "not scored", project_id=project_id, input_hash=input_hash(project, s), **prov)
        for s in rest:
            db.set_relevance(s["id"], 0, "beyond ranking pool (older)", project_id=project_id, input_hash=input_hash(project, s), **prov)
    note = None
    if failed_batches or len(scored) < len(pool):
        note = f"{len(pool) - len(scored)} of {len(pool)} videos could not be scored — press re-rank to try those again."
    db.mark_review_ranked(collection_id, note=note)
    return {"ranked": len(scored), "pool": len(pool), "unranked": len(rest), "batches": batches,
            "failed_batches": failed_batches, "repaired_batches": repaired_batches}
