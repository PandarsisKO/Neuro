"""Staleness: an artifact was correct when generated; does it still reflect the project? (hardening ladder, Mission B)

Every generated artifact carries the revisions of its inputs (brief, facts, source set, the source's own transcript,
the prompt). Comparing those with the current revisions says exactly which artifacts are stale — findings per source,
the plan, the discoveries — without any model call. Staleness is INFORMATION, never a command: nothing here launches
analysis. A rebuild is quoted in dollars first, then queued as ordinary jobs that go through the budget valve, and each
artifact becomes current on its own as its job completes.

Chat answers are records of what was said at the time and are never marked stale.
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from . import db
from .config import settings

CURRENT, STALE, REBUILDING, MISSING, SUPERSEDED, LEGACY = "current", "stale", "rebuilding", "missing", "superseded", "legacy_unverified"


ACCEPTED = "current_accepted"     # S1: stale by inputs, accepted by the user as still usable (until the inputs change again)
def next_tonight(now_ts: float | None = None) -> float:
    """L-40: the next occurrence of the nightly hour (settings.t4_nightly_hour, local) -- today's if it hasn't
    passed, else tomorrow's. One definition of "tonight" for the UI, the CLI and the nightly envelope, computed
    on the host's own clock. It is when the job becomes ELIGIBLE, never a promise of when it runs."""
    import time as _t
    from .config import settings as _s
    t = now_ts if now_ts is not None else _t.time()
    lt = _t.localtime(t)
    target = _t.mktime(_t.struct_time((lt.tm_year, lt.tm_mon, lt.tm_mday, int(_s.t4_nightly_hour), 0, 0, 0, 0, -1)))
    return target if target > t else target + 86400


LOCAL_MINUTES_PER_WINDOW = 1.2    # observed 2026-09-08: ~one findings window per minute on Claude Code (Sonnet)


_FINDINGS_JOBS = ("suggest_findings", "suggest_findings_batch")
_ACTIVE = ("queued", "running", "external_pending")


def _failed_jobs(project_id: str, kinds: tuple[str, ...]) -> list[dict[str, Any]]:
    return db.list_project_jobs(project_id, (), limit=2000, kinds=kinds, statuses=("failed",))


def _job_sources(job: dict[str, Any]) -> list[str]:
    return db.findings_job_sources(job["id"], job["kind"], (job.get("payload") or {}).get("source_ids") or [])


def _job_note(j: dict[str, Any]) -> str:
    """Rebuilding · waiting for budget / running / queued / in background — derived from the real job row."""
    msg = j.get("message") or ""
    if msg.startswith("paused:"):
        return "waiting for budget" if "budget" in msg else "paused: " + msg[7:60].strip()
    if j["kind"] == "suggest_findings_batch":
        from . import batches
        return "in background · " + batches.ui_state(j)["label"]
    return j["status"]


def source_verdicts(project: dict[str, Any], rows: list[dict[str, Any]],
                    analysis: dict[str, dict[str, Any]], analysing: set[str]) -> dict[str, tuple[str, list[str]]]:
    """Read only the inputs needed for source badges. Rebuild state comes from the current jobs."""
    from . import findings

    brief = db.brief_revision(project)
    prompt, schema = findings.prompt_version(), findings.schema_version()
    hash_source = findings.input_hasher(project)
    verdicts = {}
    stale = set()
    for row in rows:
        if row["status"] != "ready":
            continue
        sid = row["id"]
        artifact = analysis.get(sid)
        reasons: list[str] = []
        if sid in analysing:
            status = REBUILDING
        elif not artifact:
            status = MISSING
        else:
            status, reasons = _artifact_verdict(row, artifact, brief, prompt, schema, hash_source)
        verdicts[sid] = (status, reasons)
        if status == STALE:
            stale.add(sid)

    if stale:
        for job in _failed_jobs(project["id"], _FINDINGS_JOBS):
            if not stale:
                break
            for sid in stale.intersection(_job_sources(job)):
                if job["created_at"] > (analysis[sid].get("updated_at") or 0):
                    verdicts[sid][1].append("last rebuild failed: " + (job.get("message") or "")[:120])
                stale.remove(sid)
    return verdicts


