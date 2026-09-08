"""Staleness: an artifact was correct when generated; does it still reflect the project? (hardening ladder, Mission B)

Every generated artifact carries the revisions of its inputs (brief, facts, source set, the source's own transcript,
the prompt). Comparing those with the current revisions says exactly which artifacts are stale — findings per source,
the plan, the discoveries — without any model call. Staleness is INFORMATION, never a command: nothing here launches
analysis. A rebuild is quoted in dollars first, then queued as ordinary jobs that go through the budget valve, and each
artifact becomes current on its own as its job completes.

Chat answers are records of what was said at the time and are never marked stale.
"""
from __future__ import annotations

from typing import Any

from . import db
from .config import settings

CURRENT, STALE, REBUILDING, MISSING, SUPERSEDED, LEGACY = "current", "stale", "rebuilding", "missing", "superseded", "legacy_unverified"


def _project_jobs(project_id: str) -> list[dict[str, Any]]:
    return [j for j in db.list_jobs(2000) if (j.get("payload") or {}).get("project_id") == project_id]


def _job_note(j: dict[str, Any]) -> str:
    """Rebuilding · waiting for budget / running / queued / in background — derived from the real job row."""
    msg = j.get("message") or ""
    if msg.startswith("paused:"):
        return "waiting for budget" if "budget" in msg else "paused: " + msg[7:60].strip()
    if j["kind"] == "suggest_findings_batch":
        from . import batches
        return "in background · " + batches.ui_state(j)["label"]
    return j["status"]


def assess(project_id: str) -> dict[str, Any]:
    """Which artifacts are stale, why, and what a rebuild would cost."""
    from . import findings, usage
    project = db.get_project(project_id)
    if not project:
        raise RuntimeError("project not found")
    cur = db.project_revisions(project_id)
    pjobs = _project_jobs(project_id)
    live = [j for j in pjobs if j["status"] in ("queued", "running")]
    rate = usage.observed_rate_per_minute()

    # ---- findings / source analysis, per source (the 'summary' artifact + its findings share the same task inputs)
    analysis = db.project_analysis(project_id, "summary")
    live_by_source: dict[str, dict[str, Any]] = {}
    last_failed: dict[str, dict[str, Any]] = {}
    for j in sorted(pjobs, key=lambda j: j["created_at"]):
        if j["kind"] not in ("suggest_findings", "suggest_findings_batch"):
            continue
        sids = (j.get("payload") or {}).get("source_ids") or []
        if j["kind"] == "suggest_findings_batch":
            # a background job covers a source until that source's findings have landed (they land one by one)
            landed = {x["source_id"] for x in db.batch_items(j["id"], status="materialized")}
            sids = [x for x in (sids or [x["source_id"] for x in db.batch_items(j["id"])]) if x not in landed]
        for sid in sids:
            if j["status"] in ("queued", "running", "external_pending"):
                live_by_source[sid] = j
            elif j["status"] == "failed":
                last_failed[sid] = j
    sources: list[dict[str, Any]] = []
    stale_findings_cost = 0.0
    all_srcs = {s["id"]: s for s in db.list_sources(limit=100000)}
    for sid in db.project_source_ids(project_id):
        s = all_srcs.get(sid)
        if not s:
            continue
        a = analysis.get(sid)
        reasons: list[str] = []
        note = None
        if sid in live_by_source:
            status = REBUILDING
            note = _job_note(live_by_source[sid])
        elif not a:
            status = MISSING
        elif a.get("status") == LEGACY:
            status = LEGACY
            reasons.append("preserved from Neuro Search 0.15 — its original project context cannot be verified")
        elif a.get("input_hash"):
            # exact-input comparison: transcript + steering + prompt, as the task saw them
            if a["input_hash"] != findings.input_hash(project, sid, depth=a.get("depth")):
                srev = s.get("revision") or db.source_revision(sid)
                if a.get("brief_revision") != cur["brief_revision"]:
                    reasons.append("brief changed")
                if a.get("source_revision") and srev and a["source_revision"] != srev:
                    reasons.append("transcript changed")
                if a.get("prompt_version") != findings.prompt_version():
                    reasons.append("analysis prompt changed")
                if a.get("schema_version") and findings.schema_version() and a["schema_version"] != findings.schema_version():
                    reasons.append("output schema changed")
                reasons = reasons or ["inputs changed"]
            status = STALE if reasons else CURRENT
        elif not a.get("brief_revision"):
            status = STALE
            reasons.append("analysed before revisions were recorded")
        else:                                                       # 0.16.0 rows: revisions only
            srev = s.get("revision") or db.source_revision(sid)
            if a.get("brief_revision") != cur["brief_revision"]:
                reasons.append("brief changed")
            if a.get("source_revision") and srev and a["source_revision"] != srev:
                reasons.append("transcript changed")
            status = STALE if reasons else CURRENT
        if status == STALE and sid in last_failed and last_failed[sid]["created_at"] > (a or {}).get("updated_at", 0):
            reasons.append("last rebuild failed: " + (last_failed[sid].get("message") or "")[:120])
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
                        "analysed_at": (a or {}).get("updated_at"), "model": (a or {}).get("model"), "provider": (a or {}).get("provider")})
    stale_sources = [x for x in sources if x["status"] in (STALE, LEGACY)]

    # ---- plan
    plan = db.latest_plan(project_id)
    plan_info: dict[str, Any] = {"status": MISSING, "reasons": [], "estimate": 0.0}
    if plan:
        reasons = []
        plan_jobs = [j for j in live if j["kind"] == "build_plan"]
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
                    n_new = sum(1 for sid in db.project_source_ids(project_id) if (all_srcs.get(sid) or {}).get("updated_at", 0) > plan["created_at"])
                    reasons.append(f"{n_new} source{'s' if n_new != 1 else ''} added or changed since" if n_new else "sources changed")
            plan_info["status"] = STALE if reasons else CURRENT
            failed = [j for j in pjobs if j["kind"] == "build_plan" and j["status"] == "failed" and j["created_at"] > plan["created_at"]]
            if reasons and failed:
                reasons.append("last rebuild failed: " + (failed[-1].get("message") or "")[:120])
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
    return [j for j in _project_jobs(project_id) if j["kind"] in ("suggest_findings", "suggest_findings_batch") and j["status"] in ("queued", "running", "external_pending")]


