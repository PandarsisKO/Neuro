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

CURRENT, STALE, REBUILDING, MISSING, SUPERSEDED = "current", "stale", "rebuilding", "missing", "superseded"


def _live_jobs(project_id: str) -> list[dict[str, Any]]:
    return [j for j in db.list_jobs(500) if j["status"] in ("queued", "running")
            and (j.get("payload") or {}).get("project_id") == project_id]


def assess(project_id: str) -> dict[str, Any]:
    """Which artifacts are stale, why, and what a rebuild would cost."""
    from . import usage
    project = db.get_project(project_id)
    if not project:
        raise RuntimeError("project not found")
    cur = db.project_revisions(project_id)
    live = _live_jobs(project_id)
    rate = usage.observed_rate_per_minute()

    # ---- findings / source analysis, per source
    analysis = db.project_analysis(project_id)
    rebuilding_sources = {sid for j in live if j["kind"] == "suggest_findings" for sid in ((j.get("payload") or {}).get("source_ids") or [])}
    sources: list[dict[str, Any]] = []
    stale_findings_cost = 0.0
    all_srcs = {s["id"]: s for s in db.list_sources(limit=100000)}
    for sid in db.project_source_ids(project_id):
        s = all_srcs.get(sid)
        if not s:
            continue
        a = analysis.get(sid)
        reasons: list[str] = []
        if sid in rebuilding_sources:
            status = REBUILDING
        elif not a or not a.get("brief_revision"):
            status = MISSING if not a else STALE
            if a:
                reasons.append("analysed before revisions were recorded")
        else:
            srev = s.get("revision") or db.source_revision(sid)
            if a.get("brief_revision") != cur["brief_revision"]:
                reasons.append("brief changed")
            if a.get("source_revision") and srev and a["source_revision"] != srev:
                reasons.append("transcript changed")
            status = STALE if reasons else CURRENT
        est = 0.0
        if status in (STALE, MISSING):
            if s.get("duration"):
                est = usage.estimate_video(s["duration"], rate)["analyse"]
            else:
                chars = db.connect().execute("SELECT COALESCE(SUM(LENGTH(text)),0) FROM segments WHERE source_id=?", (sid,)).fetchone()[0]
                est = usage.estimate_findings(int(chars))
            if status == STALE:
                stale_findings_cost += est
        sources.append({"source_id": sid, "title": s.get("title"), "status": status, "reasons": reasons, "estimate": round(est, 4),
                        "analysed_at": (a or {}).get("updated_at"), "model": (a or {}).get("model")})
    stale_sources = [x for x in sources if x["status"] == STALE]

    # ---- plan
    plan = db.latest_plan(project_id)
    plan_info: dict[str, Any] = {"status": MISSING, "reasons": [], "estimate": 0.0}
    if plan:
        reasons = []
        if any(j["kind"] == "build_plan" for j in live):
            plan_info["status"] = REBUILDING
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
            "stale_sources": len(stale_sources), "missing_sources": sum(1 for x in sources if x["status"] == MISSING),
            "rebuilding": sum(1 for x in sources if x["status"] == REBUILDING) + (plan_info["status"] == REBUILDING),
            "estimate": {"findings": round(stale_findings_cost, 4), "plan": plan_info["estimate"], "total": total,
                         "basis": "your usage so far" if rate is not None else "list prices"},
            "budget": {"daily_remaining": None if daily_left is None else round(daily_left, 2), "daily": t["daily_budget"], "paused": t["paused"],
                       "fits": daily_left is None or total <= daily_left},
            "anything_stale": bool(stale_sources) or plan_info["status"] == STALE}


def _plan_estimate(project_id: str) -> float:
    from .planner import MATERIAL_CHARS
    from .usage import _price
    chars = db.connect().execute(
        "SELECT COALESCE(SUM(LENGTH(text)),0) FROM segments WHERE source_id IN (SELECT source_id FROM project_sources WHERE project_id=?)", (project_id,)).fetchone()[0]
    material_tokens = min(int(chars * 0.15), MATERIAL_CHARS) / 4       # the planner sees summaries + retrieved chunks, not whole transcripts
    pin, pout = _price(settings.answer_model)
    return (material_tokens * 2 * pin + 12000 * pout) / 1e6            # two passes over the material, ~12k tokens of plan out


def rebuild(project_id: str, what: list[str] | None = None, source_ids: list[str] | None = None) -> dict[str, Any]:
    """Queue the rebuild of stale artifacts as ordinary background jobs. Every job passes usage.guard on its own,
    so when the budget runs out the rest wait (nothing is lost) and the ones that finished are current already."""
    what = what or ["findings", "plan"]
    a = assess(project_id)
    jobs: list[dict[str, Any]] = []
    if "findings" in what:
        targets = [x["source_id"] for x in a["sources"] if x["status"] == STALE and (not source_ids or x["source_id"] in source_ids)]
        for sid in targets:                                           # one job per source: independent, resumable, individually current
            jobs.append(db.create_job("suggest_findings", {"project_id": project_id, "source_ids": [sid], "force": True, "reason": "stale"}))
    if "plan" in what and a["plan"]["status"] == STALE:
        jobs.append(db.create_job("build_plan", {"project_id": project_id, "reason": "stale"}))
    return {"queued": len(jobs), "job_ids": [j["id"] for j in jobs], "estimate": a["estimate"], "budget": a["budget"]}
