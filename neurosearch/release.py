"""Hardening closeout (0.24.0) — the two operational commands.

    neurosearch doctor          the FAST diagnostic: install/runtime integrity, database, backups, schemas, contracts,
                                experimental defaults, provider/model configuration, steady-state Health counters and a
                                lightweight fake smoke. Seconds. Run it after installing or when Neuro Search feels off.

    neurosearch release-check   the HEAVY deterministic release gate: pytest, Tier 1 with frozen numbers, schema/contract
                                validation, migration fixtures, crash/recovery matrix + 40-source equivalence, retrieval
                                and cache-layout regression baselines, the frozen economic gates, a backup → restore
                                round trip, and "every experimental flag off by default". Writes a machine-readable
                                artifact (evals/release/<version>-<sha>-<stamp>.json + .txt) so a release can say exactly
                                what passed against which commit. Minutes. No live calls.
"""
from __future__ import annotations

import importlib
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

from . import __version__, db
from .config import settings

ROOT = Path(__file__).resolve().parent.parent

# every experimental / rollback flag and the default the release requires — the inventory lives in HARDENING.md
EXPERIMENTAL_FLAGS: dict[str, dict[str, Any]] = {
    "NEUROSEARCH_PLANNER_V3": {"attr": "planner_v3", "safe": False, "status": "not promoted"},
    "NEUROSEARCH_FINDINGS_PREFILTER": {"attr": "findings_prefilter", "safe": False, "status": "deferred (economics)"},
    "NEUROSEARCH_RETRIEVAL_RERANK": {"attr": "retrieval_rerank", "safe": False, "status": "killed (measured live)"},
    "NEUROSEARCH_CHAT_TAIL_BREAKPOINT": {"env_default": "0", "safe": "0", "status": "off by decision"},
    "NEUROSEARCH_SCHEMA_COMPAT_FALLBACK": {"env_default": "", "safe": "", "status": "rollback hatch"},
    "NEUROSEARCH_FAKE_AI": {"attr": "fake_ai", "safe": False, "status": "test mode (never in production)"},
}


def _sha() -> str:
    """Short git commit of the code under test. `NEUROSEARCH_GIT_SHA` overrides it for a checkout that is not a git
    working tree (a CI export, a mirrored sandbox) so the artifact still names the real commit."""
    override = os.environ.get("NEUROSEARCH_GIT_SHA", "").strip()
    if override:
        return override
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, cwd=str(ROOT), timeout=10).stdout.strip() or "nogit"
    except Exception:  # noqa: BLE001
        return "nogit"


class _Report:
    def __init__(self, kind: str, progress: Any) -> None:
        self.kind, self.progress = kind, progress
        self.checks: list[dict[str, Any]] = []
        self.t0 = time.time()

    def check(self, name: str, ok: bool | None, detail: Any = None, *, warn: bool = False) -> bool:
        st = "PASS" if ok else ("WARN" if warn or ok is None else "FAIL")
        self.checks.append({"check": name, "result": st, "detail": detail})
        self.progress(f"  {st:4s}  {name}" + (f"  — {detail}" if detail is not None and (st != "PASS" or isinstance(detail, str)) else ""))
        return bool(ok)

    @property
    def verdict(self) -> str:
        return "FAIL" if any(c["result"] == "FAIL" for c in self.checks) else "PASS"

    def done(self) -> dict[str, Any]:
        return {"kind": self.kind, "app_version": __version__, "git_sha": _sha(), "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"), "seconds": round(time.time() - self.t0, 1),
                "checks": self.checks, "verdict": self.verdict, "warnings": sum(1 for c in self.checks if c["result"] == "WARN")}


# ------------------------------------------------------------------ doctor

def flags_state() -> dict[str, dict[str, Any]]:
    out = {}
    for flag, spec in EXPERIMENTAL_FLAGS.items():
        if "attr" in spec:
            cur = bool(getattr(settings, spec["attr"]))
        else:
            cur = os.environ.get(flag, spec["env_default"])
        out[flag] = {"current": cur, "safe_default": spec["safe"], "ok": cur == spec["safe"], "status": spec["status"]}
    return out