def _artifact_verdict(row: dict[str, Any], artifact: dict[str, Any], brief: str, prompt: str,
                      schema: str | None, hash_source: Callable[[str | None, str | None], str]) -> tuple[str, list[str]]:
    saved_hash = artifact.get("input_hash")
    accepted_hash = artifact.get("accepted_hash")
    legacy = artifact.get("status") == LEGACY
    if legacy and not accepted_hash:
        return LEGACY, ["preserved from Neuro Search 0.15 — its original project context cannot be verified"]
    if not legacy and not saved_hash and not artifact.get("brief_revision"):
        return STALE, ["analysed before revisions were recorded"]

    revision = row.get("revision") or db.source_revision(row["id"], persist=False)
    current_hash = hash_source(revision, artifact.get("depth")) if saved_hash or accepted_hash else None
    if legacy:
        if accepted_hash == current_hash:
            return ACCEPTED, []
        return LEGACY, ["preserved from Neuro Search 0.15 — its original project context cannot be verified"]
    if saved_hash and saved_hash == current_hash:
        return CURRENT, []

    reasons = []
    if artifact.get("brief_revision") != brief:
        reasons.append("brief changed")
    if artifact.get("source_revision") and revision and artifact["source_revision"] != revision:
        reasons.append("transcript changed")
    if saved_hash:
        if artifact.get("prompt_version") != prompt:
            reasons.append("analysis prompt changed")
        if artifact.get("schema_version") and schema and artifact["schema_version"] != schema:
            reasons.append("output schema changed")
        if "transcript changed" not in reasons and accepted_hash and accepted_hash == current_hash:
            return ACCEPTED, []
        return STALE, reasons or ["inputs changed"]
    return (STALE, reasons) if reasons else (CURRENT, [])


