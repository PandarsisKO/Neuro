"""Discover sources: who should this project be learning from?

Uses Claude with live web search to propose the leading creators, channels, podcasts and publications for
the project's brief — with why each matters, their angle, and a starting video — so someone who doesn't know
the space can get going. Results are stored per project; the user adds, dismisses or refines.
"""
from __future__ import annotations

import json
import logging
import re
import time
from typing import Any
from urllib.parse import urlparse

from . import db
from .config import int_env, settings

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


# ------------------------------------------------------------------ catalogue pass (scholar.py, $0, no model call)

SCHOLAR_MAX = 6                    # a supplement to Discover, never a takeover of it


def scholar_wanted(refine: str | None, research: dict[str, Any]) -> tuple[bool, str]:
    """A catalogue query is worth a free request when the USER asked for literature, or when an open evidence target
    already declares that it needs expert/authoritative evidence AND its own question reads like a literature
    question (scholar.target_wants_literature — 2026-09-20). It is deliberately NOT run for every project: a corpus
    of YouTube channels about editing workflow gets nothing from Crossref, and adding unrelated papers to that
    review card is exactly the noise the user asked to avoid."""
    from . import scholar
    if refine and scholar.SCHOLAR_HINT.search(refine):
        return True, "you asked for research literature"
    for t in (research.get("targets") or [])[:12]:
        if scholar.target_wants_literature(t):
            return True, f"an open question needs expert or authoritative evidence: {str(t.get('question'))[:80]}"
    return False, ""


def scholar_pass(project: dict[str, Any], refine: str | None, research: dict[str, Any],
                 progress: Any = None) -> dict[str, Any]:
    """Real records from Crossref/OpenAlex. Nothing here needs `discover.verify`: a catalogue record exists by
    construction, which is the whole reason this pass is cheaper than the model pass it supplements."""
    from . import scholar
    wanted, why_run = scholar_wanted(refine, research)
    if not wanted:
        return {"run": False, "why": "no request for literature and no open question asking for expert evidence"}
    if not scholar.ready_providers():
        a = scholar.available()
        return {"run": False, "why": "no catalogue is configured", "detail": {k: v["why"] for k, v in a.items()}}
    query = _clean_query(refine or db.project_steering(project) or project.get("name") or "")
    if progress:
        progress(0.08, "asking the research catalogues (free)…")
    try:
        recs = scholar.search(query, limit=SCHOLAR_MAX)
    except scholar.ScholarUnavailable as e:
        return {"run": False, "why": f"catalogue unavailable ({e.reason})", "detail": e.detail}
    return {"run": True, "why_run": why_run, "query": query, "found": len(recs),
            "open_access": sum(1 for r in recs if r["oa_pdf_url"]),
            "items": scholar.to_discoveries(recs), "records": recs,
            "providers": sorted({r["provider"] for r in recs})}


# ------------------------------------------------------------------ do the suggested links exist? ($0, 0.60.2)
#
# Kyle: *"discover is routinely suggesting content that has 404 issues. we need to be able to check against that
# instead of giving URLs that are broken"* — with a screenshot of `https://37signals.com/blog` failing 404 after he
# pressed Add. Both halves of that are worth naming. Discover's first pass proposes sources from the model's own
# memory, so a URL it returns is a REMEMBERED address: it was probably right once, and blogs move. The paid
# `discover.verify` pass is supposed to catch this, but it is a model with a web-search tool being asked to check a
# list — it does not have to actually fetch anything, and it says a link is fine more readily than it should.
#
# So the check is done here instead, for nothing: one bounded request per URL through the same boundary every other
# fetch uses. A dead address is then a FACT on the row rather than a failed job the user discovers by clicking. And
# on a 404 the site root is tried once, because "the blog moved" is the common case and the root is nearly always
# where it moved to — offered as a suggestion, never substituted silently.
# 0.63.14: 40, was 24. A link check is one HEAD/GET through `safe_fetch` on 4 threads and costs nothing but a
# little network, while an unchecked dead link costs a queued job that fails later. Revert with
# NEUROSEARCH_DISCOVER_LINK_MAX=24.
LINK_MAX = int_env("NEUROSEARCH_DISCOVER_LINK_MAX", 40)     # URLs checked per run: the shortlist plus a couple of start_with links each
LINK_DEADLINE_S = 8.0              # per URL
LINK_STATUSES = ("ok", "not_found", "blocked", "unreachable", "refused", "skipped")


