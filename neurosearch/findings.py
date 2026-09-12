"""Suggested findings: read a whole transcript against the project brief and propose findings for approval.

Also scores each source for substance (how much of it is actual content vs. fluff) and writes a one-paragraph
summary, so long lists of videos can be triaged at a glance.
"""
from __future__ import annotations

import json
import logging
import re
import threading
from typing import Any

from . import db, providers
from .chunking import fmt_locator
from .config import settings
from .search import deep_link

log = logging.getLogger(__name__)

WINDOW_CHARS = 60000  # ~15k tokens of transcript per call

# D1 (0.39.0) — the cap on suggested findings is LENGTH-AWARE: a 3-hour course or a book is not a 10-minute clip. Everything
# the model produced and the quote validator accepted is kept: the top `cap_for(windows)` become suggestions, every window
# contributes at least COVERAGE_FLOOR of its own (the last hour is never crowded out by the first), and the remainder land
# as `reserve` notes — never exported, never planned on, never harvested into Claims until the user promotes them.
# F4 (0.58.1): the cap is configurable, and its default is higher than it was.
#
# The cap was doing two jobs. One is real — stop a book from burying a project in 900 notes. The other was quality
# control it was never equipped for: it withheld findings ALREADY PAID FOR (`reserve`) on the basis of source
# length, which correlates with nothing about whether a finding is good. 0.58.0 built the check that actually
# answers that question (`findings_quality`), so the cap can go back to being only the first job.
#
# Measured on Kyle's live corpus 2026-09-10: length-matched to 10-40 minute sources, Haiku produced 15.6 findings
# per source against Sonnet 5's 11.3, and the raw 8x reserve gap (11.5% vs 1.4%) collapsed to 0.6% -> 1.1% once
# source length was controlled. In other words the old base of 12 was clipping ordinary sources, not just books.
#
# The previous values are the documented fallback: NEUROSEARCH_FINDINGS_CAP_BASE=12,
# NEUROSEARCH_FINDINGS_CAP_PER_WINDOW=8, NEUROSEARCH_FINDINGS_CAP_MAX=120 restores 0.58.0 behaviour exactly, with
# no code change. Raising a cap can only ever ADD notes; nothing already stored moves or disappears.
def _cap_env(name: str, default: int) -> int:
    import os
    try:
        v = int(os.environ.get(f"NEUROSEARCH_FINDINGS_{name}", "") or default)
    except ValueError:
        return default
    return v if v > 0 else default


CAP_BASE = _cap_env("CAP_BASE", 20)              # was 12
CAP_PER_WINDOW = _cap_env("CAP_PER_WINDOW", 12)  # was 8
CAP_MAX = _cap_env("CAP_MAX", 200)               # was 120
CAP_DEFAULTS_BEFORE = {"base": 12, "per_window": 8, "max": 120}   # what release-check and `doctor` report against
COVERAGE_FLOOR = 3


def cap_for(n_windows: int) -> int:
    return min(CAP_MAX, CAP_BASE + CAP_PER_WINDOW * max(0, n_windows - 1))


def select_findings(per_window: list[list[dict[str, Any]]], cap: int | None = None) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """(suggested, reserve) from validated findings grouped by window. Deterministic: per-window importance order, then
    global importance order with window index as the tie-break (earlier first) — a one-window source is exactly the old
    top-N by importance."""
    n = len(per_window)
    cap = cap if cap is not None else cap_for(n)
    tagged = [(int(f.get("importance") or 0), i, j, f) for i, ws in enumerate(per_window) for j, f in enumerate(ws)]
    chosen: list[tuple[int, int]] = []
    if n > 1:
        for i, ws in enumerate(per_window):
            ranked = sorted(range(len(ws)), key=lambda j: (-int(ws[j].get("importance") or 0), j))
            chosen.extend((i, j) for j in ranked[:COVERAGE_FLOOR])
    order = sorted(tagged, key=lambda t: (-t[0], t[1], t[2]))
    picked = set(chosen)
    for imp, i, j, f in order:
        if len(picked) >= max(cap, len(chosen)):
            break
        picked.add((i, j))
    sug = [f for imp, i, j, f in order if (i, j) in picked]
    res = [f for imp, i, j, f in order if (i, j) not in picked]
    return sug, res
TASK = {"x-neurosearch-task": "findings.extract"}


def prompt_version() -> str:
    import hashlib
    return "findings-" + hashlib.sha1(SYSTEM.encode()).hexdigest()[:8]


def schema_version() -> str | None:
    from .contracts import contract
    return contract("findings.extract").schema


