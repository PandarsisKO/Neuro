"""Rung G — the ONE small real-provider check of the Message Batches adapter (`neurosearch batch-smoke --live`).

Everything the 150 fake tests cannot prove is here, and nothing else: that Neuro Search's real Anthropic batch adapter
submits, parks, polls, persists, verifies, validates, materialises and prices the way the fakes say it does — against
the real provider, with ONE single-window findings item from the frozen golden fixture, in an eval-only database that
is deleted afterwards. No crash timing, no forced ambiguity: the fake/crash coverage owns that window.

    fixture (golden yt01, 1 window)  →  preflight model  →  token-count → expected now / batch cost
      →  ONE provider batch item (normal queue: external_pending, handle persisted)  →  poll through AnthropicBatch.check
      →  raw result persisted locally BEFORE materialisation  →  custom_id verified  →  findings-v2 structured validation
      + quote validator  →  findings.materialize(transport='batch', batch_id)  →  provenance + tokens + cost checks
      →  zero schema events  →  report (evals/batch-smoke/<stamp>-<sha>.{json,txt})  →  PASS | FAIL

Without --live the whole flow runs against the fakes (free) — the same code path, the same checks.
"""
from __future__ import annotations

import json
import logging
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

from . import __version__, db
from .config import settings

log = logging.getLogger(__name__)

FIXTURE_SOURCE = "yt01"                   # golden: one transcript window, YouTube timestamps → citations + quote validator exercised
POLL_S_LIVE = 15.0
EVAL_BUDGET = 1.0                          # dollars, in the eval-only database — never the production budget


def _sha() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, cwd=str(Path(__file__).resolve().parent.parent), timeout=10).stdout.strip() or "nogit"
    except Exception:  # noqa: BLE001
        return "nogit"