def _origin(url: str) -> str | None:
    try:
        u = urlparse(url)
        return f"{u.scheme}://{u.netloc}/" if u.scheme and u.netloc else None
    except ValueError:
        return None


def check_link(url: str, *, try_root: bool = True) -> dict[str, Any]:
    """Does this address exist? `status` is one of LINK_STATUSES; `http` is the code when there was one.

    A HEAD would be cheaper but is refused or lied about by enough servers to be worse than useless, so this is a
    GET whose body is thrown away. `blocked` is deliberately distinct from `not_found`: a 403 usually means the
    page is there and the server dislikes us, which is a reason to hand the user the link, not to hide it."""
    from . import safe_fetch as sf
    if not url or not re.match(r"^https?://", url):
        return {"status": "skipped", "reason": "not a web address"}
    try:
        res = sf.safe_fetch(url, content_class="html", deadline_s=LINK_DEADLINE_S)
        code = int(getattr(res, "status", 0) or 0)
        out: dict[str, Any] = {"status": "ok", "http": code, "final_url": getattr(res, "url", url)}
        if code in (404, 410):
            out["status"] = "not_found"
        elif code in (401, 402, 403, 407, 429) or code >= 500:
            out["status"] = "blocked"
        elif code >= 400:
            out["status"] = "blocked"
        if out["status"] == "not_found" and try_root:
            root = _origin(url)
            if root and root.rstrip("/") != url.rstrip("/"):
                r2 = check_link(root, try_root=False)
                if r2.get("status") == "ok":
                    out["suggested_url"] = root
                    out["suggested_why"] = "that address is gone, but the site itself is up"
        return out
    except sf.FetchBlocked as e:
        return {"status": "refused", "reason": e.reason, "detail": str(e)[:160]}
    except Exception as e:  # noqa: BLE001 — a link check must never fail a discover run
        return {"status": "unreachable", "detail": str(e)[:160]}


def check_links(rows: list[dict[str, Any]], *, progress: Any = None) -> dict[str, Any]:
    """Check every saved discovery's URL and record the answer on the row. $0, bounded, and it never changes a URL
    — a suggestion is offered, so a real address that merely looks odd is never thrown away by a machine.

    Skipped under the fake provider (0.61.0): this was the one thing in the app that reached the real network from
    a deterministic test, and it duly made a Tier 1 test flaky by timing rather than by logic. A suite that fails
    for a reason outside the code teaches people to re-run it instead of reading it."""
    from concurrent.futures import ThreadPoolExecutor
    if settings.fake_ai:
        return {"checked": 0, "dead": 0, "by_status": {}, "skipped": "fake provider — no network in tests"}
    todo = [(d["id"], d.get("url") or "") for d in rows if (d.get("url") or "").startswith("http")][:LINK_MAX]
    if not todo:
        return {"checked": 0, "dead": 0, "by_status": {}}
    if progress:
        progress(0.9, f"checking {len(todo)} link{'' if len(todo) == 1 else 's'} actually resolve — free")
    results: dict[int, dict[str, Any]] = {}
    with ThreadPoolExecutor(max_workers=4) as pool:
        for (did, url), res in zip(todo, pool.map(lambda u: check_link(u[1]), todo)):
            results[did] = {**res, "url": url, "checked_at": time.time()}
    by_status: dict[str, int] = {}
    for did, res in results.items():
        by_status[res["status"]] = by_status.get(res["status"], 0) + 1
        try:
            db.update_discovery(did, link_check=res)
        except Exception as e:  # noqa: BLE001
            log.warning("could not record the link check for discovery %s: %s", did, e)
    for d in rows:
        if d["id"] in results:
            d["link_check"] = results[d["id"]]
    dead = sum(n for st, n in by_status.items() if st in ("not_found", "unreachable"))
    return {"checked": len(todo), "dead": dead, "by_status": by_status,
            "note": (f"{dead} of {len(todo)} suggested addresses did not resolve — they are marked rather than "
                     "offered as something to add") if dead else None}


def _clean_query(text: str) -> str:
    """The brief is prose; a catalogue wants terms. Keep it short — a 600-character goal matches nothing."""
    t = re.sub(r"\s+", " ", str(text or "")).strip()
    return t[:240]