def input_hash(project: dict[str, Any] | str, source_id: str, depth: str | None = None) -> str:
    """Hash of exactly what this task reads: the transcript (source revision), the steering text (brief revision), the
    prompt, output schema, configured model contract and reading depth. Staleness compares this, not database rows."""
    from .contracts import contract
    c = contract("findings.extract")
    base = db._sha("findings", db.source_revision(source_id), db.brief_revision(project), prompt_version(),
                   schema_version() or "text", c.model, c.local_model, c.thinking, c.effort, c.max_output_tokens)
    return db._sha(base, "deep") if depth == "deep" else base


def work_unit_key(project: dict[str, Any], src: dict[str, Any], window: str, index: int, count: int,
                  depth: str | None = None) -> str:
    """Identity of one exact Findings request, including every input that can change its meaning or output."""
    import os
    from .contracts import contract
    c = contract("findings.extract")
    head = _head(project, src)
    fake_controls = sorted((k, v) for k, v in os.environ.items() if providers.fake() and k.startswith("NEUROSEARCH_FAKE_AI_"))
    request = {
        "system": _system_blocks(SYSTEM, head),
        "user": _user(index, count, window, depth=depth),
        "contract": {
            "task": c.task,
            "provider": c.provider,
            "model": c.model,
            "local_model": c.local_model,
            "thinking": c.thinking,
            "effort": c.effort,
            "max_output_tokens": c.max_output_tokens,
            "schema": c.schema,
        },
        "execution": {"policy": providers.current_policy(), "profile": settings.ai_profile, "fake": providers.fake(),
                      "fake_controls": fake_controls},
        "source_revision": db.source_revision(src["id"]),
        "brief_revision": db.brief_revision(project),
        "facts_revision": db.facts_revision(project["id"]),
        "depth": depth,
    }
    return db._sha("work-unit-v1", request)


# D2 (0.39.0) — "Read deeper": a second, explicit pass over long-form sources with smaller windows (≈3× the attention per
# minute) and a depth instruction in the USER message; the frozen system prompt is untouched, so ordinary analyses, their
# hashes and Tier 1 do not change. A deep analysis records depth="deep" and is current on its own terms.
DEEP_WINDOW_CHARS = 20000
DEPTH_INSTRUCTION = ("This is a long-form, information-dense source (a book, course, podcast or long interview). Read this part closely and "
                     "extract EVERY distinct, specific finding it contains — aim for 10–20 for this part: each number, step, condition, "
                     "rule of thumb, named example, warning and disagreement on its own. Do not summarise several points into one finding.")
LONG_SOURCE_SECONDS = 45 * 60

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
    m = re.match(r"(?:p\.?|§|section|sheet|post|comment)\s*(\d+)", ts, flags=re.I)
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
    if len(nums) == 1 and platform in ("document", "web", "spreadsheet", "book", "community"):
        return float(nums[0])
    return None


def _windows(segs: list[dict[str, Any]], platform: str, source_id: str | None = None, window_chars: int = WINDOW_CHARS) -> list[str]:
    if platform == "book" and source_id:
        # G6P2: the index, copyright and title pages never earn a model window; back matter goes after the body
        from .epub import SKIP_FOR_FINDINGS, role_weight, section_roles
        roles = section_roles(source_id)
        segs = [s for s in segs if roles.get(int(s["start"]), "body") not in SKIP_FOR_FINDINGS]
        segs = sorted(segs, key=lambda s: (-role_weight(roles.get(int(s["start"]))), s["start"]))
    lines = [f"[{fmt_locator(platform, s['start'])}] {s['text']}" for s in segs]
    out, cur, size = [], [], 0
    for ln in lines:
        if cur and size + len(ln) > window_chars:
            out.append("\n".join(cur)); cur, size = [], 0
        cur.append(ln); size += len(ln) + 1
    if cur:
        out.append("\n".join(cur))
    return out


_last_model: dict[str, str] = {}
_last_call: dict[str, Any] = {}          # diagnostics of the most recent window call (for OBSERVER; never changes behaviour)
_call_state = threading.local()          # R5: authoritative per-call state; globals above remain diagnostic compatibility mirrors


def _call_diagnostics() -> dict[str, Any]:
    return dict(getattr(_call_state, "diagnostics", {}) or _last_call)


def _call_model() -> str | None:
    return getattr(_call_state, "model", None) or _last_model.get("model")
OBSERVER: Any = None                     # evals hook: called with one dict per transcript window (see suggest_for_source)


HEAD_SEP = "\n\n"


