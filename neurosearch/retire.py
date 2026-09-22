"""Retire a research direction the project is no longer pursuing ($0, no model call, no network).

Kyle: *"I want to bulk remove some content that we are no longer pursuing in the large project but I dont know how.
we need to essentially get rid of ALL CPA and laundromat specific content."*

He had abandoned two candidate industries — laundromats and accounting firms — and the app had no way to say so. The
only tool was removing sources one at a time, which is both tedious at 64 sources and, on its own, **wrong**: it
leaves everything derived from them in place.

**Measured on his project before writing a line of this** (882 sources), and the measurement changed the design
twice:

* **A keyword sweep is not safe.** Matching "cpa" or "accounting firm" selects 43 sources — including *How To
  Acquire Your First Business With $0 (FREE COURSE)*, *Best Boring Businesses to Buy in 2026*, his own
  *Gio Kyle and Zach first coaching call* and his own acquisition notes, because general acquisition training
  discusses accounting firms as one example industry among many. Sweeping by keyword would have gutted the project.
  **So this module retires by CHANNEL or by explicit source id, never by keyword.** A channel is a publisher's whole
  body of work, which is the unit that actually corresponds to "a direction we were exploring".
* **Removing sources does not remove what was derived from them.** `db.remove_project_sources` is a membership
  marker, by design (0.34.2). On these two sets it would have left **1,775 findings** attached to sources no longer
  in the project and **2,509 Claims with no evidence inside it at all** — a research state asserting things nothing
  in the project supports. So retiring is three coordinated steps, and every one of them is reversible.

Nothing is deleted, ever. Sources keep their place in the global library (another project can still use them),
findings are `dismissed` rather than removed, Claims are `rejected` with the reason recorded, and `claim_evidence`
rows are left exactly as they are so the decision can be explained and undone. What retiring changes is what the
project ASSERTS, not what the app remembers.
"""
from __future__ import annotations

import logging
import time
from typing import Any

from . import db

log = logging.getLogger(__name__)

MAX_SOURCES = 2000            # a whole-project retirement is not what this is for; refuse rather than truncate
REASON_MAX = 300


def channels(project_id: str) -> list[dict[str, Any]]:
    """Every channel in the project with what it has contributed — the menu a person picks from.

    `findings` and `hours` are what makes the choice informed: "Laundromat Resource · 25 sources · 22.6 h · 1,059
    findings" is a decision a human can make, where a list of 882 titles is not."""
    ids = db.project_source_ids(project_id, ready_only=False)
    if not ids:
        return []
    rows = db.connect().execute(
        "SELECT COALESCE(NULLIF(channel,''), '(no channel)') ch, COUNT(*) n, "
        "       COALESCE(SUM(duration),0)/3600.0 hours, GROUP_CONCAT(id) sids "
        "FROM sources WHERE id IN (%s) GROUP BY ch ORDER BY n DESC" % ",".join("?" * len(ids)), ids).fetchall()
    notes = {r["source_id"]: r["n"] for r in db.connect().execute(
        "SELECT source_id, COUNT(*) n FROM project_notes WHERE project_id=? AND source_id IS NOT NULL GROUP BY source_id",
        (project_id,))}
    out = []
    for r in rows:
        sids = (r["sids"] or "").split(",")
        out.append({"channel": r["ch"], "sources": int(r["n"]), "hours": round(float(r["hours"] or 0), 1),
                    "findings": sum(notes.get(s, 0) for s in sids)})
    return sorted(out, key=lambda c: (-c["findings"], -c["sources"]))


def _select(project_id: str, channels_: list[str] | None, source_ids: list[str] | None) -> list[str]:
    ids = set(db.project_source_ids(project_id, ready_only=False))
    picked: set[str] = {s for s in (source_ids or []) if s in ids}
    if channels_:
        want = {c.strip() for c in channels_ if c and c.strip()}
        if want:
            rows = db.connect().execute(
                "SELECT id, COALESCE(NULLIF(channel,''), '(no channel)') ch FROM sources WHERE id IN (%s)"
                % ",".join("?" * len(ids)), list(ids)).fetchall()
            picked |= {r["id"] for r in rows if r["ch"] in want}
    return sorted(picked)


