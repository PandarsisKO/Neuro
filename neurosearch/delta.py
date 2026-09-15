"""L-31 (EXECUTION-LADDER.md Stage 4, PRODUCT-INTELLIGENCE-MISSION.md section 6 "The Main Product Interface:
Project Delta"): Project Delta v0, DATA ONLY. One function, ``for_envelope(envelope_id) -> dict``, answering the
mission doc's five questions for one already-run autonomous execution envelope: what changed, why it matters,
what Neuro did, what needs the user, what should happen next.

No UI, no schema migration. Every number here is either read straight off the envelope's own kv record (today,
only L-30's ``nightly.py`` produces one -- see ``_envelope_record`` below) or counted live from existing tables,
filtered to the envelope's own project set and its actual time window (the envelope's recorded start ts through
"now"). Nothing here is estimated, inferred, or carried over from a different envelope's numbers.

Needs L-30 for two reasons, not one: (1) the envelope record this reads (``kv["nightly:{date}"]``) only exists
because ``nightly.run()`` writes it, and (2) as of this rung, ``nightly.run()`` was extended to capture a cheap
per-project "before" coverage snapshot (``t1.coverage_view(pid, limit=0)``, excluding the large per-chunk
``chunks`` list) immediately before calling ``t4.execute`` -- without a real "before" snapshot, a coverage
DELTA cannot be computed honestly after the fact; re-deriving "before" from tables mutated by the run itself
would not be a real before-state, it would be a guess dressed up as one.
"""
from __future__ import annotations

import json
import time
from typing import Any

from . import db

# fields coverage_view returns that are cheap scalar/dict summaries, safe to diff directly -- never "chunks"
# (the potentially large per-chunk list), which for_envelope never requests (limit=0) or diffs.
_COVERAGE_SCALAR_FIELDS = ("denominator", "canonical_claims", "canonical_findings")


def _envelope_record(envelope_id: str) -> dict[str, Any] | None:
    """Only nightly.run()'s envelope shape is understood today (id ``"nightly-{date}"``) -- exactly why this
    rung's own ladder entry says "needs: L-30". A future second producer of preflighted envelopes needs its own
    branch added here, not a rewrite of this function's contract."""
    if envelope_id.startswith("nightly-"):
        date = envelope_id[len("nightly-"):]
        raw = db.kv_get(f"nightly:{date}")
        return json.loads(raw) if raw else None
    return None


def _coverage_delta(before: dict[str, Any] | None, after: dict[str, Any]) -> dict[str, Any]:
    if not before or before.get("status") != "measured" or after.get("status") != "measured":
        return {"available": False, "reason": "no comparable before/after coverage snapshot for this project"}
    out: dict[str, Any] = {}
    for f in _COVERAGE_SCALAR_FIELDS:
        b, a = before.get(f) or 0, after.get(f) or 0
        out[f] = {"before": b, "after": a, "delta": a - b}
    b_sig, a_sig = before.get("signals") or {}, after.get("signals") or {}
    out["signals_delta"] = {k: a_sig.get(k, 0) - b_sig.get(k, 0) for k in sorted(set(b_sig) | set(a_sig))}
    out["available"] = True
    return out


def _project_delta(conn: Any, pid: str, p: dict[str, Any], start_ts: float, end_ts: float) -> dict[str, Any]:
    if "error" in p:
        return {"project_id": pid, "what_neuro_did": "attempted, failed before any work was enqueued",
                "error": p["error"], "what_changed": None, "why_it_matters": "run failed for this project",
                "what_needs_the_user": [{"reason": f"nightly run failed: {p['error']}"}],
                "what_should_happen_next": "investigate the failure (see the error above); nothing was spent or enqueued",
                "_spend_usd": 0.0, "_new_tensions_count": 0}

    sources_read = int(p.get("count") or 0)
    job_ids = list(p.get("job_ids") or [])

    findings_suggested = int(conn.execute(
        "SELECT COUNT(*) n FROM project_notes WHERE project_id=? AND status='suggested' AND created_at>=? AND created_at<=?",
        (pid, start_ts, end_ts)).fetchone()["n"])

    analysis_rows = conn.execute(
        "SELECT source_id, prefilter FROM project_source_analysis WHERE project_id=? AND created_at>=? AND created_at<=?",
        (pid, start_ts, end_ts)).fetchall()
    sources_stopped_by_probe = 0
    touched_source_ids: set[str] = set()
    for row in analysis_rows:
        touched_source_ids.add(row["source_id"])
        raw = row["prefilter"]
        if not raw:
            continue
        try:
            probe = (json.loads(raw) or {}).get("substance_probe")
        except (TypeError, ValueError):
            continue
        if probe and probe.get("stopped"):
            sources_stopped_by_probe += 1

    revision_at_run: dict[str, str | None] = {}
    if touched_source_ids:
        marks = ",".join("?" for _ in touched_source_ids)
        for row in conn.execute(f"SELECT id, revision FROM sources WHERE id IN ({marks})", tuple(touched_source_ids)).fetchall():
            revision_at_run[row["id"]] = row["revision"]

    tension_rows = conn.execute(
        "SELECT kind FROM research_tensions WHERE project_id=? AND created_at>=? AND created_at<=?",
        (pid, start_ts, end_ts)).fetchall()
    new_tensions: dict[str, int] = {}
    for row in tension_rows:
        new_tensions[row["kind"]] = new_tensions.get(row["kind"], 0) + 1

    spend = float(conn.execute(
        "SELECT COALESCE(SUM(cost),0) c FROM usage WHERE project_id=? AND ts>=? AND ts<=?",
        (pid, start_ts, end_ts)).fetchone()["c"])

    before = p.get("snapshot_before")
    try:
        from . import t1
        after = t1.coverage_view(pid, limit=0)
    except Exception as e:  # noqa: BLE001 — a coverage read failing must not blank out everything else this project has
        after = {"status": "error", "error": str(e)}
    coverage_delta = _coverage_delta(before, after)

    why: list[str] = []
    if new_tensions:
        why.append(f"{sum(new_tensions.values())} new tension(s) ({', '.join(sorted(new_tensions))})")
    if findings_suggested:
        why.append(f"{findings_suggested} new finding(s) suggested, pending review")
    if sources_stopped_by_probe:
        why.append(f"{sources_stopped_by_probe} source(s) stopped early by the substance probe (spend saved, not lost coverage)")
    if coverage_delta.get("available") and coverage_delta.get("canonical_claims", {}).get("delta"):
        why.append("canonical claim count changed")
    why_it_matters = "; ".join(why) if why else "no material change this run"

    needs_user: list[dict[str, Any]] = []
    # v0 stays honest to the mission doc's "ideally zero items": nothing here escalates to needs_user by
    # itself. Suggested findings are the ordinary product flow (review queue), not an exceptional escalation.

    next_step = "review suggested findings" if findings_suggested else (
        "no action" if not new_tensions else "review new tension(s)")

    return {
        "project_id": pid,
        "what_neuro_did": {"sources_read": sources_read, "findings_suggested": findings_suggested,
                           "sources_stopped_by_probe": sources_stopped_by_probe, "spend_usd": round(spend, 4),
                           "job_ids": job_ids, "revision_at_run": revision_at_run},
        "what_changed": {"coverage": coverage_delta, "new_tensions": new_tensions},
        "why_it_matters": why_it_matters,
        "what_needs_the_user": needs_user,
        "what_should_happen_next": next_step,
        "_spend_usd": spend,          # internal: rolled up by for_envelope, stripped nowhere (harmless extra key)
        "_new_tensions_count": sum(new_tensions.values()),
    }