def _system_blocks(system: str, head: str, ttl: str | None = None) -> list[dict[str, Any]]:
    """Cache order (Rung G layout): [rules] [project framing → breakpoint] [source framing → breakpoint]. The project
    framing is identical for every source of a project, so bulk analysis shares one cached prefix (when rules +
    project reach the provider's minimum); the source framing is shared by the windows of a multi-window source.
    Identical block layout on both transports; only the cache duration differs (batches ask for the 1h cache)."""
    from . import usage
    if not head:
        return [usage.cached_block(system, ttl=ttl)]
    project_part, sep, source_part = head.partition(HEAD_SEP)
    if not sep:
        return [{"type": "text", "text": system}, usage.cached_block(head, min_chars=len(system), ttl=ttl)]
    return [{"type": "text", "text": system},
            usage.cached_block(project_part + "\n", min_chars=len(system), ttl=ttl),
            usage.cached_block(source_part, min_chars=len(system) + len(project_part) + 1, ttl=ttl)]


def _head(project: dict[str, Any], src: dict[str, Any]) -> str:
    """Project framing, HEAD_SEP, source framing — split into two cached blocks by _system_blocks."""
    brief = project.get("brief") or "(no brief — extract the most substantive, reusable findings)"
    return (f"PROJECT: {project['name']}\nBRIEF: {brief}\n{db.project_steering(project)}{HEAD_SEP}"
            f"SOURCE: {src['title']} ({src.get('channel') or src['platform']})\n")


def _user(i: int, n: int, window: str, depth: str | None = None) -> str:
    part = f" (part {i + 1}/{n})" if n > 1 else ""
    tail = (DEPTH_INSTRUCTION + "\n\n") if depth == "deep" else ""
    return f"TRANSCRIPT{part}:\n{window}\n\n{tail}Extract the findings now."


def canonical_requests(project_id: str, source_id: str) -> list[dict[str, Any]]:
    """The exact request content suggest_for_source sends for this source right now — one {system, messages} per
    transcript window, built from the same helpers — so a provider token count over these is the count of the real
    requests (E2 tokenizer deltas)."""
    project, src = db.get_project(project_id), db.get_source(source_id)
    if not project or not src:
        return []
    windows = _windows(db.get_segments(source_id), src["platform"], source_id)
    head = _head(project, src)
    return [{"system": _system_blocks(SYSTEM, head), "messages": [{"role": "user", "content": _user(i, len(windows), w)}]} for i, w in enumerate(windows)]


def _call(system: str, user: str, project_id: str | None = None, source_id: str | None = None, head: str = "") -> dict[str, Any]:
    """`head` (project + source framing) is sent as a second system block ending a cached prefix, so the second and
    later windows of a long transcript, and every source analysed for the same project within a few minutes, only
    pay a tenth for those instructions."""
    from . import providers, usage

    from .contracts import contract
    sys_blocks = _system_blocks(system, head)
    c = contract("findings.extract")
    messages = [{"role": "user", "content": user}]
    diagnostics = {"structured": bool(c.schema), "parse": "strict", "truncated": False, "empty": False}
    _call_state.diagnostics = diagnostics
    _last_call.clear()
    _last_call.update(diagnostics)
    if c.schema:
        # Mission F path: provider-enforced schema → json.loads → full local validation. No legacy parsing here.
        try:
            out = providers.invoke_structured("findings.extract", system=sys_blocks, messages=messages, usage_kind="findings", project_id=project_id,
                                              source_id=source_id, guard_estimate=usage.estimate_findings(len(user)), legacy=_legacy_parse)
        except providers.OutputError as e:
            diagnostics.update({"parse": "failed", "truncated": e.kind == providers.OutputError.TRUNCATED, "stop_reason": "max_tokens" if e.kind == "TRUNCATED" else e.kind.lower()})
            _last_call.update(diagnostics)
            raise
        resp = providers.last_response()
        _call_state.model = str(getattr(resp, "model", None) or settings.answer_model)
        _last_model["model"] = _call_state.model
        diagnostics.update({"stop_reason": getattr(resp, "stop_reason", None), "output_tokens": int(getattr(getattr(resp, "usage", None), "output_tokens", 0) or 0)})
        _last_call.update(diagnostics)
        return out
    # legacy/unstructured contract (NEUROSEARCH_TASK_SCHEMA_FINDINGS_EXTRACT=none): the pre-F tolerant path
    usage.guard(usage.estimate_findings(len(user)))
    resp = providers.invoke("findings.extract", system=sys_blocks, messages=messages)
    usage.record_anthropic(resp, "findings", project_id=project_id, source_id=source_id)
    _call_state.model = str(getattr(resp, "model", settings.answer_model))
    _last_model["model"] = _call_state.model
    raw = providers.text_of(resp).strip()
    u = getattr(resp, "usage", None)
    diagnostics.update({"stop_reason": getattr(resp, "stop_reason", None), "output_tokens": int(getattr(u, "output_tokens", 0) or 0),
                        "truncated": getattr(resp, "stop_reason", None) == "max_tokens", "empty": not raw})
    _last_call.update(diagnostics)
    return _legacy_parse(raw)


