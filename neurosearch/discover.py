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


def discover(project_id: str, refine: str | None = None, count: int = 10) -> dict[str, Any]:
    project = db.get_project(project_id)
    if not project:
        raise RuntimeError("project not found")
    if not settings.anthropic_api_key:
        raise RuntimeError("ANTHROPIC_API_KEY is not set")
    import anthropic

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
    user.append(f"\nPropose about {count} sources now.")

    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    resp = client.messages.create(
        model=settings.answer_model, max_tokens=6000, system=SYSTEM,
        tools=[{"type": "web_search_20260209", "name": "web_search", "max_uses": 8}],
        messages=[{"role": "user", "content": "\n".join(user)}],
    )
    try:
        from . import usage
        usage.record_anthropic(resp, "discover", project_id=project_id)
    except Exception:  # noqa: BLE001
        pass
    text = "".join(getattr(b, "text", "") for b in resp.content if getattr(b, "type", "") == "text").strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.S)
    s, e = text.find("{"), text.rfind("}")
    data = json.loads(text[s:e + 1]) if s >= 0 else {"sources": []}
    items = []
    for d in data.get("sources") or []:
        if not isinstance(d, dict) or not d.get("name"):
            continue
        items.append({
            "name": str(d.get("name"))[:120], "kind": str(d.get("kind") or "youtube_channel"), "url": str(d.get("url") or ""),
            "known_for": str(d.get("gist") or d.get("known_for") or "")[:80], "why": str(d.get("why") or "")[:300], "angle": str(d.get("angle") or "")[:160],
            "start_with": [x for x in (d.get("start_with") or []) if isinstance(x, dict) and x.get("title")][:3],
            "fit": int(d.get("fit") or 3), "depth": str(d.get("depth") or ""),
        })
    saved = db.add_discoveries(project_id, items, note=str(data.get("note") or ""), refine=refine)
    return {"added": len(saved), "note": data.get("note"), "items": saved}