def preview(project_id: str, *, channels: list[str] | None = None, source_ids: list[str] | None = None) -> dict[str, Any]:
    """What retiring this selection would do, before anything is done — including what it would NOT touch.

    `claims_losing_all_evidence` is the number that makes this an informed decision rather than a tidy-up: on
    Kyle's laundromat set it is 1,664. A person who sees that can decide; a person who only sees "44 sources" cannot."""
    if not db.get_project(project_id):
        raise KeyError(project_id)
    sids = _select(project_id, channels, source_ids)
    if len(sids) > MAX_SOURCES:
        raise ValueError(f"{len(sids)} sources is more than this is for (max {MAX_SOURCES})")
    out: dict[str, Any] = {"project_id": project_id, "sources": len(sids), "source_ids": sids,
                           "channels": sorted({c for c in (channels or []) if c})}
    if not sids:
        out.update({"hours": 0.0, "findings": 0, "claims_losing_all_evidence": 0, "claims_partly_affected": 0,
                    "by_channel": [], "note": "nothing selected"})
        return out
    conn = db.connect()
    q = "(%s)" % ",".join("?" * len(sids))
    out["hours"] = round(float(conn.execute(
        f"SELECT COALESCE(SUM(duration),0)/3600.0 h FROM sources WHERE id IN {q}", sids).fetchone()["h"] or 0), 1)
    out["findings"] = int(conn.execute(
        f"SELECT COUNT(*) n FROM project_notes WHERE project_id=? AND source_id IN {q}", [project_id, *sids]
    ).fetchone()["n"] or 0)
    # A Claim is only "lost" when NONE of its remaining evidence comes from a source the project still has. Scoped
    # to this project's claims, because claim_evidence is global and another project's Claim is not ours to touch.
    out["claims_losing_all_evidence"] = int(conn.execute(
        f"""SELECT COUNT(*) n FROM (
                SELECT e.claim_id FROM claim_evidence e JOIN project_claims c ON c.id = e.claim_id
                WHERE c.project_id=? AND c.status != 'rejected'
                GROUP BY e.claim_id
                HAVING SUM(CASE WHEN e.source_id IN {q} THEN 0 ELSE 1 END) = 0)""",
        [project_id, *sids]).fetchone()["n"] or 0)
    out["claims_partly_affected"] = int(conn.execute(
        f"""SELECT COUNT(*) n FROM (
                SELECT e.claim_id FROM claim_evidence e JOIN project_claims c ON c.id = e.claim_id
                WHERE c.project_id=? AND c.status != 'rejected'
                GROUP BY e.claim_id
                HAVING SUM(CASE WHEN e.source_id IN {q} THEN 1 ELSE 0 END) > 0
                   AND SUM(CASE WHEN e.source_id IN {q} THEN 0 ELSE 1 END) > 0)""",
        [project_id, *sids, *sids]).fetchone()["n"] or 0)      # `q` twice → the ids twice
    rows = conn.execute(
        f"SELECT COALESCE(NULLIF(channel,''), '(no channel)') ch, COUNT(*) n FROM sources WHERE id IN {q} "
        "GROUP BY ch ORDER BY n DESC", sids).fetchall()
    out["by_channel"] = [{"channel": r["ch"], "sources": int(r["n"])} for r in rows]
    out["reversible"] = ("sources return to the project by adding them again; findings are dismissed, not deleted; "
                         "Claims are rejected with the reason recorded; evidence rows are untouched")
    out["note"] = (f"{len(sids)} sources ({out['hours']} h) leave this project. {out['findings']} findings are "
                   f"dismissed and {out['claims_losing_all_evidence']} Claims lose every piece of evidence the "
                   f"project still holds, so they are rejected. {out['claims_partly_affected']} more keep some "
                   f"evidence and are re-assessed rather than rejected.")
    return out


def reason_of(reason: str) -> str:
    return (reason or "no longer pursuing this direction").strip()[:REASON_MAX]