def _legacy_parse(raw: str) -> dict[str, Any]:
    """The pre-Mission-F tolerant parser: fences, surrounding prose, first { … last }. Emergency fallback only."""
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw, flags=re.S)
    s, e = text.find("{"), text.rfind("}")
    if s < 0:
        _last_call["parse"] = "no_json"
        return {}
    if text[s:e + 1] != raw:
        _last_call["parse"] = "repaired"             # fences or surrounding prose had to be stripped
    try:
        return json.loads(text[s:e + 1])
    except ValueError:
        _last_call["parse"] = "failed"
        raise


def is_current(project: dict[str, Any], source_id: str, depth: str | None = None) -> bool:
    """Current for the depth asked: an ordinary request is satisfied by an ordinary OR a deep analysis of the same inputs; a
    deep request only by a deep one."""
    prev = db.get_analysis(project["id"], source_id, "summary")
    if not prev or prev.get("status") != "current":
        return False
    prev_depth = prev.get("depth") or None
    if depth == "deep" and prev_depth != "deep":
        return False
    return prev.get("input_hash") == input_hash(project, source_id, depth=prev_depth)


def _skipped(project_id: str, source_id: str, src: dict[str, Any]) -> dict[str, Any]:
    prev = db.get_analysis(project_id, source_id, "summary") or {}
    n = len([x for x in db.list_project_notes(project_id, status="suggested") if x.get("source_id") == source_id])
    return {"source_id": source_id, "title": src["title"], "suggested": n, "substance": prev.get("substance"),
            "summary": prev.get("summary"), "rejected_quotes": 0, "skipped": "already current for these inputs"}