def _adjudication_summary(a: dict[str, Any] | None) -> dict[str, Any] | None:
    """L-60: what the night's T5 pass did, straight off the envelope record (its own budget, its own numbers)."""
    if not a:
        return None
    if not a.get("ran"):
        return {"ran": False, "reason": a.get("reason") or a.get("error"), "budget": a.get("budget")}
    return {"ran": True, "budget": a.get("budget"), "spent": a.get("spent"), "count": len(a.get("adjudicated") or []),
            "items": a.get("adjudicated") or [], "skipped_already": a.get("skipped_already", 0),
            "stopped_by_budget": a.get("stopped_by_budget"), "errors": a.get("errors") or []}


def _research_refresh_summary(r: dict[str, Any] | None) -> dict[str, Any] | None:
    """CR6: what the night's research-refresh pass STARTED, straight off the envelope record. Never claims a
    Claim actually changed -- that is research_refresh.check()'s job, read any time after the async harvest runs."""
    if not r:
        return None
    if not r.get("ran"):
        return {"ran": False, "reason": r.get("reason") or r.get("error"), "budget": r.get("budget")}
    return {"ran": True, "budget": r.get("budget"), "spent_estimate": r.get("spent_estimate"),
           "count": len(r.get("requested") or []), "requested": r.get("requested") or [],
           "stopped_by_budget": r.get("stopped_by_budget")}


def for_envelope(envelope_id: str) -> dict[str, Any]:
    """Compute the Project Delta for one already-run autonomous execution envelope. Returns
    ``{"found": False, ...}`` for an unknown or not-yet-run envelope id -- never raises for that, since "nothing
    to report yet" is an ordinary, expected answer, not an error."""
    record = _envelope_record(envelope_id)
    if record is None:
        return {"envelope_id": envelope_id, "found": False,
                "reason": "no envelope record in kv for this id (unrecognised producer, or it hasn't run yet)"}

    preflight_raw = db.kv_get(f"preflight:{envelope_id}")
    preflight = json.loads(preflight_raw) if preflight_raw else None
    start_ts = float(preflight["ts"]) if preflight else float(record.get("ts") or 0)
    end_ts = time.time()

    conn = db.connect()
    projects = [_project_delta(conn, p.get("project_id"), p, start_ts, end_ts)
                for p in record.get("projects", []) if p.get("project_id")]

    needs_user: list[dict[str, Any]] = []
    for pd in projects:
        for item in pd.get("what_needs_the_user") or []:
            needs_user.append({"project_id": pd["project_id"], **item})

    total_spend = round(sum(pd.pop("_spend_usd") for pd in projects), 4)
    total_new_tensions = sum(pd.pop("_new_tensions_count") for pd in projects)

    out = {
        "envelope_id": envelope_id, "found": True, "ok": bool(record.get("ok", False)),
        "window": {"start": start_ts, "end": end_ts},
        "budget": {"authorized_usd": float(record.get("budget") or 0),
                   "estimated_usd": float(record.get("spent_estimate") or 0),
                   "actual_usd": total_spend},
        "projects": projects,
        "new_tensions_total": total_new_tensions,
        "needs_user": needs_user,
        "adjudication": _adjudication_summary(record.get("adjudication")),
        "research_refresh": _research_refresh_summary(record.get("research_refresh")),
        "assumptions": None,   # filled below: t6.surface() needs the assembled dict
        "preflight_backup": record.get("preflight_backup"),
        "ts": time.time(),
    }
    try:
        from . import t6
        out["assumptions"] = t6.surface(out)
    except Exception as e:  # noqa: BLE001 -- the ledger read failing must never blank out the delta
        out["assumptions"] = {"error": str(e), "items": []}
    return out