def run(live: bool, progress: Any = print, out_dir: Path = Path("evals"), timeout_min: float = 60.0, poll_s: float | None = None) -> dict[str, Any]:
    from . import batches, contracts, evals, findings, jobs, migration, usage
    t0 = time.time()
    stamp, sha = time.strftime("%Y%m%d-%H%M%S"), _sha()
    rep: dict[str, Any] = {"eval": "batch-smoke", "tier": "live" if live else "fake", "app_version": __version__, "git_sha": sha, "started": stamp,
                           "checks": [], "pass": True}
    fails: list[str] = []

    def check(name: str, ok: bool, detail: Any = None) -> bool:
        rep["checks"].append({"check": name, "pass": bool(ok), "detail": detail})
        if not ok:
            fails.append(name)
            rep["pass"] = False
        progress(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  — {detail}" if detail is not None and (not ok or isinstance(detail, str)) else ""))
        return bool(ok)

    was_fake, was_dir = settings.fake_ai, settings.data_dir
    tmp = Path(tempfile.mkdtemp(prefix="ns_batch_smoke_"))
    settings.fake_ai = not live
    settings.data_dir = tmp
    db._local.conn = None
    try:
        db.init_db()
        db.kv_set("daily_budget", str(EVAL_BUDGET)); db.kv_set("monthly_budget", str(EVAL_BUDGET))
        rep["database"] = str(tmp)
        progress(f"batch smoke · app {__version__} @ {sha} · {'LIVE — one real Message Batch item' if live else 'fake dry run (free)'} · eval-only database {tmp}")

        # ---- fixture + contract
        g = evals.load_golden(only={FIXTURE_SOURCE})              # the one frozen fixture, nothing else is ingested or embedded
        pid, sid = g["project_id"], g["sources"][FIXTURE_SOURCE]
        c = contracts.contract("findings.extract")
        rep["contract"] = {"task": c.task, "model": c.model, "thinking": c.thinking, "schema": c.schema, "batch_allowed": c.batch_allowed, "max_output_tokens": c.max_output_tokens}
        items = findings.batch_requests(pid, sid)
        check("fixture is one single-window findings item", len(items) == 1, {"source": FIXTURE_SOURCE, "windows": len(items)})
        expected_cid = items[0]["custom_id"]
        rep["expected_custom_id"] = expected_cid
        rep["schema_version"] = findings.schema_version()
        check("contract allows batch execution and enforces findings-v2", c.batch_allowed and c.schema == "findings-v2" and items[0]["params"].get("output_config", {}).get("format", {}).get("type") == "json_schema", rep["contract"])

        # ---- preflight the production findings model (free)
        try:
            pf = migration.preflight([c.model], live)
            check(f"preflight {c.model}", pf.get(c.model) is not None or not live, pf)
        except Exception as e:  # noqa: BLE001
            check(f"preflight {c.model}", False, str(e)[:300])
            raise

        # ---- expected cost before submission (token counted)
        est = batches.estimate(pid, [sid], force=True)
        rep["estimate"] = est
        check("token-counted estimate (standard vs batch model cost)", est["items"] == 1 and est["now"] > 0 and abs(est["background"] - est["now"] * usage.BATCH_MULT) < 1e-4,
              f"basis {est['basis']} · input tokens {est['input_tokens']} · now ${est['now']:.4f} · batch ${est['background']:.4f}")

        # ---- submit exactly one item through the normal queue
        job = db.create_job(batches.JOB_KIND, {"project_id": pid, "source_ids": [sid], "force": True, "reason": "batch-smoke"})
        claimed = db.claim_job((batches.JOB_KIND,), worker_id="batch-smoke")
        st = jobs.execute(claimed, "batch-smoke")
        j = db.get_job(job["id"])
        handle = j.get("external_handle") or ""
        rep["batch_id"] = handle
        check("job parked external_pending with the provider batch id persisted", st == "external_pending" and j["status"] == "external_pending" and handle.startswith("msgbatch_") and not handle.startswith(batches.TENTATIVE),
              {"status": st, "handle": handle})
        rows = db.batch_items(job["id"])
        check("exactly one submitted item with the expected custom_id", len(rows) == 1 and rows[0]["status"] == "submitted" and rows[0]["custom_id"] == expected_cid and rows[0]["batch_id"] == handle,
              [{"custom_id": r["custom_id"], "status": r["status"]} for r in rows])
        check("submission intent cleared once the handle was persisted", db.kv_get(f"batch:intent:{job['id']}#1") is None)

        # ---- poll to completion through the real adapter
        wait = poll_s if poll_s is not None else (POLL_S_LIVE if live else 0.0)
        deadline = time.time() + timeout_min * 60
        polls = 0
        progress(f"polling batch {handle} every {wait:.0f}s (timeout {timeout_min:.0f} min)…")
        while True:
            polls += 1
            n = jobs.poll_external_once()
            j = db.get_job(job["id"])
            if n and j["status"] != "external_pending":
                break
            if time.time() > deadline:
                break
            if j["status"] != "external_pending":
                break
            time.sleep(wait)
        rep["polls"] = polls
        rep["poll_seconds"] = round(time.time() - t0, 1)
        if j["status"] == "external_pending":
            check("batch ended within the timeout", False, f"batch {handle} still processing after {timeout_min:.0f} min — it was NOT cancelled (the provider keeps it up to 24 h); rerun later is safe: nothing is materialised until results exist")
            return _finish(rep, fails, out_dir, stamp, sha, progress)
        check("batch ended and the job was handed back to the queue", j["status"] == "queued" and (j.get("payload") or {}).get("_external_result", {}).get("batch_id") == handle, {"status": j["status"], "polls": polls})

        # ---- raw result persisted locally BEFORE materialisation; custom_id verified
        rows = db.batch_items(job["id"])
        raw = rows[0].get("raw") if rows else None
        counts = (j.get("payload") or {}).get("_external_result", {}).get("counts") or {}
        rep["result_counts"] = counts
        check("raw provider result persisted locally before materialisation", len(rows) == 1 and rows[0]["status"] == "succeeded" and bool(raw) and bool(raw.get("content")) and not db.project_analysis(pid, "summary").get(sid),
              {"status": rows[0]["status"] if rows else None, "raw_content_blocks": len((raw or {}).get("content") or [])})
        check("returned custom_id set matches the expected item exactly", counts.get("succeeded") == 1 and counts.get("unknown_custom_id", 0) == 0 and rows[0]["custom_id"] == expected_cid, counts)
        inv = db.connect().execute("SELECT state, provider_request_id, returned_model FROM invocations WHERE provider=?", (batches.PROVIDER,)).fetchall()
        check("ledger: one completed invocation on the batch provider carrying the batch id", len(inv) == 1 and inv[0]["state"] == "completed" and inv[0]["provider_request_id"] == handle,
              [dict(r) for r in inv])
        rep["returned_model"] = (raw or {}).get("model")

        # ---- materialise through the production path (structured validation + quote validator inside)
        claimed = db.claim_job((batches.JOB_KIND,), worker_id="batch-smoke")
        st = jobs.execute(claimed, "batch-smoke")
        j = db.get_job(job["id"])
        res = j.get("result") or {}
        rep["job_result"] = res
        check("job completed through findings.materialize", st == "done" and res.get("done") == 1 and res.get("failed") == 0 and res.get("cohorts") == 1, {"status": st, "result": {k: res.get(k) for k in ("sources", "done", "failed", "items", "cohorts")}})
        an = db.get_analysis(pid, sid, "summary") or {}
        notes = db.list_project_notes(pid, status="suggested")
        rep["analysis"] = {k: an.get(k) for k in ("status", "transport", "batch_id", "model", "schema_version", "prompt_version", "input_hash")}
        rep["notes"] = len(notes)
        check("provenance: transport=batch with the provider batch id, analysis current", an.get("transport") == "batch" and an.get("batch_id") == handle and an.get("status") == "current" and an.get("schema_version") == findings.schema_version(), rep["analysis"])
        check("findings written with evidence", len(notes) >= 1 and all(n.get("citations") for n in notes) and all(r["transport"] == "batch" and r["batch_id"] == handle for r in
              db.connect().execute("SELECT transport, batch_id FROM project_notes WHERE project_id=? AND source_id=?", (pid, sid)).fetchall()), f"{len(notes)} suggested findings")
        ev = db.health()["evidence"]
        rep["evidence"] = {k: ev.get(k) for k in ("findings_checked", "findings_rejected", "citations_checked", "citations_invalid")}
        check("quote validator ran on every finding", (ev.get("findings_checked") or 0) >= len(notes) >= 1, rep["evidence"])
        so = db.health()["structured_outputs"]
        rep["structured_outputs"] = so
        check("zero schema mismatch / fallback / truncation / refusal events", all(so.get(k, 0) == 0 for k in ("mismatches", "fallbacks", "unrecovered", "truncated", "refused")), so)

        # ---- economics: tokens, actual batch cost vs the expected 50% model-rate calculation
        u = db.connect().execute("SELECT model, input_tokens, output_tokens, cache_read, cache_write, cost, saved, transport FROM usage WHERE kind='findings' AND source_id=?", (sid,)).fetchall()
        rep["usage"] = [dict(r) for r in u]
        ok_usage = len(u) == 1 and u[0]["transport"] == "batch"
        if ok_usage:
            r0 = u[0]
            pin, pout = usage._price(r0["model"])                     # priced by the model the provider RETURNED, as the ledger does
            full = (r0["input_tokens"] + r0["cache_write"] * usage.CACHE_WRITE_MULT + r0["cache_read"] * usage.CACHE_READ_MULT) / 1e6 * pin + r0["output_tokens"] / 1e6 * pout
            expected_batch = full * usage.BATCH_MULT
            rep["pricing"] = {"model": r0["model"], "configured_model": c.model, "price_in_per_mtok": pin, "price_out_per_mtok": pout, "input_tokens": r0["input_tokens"], "output_tokens": r0["output_tokens"],
                              "cache_read": r0["cache_read"], "cache_write": r0["cache_write"], "standard_model_cost": round(full, 6), "expected_batch_cost": round(expected_batch, 6),
                              "actual_batch_cost": round(r0["cost"], 6), "saved_recorded": round(r0["saved"], 6), "estimate_before_submission": est["background"]}
            check("actual batch cost = 50% of the standard model-rate calculation", abs(r0["cost"] - expected_batch) < 1e-9 and abs(r0["saved"] - (full - expected_batch)) < 1e-9,
                  f"in {r0['input_tokens']} · out {r0['output_tokens']} · cache read {r0['cache_read']} / write {r0['cache_write']} · standard ${full:.6f} · batch ${r0['cost']:.6f} (expected ${expected_batch:.6f})")
            check("pre-submission estimate within 2× of the actual batch cost", 0 < r0["cost"] and (est["background"] / r0["cost"] if r0["cost"] else 0) < 2 and (r0["cost"] / est["background"] if est["background"] else 0) < 2,
                  f"estimated ${est['background']:.4f} vs actual ${r0['cost']:.4f}")
        else:
            check("one batch-priced usage row for the item", False, rep["usage"])
        evs = [e["event_type"] for e in db.job_events(job["id"])]
        rep["job_events"] = evs
        check("job history: planned → submitting → submitted → result → ended, no re-attach/retry/cancel", all(k in evs for k in ("batch_planned", "external_submitting", "external_submitted", "external_result", "batch_ended"))
              and not any(k in evs for k in ("external_reattached", "external_candidates", "batch_retry_planned", "batch_cancelled")), evs)
        return _finish(rep, fails, out_dir, stamp, sha, progress)
    finally:
        db._local.conn = None
        settings.fake_ai, settings.data_dir = was_fake, was_dir
        shutil.rmtree(tmp, ignore_errors=True)               # eval-only database: nothing of it survives


def _finish(rep: dict[str, Any], fails: list[str], out_dir: Path, stamp: str, sha: str, progress: Any) -> dict[str, Any]:
    rep["fails"] = fails
    rep["verdict"] = "PASS" if not fails else "FAIL"
    rep["seconds"] = round(time.time() - time.mktime(time.strptime(stamp, "%Y%m%d-%H%M%S")), 1)
    rep["text"] = format_report(rep)
    d = out_dir / "batch-smoke"
    d.mkdir(parents=True, exist_ok=True)
    base = d / f"{stamp}-{sha}-{rep['tier']}"
    base.with_suffix(".json").write_text(json.dumps({k: v for k, v in rep.items() if k != "text"}, indent=1, default=str))
    base.with_suffix(".txt").write_text(rep["text"])
    rep["artifact"] = str(base.with_suffix(".json"))
    progress(f"report: {base.with_suffix('.txt')}")
    return rep


def format_report(rep: dict[str, Any]) -> str:
    p = rep.get("pricing") or {}
    lines = [f"Batch smoke ({rep['tier']}) · app {rep['app_version']} @ {rep['git_sha']} · {rep['started']} · {rep['seconds']}s",
             f"  model {rep.get('contract', {}).get('model')} · schema {rep.get('schema_version')} · fixture {FIXTURE_SOURCE} · custom_id {rep.get('expected_custom_id')}",
             f"  batch {rep.get('batch_id')} · polls {rep.get('polls')} · returned model {rep.get('returned_model')} · findings {rep.get('notes')}"]
    if p:
        lines.append(f"  tokens in {p['input_tokens']} / out {p['output_tokens']} / cache read {p['cache_read']} / cache write {p['cache_write']}")
        lines.append(f"  standard model cost ${p['standard_model_cost']:.6f} · expected batch ${p['expected_batch_cost']:.6f} · actual batch ${p['actual_batch_cost']:.6f} · saved ${p['saved_recorded']:.6f} · estimated before submission ${p['estimate_before_submission']:.4f}")
    so = rep.get("structured_outputs") or {}
    if so:
        lines.append(f"  structured outputs: mismatches {so.get('mismatches')} · fallbacks {so.get('fallbacks')} · truncated {so.get('truncated')} · refused {so.get('refused')}")
    for c in rep["checks"]:
        lines.append(f"  {'PASS' if c['pass'] else 'FAIL'}  {c['check']}" + ("" if c["pass"] else f"  — {c['detail']}"))
    lines.append(f"Batch smoke {rep['verdict']}" + ("" if rep["verdict"] == "PASS" else " — " + "; ".join(rep["fails"])))
    return "\n".join(lines)