def materialize(project_id: str, source_id: str, window_results: list[tuple[str, dict[str, Any]]], *, model: str | None,
                transport: str = "interactive", batch_id: str | None = None, max_findings: int | None = None, prefilter: dict[str, Any] | None = None,
                depth: str | None = None, routing: str | None = None, r6_wave: str | None = None,
                r6_provisional: bool = False) -> dict[str, Any]:
    """Turn validated per-window outputs into the stored research artifact — the ONE place findings become notes and an
    analysis, shared by the interactive and the batch path. `window_results` = [(window_text, parsed_output), …] in
    window order; quote validation, note shaping, provenance and the atomic write are identical either way; only the
    transport-specific provenance (transport, batch_id, model id as returned) differs, explicitly."""
    from .evidence import evidence_for, locate_quote
    from .jobs import crash_point
    project = db.get_project(project_id)
    src = db.get_source(source_id)
    if not project or not src:
        raise RuntimeError("project or source not found")
    platform = src["platform"]
    # 0.63.9 — a quote is evidence if it is in the SOURCE, not only in the window the model happened to be given.
    # Measured on Kyle's 200 most recent rejections: 105 of them (53%) were quotes that really are in the
    # transcript. Windows are cut at WINDOW_CHARS on a line boundary, so a quote straddling one can never verify.
    segs = db.get_segments(source_id)
    source_text = " ".join((sg.get("text") or "") for sg in segs)
    all_findings: list[dict[str, Any]] = []
    per_window: list[list[dict[str, Any]]] = []
    summaries: list[str] = []
    substances: list[int] = []
    rejected = 0
    n_windows = len(window_results)
    for i, (w, res) in enumerate(window_results):
        call_diagnostics = dict(res.pop("_neurosearch_call_diagnostics", {}) or {})
        if res.get("summary"):
            summaries.append(str(res["summary"]))
        if isinstance(res.get("substance"), (int, float)):
            substances.append(int(res["substance"]))
        kept_before, rejected_before = len(all_findings), rejected
        per_window.append([])
        for f in res.get("findings") or []:
            if not (isinstance(f, dict) and f.get("finding")):
                continue
            ev = evidence_for(f, w, source_text)   # the quote must be in the transcript — no quote, no finding
            why = ev["reason"]
            if not why and ev["scope"] == "source":
                # The model was reading a different part of the transcript, so its own locator describes a place it
                # was not looking at. The true one is recoverable, and a corrected citation is better than none.
                at = locate_quote(f.get("quote") or "", segs)
                if at is not None:
                    f["ts"] = fmt_locator(platform, at)
                    f["_relocated"] = True
            if why:
                rejected += 1
                log.info("finding rejected (%s): %s", why, str(f.get("title") or f.get("finding"))[:80])
                db.validation_event("finding_validation_failed", {"candidate_title": f.get("title"), "candidate_quote": f.get("quote"),
                                                                  "candidate_finding": f.get("finding"), "claimed_locator": f.get("ts"),
                                                                  "reason": why, "window": i + 1, "windows": n_windows, "transport": transport},
                                    project_id=project_id, source_id=source_id, prompt_version=prompt_version())
                continue
            all_findings.append(f)
            per_window[-1].append(f)
        if OBSERVER:
            OBSERVER({"source_id": source_id, "window": i + 1, "windows": n_windows, "raw_findings": len(res.get("findings") or []),
                      "kept": len(all_findings) - kept_before, "rejected": rejected - rejected_before,
                      "summary_ok": bool(str(res.get("summary") or "").strip()), "substance_ok": isinstance(res.get("substance"), (int, float)) and 0 <= res["substance"] <= 100,
                      **(call_diagnostics or _last_call), "transport": transport})
    for f in all_findings:
        if f.pop("_relocated", False):
            db.kv_bump("evidence:quote_relocated")
    if rejected:
        db.kv_bump("evidence:findings_rejected", rejected)
    db.kv_bump("evidence:findings_checked", rejected + len(all_findings))
    chosen, reserve = select_findings(per_window, cap=max_findings)
    notes = []
    uncitable = 0
    from_quote = 0
    for f in chosen + reserve:
        start = _ts_to_seconds(str(f.get("ts", "")), platform)
        if start is None:
            # 0.63.22 — the quote is already VERIFIED to be in this source at this point, so its position is a
            # fact we hold, not something to take the model's word for. Before this, a locator the parser could
            # not read meant the finding was stored with NO citation at all — silently, with no event and no
            # counter, so an uncited finding was indistinguishable from a cited one.
            #
            # Measured on Kyle's corpus: **51.5% of spreadsheet findings (69 of 134) and 100% of community
            # findings (9 of 9)** had empty citations, against **0.0%** for YouTube, web, document, book, file,
            # media and Instagram. The cause is in his own rejection log: on a spreadsheet the model writes the
            # sheet by NAME — `§ Reverse Calculator`, `§ Sheet: Profile` — because a sheet's name is the
            # meaningful thing about it and its ordinal is not. No digits, so `_ts_to_seconds` returns None.
            # `locate_quote` needs no per-platform parsing and no model call, and it answers for every platform.
            at = locate_quote(f.get("quote") or "", segs)
            if at is not None:
                start, f["ts"] = at, fmt_locator(platform, at)
                from_quote += 1
        cites = []
        if start is not None:
            from .search import locator_for
            label, link = locator_for(source_id, src["url"], platform, start) if platform in ("book", "community") else (fmt_locator(platform, start), deep_link(src["url"], platform, start))
            cites.append({"n": 1, "source_id": source_id, "title": src["title"], "channel": src.get("channel"),
                          "url": src["url"], "link": link,
                          "timestamp": label, "start": start, "end": start, "platform": platform,
                          "snippet": (f.get("quote") or "")[:300]})
        if not cites:
            # Neither the model's locator nor the quote could be placed. The finding keeps its verified quote, so
            # it is not discarded — but it can never be cited, `harvest` would turn it into a Claim resting on
            # nothing, and that has to be VISIBLE rather than inferred from an empty list later.
            uncitable += 1
            db.validation_event("finding_uncitable", {"title": f.get("title"), "claimed_locator": f.get("ts"),
                                                      "quote": (f.get("quote") or "")[:200], "platform": platform},
                                project_id=project_id, source_id=source_id, prompt_version=prompt_version())
        content = f["finding"].strip()
        if cites and "[1]" not in content:
            content += " [1]"
        notes.append({"title": (f.get("title") or "").strip()[:120] or None, "content": content, "citations": cites,
                      "importance": int(f.get("importance") or 0), "status": "suggested" if len(notes) < len(chosen) else "reserve"})
    if from_quote:
        db.kv_bump("evidence:locator_from_quote", from_quote)
    if uncitable:
        db.kv_bump("evidence:findings_uncitable", uncitable)
    # The citable count exists so the RATE has a denominator from the same period as its numerator. 0.63.23 derived
    # it from `findings_checked`, an all-time counter standing at 25,709 on Kyle's machine, against an uncitable
    # count that started at zero that morning — so it read 100% while 79 uncited findings sat in his library. A
    # rate whose two halves measure different windows flatters, which is the fault this pair of counters exists to
    # expose (0.63.24).
    citable = len(chosen) + len(reserve) - uncitable
    if citable > 0:
        db.kv_bump("evidence:findings_citable", citable)
    prov = {"model": model, "provider": "fake" if providers.fake() else "anthropic", "prompt_version": prompt_version(),
            "schema_version": schema_version() or "findings-v1", "source_revision": db.source_revision(source_id), "brief_revision": db.brief_revision(project),
            "facts_revision": db.facts_revision(project_id), "input_hash": input_hash(project, source_id, depth=depth), "transport": transport, "batch_id": batch_id, "depth": depth,
            "prefilter": json.dumps(prefilter) if prefilter else None,
            "routing": routing or providers.routing_json("findings.extract", model), "r6_wave": r6_wave,
            "r6_provisional": 1 if r6_provisional else 0}
    substance = int(sum(substances) / len(substances)) if substances else None
    summary = " ".join(summaries)[:1200] if summaries else None
    with db.batch():                                     # notes + analysis land together or not at all
        n = db.replace_suggestions(project_id, source_id, notes, provenance=prov)
        db.set_source_summary(source_id, summary, substance, project_id=project_id, **prov)
    crash_point("findings_persisted_before_done")
    return {"source_id": source_id, "title": src["title"], "suggested": n, "reserve": len(reserve), "windows": n_windows, "cap": max_findings if max_findings is not None else cap_for(n_windows), "depth": depth,
            "substance": substance, "summary": summary, "rejected_quotes": rejected, "transport": transport, "batch_id": batch_id, "prefilter": prefilter}


