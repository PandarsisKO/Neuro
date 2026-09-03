"""Suggested findings: read a whole transcript against the project brief and propose findings for approval.

Also scores each source for substance (how much of it is actual content vs. fluff) and writes a one-paragraph
summary, so long lists of videos can be triaged at a glance.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any

from . import db
from .chunking import fmt_locator
from .config import settings
from .search import deep_link

log = logging.getLogger(__name__)

WINDOW_CHARS = 60000  # ~15k tokens of transcript per call

SYSTEM = """You are a research analyst reading a transcript on behalf of a project. Extract the findings that matter for
the project brief — concrete claims, numbers, techniques, recommendations, warnings, disagreements, or notable
examples — and ignore fluff (intros, sponsor reads, banter, repetition, vague motivation).

Rules:
- "title": the meat in ≤ 8 words — the claim, number, or action itself. Write it like a headline, in the
  imperative or as a fact. NEVER "X says/recommends/states/advises"; the speaker is implied.
    bad:  "Hormozi recommends adding a speed/priority upsell (e.g. 20% fee to move to the…"
    good: "20% priority fee = pure-margin upsell"
    bad:  "Hormozi states the very first step of starting any business from scratch is alwa…"
    good: "Step one: form an LLC to accept money"
- "finding": ONE sentence with what the title leaves out — the how, the why, the numbers, the condition. It must
  NOT restate the title and must NOT contain the quote. If the title already says everything, use "".
    good: "Customers who want the job done this week pay 20% extra to jump the queue; demand routinely exceeds capacity so it costs nothing to offer."
- "quote": ≤ 20 verbatim words from the transcript that back it up. "ts": the [m:ss] marker just before it.
- Rate importance 1–5 for THIS brief (5 = directly answers what the project is trying to find out).
- Extract nothing that is not in the transcript. If the transcript has nothing relevant, return an empty list.
- Aim for the 3–12 findings that matter, not everything that was said. Fewer, sharper findings are better.
- Also rate the whole transcript's substance 0–100 (100 = dense, specific, on-topic; 0 = pure fluff) and write a
  two-sentence summary of what it actually covers.

