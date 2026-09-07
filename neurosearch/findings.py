"""Suggested findings: read a whole transcript against the project brief and propose findings for approval.

Also scores each source for substance (how much of it is actual content vs. fluff) and writes a one-paragraph
summary, so long lists of videos can be triaged at a glance.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any

from . import db, providers
from .chunking import fmt_locator
from .config import settings
from .search import deep_link

log = logging.getLogger(__name__)

WINDOW_CHARS = 60000  # ~15k tokens of transcript per call
TASK = {"x-neurosearch-task": "findings.extract"}


def prompt_version() -> str:
    import hashlib
    return "findings-" + hashlib.sha1(SYSTEM.encode()).hexdigest()[:8]


def schema_version() -> str | None:
    from .contracts import contract
    return contract("findings.extract").schema


def input_hash(project: dict[str, Any] | str, source_id: str) -> str:
    """Hash of exactly what this task reads: the transcript (source revision), the steering text (brief revision), the
    prompt and (Mission F) the output schema. Staleness compares this, not database rows."""
    return db._sha("findings", db.source_revision(source_id), db.brief_revision(project), prompt_version(), schema_version() or "text")

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
    m = re.match(r"(?:p\.?|§|section|sheet)\s*(\d+)", ts, flags=re.I)
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
    if len(nums) == 1 and platform in ("document", "web", "spreadsheet"):
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


_last_model: dict[str, str] = {}
_last_call: dict[str, Any] = {}          # diagnostics of the most recent window call (for OBSERVER; never changes behaviour)
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


def _user(i: int, n: int, window: str) -> str:
    part = f" (part {i + 1}/{n})" if n > 1 else ""
    return f"TRANSCRIPT{part}:\n{window}\n\nExtract the findings now."


def canonical_requests(project_id: str, source_id: str) -> list[dict[str, Any]]:
    """The exact request content suggest_for_source sends for this source right now — one {system, messages} per
    transcript window, built from the same helpers — so a provider token count over these is the count of the real
    requests (E2 tokenizer deltas)."""
    project, src = db.get_project(project_id), db.get_source(source_id)
    if not project or not src:
        return []
    windows = _windows(db.get_segments(source_id), src["platform"])
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
    _last_call.clear()
    _last_call.update({"structured": bool(c.schema), "parse": "strict", "truncated": False, "empty": False})
    if c.schema:
        # Mission F path: provider-enforced schema → json.loads → full local validation. No legacy parsing here.
        try:
            out = providers.invoke_structured("findings.extract", system=sys_blocks, messages=messages, usage_kind="findings", project_id=project_id,
                                              source_id=source_id, guard_estimate=usage.estimate_findings(len(user)), legacy=_legacy_parse)
        except providers.OutputError as e:
            _last_call.update({"parse": "failed", "truncated": e.kind == providers.OutputError.TRUNCATED, "stop_reason": "max_tokens" if e.kind == "TRUNCATED" else e.kind.lower()})
            raise
        resp = providers.last_response()
        _last_model["model"] = str(getattr(resp, "model", None) or settings.answer_model)
        _last_call.update({"stop_reason": getattr(resp, "stop_reason", None), "output_tokens": int(getattr(getattr(resp, "usage", None), "output_tokens", 0) or 0)})
        return out
    # legacy/unstructured contract (NEUROSEARCH_TASK_SCHEMA_FINDINGS_EXTRACT=none): the pre-F tolerant path
    usage.guard(usage.estimate_findings(len(user)))
    resp = providers.invoke("findings.extract", system=sys_blocks, messages=messages)
    usage.record_anthropic(resp, "findings", project_id=project_id, source_id=source_id)
    _last_model["model"] = str(getattr(resp, "model", settings.answer_model))
    raw = providers.text_of(resp).strip()
    u = getattr(resp, "usage", None)
    _last_call.update({"stop_reason": getattr(resp, "stop_reason", None), "output_tokens": int(getattr(u, "output_tokens", 0) or 0),
                       "truncated": getattr(resp, "stop_reason", None) == "max_tokens", "empty": not raw})
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


def is_current(project: dict[str, Any], source_id: str) -> bool:
    ih = input_hash(project, source_id)
    prev = db.get_analysis(project["id"], source_id, "summary")
    return bool(prev and prev.get("input_hash") == ih and prev.get("status") == "current")


def _skipped(project_id: str, source_id: str, src: dict[str, Any]) -> dict[str, Any]:
    prev = db.get_analysis(project_id, source_id, "summary") or {}
    n = len([x for x in db.list_project_notes(project_id, status="suggested") if x.get("source_id") == source_id])
    return {"source_id": source_id, "title": src["title"], "suggested": n, "substance": prev.get("substance"),
            "summary": prev.get("summary"), "rejected_quotes": 0, "skipped": "already current for these inputs"}


def materialize(project_id: str, source_id: str, window_results: list[tuple[str, dict[str, Any]]], *, model: str | None,
                transport: str = "interactive", batch_id: str | None = None, max_findings: int = 12, prefilter: dict[str, Any] | None = None) -> dict[str, Any]:
    """Turn validated per-window outputs into the stored research artifact — the ONE place findings become notes and an
    analysis, shared by the interactive and the batch path. `window_results` = [(window_text, parsed_output), …] in
    window order; quote validation, note shaping, provenance and the atomic write are identical either way; only the
    transport-specific provenance (transport, batch_id, model id as returned) differs, explicitly."""
    from .evidence import check_finding
    from .jobs import crash_point
    project = db.get_project(project_id)
    src = db.get_source(source_id)
    if not project or not src:
        raise RuntimeError("project or source not found")
    platform = src["platform"]
    all_findings: list[dict[str, Any]] = []
    summaries: list[str] = []
    substances: list[int] = []
    rejected = 0
    n_windows = len(window_results)
    for i, (w, res) in enumerate(window_results):
        if res.get("summary"):
            summaries.append(str(res["summary"]))
        if isinstance(res.get("substance"), (int, float)):
            substances.append(int(res["substance"]))
        kept_before, rejected_before = len(all_findings), rejected
        for f in res.get("findings") or []:
            if not (isinstance(f, dict) and f.get("finding")):
                continue
            why = check_finding(f, w)          # the quote must be in the transcript — no quote, no finding
            if why:
                rejected += 1
                log.info("finding rejected (%s): %s", why, str(f.get("title") or f.get("finding"))[:80])
                db.validation_event("finding_validation_failed", {"candidate_title": f.get("title"), "candidate_quote": f.get("quote"),
                                                                  "candidate_finding": f.get("finding"), "claimed_locator": f.get("ts"),
                                                                  "reason": why, "window": i + 1, "windows": n_windows, "transport": transport},
                                    project_id=project_id, source_id=source_id, prompt_version=prompt_version())
                continue
            all_findings.append(f)
        if OBSERVER:
            OBSERVER({"source_id": source_id, "window": i + 1, "windows": n_windows, "raw_findings": len(res.get("findings") or []),
                      "kept": len(all_findings) - kept_before, "rejected": rejected - rejected_before,
                      "summary_ok": bool(str(res.get("summary") or "").strip()), "substance_ok": isinstance(res.get("substance"), (int, float)) and 0 <= res["substance"] <= 100,
                      **_last_call, "transport": transport})
    if rejected:
        db.kv_bump("evidence:findings_rejected", rejected)
    db.kv_bump("evidence:findings_checked", rejected + len(all_findings))
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
    prov = {"model": model, "provider": "fake" if providers.fake() else "anthropic", "prompt_version": prompt_version(),
            "schema_version": schema_version() or "findings-v1", "source_revision": db.source_revision(source_id), "brief_revision": db.brief_revision(project),
            "facts_revision": db.facts_revision(project_id), "input_hash": input_hash(project, source_id), "transport": transport, "batch_id": batch_id,
            "prefilter": json.dumps(prefilter) if prefilter else None}
    substance = int(sum(substances) / len(substances)) if substances else None
    summary = " ".join(summaries)[:1200] if summaries else None
    with db.batch():                                     # notes + analysis land together or not at all
        n = db.replace_suggestions(project_id, source_id, notes, provenance=prov)
        db.set_source_summary(source_id, summary, substance, project_id=project_id, **prov)
    crash_point("findings_persisted_before_done")
    return {"source_id": source_id, "title": src["title"], "suggested": n, "substance": substance, "summary": summary,
            "rejected_quotes": rejected, "transport": transport, "batch_id": batch_id, "prefilter": prefilter}


def suggest_for_source(project_id: str, source_id: str, max_findings: int = 12, force: bool = False) -> dict[str, Any]:
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
    if is_current(project, source_id) and not force:
        return _skipped(project_id, source_id, src)
    head = _head(project, src)
    windows = _windows(segs, src["platform"])
    from .jobs import check_cancel, crash_point
    kept, pf_summary = window_plan(project, src, windows)
    results: list[tuple[str, dict[str, Any]]] = []
    for i, w in enumerate(windows):
        if i not in kept:                                # H1: the pre-filter dropped this window (recorded in window_decisions + the analysis row)
            continue
        check_cancel()                                   # safe boundary: nothing of this source is written yet
        crash_point("findings_before_response")
        try:
            res = _call(SYSTEM, _user(i, len(windows), w), project_id, source_id, head=head)
        except Exception:
            if OBSERVER:
                OBSERVER({"source_id": source_id, "window": i + 1, "windows": len(windows), "raw_findings": 0, "kept": 0, "rejected": 0,
                          "summary_ok": False, "substance_ok": False, **_last_call, "error": True})
            raise
        results.append((w, res))
    return materialize(project_id, source_id, results, model=_last_model.get("model"), transport="interactive", max_findings=max_findings, prefilter=pf_summary)


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
    windows = _windows(segs, src["platform"])
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


def suggest_for_project(project_id: str, source_ids: list[str] | None = None, progress=None, force: bool = False) -> dict[str, Any]:
    ids = source_ids or db.sources_needing_suggestions(project_id)
    done, failed = 0, []
    for i, sid in enumerate(ids):
        if progress:
            progress(i / max(len(ids), 1), f"reading {i + 1}/{len(ids)}")
        try:
            suggest_for_source(project_id, sid, force=force)
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