def doctor(progress: Any = print, fake_smoke: bool = True) -> dict[str, Any]:
    """Fast operational diagnostic (seconds). Never touches the production database except to read it."""
    from . import contracts, schemas
    r = _Report("doctor", progress)
    progress(f"neurosearch doctor · app {__version__} · data {settings.data_dir}")
    # --- install / runtime
    missing = []
    for mod in ("jsonschema", "fastapi", "httpx", "numpy", "anthropic", "openai", "typer", "yt_dlp"):
        try:
            importlib.import_module(mod)
        except Exception:  # noqa: BLE001
            missing.append(mod)
    r.check("required packages importable", not missing, missing or "jsonschema, fastapi, httpx, numpy, anthropic, openai, typer, yt_dlp")
    r.check("python version", sys.version_info >= (3, 11), sys.version.split()[0])
    try:
        from importlib.metadata import version as _v
        inst = _v("neurosearch")
        r.check("installed package version matches the code", inst == __version__, f"installed {inst}, code {__version__}" if inst != __version__ else __version__,
                warn=inst != __version__)
    except Exception as e:  # noqa: BLE001
        r.check("installed package version matches the code", None, f"not installed as a package ({e})", warn=True)
    r.check("data directory writable", os.access(settings.data_dir, os.W_OK) if settings.data_dir.exists() else False, str(settings.data_dir))
    # --- database + backups
    if settings.db_path.exists():
        try:
            res = db.connect().execute("PRAGMA quick_check").fetchone()[0]
            r.check("database quick_check", res == "ok", res)
            n_tables = db.connect().execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table'").fetchone()[0]
            r.check("schema present", n_tables >= 20, f"{n_tables} tables")
            h = db.health()
            bk = h["backup"]["last_verified"]
            age_h = (time.time() - bk["ts"]) / 3600 if bk else None
            r.check("verified backup exists", bool(bk), f"{age_h:.1f} h old" if bk else "none yet — a snapshot is taken hourly while the server runs", warn=not bk)
            if bk:
                r.check("latest backup file present", Path(bk["path"]).exists(), bk["path"], warn=True)
            jobs = h["jobs"]
            r.check("no stale running jobs", not jobs.get("stale_running"), f"queued {jobs.get('queued', 0)} · running {jobs.get('running', 0)} · failed {jobs.get('failed', 0)} · external {jobs.get('external_pending', 0)}")
            so = h["structured_outputs"]
            r.check("structured outputs at steady state (0 fallbacks / unrecovered)", not so["fallbacks"] and not so["unrecovered"], so, warn=True)
            ev = h["evidence"]
            r.check("finding quote validity ≥ 98%", ev["finding_quote_validity"] is None or ev["finding_quote_validity"] >= 0.98, ev["finding_quote_validity"], warn=True)
            r.check("citation validity ≥ 99%", ev["citation_validity"] is None or ev["citation_validity"] >= 0.99, ev["citation_validity"], warn=True)
            r.check("no ambiguous provider executions", not h["invocations"].get("ambiguous"), h["invocations"].get("ambiguous", 0), warn=True)
            lib = h.get("library") or {}
            r.check("global library: no duplicate content fingerprints", not lib.get("duplicate_fingerprints"),
                    f"{lib.get('sources', 0)} sources · {lib.get('shared_by_projects', 0)} shared · {lib.get('acquisitions_avoided', 0)} acquisitions avoided", warn=True)
            prov = {p["label"]: p["status"] for p in h["providers"]}
            r.check("provider circuits healthy", all(v == "Healthy" for v in prov.values()), prov, warn=True)
            r.check("network boundary refusals (informational)", None, h["network"]["fetch_blocked"], warn=True)
        except sqlite3.Error as e:
            r.check("database opens", False, str(e)[:200])
    else:
        r.check("database", None, "no database yet (created on first run)", warn=True)
    # --- schemas, contracts, flags, providers
    try:
        for name, sch in schemas.REGISTRY.items():
            schemas.check_provider_compat(sch, name)
        r.check("schema registry valid + provider-compatible", True, sorted(schemas.REGISTRY))
    except Exception as e:  # noqa: BLE001
        r.check("schema registry valid + provider-compatible", False, str(e)[:200])
    try:
        bad = []
        for task in ("answer.chat", "answer.repair", "findings.extract", "rank.relevance", "discover.quick", "discover.verify", "planner.analysis", "planner.build",
                     "planner.update", "export.synthesis", "planner.situation", "planner.core", "planner.execution", "planner.economics", "planner.actions",
                     "findings.prefilter", "retrieval.rerank", "embed", "transcribe"):
            c = contracts.contract(task)
            if c.fallback != "NO_FALLBACK":
                bad.append(task)
        r.check("every AI contract valid and NO_FALLBACK", not bad, bad or "19 contracts")
    except Exception as e:  # noqa: BLE001
        r.check("every AI contract valid and NO_FALLBACK", False, str(e)[:200])
    # 0.54.0: the model decision engine is ENFORCED here, not merely documented. A task above the cheapest tier
    # with no admissible reason is a config error — the expensive choice has to justify itself or it does not ship.
    try:
        viol = contracts.policy_violations()
        r.check("every model above the cheapest tier names a reason", not viol, "; ".join(viol) or
                f"{sum(1 for d in contracts.policy_report() if d['verdict'] == 'cheapest')} at {contracts.cheapest()}, the rest justified")
    except Exception as e:  # noqa: BLE001
        r.check("every model above the cheapest tier names a reason", False, str(e)[:200])
    fl = flags_state()
    r.check("experimental flags at their safe defaults", all(v["ok"] for v in fl.values()), {k: v["current"] for k, v in fl.items() if not v["ok"]} or "all off")
    from . import claude_code
    lh = claude_code.health(wait=True)                      # doctor may block for the probe; the API surfaces never do
    r.check(claude_code.status_line(wait=True), lh.get("state") in ("ready", "disabled"), lh.get("detail") or "", warn=True)
    r.check("ANTHROPIC_API_KEY configured", bool(settings.anthropic_api_key) or settings.fake_ai, "set" if settings.anthropic_api_key else ("fake mode" if settings.fake_ai else "missing — chat, findings, ranking and planning need it"), warn=True)
    r.check("OPENAI_API_KEY configured", bool(settings.openai_api_key) or settings.fake_ai, "set" if settings.openai_api_key else ("fake mode" if settings.fake_ai else "missing — embeddings and transcription need it"), warn=True)
    r.check("Reddit API credentials (optional)", bool(settings.reddit_client_id and settings.reddit_client_secret) or None,
            "set" if settings.reddit_client_id else "not set — subreddit search (Explore) needs REDDIT_CLIENT_ID / REDDIT_CLIENT_SECRET; threads still arrive via the extension", warn=True)
    r.check("production models", True, {"answer": settings.answer_model, "findings": contracts.contract("findings.extract").model, "ranking": contracts.contract("rank.relevance").model, "embeddings": settings.embedding_model})
    # 0.52.0: a global local-model override silently replaces a per-task, measured model choice on every local call.
    # It is allowed — it is how the free subscription stays usable — but it must be visible, because the difference
    # between "Haiku because we measured it" and "Haiku because of one .env line" is the difference between a trade
    # and a regression.
    ov = settings.claude_code_model
    if ov:
        differs = sorted({c.task: c.model_for("local") for c in contracts.all_contracts()
                          if c.local_capable and c.model_for("local") != ov})
        r.check("local model override (NEUROSEARCH_CLAUDE_CODE_MODEL)", not differs,
                f"{ov} runs EVERY local task; the contracts ask for a different model on: {', '.join(differs)}" if differs
                else f"{ov} matches every local-capable contract", warn=True)
    else:
        r.check("local model follows each contract", True,
                {c.task: c.model_for("local") for c in contracts.all_contracts() if c.local_capable})
    # 0.56.3: what the contracts ASK for is only half of it — a provider can return something else. The local Claude
    # Code CLI did exactly that (claude-haiku-4-5 for a call pinned to claude-sonnet-4-6), which is a silent model
    # substitution arriving from outside the app. `providers.routing_for` now records every one; steady state is none.
    # 0.59.0: whoever pays for a local call decides whether "local-first" saves money or hides it.
    try:
        from . import claude_code as _cc
        from . import usage as _u
        mode = _cc.billing_mode()
        if settings.ai_profile == "local" and mode != _cc.BILLING_SUBSCRIPTION:
            rec = _u.reconcile(days=7)
            r.check("local calls are free (Claude Code on a subscription)", False,
                    f"billing_mode={mode} — {_cc.billing_note()} Last 7 days: ${rec['week']['recorded']:.2f} recorded, "
                    f"${rec['week']['local_if_billed']:.2f} on the local path, "
                    f"${rec['week']['likely_total']:.2f} likely charged.", warn=True)
        else:
            r.check("local billing understood", True, f"{mode} — {_cc.billing_note()}")
    except Exception as e:  # noqa: BLE001
        r.check("local billing understood", False, str(e)[:200], warn=True)
    mm = db.model_mismatches()
    r.check("no model substitutions recorded", not mm,
            "; ".join(f"{m['task']}: asked {m['requested']}, {m['executed_by']} returned {m['actual']} ×{m['count']}" for m in mm)
            or "every provider returned the model the contract requested", warn=True)
    # --- lightweight fake smoke: the deterministic engine works end to end in a temp database (no spend)
    if fake_smoke:
        was_fake, was_dir = settings.fake_ai, settings.data_dir
        tmp = Path(tempfile.mkdtemp(prefix="ns_doctor_"))
        settings.fake_ai, settings.data_dir = True, tmp
        db._local.conn = None
        try:
            from . import evals, findings, qa
            db.init_db()
            g = evals.load_golden(only={"yt01"})
            res = findings.suggest_for_source(g["project_id"], g["sources"]["yt01"])
            a = qa.ask("What is the minimum down payment?", project_id=g["project_id"])
            r.check("fake smoke: ingest → findings → chat", res["suggested"] > 0 and bool(a["citations"]), f"{res['suggested']} findings, {len(a['citations'])} citations")
        except Exception as e:  # noqa: BLE001
            r.check("fake smoke: ingest → findings → chat", False, str(e)[:200])
        finally:
            db._local.conn = None
            settings.fake_ai, settings.data_dir = was_fake, was_dir
            shutil.rmtree(tmp, ignore_errors=True)
    rep = r.done()
    rep["flags"] = fl
    progress(f"doctor: {rep['verdict']} ({rep['warnings']} warning{'s' if rep['warnings'] != 1 else ''}) in {rep['seconds']}s")
    return rep