Output ONLY JSON:
{"summary": str, "substance": int, "findings": [{"title": str, "finding": str, "ts": "m:ss or h:mm:ss, or p. N / § N for documents and web pages", "quote": str, "importance": int}]}"""


def _ts_to_seconds(ts: str, platform: str) -> float | None:
    ts = (ts or "").strip()
    m = re.match(r"(?:p\.?|§|section)\s*(\d+)", ts, flags=re.I)
    if m:
        return float(m.group(1))
    parts = ts.replace("[", "").replace("]", "").split(":")
    try:
        nums = [int(p) for p in parts]
    except ValueError:
        return None
    if len(nums) == 3:
        return float(nums[0] * 3600 + nums[1] * 60 + nums[2])
    if len(nums) == 2:
        return float(nums[0] * 60 + nums[1])
    if len(nums) == 1 and platform in ("document", "web"):
        return float(nums[0])
    return None


def _windows(segs: list[dict[str, Any]], platform: str) -> list[str]:
    lines = [f"[{fmt_locator(platform, s['start'])}] {s['text']}" for s in segs]
    out, cur, size = [], [], 0
    for ln in lines:
        if cur and size + len(ln) > WINDOW_CHARS:
            out.append("\n".join(cur)); cur, size = [], 0
        cur.append(ln); size += len(ln) + 1
    if cur:
        out.append("\n".join(cur))
    return out


def _call(system: str, user: str, project_id: str | None = None, source_id: str | None = None) -> dict[str, Any]:
    if not settings.anthropic_api_key:
        raise RuntimeError("ANTHROPIC_API_KEY is not set")
    import anthropic
    from . import usage

    usage.guard(usage.estimate_findings(len(user)))
    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    resp = client.messages.create(model=settings.answer_model, max_tokens=4000, system=system,
                                  messages=[{"role": "user", "content": user}])
    usage.record_anthropic(resp, "findings", project_id=project_id, source_id=source_id)
    text = "".join(getattr(b, "text", "") for b in resp.content).strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.S)
    s, e = text.find("{"), text.rfind("}")
    return json.loads(text[s:e + 1]) if s >= 0 else {}


def suggest_for_source(project_id: str, source_id: str, max_findings: int = 12) -> dict[str, Any]:
    """Extract candidate findings for one source in the context of one project. Stores them as 'suggested'."""
    project = db.get_project(project_id)
    src = db.get_source(source_id)
    if not project or not src:
        raise RuntimeError("project or source not found")
    segs = db.get_segments(source_id)
    if not segs:
        raise RuntimeError("source has no transcript")
    platform = src["platform"]
    brief = project.get("brief") or "(no brief — extract the most substantive, reusable findings)"
    head = (f"PROJECT: {project['name']}\nBRIEF: {brief}\n{db.project_steering(project)}\n\n"
            f"SOURCE: {src['title']} ({src.get('channel') or platform})\n")
    windows = _windows(segs, platform)
    all_findings: list[dict[str, Any]] = []
    summaries: list[str] = []
    substances: list[int] = []
    for i, w in enumerate(windows):
        part = f" (part {i + 1}/{len(windows)})" if len(windows) > 1 else ""
        res = _call(SYSTEM, head + f"\nTRANSCRIPT{part}:\n{w}\n\nExtract the findings now.", project_id, source_id)
        if res.get("summary"):
            summaries.append(str(res["summary"]))
        if isinstance(res.get("substance"), (int, float)):
            substances.append(int(res["substance"]))
        for f in res.get("findings") or []:
            if isinstance(f, dict) and f.get("finding"):
                all_findings.append(f)
    all_findings.sort(key=lambda f: -int(f.get("importance") or 0))
    notes = []
    for f in all_findings[:max_findings]:
        start = _ts_to_seconds(str(f.get("ts", "")), platform)
        cites = []
        if start is not None:
            cites.append({"n": 1, "source_id": source_id, "title": src["title"], "channel": src.get("channel"),
                          "url": src["url"], "link": deep_link(src["url"], platform, start),
                          "timestamp": fmt_locator(platform, start), "start": start, "end": start, "platform": platform,
                          "snippet": (f.get("quote") or "")[:300]})
        content = f["finding"].strip()
        if cites and "[1]" not in content:
            content += " [1]"
        notes.append({"title": (f.get("title") or "").strip()[:120] or None, "content": content, "citations": cites,
                      "importance": int(f.get("importance") or 0)})
    n = db.replace_suggestions(project_id, source_id, notes)
    substance = int(sum(substances) / len(substances)) if substances else None
    summary = " ".join(summaries)[:1200] if summaries else None
    db.set_source_summary(source_id, summary, substance)
    return {"source_id": source_id, "title": src["title"], "suggested": n, "substance": substance, "summary": summary}


def suggest_for_project(project_id: str, source_ids: list[str] | None = None, progress=None) -> dict[str, Any]:
    ids = source_ids or db.sources_needing_suggestions(project_id)
    done, failed = 0, []
    for i, sid in enumerate(ids):
        if progress:
            progress(i / max(len(ids), 1), f"reading {i + 1}/{len(ids)}")
        try:
            suggest_for_source(project_id, sid)
            done += 1
        except Exception as e:  # noqa: BLE001
            from .usage import BudgetPaused
            if isinstance(e, BudgetPaused):
                # hand the remaining sources back to the queue as a fresh job and stop
                remaining = ids[i:]
                db.create_job("suggest_findings", {"project_id": project_id, "source_ids": remaining})
                raise
            log.warning("suggest failed for %s: %s", sid, e)
            failed.append(sid)
    return {"sources": len(ids), "done": done, "failed": len(failed)}