def apply(project_id: str, *, channels: list[str] | None = None, source_ids: list[str] | None = None,
          reason: str = "", dismiss_findings: bool = True, reject_claims: bool = True,
          record_decision: bool = True) -> dict[str, Any]:
    """Do it, in bulk, in one transaction per step — and record it as a decision the project made.

    Bulk SQL rather than a loop over `claims.set_status`: that calls `assess()` per Claim, and 2,509 assessments is
    the shape of pass that cost 431 s in a request (0.62.2). The statuses are set in one statement each and the
    research state is re-derived by the queued `refresh_research` job instead."""
    plan = preview(project_id, channels=channels, source_ids=source_ids)
    sids = plan["source_ids"]
    if not sids:
        # The same shape whether or not there was anything to do — a caller should not have to branch on the keys
        # to find out. A second run lands here, because the sources are already excluded and no longer selectable.
        return {**plan, "applied": False, "why": "nothing selected (already retired, or no such channel)",
                "sources_removed": 0, "findings_dismissed": 0, "claims_rejected": 0, "reason": reason_of(reason)}
    reason = reason_of(reason)
    q = "(%s)" % ",".join("?" * len(sids))
    done: dict[str, Any] = {"sources_removed": 0, "findings_dismissed": 0, "claims_rejected": 0}

    db.remove_project_sources(project_id, sids)                       # membership marker; the library keeps them
    done["sources_removed"] = len(sids)

    if dismiss_findings:
        with db.tx() as conn:
            prior = [(r["id"], r["status"]) for r in conn.execute(
                f"SELECT id, status FROM project_notes WHERE project_id=? AND source_id IN {q} AND status != 'dismissed'", [project_id, *sids])]
            cur = conn.execute(
                f"UPDATE project_notes SET status='dismissed' WHERE project_id=? AND source_id IN {q} "
                "AND status != 'dismissed'", [project_id, *sids])
            done["findings_dismissed"] = cur.rowcount or 0
            from . import ledger
            for nid, st in prior:
                ledger.record(conn, project_id, event_type="finding_status_changed", object_type="finding", object_id=nid,
                              before={"status": st}, after={"status": "dismissed", "reason": f"retired: {reason}"[:200]})

    if reject_claims:
        with db.tx() as conn:
            ids = [r["claim_id"] for r in conn.execute(
                f"""SELECT e.claim_id FROM claim_evidence e JOIN project_claims c ON c.id = e.claim_id
                    WHERE c.project_id=? AND c.status != 'rejected'
                    GROUP BY e.claim_id
                    HAVING SUM(CASE WHEN e.source_id IN {q} THEN 0 ELSE 1 END) = 0""",
                [project_id, *sids])]
            for i in range(0, len(ids), 400):
                part = ids[i:i + 400]
                conn.execute(
                    "UPDATE project_claims SET status='rejected', application=?, updated_at=? WHERE id IN (%s)"
                    % ",".join("?" * len(part)),
                    [f"retired: {reason}", time.time(), *part])
            from . import ledger
            for cid in ids:
                ledger.record(conn, project_id, event_type="claim_status_changed", object_type="claim", object_id=cid,
                              before={"status": "not rejected"}, after={"status": "rejected", "reason": f"retired: {reason}"[:200]})
            done["claims_rejected"] = len(ids)

    if record_decision:
        # His own words become project state, not a log line: "we are no longer pursuing X" is exactly the kind of
        # durable decision the research state is supposed to carry.
        db.add_fact(project_id, "rejected",
                    f"No longer pursuing: {reason} — retired {len(sids)} sources "
                    f"({', '.join(c['channel'] for c in plan['by_channel'][:6])})", origin="user")

    try:
        from . import claims as _claims, research_view
        research_view.user_changed(project_id)          # their decision must show on the next read (0.62.8)
        done["refresh_job"] = _claims.maybe_refresh(project_id)
    except Exception as e:  # noqa: BLE001 — the retirement stands whether or not the refresh queues
        log.warning("research refresh not queued after retiring: %s", e)

    log.info("retired %d sources from %s (%s)", len(sids), project_id, reason)
    return {**plan, "applied": True, **done, "reason": reason}