# ------------------------------------------------------------------ release-check

def _pytest(args: list[str], timeout: int = 1800) -> tuple[bool, str]:
    env = {k: v for k, v in os.environ.items() if not k.startswith("NEUROSEARCH_")}
    p = subprocess.run([sys.executable, "-m", "pytest", *args, "-q", "-p", "no:cacheprovider"], cwd=str(ROOT), capture_output=True, text=True, timeout=timeout, env=env)
    tail = (p.stdout.strip().splitlines() or [""])[-1]
    return p.returncode == 0, tail if p.returncode == 0 else (p.stdout[-1500:] + p.stderr[-500:])


def _fresh(prefix: str) -> Path:
    tmp = Path(tempfile.mkdtemp(prefix=prefix))
    settings.data_dir = tmp
    db._local.conn = None
    db.init_db()
    return tmp


def release_check(progress: Any = print, out_dir: Path = Path("evals") / "release", skip_pytest: bool = False) -> dict[str, Any]:
    """The deterministic release gate. Every gate is one of the project's own frozen proofs; nothing is live."""
    from . import cache_layout, contracts, evals, prefilter_eval, retrieval_eval, schemas
    from .repo_check import check_repo
    r = _Report("release-check", progress)
    sha = _sha()
    progress(f"neurosearch release-check · app {__version__} @ {sha}")
    baselines: dict[str, Any] = {}
    fl = flags_state()
    r.check("experimental flags off by default", all(v["ok"] for v in fl.values() if v["status"] != "test mode (never in production)") and not settings.fake_ai,
            {k: v["current"] for k, v in fl.items() if not v["ok"]} or "all off")
    repo_findings = check_repo(ROOT)
    r.check("repository hygiene and architecture boundaries", not repo_findings,
            "; ".join(f"{f.rule} {f.file}:{f.location}" for f in repo_findings[:8]) or "repo-check PASS")
    ok, tail = _pytest(["tests/test_s43_foundation.py", "tests/test_s44_frontend_integrity.py", "tests/test_s45_storage_hygiene.py"])
    r.check("Foundation: worker lifecycle, DB ownership, explicit paid fallback, stale-client refusal, frontend and storage integrity", ok, tail)
    # 1. unit + indestructible + boundary suites (includes the crash matrix, the 40-source equivalence, migrations, breakers, fallback)
    if not skip_pytest:
        progress("pytest (whole suite)…")
        ok, tail = _pytest(["tests"])
        r.check("pytest: whole suite", ok, tail)
        if not ok:
            rep = r.done(); rep["baselines"] = baselines; rep["flags"] = fl
            return _finish(rep, out_dir, progress)
        ok, tail = _pytest(["tests/test_core.py", "-k", "migration or fixture_database or upgrade"])
        r.check("migration fixtures (0.1.0 → 0.16.0 databases upgrade cleanly)", ok, tail)
        ok, tail = _pytest(["tests/test_indestructible.py", "-k", "crash_recovery_equivalence or crash_matrix or crash"])
        r.check("crash/recovery matrix + 40-source equivalence", ok, tail)
        ok, tail = _pytest(["tests/test_k2_identity.py"])
        r.check("global identity: one acquisition, N project relationships (G1 feature gate)", ok, tail)
        ok, tail = _pytest(["tests/test_k3_resources.py"])
        r.check("universal input: containers never fall through to naive page ingestion (G2 feature gate)", ok, tail)
        ok, tail = _pytest(["tests/test_k4_explore.py"])
        r.check("exploration + Candidate Index: bounded listing, skipped candidates retained, never evidence (G3 feature gate)", ok, tail)
        ok, tail = _pytest(["tests/test_k5_library.py"])
        r.check("library intelligence: recall works with ZERO enriched profiles; profiles project-neutral; nothing attached (G4 gate)", ok, tail)
        ok, tail = _pytest(["tests/test_k7_chat_truncation.py"])
        r.check("chat never silently returns an incomplete generation: max_tokens → continuation, text+tool_use → final text, no dangling tool round (0.30.3 gate)", ok, tail)
        ok, tail = _pytest(["tests/test_k9_community.py"])
        r.check("community evidence: thread hierarchy + corrections preserved, independent experience ≠ repeated information, engagement never outranks substance, "
                "self-described context unverified, community cannot establish a rule, injection text is data, candidates resurface without re-enumeration (G7 gate)", ok, tail)
        ok, tail = _pytest(["tests/test_l1_browser_capture.py"])
        r.check("browser acquisition (B1): browser-solvable failure → requires_browser (durable external job), source stays in its project, the capture resolves the SAME job/source "
                "(also across restart and unsolicited), non-solvable failures stay failed, a successful reading never asks for Chrome, owned sources bypass the browser, queue carries no secrets", ok, tail)
        ok, tail = _pytest(["tests/test_m3_links.py"])
        r.check("candidate links (B3): an open question durably remembers the known-but-uncaptured sources that could fill it; acquisition by any path satisfies the link; "
                "dismissal is the user's word; Capture best N goes through attach → ingest job, never the web; chat's research state names what is known but uncaptured", ok, tail)
        ok, tail = _pytest(["tests/test_o1_accelerate.py"])
        r.check("acceleration dialog (L3): the backlog reports time on Claude Code and the SAME per-source dollar estimate the stale triage quotes; buying speed moves exactly the jobs chosen "
                "(api_requested, value order honoured) and nothing else; a cloud profile never offers it — slowness alone never spends", ok, tail)
        ok, tail = _pytest(["tests/test_o2_claims_workbench.py"])
        r.check("Claims workbench (R7): filter/facet/sort/page over the FULL claim set, never the 300-cap bootstrap page; one plain-language line replaces the internal vocabulary; "
                "batch accept/reject is project-scoped and refreshes once; 'Why this answer' finds the Claims a chat citation's source feeds; 'Settle this' reuses the normal target path", ok, tail)
        ok, tail = _pytest(["tests/test_n9_source_drawer.py"])
        r.check("source drawer (S3): one $0 request per source returns its measured value, its findings by status with what used each, the Claims resting on it, where it shows up "
                "(plan steps by title, chat answers by conversation — never a use the plan body does not reference) and its staleness tier with the one-source actions", ok, tail)
        ok, tail = _pytest(["tests/test_n8_research_shell.py"])
        r.check("Research shell (R2): the tab renders from ONE $0 request (overview(full=True) == the separate endpoints, one pass); a watch-out carries one verdict for every tension "
                "behind it and a dismissal survives the next refresh; the shell's panes, endpoints and question actions all exist on this build", ok, tail)
        ok, tail = _pytest(["tests/test_n7_pool.py"])
        r.check("known-but-uncaptured pool (S5): skipped pre-cutoff sources + Candidate Index rows in one list with a $0 potential scan (open questions, weak areas, vocabulary, "
                "timeless vs dated), why-known, capture through retry/acquire only, durable dismissal, never evidence", ok, tail)
        ok, tail = _pytest(["tests/test_n6_findings_workbench.py"])
        r.check("findings workbench (S4): server-side composable filters (text/status/importance/source/used-by/staleness/area), facets, sorts, paging, use badges from real plan/chat/Claim rows, "
                "the low-value sweep is a review list and never dismisses by itself", ok, tail)
        ok, tail = _pytest(["tests/test_n5_source_value.py"])
        r.check("source value (S2): what a source gave is measured from findings/Claims (independent evidence only)/plan/chat/priority with documented weights; 'matters' is a rule; "
                "rows on /api/sources carry value + staleness so the Sources filters compose", ok, tail)
        ok, tail = _pytest(["tests/test_n4_stale_triage.py"])
        r.check("stale triage (S1): the stale set partitions into rebuild-matters / transcript-changed / accept / retry-failed by why and weight; accepting is recorded against the exact inputs, "
                "survives assess until the inputs change, never touches findings, is refused for transcript changes; tier rebuilds queue only that tier; cost lines name the provider", ok, tail)
        ok, tail = _pytest(["tests/test_n3_deep_findings.py"])
        r.check("deep content (D1–D3): the findings cap is length-aware with a per-window coverage floor; overflow is kept as reserve (promotable, never exported/planned/harvested); "
                "a one-window source is the old top-12; Read deeper = smaller windows + a USER-message depth instruction, current on its own terms, staleness agrees; long sources are flagged under-read", ok, tail)
        ok, tail = _pytest(["tests/test_n2_local_ai.py"])
        r.check("Local-First AI (L1): local runs when ready; unavailable/usage-limit reaches the API only with explicit fallback opt-in and records why; local_only never touches the API; "
                "api_only/api_requested never touch local; cloud profile = local absent; the ledger carries provider + avoided spend; the stub CLI proves the subprocess contract", ok, tail)
        ok, tail = _pytest(["tests/test_n1_research_view.py"])
        r.check("Research view engine (R1/R3/R5/R6): a deterministic $0 priority order over questions and watch-outs (importance, planner dependence, impact, breadth, known sources); "
                "watch-outs are issues grouped by kind and area, never rows; areas are named from finding titles, never generic tokens; the sidebar number is what needs the user, never the Claim count", ok, tail)
        ok, tail = _pytest(["tests/test_m2_share.py"])
        r.check("portable answers (C0 Share ▾): a share variant is one model call over the finished answer, never a research pass; it can only cite the original's markers (strays removed and reported); budget-guarded", ok, tail)
        ok, tail = _pytest(["tests/test_m1_epub.py"])
        r.check("EPUB core (G6P1): spine order never ZIP order, EPUB 2 + 3, nested/missing TOC, non-English, broken markup, protected books refused (no circumvention); "
                "ordinary upload lifecycle, searchable, findings, answers, deterministic 'Ch. N → title · section' citations, same source on re-upload, ISBN/title+creator → the existing Work; "
                "G6P2: roles weight retrieval and findings windows without discarding anything, reader contract + in-app deep links", ok, tail)
        ok, tail = _pytest(["tests/test_l2_completeness.py"])
        r.check("capture completeness (B2): partial stays visibly partial (accept never means complete), 'more' stubs and DOM shortfalls recorded as provenance, a partial capture merges and never deletes "
                "what an earlier reading saw, only a complete reading marks vanished posts, several requests form a queue that advances, Reopen re-requests the SAME source", ok, tail)
        ok, tail = _pytest(["tests/test_k9b_reddit_html.py"])
        r.check("Reddit after 2026-06-30: extension-read thread → same global source; official API via app-only OAuth for threads + search; old.reddit page reading = JSON reading; refusals name the way forward (0.32.2 gate)", ok, tail)
        ok, tail = _pytest(["tests/test_k8_works.py"])
        r.check("canonical works: identifier → owned copy at $0; copies + derivatives = one lineage; citation → stub/candidate/target; version relationship drives freshness; "
                "ambiguous titles never merge; project relevance never mutates the Work (G6 gate)", ok, tail)
        ok, tail = _pytest(["tests/test_k6_claims.py"])
        r.check("research intelligence: one primary source → Strong; derivatives ≠ corroboration; outlier → tension; stale flagged; "
                "target escalates project → library → candidates → external and resurfaces a skipped candidate; boundary + provenance hold; $0 path (G5 gate)", ok, tail)
    # 2. schemas + contracts
    try:
        for name, sch in schemas.REGISTRY.items():
            schemas.check_provider_compat(sch, name)
        r.check("schema registry provider-compatible", True, sorted(schemas.REGISTRY))
        for task in ("answer.chat", "findings.extract", "rank.relevance", "planner.update", "discover.quick", "findings.prefilter", "retrieval.rerank"):
            contracts.contract(task)
        r.check("contracts valid", True)
    except Exception as e:  # noqa: BLE001
        r.check("schemas/contracts", False, str(e)[:200])
    # 0.58.3: the single-file UI is ~247 KB of inline JavaScript with no build step, so a stray brace shipped
    # silently and surfaced as a blank panel in the browser. release-check never looked at it until now.
    try:
        import re as _re
        import shutil as _sh
        import subprocess as _sp
        import tempfile as _tf
        html = (Path(__file__).resolve().parent / "web" / "index.html").read_text()
        js = "\n".join(_re.findall(r"<script(?![^>]*src=)[^>]*>(.*?)</script>", html, _re.S))
        node = _sh.which("node") or _sh.which("nodejs")
        ui_v = (_re.search(r"const UI_VERSION = '([^']+)'", html) or [None, None])[1]
        if ui_v != __version__:
            r.check("web/index.html UI_VERSION matches the package", False, f"{ui_v} != {__version__}")
        elif not node:
            r.check("web/index.html parses", True, "skipped — no JavaScript engine on this machine", warn=True)
        else:
            with _tf.NamedTemporaryFile("w", suffix=".js", delete=False) as f:
                f.write(js)
                jp = f.name
            out = _sp.run([node, "--check", jp], capture_output=True, text=True, timeout=90)
            r.check("web/index.html parses", out.returncode == 0,
                    (out.stderr or "")[:300] or f"{len(js)} chars of inline JS, UI_VERSION {ui_v}")
    except Exception as e:  # noqa: BLE001
        r.check("web/index.html parses", False, str(e)[:200])
    was_fake, was_dir, was_profile = settings.fake_ai, settings.data_dir, settings.ai_profile
    # Deterministic release proofs must use the same cloud-shaped fake adapter
    # as the test harness.  A developer .env may select local Claude Code; that
    # profile changes prompt/cache accounting even when fake_ai is enabled.
    settings.fake_ai = True
    settings.ai_profile = "cloud"
    try:
        # 3. Tier 1 with frozen numbers
        tmp = _fresh("ns_rc_tier1_")
        try:
            rep1 = evals.run(progress=lambda m: None)
            v = rep1["volume"]["by_task"]
            tot = lambda t: t["input_tokens"] + t["cache_read"] + t["cache_write"]  # noqa: E731
            frozen = {"answer": (34, 200052), "findings": (9, 30297), "plan": (2, 11026)}
            drift = {k: (v[k]["calls"], tot(v[k])) for k in frozen if (v[k]["calls"], tot(v[k])) != frozen[k]}
            r.check("Tier 1 gates PASS", rep1["pass"], {k: g for k, g in rep1["gates"].items() if not g["pass"]} or f"cache read rate {rep1['volume']['cache_read_rate']:.1%}")
            r.check("Tier 1 frozen totals unchanged (router-equivalence)", not drift, drift or frozen)
            so = rep1["structured_outputs"]
            r.check("Tier 1 zero structured-output events", all(so[k] == 0 for k in ("schema_mismatches", "schema_fallbacks", "output_truncated", "output_refused")), so)
            baselines["tier1"] = {"frozen_totals": frozen, "golden_fixture": "tests/fixtures/golden (manifest v%s)" % rep1.get("fixture_version", "1")}
        finally:
            db._local.conn = None; shutil.rmtree(tmp, ignore_errors=True)
        # 4. retrieval regression (hard fixture, fake tier baseline frozen at 0.22.0+i1)
        tmp = _fresh("ns_rc_retr_")
        try:
            rr = retrieval_eval.run(progress=lambda m: None)
            m = rr["metrics"]
            want = {"recall_at_1": 0.8, "recall_at_3": 0.9333, "recall_at_10": 1.0, "mrr": 0.8736, "ndcg_at_10": 0.8155, "locator_exact_at_first_hit": 0.8205, "hard_negative_false_positives": 2}
            drift = {k: m[k] for k in want if m[k] != want[k]}
            r.check("retrieval regression baseline (fake tier) unchanged", not drift, drift or want)
            baselines["retrieval"] = {"fake": want, "live_reference": "evals/retrieval/baseline-retrieval-0.22.0+i15-live.json (MRR 0.9093, R@1 86.7%, exact 87.2%)",
                                      "reranker_decision": "evals/retrieval/rerank-compare-20260907-115218-live.txt (KILL)"}
        finally:
            db._local.conn = None; shutil.rmtree(tmp, ignore_errors=True)
        # 5. cache-layout regression
        tmp = _fresh("ns_rc_cache_")
        try:
            cl = cache_layout.run(progress=lambda m: None)
            r.check("cache layout: stable chat prefix read on every later turn", cl["chat_layout"][0]["read"] == 0 and all(t["read"] > 0 for t in cl["chat_layout"][1:]) and all(t["write"] == 0 for t in cl["chat_layout"][1:]), [(t["read"], t["write"]) for t in cl["chat_layout"]])
            r.check("cache layout: input cost index below 1.0", cl["input_cost_index"] < 1.0, cl["input_cost_index"])
            baselines["cache_layout"] = {"input_cost_index": cl["input_cost_index"], "reference": "HARDENING.md Rung G second portion (0.844 at 0.20.0+g5)"}
        finally:
            db._local.conn = None; shutil.rmtree(tmp, ignore_errors=True)
        # 6. frozen economic gates (H1 stays deferred: the background path must still FAIL its gate; quality gates must hold)
        tmp = _fresh("ns_rc_econ_")
        try:
            pe = prefilter_eval.run(progress=lambda m: None)
            w = pe["modes"]["whole window"]
            r.check("H1 prefilter quality gates hold (recall 100%, nuggets reachable)", w["quality_pass"], {k: v for k, v in w["gates"].items() if not v and not k.startswith("background")} or "all pass")
            r.check("H1 prefilter economic gate still FAILS on the batch path (stays deferred)", not w["economics_pass"], w["scenarios"]["background"]["net_saved_share"])
            baselines["economics"] = {"prefilter_background_net_share": w["scenarios"]["background"]["net_saved_share"], "batch_discount": 0.5, "prices": "usage.PRICES (Haiku 1/5, Sonnet 5 2/10)"}
        finally:
            db._local.conn = None; shutil.rmtree(tmp, ignore_errors=True)
        # 7. backup → restore round trip
        tmp = _fresh("ns_rc_backup_")
        try:
            g = evals.load_golden(only={"yt01", "yt02"})
            n_before = db.connect().execute("SELECT COUNT(*) FROM segments").fetchone()[0]
            bp = db.backup()
            info = db.verify_database(bp)
            db._local.conn = None
            restored = tmp / "restored"; restored.mkdir()
            shutil.copy(bp, restored / "neurosearch.db")
            settings.data_dir = restored
            db._local.conn = None
            n_after = db.connect().execute("SELECT COUNT(*) FROM segments").fetchone()[0]
            ok_int = db.connect().execute("PRAGMA integrity_check").fetchone()[0] == "ok"
            r.check("backup verified and restore round trip equal", bool(info.get("ok", True)) and ok_int and n_after == n_before and n_before > 0, f"{n_before} segments → backup {bp.name} → restored {n_after}")
        except Exception as e:  # noqa: BLE001
            r.check("backup verified and restore round trip equal", False, str(e)[:200])
        finally:
            db._local.conn = None; shutil.rmtree(tmp, ignore_errors=True)
    finally:
        db._local.conn = None
        settings.fake_ai, settings.data_dir, settings.ai_profile = was_fake, was_dir, was_profile
    rep = r.done()
    rep["baselines"] = baselines
    rep["flags"] = fl
    return _finish(rep, out_dir, progress)


def _finish(rep: dict[str, Any], out_dir: Path, progress: Any) -> dict[str, Any]:
    rep["text"] = format_release(rep)
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    base = str(out_dir / f"release-check-{__version__}-{rep['git_sha']}-{stamp}")     # string concat: the version contains dots
    Path(base + ".json").write_text(json.dumps({k: v for k, v in rep.items() if k != "text"}, indent=1, default=str))
    Path(base + ".txt").write_text(rep["text"])
    rep["artifact"] = base + ".json"
    progress(f"artifact: {base}.json")
    return rep


def format_release(rep: dict[str, Any]) -> str:
    lines = [f"Release check · app {rep['app_version']} @ {rep['git_sha']} · {rep['timestamp']} · {rep['seconds']}s"]
    for c in rep["checks"]:
        lines.append(f"  {c['result']:4s}  {c['check']}" + (f"  — {c['detail']}" if c["result"] != "PASS" and c["detail"] is not None else ""))
    if rep.get("baselines"):
        lines.append("  baselines: " + json.dumps(rep["baselines"], default=str)[:600])
    lines.append(f"RELEASE CHECK {rep['verdict']}")
    return "\n".join(lines)
