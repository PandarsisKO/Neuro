"""Discover sources: who should this project be learning from?

Uses Claude with live web search to propose the leading creators, channels, podcasts and publications for
the project's brief — with why each matters, their angle, and a starting video — so someone who doesn't know
the space can get going. Results are stored per project; the user adds, dismisses or refines.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any

from . import db
from .config import settings

log = logging.getLogger(__name__)

SYSTEM = """You are a research librarian helping someone who does not yet know a field. Given a project brief, propose
the people and channels they should learn from first. Use web search to verify names, find the real YouTube
channel / podcast URLs, and check they are still active. Prefer sources with real depth and a track record over
whoever is loudest; include a mix of perspectives (e.g. mainstream + contrarian, practitioners + educators), and
note each one's angle or bias honestly. Respect the user's source preferences if given, and do not repeat
channels already in the project.

For each source give:
- name, kind (youtube_channel | podcast | newsletter | website | person), url (the canonical channel/show page),
- gist: at most 5 words that say what they are for (e.g. "debt-free budgeting basics", "index-fund investing, CFP-led"),
- why: ONE sentence, max 20 words, why it matters for THIS brief; angle: their bias/lens in max 12 words,
- start_with: 1–2 specific episodes/videos to begin with — title and URL if you found them, else title only,
- fit: 1–5 (5 = directly on the brief), depth: "beginner" | "intermediate" | "advanced".

Output ONLY JSON:
{"sources": [{"name": str, "kind": str, "url": str, "gist": str, "why": str, "angle": str,
              "start_with": [{"title": str, "url": str}], "fit": int, "depth": str}],
 "note": str}   // note: one or two sentences on how you'd sequence them, or caveats about the space
Return about 10 sources. Never invent URLs: if unsure, give the search you'd run instead (e.g. "youtube.com/results?search_query=...")."""


QUICK_SYSTEM = SYSTEM.replace(
    "Use web search to verify names, find the real YouTube\nchannel / podcast URLs, and check they are still active.",
    "Answer from what you already know — do NOT search. Give the canonical URL only when you are confident of it; "
    "otherwise leave url empty and we will look it up.")

VERIFY_SYSTEM = """You are checking a shortlist of learning sources for a research project. For each one, use web search
(at most one search per item, skip the ones whose URL is already plausible) to confirm the real, current URL of the
channel/podcast/site and that it is still active. Then, if the brief clearly deserves it, add up to 3 sources the
shortlist missed. Keep every description short: gist ≤5 words, why ≤20 words, angle ≤12 words.

Output ONLY JSON: {"fixes": [{"name": str, "url": str, "start_with": [{"title": str, "url": str}]}],
                   "added": [ same shape as the shortlist items ], "note": str}
Never invent URLs."""


def _parse(text: str) -> dict[str, Any]:
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(), flags=re.S)
    s, e = text.find("{"), text.rfind("}")
    try:
        return json.loads(text[s:e + 1]) if s >= 0 else {}
    except ValueError:
        log.warning("discover: unparseable model output: %s", text[:300])
        return {}


def _items(raw: list[Any]) -> list[dict[str, Any]]:
    items = []
    for d in raw or []:
        if not isinstance(d, dict) or not d.get("name"):
            continue
        items.append({
            "name": str(d.get("name"))[:120], "kind": str(d.get("kind") or "youtube_channel"), "url": str(d.get("url") or ""),
            "known_for": str(d.get("gist") or d.get("known_for") or "")[:80], "why": str(d.get("why") or "")[:300], "angle": str(d.get("angle") or "")[:160],
            "start_with": [x for x in (d.get("start_with") or []) if isinstance(x, dict) and x.get("title")][:3],
            "fit": int(d.get("fit") or 3), "depth": str(d.get("depth") or ""),
        })
    return items