def suggest_for_source(project_id: str, source_id: str, max_findings: int | None = None, force: bool = False, depth: str | None = None,
                       progress=None, r6_wave: str | None = None, r6_provisional: bool = False) -> dict[str, Any]:
    """Extract candidate findings for one source in the context of one project (interactive transport). Stores them as
    'suggested'. Idempotent: if a current analysis exists for exactly these inputs (input_hash) the work is skipped, so a
    retried or duplicated job never pays twice; force=True re-analyses regardless."""
    project = db.get_project(project_id)
    src = db.get_source(source_id)
    if not project or not src:
        raise RuntimeError("project or source not found")
    segs = db.get_segments(source_id)
    if not segs:
        raise RuntimeError("source has no transcript")
    if is_current(project, source_id, depth=depth) and not force:
        return _skipped(project_id, source_id, src)
    # 0.62.6 — WORK IN FLIGHT IS STILL WORK. `is_current` reads the analysis row, so a batch that has been submitted
    # (and charged) but not yet collected is invisible to it, and the ordinary queue reads the source again. Measured:
    # 166 sources re-read on 2026-09-10 for $22.67, every one of them a local pass at midday followed by the batch
    # pass that settled a cohort submitted two days earlier, at identical revisions.
    #
    # This holds even under `force`, because the hash is what makes it safe: a stale rebuild, a brief edit or a deep
    # read all change `input_hash`, so none of them match and none of them are blocked. A match means the answer to
    # exactly this question has already been paid for and is on its way.
    ih = input_hash(project, source_id, depth=depth)
    cov = db.batch_coverage(source_id, ih)
    if cov["covered"]:
        out = _skipped(project_id, source_id, src)
        out["skipped"] = "a batch already covers these exact inputs"
        out["skipped_reason"] = "batch_in_flight"
        out["batch"] = cov
        out["note"] = (f"already bought: {cov['items']} window(s) of this exact analysis are in a batch "
                       f"({cov['waiting']} still with the provider, {cov['collected']} collected and waiting to be "
                       f"written). Re-reading it now would pay twice for the same answer.")
        log.info("findings skipped for %s: batch already covers these inputs (%s)", source_id, cov)
        return out
    head = _head(project, src)
    windows = _windows(segs, src["platform"], source_id, window_chars=DEEP_WINDOW_CHARS if depth == "deep" else WINDOW_CHARS)
    from .jobs import check_cancel, crash_point
    kept, pf_summary = window_plan(project, src, windows)
    results: list[tuple[str, dict[str, Any]]] = []
    found = 0
    last_routing: str | None = None
    source_rev = db.source_revision(source_id)
    brief_rev = db.brief_revision(project)
    facts_rev = db.facts_revision(project_id)

    def _inputs_current() -> bool:
        current_project = db.get_project(project_id)
        return bool(current_project) and db.source_revision(source_id) == source_rev and db.brief_revision(current_project) == brief_rev
    # A progress bar that reads i/n reports the work ALREADY finished, so it shows 0% while the first (often only)
    # part is being read, and never passes (n-1)/n. Kyle, live: "how do I know it's actually doing anything?".
    # Report on both edges instead — starting part i, then finished part i — and never report a bare zero.
    def _say(frac: float, verb: str, i: int) -> None:
        if progress:
            progress(max(0.02, min(0.99, frac)),
                     f"{verb} · part {i + 1}/{len(windows)}" + (f" · {found} finding{'' if found == 1 else 's'} so far" if found else ""))

    reading = "reading deeper" if depth == "deep" else "reading"

    def _run_window(item: tuple[int, str]) -> tuple[str, dict[str, Any], str, str | None, int, bool]:
        i, w = item
        check_cancel()                                   # safe boundary: nothing of this source is written yet
        if not _inputs_current():
            raise RuntimeError("findings inputs changed during analysis; completed compatible windows were kept for retry")
        crash_point("findings_before_response")
        unit_key = work_unit_key(project, src, w, i, len(windows), depth=depth)
        with db.work_unit_lock(unit_key):
            saved = db.work_unit_get(unit_key)
            if saved:
                res = dict(saved["result"])
                routing = res.pop("_neurosearch_work_unit_routing", None)
                return w, res, str(saved["model"]), routing, len(res.get("findings") or []), True
            try:
                res = _call(SYSTEM, _user(i, len(windows), w, depth=depth), project_id, source_id, head=head)
                from .contracts import contract
                c = contract("findings.extract")
                model = _call_model() or c.model
                routing = providers.routing_json("findings.extract", model)
                durable_result = dict(res)
                durable_result["_neurosearch_work_unit_routing"] = routing
                durable_result["_neurosearch_call_diagnostics"] = _call_diagnostics()
                db.work_unit_complete(
                    unit_key, task="findings.extract", project_id=project_id, source_id=source_id,
                    parent_hash=ih, unit_index=i, unit_count=len(windows), model=str(model),
                    prompt_version=prompt_version(), schema_version=schema_version(),
                    source_revision=source_rev, brief_revision=brief_rev,
                    facts_revision=facts_rev, depth=depth, result=durable_result,
                )
                crash_point("findings_window_persisted")
                check_cancel()                           # keep the paid response, but never materialise a cancelled parent
                if not _inputs_current():
                    raise RuntimeError("findings inputs changed during analysis; completed compatible windows were kept for retry")
                res["_neurosearch_call_diagnostics"] = _call_diagnostics()
                return w, res, str(model), routing, len(res.get("findings") or []), False
            except Exception:
                if OBSERVER:
                    OBSERVER({"source_id": source_id, "window": i + 1, "windows": len(windows), "raw_findings": 0, "kept": 0, "rejected": 0,
                              "summary_ok": False, "substance_ok": False, **_call_diagnostics(), "error": True})
                raise

    # R7: embeddings only reorder equivalent work.  The complete kept set is
    # still read, and durable work-unit keys retain original transcript indexes.
    from . import novelty
    residual = novelty.profile(project_id, source_id)
    ordered_indexes = novelty.order_windows(windows, kept, residual)
    items = [(i, windows[i]) for i in ordered_indexes]
    for i, _ in items[:1]:
        _say(i / max(1, len(windows)), reading, i)

    def _completed(index: int, value: tuple[str, dict[str, Any], str, str | None, int, bool]) -> None:
        nonlocal found
        _, _, _, _, count, reused = value
        found += count
        i = items[index][0]
        _say((i + 1) / max(1, len(windows)), "reused" if reused else "read", i)

    from . import concurrency
    from .jobs import current_job
    max_workers = concurrency.limit_for("findings.extract") if current_job()[0] else 1
    from . import usage
    completed_units = concurrency.bounded_map(
        _run_window, items, max_workers=max_workers, completed=_completed,
        estimate=lambda item: usage.estimate_findings(len(_user(item[0], len(windows), item[1], depth=depth))),
    )
    # Materialisation stays in source order even when residual windows were read first.
    results = [(w, res) for _, (w, res, _, _, _, _) in sorted(zip(ordered_indexes, completed_units), key=lambda row: row[0])]
    models = [model for _, _, model, _, _, _ in completed_units]
    routings = [routing for _, _, _, routing, _, _ in completed_units if routing]
    if models:
        _last_model["model"] = models[-1]
    if routings:
        last_routing = routings[-1]
    if not _inputs_current():
        raise RuntimeError("findings inputs changed during analysis; completed compatible windows were kept for retry")
    return materialize(project_id, source_id, results, model=models[-1] if models else _last_model.get("model"), transport="interactive",
                       max_findings=max_findings, prefilter=pf_summary, depth=depth, routing=last_routing,
                       r6_wave=r6_wave, r6_provisional=r6_provisional)