def assess(project_id: str) -> dict[str, Any]:
    """Which artifacts are stale, why, and what a rebuild would cost."""
    from . import usage
    project = db.get_project(project_id)
    if not project:
        raise RuntimeError("project not found")
    cur = db.project_revisions(project_id)
    live = db.list_project_jobs(project_id, (), limit=None, kinds=(*_FINDINGS_JOBS, "build_plan"),
                                statuses=_ACTIVE)
    rate = usage.observed_rate_per_minute()

    analysis = db.project_analysis(project_id, "summary")
    live_by_source = {}
    for job in reversed(live):
        if job["kind"] in _FINDINGS_JOBS:
            for sid in _job_sources(job):
                live_by_source[sid] = job
    rows = db.list_sources(ids=db.project_source_ids(project_id), status="ready", limit=None)
    verdicts = source_verdicts(project, rows, analysis, set(live_by_source))
    sources: list[dict[str, Any]] = []
    stale_findings_cost = 0.0
    for s in rows:
        sid = s["id"]
        a = analysis.get(sid)
        status, reasons = verdicts[sid]
        note = (_job_note(live_by_source[sid]) if status == REBUILDING
                else "accepted as still usable for the current brief" if status == ACCEPTED else None)
        est = 0.0
        if status in (STALE, MISSING, LEGACY):
            if s.get("duration"):
                est = usage.estimate_video(s["duration"], rate)["analyse"]
            else:
                chars = db.connect().execute("SELECT COALESCE(SUM(LENGTH(text)),0) FROM segments WHERE source_id=?", (sid,)).fetchone()[0]
                est = usage.estimate_findings(int(chars))
            if status in (STALE, LEGACY):
                stale_findings_cost += est
        sources.append({"source_id": sid, "title": s.get("title"), "status": status, "note": note, "reasons": reasons, "estimate": round(est, 4),
                        "analysed_at": (a or {}).get("updated_at"), "model": (a or {}).get("model"), "provider": (a or {}).get("provider"),
                        "duration": s.get("duration"), "platform": s.get("platform"), "depth": (a or {}).get("depth"),
                        "windows": max(1, int(((s.get("duration") or 0) + 3599) // 3600)) if s.get("duration") else 1})
    stale_sources = [x for x in sources if x["status"] in (STALE, LEGACY)]

    # ---- plan
    plan = db.latest_plan(project_id)
    plan_info: dict[str, Any] = {"status": MISSING, "reasons": [], "estimate": 0.0}
    if plan:
        reasons = []
        plan_jobs = [j for j in live if j["kind"] == "build_plan" and j["status"] != "external_pending"]
        if plan_jobs:
            plan_info["status"] = REBUILDING
            j = plan_jobs[0]
            plan_info["note"] = "waiting for research to finish re-analysing" if j.get("blocked_by") and j["status"] == "queued" and any(
                d in {x["id"] for x in live} for d in (j["blocked_by"] or [])) else _job_note(j)
        else:
            if not plan.get("brief_revision"):
                reasons.append("built before revisions were recorded")
            else:
                if plan["brief_revision"] != cur["brief_revision"]:
                    reasons.append("brief changed")
                if plan["facts_revision"] != cur["facts_revision"]:
                    reasons.append("decisions/constraints changed")
                if plan["source_set_revision"] != cur["source_set_revision"]:
                    n_new = sum(1 for row in rows if (row.get("updated_at") or 0) > plan["created_at"])
                    reasons.append(f"{n_new} source{'s' if n_new != 1 else ''} added or changed since" if n_new else "sources changed")
            plan_info["status"] = STALE if reasons else CURRENT
            failed = [j for j in _failed_jobs(project_id, ("build_plan",)) if j["created_at"] > plan["created_at"]] if reasons else []
            if reasons and failed:
                reasons.append("last rebuild failed: " + (failed[0].get("message") or "")[:120])
        plan_info.update({"reasons": reasons, "version": plan["version"], "plan_id": plan["id"], "built_at": plan["created_at"], "model": plan.get("model")})
        if plan_info["status"] == STALE:
            plan_info["estimate"] = round(_plan_estimate(project_id), 4)

    # ---- discoveries (informational: they are suggestions, cheap to re-run, never auto)
    disc = db.list_discoveries(project_id)
    disc_info = {"status": MISSING, "count": len(disc)}
    if disc:
        latest = max(disc, key=lambda d: d["created_at"])
        disc_info["status"] = STALE if latest.get("brief_revision") and latest["brief_revision"] != cur["brief_revision"] else CURRENT

    t = usage.totals()
    total = round(stale_findings_cost + plan_info["estimate"], 4)
    daily_left = max(0.0, t["daily_budget"] - t["today"]) if t["daily_budget"] > 0 else None
    return {"project_id": project_id, "revisions": cur, "plan": plan_info, "sources": sources, "discoveries": disc_info,
            "stale_sources": len(stale_sources), "legacy_sources": sum(1 for x in sources if x["status"] == LEGACY),
            "missing_sources": sum(1 for x in sources if x["status"] == MISSING),
            "rebuilding": sum(1 for x in sources if x["status"] == REBUILDING) + (plan_info["status"] == REBUILDING),
            "estimate": {"findings": round(stale_findings_cost, 4), "findings_background": round(stale_findings_cost * usage.BATCH_MULT, 4),
                         "plan": plan_info["estimate"], "total": total, "total_background": round(stale_findings_cost * usage.BATCH_MULT + plan_info["estimate"], 4),
                         "basis": "your usage so far" if rate is not None else "list prices",
                         "background_note": "model cost only; background analysis may take up to 24 hours; the plan itself is never batched"},
            "budget": {"daily_remaining": None if daily_left is None else round(daily_left, 2), "daily": t["daily_budget"], "paused": t["paused"],
                       "fits": daily_left is None or total <= daily_left},
            "anything_stale": bool(stale_sources) or plan_info["status"] == STALE}


def live_findings_jobs(project_id: str) -> list[dict[str, Any]]:
    return db.list_project_jobs(project_id, (), limit=None, kinds=_FINDINGS_JOBS, statuses=_ACTIVE)


def _plan_estimate(project_id: str) -> float:
    from .planner import MATERIAL_CHARS
    from .usage import _price
    chars = db.connect().execute(
        "SELECT COALESCE(SUM(LENGTH(text)),0) FROM segments WHERE source_id IN (SELECT source_id FROM project_sources WHERE project_id=?)", (project_id,)).fetchone()[0]
    material_tokens = min(int(chars * 0.15), MATERIAL_CHARS) / 4       # the planner sees summaries + retrieved chunks, not whole transcripts
    pin, pout = _price(settings.answer_model)
    return (material_tokens * 2 * pin + 12000 * pout) / 1e6            # two passes over the material, ~12k tokens of plan out


def rebuild(project_id: str, what: list[str] | None = None, source_ids: list[str] | None = None, transport: str = "interactive",
           not_before: float | None = None) -> dict[str, Any]:
    """Queue the rebuild of stale artifacts as ordinary background jobs. Every job passes usage.guard on its own,
    so when the budget runs out the rest wait (nothing is lost) and the ones that finished are current already.
    transport is explicit per request: 'interactive' = one job per source now; 'batch' = ONE background batch job for
    all the stale sources (each source becomes current as its results land). The plan waits for whichever was chosen.

    not_before (L-20, EXECUTION-LADDER.md P1A): schedule every job this call creates to run no earlier than a
    future time, rather than now. `assess()` still runs HERE, at call time (now), not deferred to the scheduled
    time -- but that is not a "no longer current" gap: findings.suggest_for_source()'s own is_current/input_hash
    check already makes a job for a source that became current again before it actually runs a $0 no-op (the
    'skipped' path), and staleness itself is re-derived fresh on the NEXT ordinary assess()/triage() call, so
    nothing is silently stuck on a stale verdict. A caller wanting the staleness set itself re-evaluated at
    execution time (not just each job's own currency) would need a different, deferred-assess design -- not
    needed by anything asking for this yet, so not built speculatively here."""
    what = what or ["findings", "plan"]
    a = assess(project_id)
    jobs: list[dict[str, Any]] = []
    if "findings" in what:
        targets = [x["source_id"] for x in a["sources"] if x["status"] in (STALE, LEGACY) and (not source_ids or x["source_id"] in source_ids)]
        if transport == "batch" and targets:
            jobs.append(db.create_job("suggest_findings_batch", {"project_id": project_id, "source_ids": targets, "force": True, "reason": "stale"}, not_before=not_before))
        else:
            for sid in targets:                                       # one job per source: independent, resumable, individually current
                jobs.append(db.create_job("suggest_findings", {"project_id": project_id, "source_ids": [sid], "force": True, "reason": "stale"}, not_before=not_before))
    if "plan" in what and a["plan"]["status"] == STALE:
        # Dependency barrier: the plan must not be built until the research it depends on has settled. It waits for
        # every upstream job to REACH A CONCLUSION, not for every one to succeed (0.61.0).
        #
        # ALL_SUCCESS was the original choice, so that a failed findings job could not let the planner quietly plan
        # over stale evidence. Measured on Kyle's project it does something worse: 11 of 199 upstream jobs had
        # succeeded, so the plan refused to build at all and reported "not run". On a 199-source project some
        # ingest will always fail — a deleted video, an Instagram carousel, a 403 — and a plan that needs a perfect
        # run is a plan that never runs. ALL_TERMINAL keeps the barrier (nothing plans over work still in flight)
        # while letting the planner do what it is for: plan from the evidence that exists. The plan already records
        # the snapshot it was built from, so what was missing stays visible.
        upstream = [j["id"] for j in jobs] + [j["id"] for j in live_findings_jobs(project_id)]
        jobs.append(db.create_job("build_plan", {"project_id": project_id, "reason": "stale"},
                                  blocked_by=upstream or None, dependency_policy="ALL_TERMINAL", not_before=not_before))
    return {"queued": len(jobs), "job_ids": [j["id"] for j in jobs], "estimate": a["estimate"], "budget": a["budget"], "transport": transport}


# ------------------------------------------------------------------ S1: stale triage (three answers, not one bill)

def _matters(project_id: str) -> dict[str, dict[str, Any]]:
    """Why a source matters — the S2 value spine's rule (priority · plan evidence · strong-Claim evidence · ≥ 3 findings rated 4–5). $0."""
    from . import sources_value
    return {sid: {"why": v["why"]} for sid, v in sources_value.compute(project_id).items() if v["matters"]}


def triage(project_id: str) -> dict[str, Any]:
    """Partition the stale set: rebuild_matters · rebuild_transcript · accept (brief-only staleness on sources that carry no
    weight) · retry_failed. Each tier carries its sources, why, and the cost as time on the local provider or dollars on the API."""
    from . import claude_code, usage
    a = assess(project_id)
    why = _matters(project_id)
    tiers: dict[str, list[dict[str, Any]]] = {"rebuild_matters": [], "rebuild_transcript": [], "accept": [], "retry_failed": []}
    for x in a["sources"]:
        if x["status"] not in (STALE, LEGACY):
            continue
        row = {**x, "why": (why.get(x["source_id"]) or {}).get("why") or []}
        if any(r.startswith("last rebuild failed") for r in x["reasons"]):
            tiers["retry_failed"].append(row)
        elif "transcript changed" in x["reasons"]:
            tiers["rebuild_transcript"].append(row)
        elif row["why"]:
            tiers["rebuild_matters"].append(row)
        else:
            tiers["accept"].append(row)
    # 0.63.35: this asked whether "local" was ready without naming a model, so `wait=False` kicked off a
    # background probe of the CLI's bare DEFAULT — claude-opus-5 on Kyle's subscription — 7 times in 45
    # minutes, for a verdict about a model no task here uses. It is the third appearance of one bug
    # (0.45.14 keyed the fix on an override nobody sets, 0.63.30 made health per-model, 0.63.31 fixed the
    # background probe) and this was the site all three missed. A rebuild would be run by
    # findings.extract, so that is the model whose health decides whether to price it in hours or dollars.
    local = claude_code.health_snapshot(model=claude_code.local_model_for(claude_code.DOMINANT_LOCAL_TASK)).get("state") == "ready" and settings_profile_local()
    out_tiers = {}
    for k, rows in tiers.items():
        api_cost = round(sum(r["estimate"] for r in rows), 4)
        windows = sum(r.get("windows") or 1 for r in rows)
        # 0.45.2: quote BOTH prices, always. The card used to show whichever provider was configured and nothing else, so on
        # a local setup a 4-hour tier looked like the only option there was — the user could not even see that the same work
        # was a few dollars on the API, let alone choose it. Time and money are the two currencies; the card names both.
        # 0.45.3: the local ETA is WALL CLOCK, so it must divide by the pool that is actually doing the work. It used to be
        # windows × 1.2 min regardless of NEUROSEARCH_LOCAL_AI_WORKERS, which quoted 4 h 24 min for a job two workers finish
        # in about half that — the free option was made to look twice as slow as it is.
        workers = max(1, settings.local_ai_workers)
        local_minutes = windows * LOCAL_MINUTES_PER_WINDOW / workers
        api_line = f"${api_cost:.2f} on the API" if rows else ""
        local_line = (f"$0 · about {_hm(local_minutes)} on Claude Code" + (f" ({workers} at a time)" if workers > 1 else "")) if rows and local else ""
        # the third option that already existed and was never offered: the same model through the Message Batches API at
        # BATCH_MULT of the price, in the background. Between "free but hours" and "now but full price" this is the middle.
        batch_cost = round(api_cost * usage.BATCH_MULT, 4)
        batch_line = f"${batch_cost:.2f} on the API in the background" if rows else ""
        out_tiers[k] = {"count": len(rows), "sources": rows, "api_cost": api_cost, "windows": windows,
                        "local_minutes": round(local_minutes) if local else None, "local_workers": workers,
                        "local_line": local_line, "api_line": api_line, "batch_cost": batch_cost, "batch_line": batch_line,
                        "cost_line": (local_line or api_line) if rows else ""}
    t = usage.totals()
    return {"project_id": project_id, "tiers": out_tiers, "plan": a["plan"], "stale_total": sum(len(v) for v in tiers.values()),
            "accepted": sum(1 for x in a["sources"] if x["status"] == ACCEPTED), "local": local,
            "budget": a["budget"], "why_legend": {"priority source": "you starred it", "evidence in the Master Plan": "a plan step cites it",
                                                  "evidence of a strong Claim": "a Strong Claim rests on it", "rated": "you rated its findings 4 or 5"},
            "explain": {"rebuild_matters": "Stale sources that carry weight: the plan, a Strong Claim, a priority star or a finding you rated 4–5 rests on them. Re-read these first.",
                        "rebuild_transcript": "Their transcript changed since the findings were written — the quoted evidence may no longer be there. Not acceptable as-is.",
                        "accept": "Stale only because the brief (or the prompt) changed, and nothing important rests on them. Accepting keeps their findings and stops the nagging until the inputs change again.",
                        "retry_failed": "The last rebuild failed. The reason is on each row; Retry runs them through the normal path."}}


def settings_profile_local() -> bool:
    from .config import settings
    return settings.ai_profile == "local"


def _hm(minutes: float) -> str:
    m = int(round(minutes))
    return f"{m // 60} h {m % 60:02d} min" if m >= 60 else f"{m} min"


def accept(project_id: str, source_ids: list[str] | None = None, tier: str | None = None) -> dict[str, Any]:
    """Mark stale analyses as accepted for exactly their current inputs (never a transcript change)."""
    from . import findings
    project = db.get_project(project_id)
    if not project:
        raise RuntimeError("project not found")
    if tier:
        source_ids = [r["source_id"] for r in triage(project_id)["tiers"].get(tier, {}).get("sources", [])]
    ids = list(dict.fromkeys(source_ids or []))
    a = assess(project_id)
    by = {x["source_id"]: x for x in a["sources"]}
    accepted, refused = [], []
    with db.tx() as conn:
        for sid in ids:
            x = by.get(sid)
            if not x or x["status"] not in (STALE, LEGACY) or "transcript changed" in x["reasons"]:
                refused.append(sid)
                continue
            an = db.get_analysis(project_id, sid, "summary") or {}
            conn.execute("UPDATE project_source_analysis SET accepted_hash=?, accepted_at=? WHERE project_id=? AND source_id=? AND analysis_kind='summary'",
                         (findings.input_hash(project, sid, depth=an.get("depth")), db.now(), project_id, sid))
            accepted.append(sid)
    return {"accepted": len(accepted), "refused": len(refused), "source_ids": accepted}