def discover(project_id: str, refine: str | None = None, count: int = 10,
             progress: Any = None) -> dict[str, Any]:
    """Two passes: a quick one from the model's own knowledge (results appear in ~10 s), then a short web-search
    pass that verifies URLs and adds what the quick pass missed."""
    project = db.get_project(project_id)
    if not project:
        raise RuntimeError("project not found")
    from . import providers, usage

    providers.require_anthropic()

    existing = [s for s in db.list_sources(limit=100000) if s["id"] in set(db.project_source_ids(project_id, ready_only=False))]
    channels = sorted({s.get("channel") for s in existing if s.get("channel")})
    prior = [d["name"] for d in db.list_discoveries(project_id)]
    user = [f"PROJECT: {project['name']}", db.project_steering(project)]
    if channels:
        user.append("ALREADY IN THE PROJECT (do not repeat): " + ", ".join(channels[:40]))
    if prior:
        user.append("ALREADY SUGGESTED EARLIER (do not repeat unless refinement asks): " + ", ".join(prior[:40]))
    if refine:
        user.append(f"REFINEMENT FROM THE USER: {refine}")
    brief = "\n".join(user)

    usage.guard(0.15)
    client = providers.anthropic_client(timeout=180.0, max_retries=2)

    # ---- pass 1: instant shortlist (no tools) ----
    if progress:
        progress(0.1, "first take from what the model already knows…")
    resp = client.messages.create(model=settings.answer_model, max_tokens=3500, system=QUICK_SYSTEM,
                                  messages=[{"role": "user", "content": brief + f"\n\nPropose about {count} sources now."}],
                                  extra_headers={"x-neurosearch-task": "discover.quick"})
    usage.record_anthropic(resp, "discover", project_id=project_id)
    data = _parse("".join(getattr(b, "text", "") for b in resp.content if getattr(b, "type", "") == "text"))
    items = _items(data.get("sources") or [])
    saved = db.add_discoveries(project_id, items, note=str(data.get("note") or ""), refine=refine)
    if progress:
        progress(0.45, f"{len(saved)} suggestions ready — verifying links on the web…")

    # ---- pass 2: verify + top up (few searches, short output) ----
    fixed, added = 0, 0
    try:
        shortlist = [{"name": d["name"], "kind": d["kind"], "url": d.get("url") or ""} for d in saved]
        msgs: list[dict[str, Any]] = [{"role": "user", "content": brief + "\n\nSHORTLIST TO CHECK:\n" + json.dumps(shortlist, ensure_ascii=False)}]
        text = ""
        for turn in range(4):
            resp = client.messages.create(
                model=settings.answer_model, max_tokens=2500, system=VERIFY_SYSTEM,
                tools=[{"type": "web_search_20260209", "name": "web_search", "max_uses": 5}], messages=msgs,
                extra_headers={"x-neurosearch-task": "discover.verify"})
            usage.record_anthropic(resp, "discover", project_id=project_id)
            text = "".join(getattr(b, "text", "") for b in resp.content if getattr(b, "type", "") == "text").strip()
            if getattr(resp, "stop_reason", None) == "pause_turn":
                msgs = msgs + [{"role": "assistant", "content": resp.content}]
                continue
            break
        v = _parse(text)
        by_name = {d["name"].lower(): d for d in saved}
        for f in v.get("fixes") or []:
            if not isinstance(f, dict):
                continue
            d = by_name.get(str(f.get("name", "")).lower())
            if d and (f.get("url") or f.get("start_with")):
                db.update_discovery(d["id"], url=f.get("url") or None,
                                    start_with=[x for x in (f.get("start_with") or []) if isinstance(x, dict) and x.get("title")][:3] or None)
                fixed += 1
        extra = db.add_discoveries(project_id, _items(v.get("added") or []), note=str(v.get("note") or data.get("note") or ""), refine=refine)
        added = len(extra)
        saved = saved + extra
    except Exception as e:  # noqa: BLE001
        log.warning("discover verification pass failed (shortlist kept): %s", e)
    note = str(data.get("note") or "")
    return {"added": len(saved), "verified": fixed, "extra": added, "note": note, "items": saved}
