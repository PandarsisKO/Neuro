"""Destructive-testing kit for Mission D: fixture 'videos', a hand-driven worker that can die at any crash point,
and the restart that follows. Everything runs under the fake providers."""
from __future__ import annotations

import json
import random
from pathlib import Path
from typing import Any

from neurosearch import db, jobs

CRASH_POINTS = ["before_metadata", "metadata_complete", "audio_downloaded", "transcription_before_response", "transcript_complete",
                "chunks_complete", "embeddings_half", "findings_before_response", "findings_persisted_before_done",
                "external_before_ack", "external_result_before_done"]


def write_fixtures(root: Path, n: int, captions_every: int = 2, seed: int = 7) -> list[str]:
    """n deterministic fixture items; every `captions_every`-th has captions, the rest must be 'transcribed'."""
    rng = random.Random(seed)
    root.mkdir(parents=True, exist_ok=True)
    topics = ["equity injection", "seller note", "quality of earnings", "customer concentration", "working capital peg",
              "personal guarantee", "SDE multiple", "transition period", "debt service coverage", "letter of intent"]
    urls = []
    for i in range(n):
        lines = []
        t = 0.0
        for k in range(30 + (i % 7) * 10):
            topic = topics[(i + k) % len(topics)]
            lines.append({"start": round(t, 1), "end": round(t + 6, 1), "text": f"Point {k} of video {i}: the {topic} matters because it changes the deal, number {rng.randint(1, 99)} percent."})
            t += 6
        d = {"title": f"Fixture video {i:02d}", "duration": t, "channel": "Fixture Channel", "published_at": "2026-01-15",
             "captions": (captions_every > 0 and i % captions_every == 0), "segments": lines}
        p = root / f"item{i:02d}.json"
        p.write_text(json.dumps(d))
        urls.append(f"fixture://{p}")
    return urls


class Sim:
    """A worker that runs claimed jobs one at a time and can be 'killed' at crash points. `restart()` is what a
    process start does: recover every running job's lease, then carry on."""

    def __init__(self, rng: random.Random | None = None, crash_prob: float = 0.0, points: list[str] | None = None) -> None:
        self.rng = rng or random.Random(0)
        self.crash_prob = crash_prob
        self.points = points or CRASH_POINTS
        self.crashes: list[str] = []
        self.restarts = 0
        self.executed = 0

    def restart(self) -> None:
        jobs.CRASH_AT.clear()
        with jobs._running_lock:
            jobs._running.clear()
        db.recover_expired_leases(all_running=True)
        self.restarts += 1

    def step(self, kinds: tuple[str, ...] | None = None) -> str | None:
        """Claim and execute one job (possibly crashing). Returns the resulting status, or None when nothing to do."""
        jobs.poll_external_once()
        job = db.claim_job(kinds, worker_id="sim")
        if not job:
            return None
        if self.crash_prob and self.rng.random() < self.crash_prob:
            jobs.CRASH_AT[self.rng.choice(self.points)] = 1
        try:
            st = jobs.execute(job, "sim")
        except jobs.SimulatedCrash as e:
            self.crashes.append(str(e))
            self.restart()
            return "crashed"
        finally:
            jobs.CRASH_AT.clear()
            self.executed += 1
        return st

    def run_until_idle(self, max_steps: int = 5000, kinds: tuple[str, ...] | None = None) -> None:
        for _ in range(max_steps):
            st = self.step(kinds)
            if st is None:
                # nothing claimable: waiting jobs (retry/budget) are woken so the simulation does not depend on clocks
                wake = db.connect().execute("UPDATE jobs SET not_before=NULL WHERE status='queued' AND not_before IS NOT NULL").rowcount
                db.connect().commit()
                ext = db.connect().execute("SELECT COUNT(*) FROM jobs WHERE status='external_pending'").fetchone()[0]
                if not wake and not ext:
                    return
                if ext:
                    jobs.poll_external_once()
        raise AssertionError("simulation did not settle")


def active_jobs() -> int:
    return db.connect().execute("SELECT COUNT(*) FROM jobs WHERE status IN ('queued','running','external_pending')").fetchone()[0]


def project_state(pid: str) -> dict[str, Any]:
    """The comparable final state of a project: what crash-recovery equivalence is measured on."""
    conn = db.connect()
    out: dict[str, Any] = {"sources": {}}
    for sid in sorted(db.project_source_ids(pid)):
        s = db.get_source(sid)
        segs = db.get_segments(sid)
        n_chunks = conn.execute("SELECT COUNT(*) FROM chunks WHERE source_id=?", (sid,)).fetchone()[0]
        n_emb = conn.execute("SELECT COUNT(*) FROM chunks WHERE source_id=? AND embedding IS NOT NULL", (sid,)).fetchone()[0]
        notes = [n for n in db.list_project_notes(pid, status="suggested") if n["source_id"] == sid]
        an = db.get_analysis(pid, sid, "summary") or {}
        out["sources"][s["url"]] = {"status": s["status"], "stage": s["stage"], "segments": len(segs), "revision": s["revision"],
                                    "chunks": n_chunks, "embedded": n_emb, "transcript_kind": s["transcript_kind"],
                                    "findings": sorted(n["content"] for n in notes), "analysis_hash": an.get("input_hash"), "analysis_status": an.get("status")}
    plan = db.latest_plan(pid)
    # (source_set_revision hashes source ids, which differ between databases — the per-source table above is the real comparison)
    out["plan"] = {"version": plan["version"], "brief_revision": plan["brief_revision"], "sources_in_scope": plan["snapshot"].get("sources"),
                   "evidence": len(plan["plan"].get("_evidence") or {})} if plan else None
    return out
