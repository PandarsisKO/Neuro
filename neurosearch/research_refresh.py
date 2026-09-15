"""CR5 (mission §12, EXECUTION-LADDER.md Stage 10): the P8 vertical slice -- one important Claim refreshed
end-to-end, through the EXISTING paths only, never a second ingestion or evidence pipeline.

request_refresh() is the cheap synchronous half: resolve a Claim-shaped need to a real Evidence Target (reusing
one if it already exists -- several paths already create these; creating a new one only when none does, so
knowledge.pursue has somewhere durable to record its escalation -- see the planning checkpoint's open question,
resolved this way rather than a throwaway synthetic dict), run pursue()'s free steps 1-3, then
knowledge.capture_best() to enqueue the SAME ingest job every other acquisition in this app uses. The
findings/claims harvest that follows is the existing pipeline, completely unchanged, and runs asynchronously on
the job queue -- this never blocks on it and never spends anything itself beyond pursue's own tiny embeddings
call.

check() is the other half: what actually happened, read any time after, by comparing the Claim's current state
to the snapshot request_refresh() took before it started. "Unchanged" is a normal, honest outcome, never a
failure. Neither function ever flips a Claim's status (mission §12: no auto-accept)."""
from __future__ import annotations

import json
import time
from typing import Any

from . import claims, db, knowledge, research_needs


def _resolve_target(project_id: str, need: dict[str, Any]) -> str:
    if need["kind"] == "open_target" and need.get("target_id"):
        return need["target_id"]
    claim_id = need.get("claim_id")
    for tg in knowledge.list_targets(project_id, status="open"):
        if tg.get("claim_id") == claim_id:
            return tg["id"]
    tg = knowledge.add_target(project_id, need.get("question") or need.get("text") or f"refresh: {claim_id}",
                              topic=need.get("topic"), claim_id=claim_id, sufficiency="corroborative", origin="research_needs")
    return tg["id"]


def _snapshot(claim_id: str) -> dict[str, Any] | None:
    c = claims.get(claim_id)
    if not c:
        return None
    return {"strength": c.get("strength"), "freshness_status": c.get("freshness_status"), "evidence_count": len(c.get("evidence") or [])}


def request_refresh(project_id: str, need: dict[str, Any] | None = None, cap_usd: float = 1.0) -> dict[str, Any]:
    """Picks the top due need under cap_usd (or uses `need` directly -- e.g. one item from a caller's own
    due_tonight() result) and starts its refresh through the existing ingest path. Returns immediately; ingest,
    findings and claim reassessment happen on the job queue like any other acquisition. Never enqueues more than
    one capture (n=1) and never builds a second parallel pipeline."""
    if need is None:
        due = [n for n in research_needs.due_tonight(project_id) if n["estimated_cost_usd"] <= cap_usd]
        if not due:
            return {"started": False, "reason": f"nothing due under ${cap_usd:.2f}"}
        need = due[0]
    claim_id = need.get("claim_id")
    if not claim_id:
        return {"started": False, "reason": "this need has no claim to refresh (an open target with no linked "
                                            "claim -- use knowledge.capture_best directly)"}
    before = _snapshot(claim_id)
    target_id = _resolve_target(project_id, need)
    knowledge.pursue(target_id, external=False)
    captured = knowledge.capture_best(project_id, target_id, n=1)
    rec = {"claim_id": claim_id, "target_id": target_id, "before": before, "ts": time.time(),
          "estimated_cost_usd": need.get("estimated_cost_usd")}
    db.kv_set(f"research:refresh:{claim_id}", json.dumps(rec))
    return {**rec, "started": bool(captured["started"]), "capture": captured["started"]}


def check(project_id: str, claim_id: str) -> dict[str, Any]:
    """What changed, read any time after request_refresh(). "Unchanged" is a normal outcome, not a failure --
    the CR5 gate names this explicitly."""
    raw = db.kv_get(f"research:refresh:{claim_id}")
    if not raw:
        return {"known": False, "reason": "no refresh was requested for this claim"}
    try:
        rec = json.loads(raw)
    except ValueError:
        return {"known": False, "reason": "refresh record unreadable"}
    after = _snapshot(claim_id)
    if after is None:
        return {"known": False, "reason": "claim no longer exists"}
    before = rec.get("before") or {}
    changed = before.get("strength") != after.get("strength") or before.get("freshness_status") != after.get("freshness_status")
    return {"known": True, "claim_id": claim_id, "before": before, "after": after, "changed": changed, "requested_at": rec.get("ts")}