MODES = ("library_first", "library_only", "web_first", "web_only", "scholar_only")
# Conservative on purpose (G4 has no Claim/Evidence sufficiency model yet — that is G5): Library-first skips the web
# pass only when several owned sources match STRONGLY with more than one passage each, and even then it says the library
# "appears to cover this well" and offers Web first. Strong relevance is not proof that the project's evidence needs are met.
LIBRARY_ENOUGH = 4            # strong owned sources required before a refine-less Library-first run skips the web pass
LIBRARY_STRONG = 3.0          # × library.MIN_SCORE, and at least two matching passages, to count as strong


def _library_query(project: dict[str, Any], refine: str | None) -> str:
    if refine:
        return refine
    parts = [project.get("goal") or "", " ".join(json.loads(project.get("questions") or "[]") if isinstance(project.get("questions"), str) else (project.get("questions") or [])),
             (project.get("brief") or "")[:400]]
    return " ".join(p for p in parts if p).strip()


def discover(project_id: str, refine: str | None = None, count: int = 10,
             progress: Any = None, verify: bool = True, mode: str = "library_first") -> dict[str, Any]:
    """G4 Library-first Discover: what the user ALREADY OWNS comes first ($0, chunk-level recall over the global library),
    the model/web passes run only when the library does not cover the request (or the mode asks for the web).
    Modes: library_first (default) · library_only · web_first · web_only. Library suggestions are never attached.
    Then the two web passes: a quick one from the model's own knowledge, then a short web-search pass that verifies
    URLs and adds what the quick pass missed (verify=False: pass 1 only — evals)."""
    project = db.get_project(project_id)
    if not project:
        raise RuntimeError("project not found")
    from . import library, providers, usage

    if mode not in MODES:
        raise ValueError(f"unknown discover mode {mode!r}")
    # G5: Discover leads with research STATE — Claims are harvested ($0) and open Evidence Targets steer the passes
    research: dict[str, Any] = {}
    _t_research = time.perf_counter()
    try:
        from . import claims, knowledge
        # 0.62.2: `claims.ensure` here cost 431.6 s of the 432 s a library-only Discover took on Kyle's project —
        # harvesting 17,119 notes, assessing 4,331 Claims and rebuilding the whole knowledge map so that a
        # discovery pass could read some counts and open questions. Steering needs a RECENT map, not a current one.
        cheap = claims.ensure_cheap(project_id)
        st = knowledge.state(project_id)
        research = {"counts": cheap["map"]["counts"], "nodes": cheap["map"]["nodes"][:12], "tensions": st["tensions"][:6],
                    "targets": [t for t in st["targets"] if t["status"] == "open"][:8], "summary": knowledge.summary_text(project_id),
                    "as_of": "current" if cheap.get("computed") else "a moment ago",
                    "refresh_queued": cheap.get("queued")}
    except Exception as e:  # noqa: BLE001
        log.warning("research state unavailable for discover: %s", e)
    try:
        from . import perf as _perf
        _perf.record("discover.research_state", max(0.0, time.perf_counter() - _t_research))
    except Exception:  # noqa: BLE001
        pass
    lib: dict[str, Any] = {"suggestions": [], "query": None}
    if mode != "web_only":
        if progress:
            progress(0.05, "checking what your library already covers…")
        from . import perf
        with perf.timed("discover.library"):
            lib = library.recall(project_id, _library_query(project, refine), limit=8, reason=f"discover: {refine or project.get('name')}")
        try:
            library.maybe_queue_batch()                                   # opportunistic: only if enough wanted profiles piled up
        except Exception as e:  # noqa: BLE001
            log.warning("profile batch not queued: %s", e)
    # 0.62.0: the weak-query judgement built in 0.61.0 lived only in the project-bootstrap scan, so Discover's
    # library pass had no way to say "this search cannot be answered from what you own" and returned eight
    # confident rows for "Modern CPA" instead. A search whose every word is a generic modifier, or whose rarest
    # word is in most of the library, is reported as vague rather than answered — the hits are kept and tagged, so
    # nothing is hidden, but they no longer count as `strong` and cannot suppress the web search below.
    lib_anchor = (lib.get("anchor") or {})
    lib_vague = bool(lib_anchor.get("all_generic") or lib_anchor.get("too_common"))
    # 0.62.4: a project that already holds most of the library's coverage of the subject has an empty library pass by
    # construction, and "no new acquisition needed" is then a false claim about the leftovers. Saturation never
    # suppresses the web search — it is the reason to run it.
    owned = lib.get("owned") or {}
    if owned.get("saturated"):
        lib["saturated"] = owned
    if lib_vague:
        lib["vague_query"] = {"why": lib_anchor.get("reason") or "this search cannot separate one topic from another",
                              "advice": "name the subject rather than describing it — one specific noun beats an adjective",
                              "shown_anyway": len(lib.get("suggestions") or [])}
        for s_ in lib.get("suggestions") or []:
            s_["generic_match"] = True
    # 0.62.5 — THE RUNG THAT WAS MISSING. Kyle's ladder, in his words: things we chose not to ingest but have seen,
    # then the web. `knowledge.pursue` has climbed it since G5; Discover went library → catalogues → web. The seen
    # pool is 10,319 candidates + 558 skipped sources against a library scope of 387.
    seen: dict[str, Any] = {"items": [], "counts": {"candidates": 0, "skipped": 0}}
    if mode != "web_only":
        from . import candidates as _cand
        from . import perf as _perf
        try:
            with _perf.timed("discover.seen"):
                seen = _cand.seen_for_query(project_id, refine or _library_query(project, None))
        except Exception as e:  # noqa: BLE001 — a rung that fails must not take the ladder down
            log.warning("seen-but-not-read pass skipped: %s", e)
        if progress and seen.get("items"):
            progress(0.08, f"{seen['total']} already-seen sources match — none of them cost anything to find")
    strong = [] if (lib_vague or owned.get("saturated")) else [s for s in lib["suggestions"] if s["score"] >= LIBRARY_STRONG * library.MIN_SCORE and len(s.get("chunks") or []) >= 2
              and s.get("coverage", 0) >= library.STRONG_COVERAGE]
    sch = scholar_pass(project, refine, research, progress) if mode != "library_only" else {"run": False, "why": "library_only"}
    sch_saved: list[dict[str, Any]] = []
    if sch.get("run") and sch.get("items"):
        # real records, so they are saved as verified discoveries and never handed to `discover.verify`
        sch_saved = db.add_discoveries(project_id, sch["items"], note=f"from research catalogues ({', '.join(sch['providers'])}) — {sch['why_run']}",
                                       refine=refine, provenance={"model": None, "prompt_version": "scholar-catalogue",
                                                                  "routing": json.dumps({"executed_by": "catalogue", "providers": sch["providers"]})})
        from . import scholar as _scholar
        _scholar.to_candidates(sch["records"], project_id, origin={"kind": "discovery", "query": sch["query"]})
        if progress:
            progress(0.12, f"{len(sch_saved)} real papers from the catalogues ({sch['open_access']} with free full text)")
    if mode == "scholar_only":
        return {"added": len(sch_saved), "verified": len(sch_saved), "extra": 0, "items": sch_saved, "library": lib, "seen": seen,
                "mode": mode, "research": research, "scholar": {k: v for k, v in sch.items() if k != "records"},
                "note": sch.get("why") if not sch.get("run") else
                        f"{len(sch_saved)} records from {', '.join(sch.get('providers') or [])} — every one exists, so none needed verifying."}
    if mode == "library_only" or (mode == "library_first" and not refine and len(strong) >= LIBRARY_ENOUGH):
        note = ("Library only — no web search was run." if mode == "library_only" else
                f"Your library appears to cover this well ({len(strong)} owned sources match strongly, not yet in this project) — the web search was skipped. "
                "This is about relevance, not proof that your evidence needs are met: use 'Web first' to search anyway.")
        open_targets = len(research.get("targets") or [])
        return {"added": 0, "verified": 0, "extra": 0, "note": note, "items": [], "library": lib, "seen": seen, "mode": mode, "web_skipped": True, "research": research,
                "coverage_note": (f"library relevance only — {open_targets} evidence target(s) remain open in the Knowledge Map" if open_targets else "library relevance only; no open evidence targets")}

    providers.require_anthropic()

    existing = [s for s in db.list_sources(limit=100000) if s["id"] in set(db.project_source_ids(project_id, ready_only=False))]
    channels = sorted({s.get("channel") for s in existing if s.get("channel")})
    prior = [d["name"] for d in db.list_discoveries(project_id)]
    user = [f"PROJECT: {project['name']}", db.project_steering(project)]
    if channels:
        user.append("ALREADY IN THE PROJECT (do not repeat): " + ", ".join(channels[:40]))
    if research.get("targets") and not refine:
        user.append("OPEN EVIDENCE TARGETS (prioritise sources that could close these; note the evidence class each needs): " +
                    "; ".join(f"{t['question'][:120]} [{t['sufficiency']}: {', '.join(t.get('preferred_classes') or [])}]" for t in research["targets"][:6]))
    if research.get("tensions") and not refine:
        user.append("OPEN RESEARCH TENSIONS (corroborate or refute, do not assume consensus): " + "; ".join(t["description"][:140] for t in research["tensions"][:4]))
    if prior:
        user.append("ALREADY SUGGESTED EARLIER (do not repeat unless refinement asks): " + ", ".join(prior[:40]))
    if refine:
        user.append(f"REFINEMENT FROM THE USER: {refine}")
    if lib["suggestions"]:
        user.append("ALREADY OWNED IN THE LIBRARY (do not propose these again): " + ", ".join((s.get("title") or s.get("url") or "")[:80] for s in lib["suggestions"][:12]))
    brief = "\n".join(user)

    usage.guard(0.15)

    # ---- pass 1: instant shortlist (no tools) — structured (F3); pass 2 stays on the citation-capable text/tool path ----
    if progress:
        progress(0.1, "first take from what the model already knows…")
    from .contracts import contract
    quick_msgs = [{"role": "user", "content": brief + f"\n\nPropose about {count} sources now."}]
    if contract("discover.quick").schema:
        data = providers.invoke_structured("discover.quick", system=QUICK_SYSTEM, messages=quick_msgs, usage_kind="discover", project_id=project_id,
                                           guard_estimate=0.05, legacy=_parse)
    else:
        resp = providers.invoke("discover.quick", system=QUICK_SYSTEM, messages=quick_msgs)
        usage.record_anthropic(resp, "discover", project_id=project_id)
        data = _parse(providers.text_of(resp))
    items = _items(data.get("sources") or [])
    import hashlib
    returned = getattr(providers.last_response(), "model", None) if contract("discover.quick").schema else getattr(resp, "model", None)
    saved = db.add_discoveries(project_id, items, note=str(data.get("note") or ""), refine=refine,
                               provenance={"model": returned or settings.answer_model, "prompt_version": "discover-" + hashlib.sha1(QUICK_SYSTEM.encode()).hexdigest()[:8],
                                           "routing": providers.routing_json("discover.quick", returned)})
    if progress:
        progress(0.45, f"{len(saved)} suggestions ready — verifying links on the web…")

    # ---- pass 2: verify + top up (few searches, short output) ----
    fixed, added = 0, 0
    scholar_meta = {k: v for k, v in sch.items() if k != "records"}
    if not verify:
        return {"added": len(saved) + len(sch_saved), "verified": len(sch_saved), "extra": 0, "note": str(data.get("note") or ""),
                "items": sch_saved + saved, "quick_only": True, "library": lib, "seen": seen, "mode": mode, "research": research, "scholar": scholar_meta}
    try:
        shortlist = [{"name": d["name"], "kind": d["kind"], "url": d.get("url") or ""} for d in saved]
        msgs: list[dict[str, Any]] = [{"role": "user", "content": brief + "\n\nSHORTLIST TO CHECK:\n" + json.dumps(shortlist, ensure_ascii=False)}]
        text = ""
        for turn in range(4):
            resp = providers.invoke("discover.verify", system=VERIFY_SYSTEM, messages=msgs,
                                    tools=[{"type": "web_search_20260209", "name": "web_search", "max_uses": 5}])
            usage.record_anthropic(resp, "discover", project_id=project_id)
            text = providers.text_of(resp).strip()
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
    links = {"checked": 0, "dead": 0, "by_status": {}}
    try:
        links = check_links(saved, progress=progress)
    except Exception as e:  # noqa: BLE001 — a free check must never cost the run
        log.warning("link check skipped: %s", e)
    note = str(data.get("note") or "")
    if links.get("note"):
        note = (note + " " if note else "") + links["note"] + "."
    if sch_saved:
        note = (note + " " if note else "") + (f"{len(sch_saved)} of these came from research catalogues and did not need verifying "
                                               f"({sch.get('open_access', 0)} have free full text).")
    # catalogue records first: they are real by construction, where the model's suggestions are checked claims about reality
    return {"added": len(saved) + len(sch_saved), "verified": fixed + len(sch_saved), "extra": added, "note": note,
            "items": sch_saved + saved, "library": lib, "seen": seen, "mode": mode, "research": research, "scholar": scholar_meta,
            "links": links}
