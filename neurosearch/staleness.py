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


ACCEPTED = "current_accepted"     # S1: stale by inputs, accepted by the user as still usable (until the inputs change again)
LOCAL_MINUTES_PER_WINDOW = 1.2    # observed 2026-09-08: ~one findings window per minute on Claude Code (Sonnet)


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
            if a.get("accepted_hash") and a["accepted_hash"] == findings.input_hash(project, sid, depth=a.get("depth")):
                # 0.45.1: a legacy row can be accepted too. accept() has always written the hash for these (they are in the
                # accept tier), but this branch returned before reading it, so accepting a legacy source did nothing at all
                # and the tier could never empty. The hash covers the transcript revision, so a later transcript change
                # un-accepts the source on its own — the same guarantee the stale branch gives.
                status, reasons, note = ACCEPTED, [], "accepted as still usable for the current brief"
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
            if status == STALE and "transcript changed" not in reasons and a.get("accepted_hash") == findings.input_hash(project, sid, depth=a.get("depth")):
                status = ACCEPTED                                        # S1: the user accepted these findings as still usable for exactly these inputs
                note = "accepted as still usable for the current brief"
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
                        "analysed_at": (a or {}).get("updated_at"), "model": (a or {}).get("model"), "provider": (a or {}).get("provider"),
                        "duration": s.get("duration"), "platform": s.get("platform"), "depth": (a or {}).get("depth"),
                        "windows": max(1, int(((s.get("duration") or 0) + 3599) // 3600)) if s.get("duration") else 1})
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
                                  blocked_by=upstream or None, dependency_policy="ALL_TERMINAL"))
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
    local = claude_code.health(wait=False, model=claude_code.local_model_for(claude_code.DOMINANT_LOCAL_TASK)).get("state") == "ready" and settings_profile_local()
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