def window_plan(project: dict[str, Any], src: dict[str, Any], windows: list[str]) -> tuple[set[int], dict[str, Any] | None]:
    """Which windows findings.extract will read. Without the H1 pre-filter (default): all of them. With it
    (NEUROSEARCH_FINDINGS_PREFILTER=1): every window the cheap filter did not confidently DROP — keep and uncertain
    both go to the extractor, and every failure of the filter fails open. Returns (kept indexes, filter summary)."""
    from . import prefilter
    if not prefilter.enabled() or not windows:
        return set(range(len(windows))), None
    rows = prefilter.decide_windows(project, src, windows)
    kept = {r["window_index"] for r in rows if r["decision"] != "drop"}
    return kept, prefilter.summary(rows)


def batch_requests(project_id: str, source_id: str) -> list[dict[str, Any]]:
    """The logical work items of one source for a batch cohort: one per transcript window, each with a stable custom_id
    (source + window + input hash — the same inputs always map to the same id) and the exact params the interactive
    path would send, except the cached head block asks for the 1-hour cache so items of a cohort can share it."""
    from . import usage
    from .contracts import contract
    project, src = db.get_project(project_id), db.get_source(source_id)
    if not project or not src:
        return []
    segs = db.get_segments(source_id)
    windows = _windows(segs, src["platform"], source_id)
    head = _head(project, src)
    ih = input_hash(project, source_id)
    c = contract("findings.extract")
    kept, pf_summary = window_plan(project, src, windows)
    out = []
    for i, w in enumerate(windows):
        if i not in kept:
            continue
        params = providers.batch_params("findings.extract", system=_system_blocks(SYSTEM, head, ttl="1h"), messages=[{"role": "user", "content": _user(i, len(windows), w)}])
        out.append({"custom_id": f"fw-{source_id[:12]}-{i}-{ih[:12]}", "task": "findings.extract", "project_id": project_id, "source_id": source_id,
                    "window_index": i, "windows": len(kept), "window_text": w, "params": params, "schema": c.schema, "prefilter": pf_summary})
    return out