def _plan_estimate(project_id: str) -> float:
    from .planner import MATERIAL_CHARS
    from .usage import _price
    chars = db.connect().execute(
        "SELECT COALESCE(SUM(LENGTH(text)),0) FROM segments WHERE source_id IN (SELECT source_id FROM project_sources WHERE project_id=?)", (project_id,)).fetchone()[0]
    material_tokens = min(int(chars * 0.15), MATERIAL_CHARS) / 4       # the planner sees summaries + retrieved chunks, not whole transcripts
    pin, pout = _price(settings.answer_model)
    return (material_tokens * 2 * pin + 12000 * pout) / 1e6            # two passes over the material, ~12k tokens of plan out


def rebuild(project_id: str, what: list[str] | None = None, source_ids: list[str] | None = None, transport: str = "interactive") -> dict[str, Any]:
    """Queue the rebuild of stale artifacts as ordinary background jobs. Every job passes usage.guard on its own,
    so when the budget runs out the rest wait (nothing is lost) and the ones that finished are current already.
    transport is explicit per request: 'interactive' = one job per source now; 'batch' = ONE background batch job for
    all the stale sources (each source becomes current as its results land). The plan waits for whichever was chosen."""
    what = what or ["findings", "plan"]
    a = assess(project_id)
    jobs: list[dict[str, Any]] = []
    if "findings" in what:
        targets = [x["source_id"] for x in a["sources"] if x["status"] in (STALE, LEGACY) and (not source_ids or x["source_id"] in source_ids)]
        if transport == "batch" and targets:
            jobs.append(db.create_job("suggest_findings_batch", {"project_id": project_id, "source_ids": targets, "force": True, "reason": "stale"}))
        else:
            for sid in targets:                                       # one job per source: independent, resumable, individually current
                jobs.append(db.create_job("suggest_findings", {"project_id": project_id, "source_ids": [sid], "force": True, "reason": "stale"}))
    if "plan" in what and a["plan"]["status"] == STALE:
        # dependency barrier: the plan must not be built until the research it depends on is current again. If a
        # findings job fails, the plan job fails with it instead of quietly planning over stale evidence.
        upstream = [j["id"] for j in jobs] + [j["id"] for j in live_findings_jobs(project_id)]
        jobs.append(db.create_job("build_plan", {"project_id": project_id, "reason": "stale"}, blocked_by=upstream or None))
    return {"queued": len(jobs), "job_ids": [j["id"] for j in jobs], "estimate": a["estimate"], "budget": a["budget"], "transport": transport}