def is_long(src: dict[str, Any], n_segments: int | None = None) -> bool:
    """A source worth a deep read: a book, or media over LONG_SOURCE_SECONDS, or a document/page long enough for more than one window."""
    if src.get("platform") == "book":
        return True
    if (src.get("duration") or 0) >= LONG_SOURCE_SECONDS:
        return True
    return False


def suggest_for_project(project_id: str, source_ids: list[str] | None = None, progress=None, force: bool = False, depth: str | None = None,
                        r6_wave: str | None = None, r6_provisional: bool = False) -> dict[str, Any]:
    ids = source_ids or db.sources_needing_suggestions(project_id)
    done, failed = 0, []
    for i, sid in enumerate(ids):
        if progress:
            progress(i / max(len(ids), 1), f"reading {i + 1}/{len(ids)}")
        title = (db.get_source(sid) or {}).get("title") or sid[:8]

        def sub(frac: float, msg: str, _i=i, _title=title) -> None:          # per-window progress inside the per-source progress
            if progress:
                progress(max(0.02, (_i + frac) / max(len(ids), 1)), (f"{_i + 1}/{len(ids)} · " if len(ids) > 1 else "") + msg + f" — {_title[:50]}")
        try:
            suggest_for_source(project_id, sid, force=force, depth=depth, progress=sub, r6_wave=r6_wave, r6_provisional=r6_provisional)
            done += 1
        except Exception as e:  # noqa: BLE001
            from .breakers import ProviderUnavailable
            from .usage import BudgetPaused
            if isinstance(e, (BudgetPaused, ProviderUnavailable)):
                # hand the remaining sources back to the queue as a fresh job and stop
                remaining = ids[i:]
                db.create_job("suggest_findings", {"project_id": project_id, "source_ids": remaining, "depth": depth})
                raise
            log.warning("suggest failed for %s: %s", sid, e)
            failed.append(sid)
    return {"sources": len(ids), "done": done, "failed": len(failed)}
