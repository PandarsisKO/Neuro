"""Command line interface.  `neurosearch --help`"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

import typer

from . import db
from .config import settings

app = typer.Typer(help="Neuro Search — turn videos and podcasts into a citation-backed knowledge base.", no_args_is_help=True)
project_app = typer.Typer(help="Manage projects (topic groupings).", no_args_is_help=True)
app.add_typer(project_app, name="project")
t4_app = typer.Typer(help="T4: relevance-ranked, budgeted findings extraction.", no_args_is_help=True)
app.add_typer(t4_app, name="t4")


def _init() -> None:
    from .logctx import configure
    from .schemas import check_installation
    configure()
    check_installation()
    db.init_db()


@app.command()
def serve(host: str = "0.0.0.0", port: int = 8000,
          reload: bool = typer.Option(False, help="Restart automatically when the code changes (so updates apply without Ctrl+C)")) -> None:
    """Run the web app + API + MCP endpoint (background workers included). Alias: `neurosearch start`."""
    import uvicorn

    from . import __version__
    typer.echo(f"Neuro Search v{__version__} → http://localhost:{port}  (Ctrl+C to stop)")
    if reload:
        uvicorn.run("neurosearch.api:app", host=host, port=port, reload=True,
                    reload_dirs=[str(Path(__file__).parent)], reload_includes=["*.py", "*.html"])
    else:
        uvicorn.run("neurosearch.api:app", host=host, port=port)


@app.command()
def start(port: int = 8000) -> None:
    """Start the app with auto-restart on code updates (same as `serve --reload`)."""
    serve(port=port, reload=True)


@app.command()
def ingest(
    urls: list[str] = typer.Argument(..., help="Video / playlist / channel / podcast / Instagram / audio URLs"),
    tag: list[str] = typer.Option([], "--tag", "-t", help="Tag(s) to attach"),
    project: Optional[str] = typer.Option(None, "--project", "-p", help="Project name or id to add to"),
    force: bool = typer.Option(False, help="Re-ingest even if already ready"),
    wait: bool = typer.Option(True, help="Run workers here and wait until done"),
    remote: Optional[str] = typer.Option(None, envvar="NEUROSEARCH_REMOTE_URL",
                                         help="Legacy unsupported compatibility: extract here, store on a remote server"),
    token: Optional[str] = typer.Option(None, envvar="NEUROSEARCH_REMOTE_TOKEN", help="Legacy remote server token"),
) -> None:
    """Ingest URLs. Playlists and channels expand into every video."""
    from . import jobs

    if remote:
        from .remote import ingest_remote

        ingest_remote(urls, remote, token, tags=tag, project=project, force=force, echo=typer.echo)
        return

    _init()
    pid = None
    if project:
        p = db.find_project(project)
        if not p:
            typer.echo(f"no project '{project}'"); raise typer.Exit(1)
        pid = p["id"]
    for u in urls:
        j = jobs.enqueue("ingest_url", {"url": u, "tags": tag, "project_id": pid, "force": force, "review": False})
        typer.echo(f"queued {j['id'][:8]}  {u}")
    if wait:
        _run_until_idle()


@app.command()
def ingest_file(
    path: Path, title: Optional[str] = None, tag: list[str] = typer.Option([], "--tag", "-t"),
    project: Optional[str] = typer.Option(None, "--project", "-p"),
) -> None:
    """Transcribe and ingest a local audio/video file."""
    from .ingest import ingest_local_file

    _init()
    pid = _project_id(project)
    res = ingest_local_file(path, title=title, tags=tag, project_id=pid, progress=lambda p, m: typer.echo(f"  {int(p*100):3d}% {m}"))
    typer.echo(json.dumps(res, indent=1))


@app.command()
def ingest_text(
    path: Path, title: str = typer.Option(..., "--title"), url: Optional[str] = None,
    tag: list[str] = typer.Option([], "--tag", "-t"), project: Optional[str] = typer.Option(None, "--project", "-p"),
) -> None:
    """Ingest a transcript you already have as a text file (timestamps like `12:34 text` are honoured)."""
    from .ingest import ingest_text as _it

    _init()
    res = _it(title, path.read_text(), url=url, tags=tag, project_id=_project_id(project))
    typer.echo(json.dumps(res, indent=1))


@app.command()
def worker(n: Optional[int] = None) -> None:
    """Run background workers only (useful alongside `serve --workers 0` or on a separate machine)."""
    from . import jobs

    _init()
    jobs.start_workers(n)
    typer.echo("workers running; Ctrl-C to stop")
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        jobs.stop_workers()


def _run_until_idle() -> None:
    from . import jobs

    jobs.start_workers()
    last = ""
    try:
        while True:
            row = db.connect().execute(
                "SELECT SUM(status='queued') q, SUM(status='running') r FROM jobs WHERE status IN ('queued','running')").fetchone()
            q, r = row["q"] or 0, row["r"] or 0
            if q == 0 and r == 0:
                break
            running = db.connect().execute(
                "SELECT message FROM jobs WHERE status='running' ORDER BY started_at LIMIT 1").fetchone()
            msg = f"queued {q}  running {r}  {running['message'] if running else ''}"
            if msg != last:
                typer.echo(msg); last = msg
            time.sleep(2)
    finally:
        jobs.stop_workers()
    s = db.source_stats()
    typer.echo(f"done. {s['ready']} ready, {s['failed']} failed, {s['total_hours']} h total")
    for f in db.list_sources(status="failed", limit=20):
        typer.echo(f"  FAILED {f['title'] or f['url']}: {f['error']}")


@app.command()
def search(query: str, project: Optional[str] = typer.Option(None, "-p"), limit: int = 10) -> None:
    """Keyword + semantic search; prints excerpts with timestamp links."""
    from .search import search as _search

    _init()
    pid = _project_id(project)
    sids = (db.project_source_ids(pid) or ["__none__"]) if pid else None
    for h in _search(query, limit=limit, source_ids=sids):
        typer.echo(f"\n{h['title']} @ {h['timestamp']}  {h['link']}\n  {h['text'][:300]}")


@app.command()
def ask(question: str, project: Optional[str] = typer.Option(None, "-p"), web: bool = False,
        conversation: Optional[str] = typer.Option(None, "-c", help="conversation id to continue")) -> None:
    """Ask a question; prints an answer with numbered, timestamped citations."""
    from . import qa

    _init()
    res = qa.ask(question, project_id=_project_id(project), use_web=web, conversation_id=conversation)
    typer.echo(qa.render_markdown(res))


@app.command()
def cancel(kind: Optional[str] = typer.Option(None, help="only this job kind, e.g. ingest_source"),
           job_id: Optional[list[str]] = typer.Option(None, "--job", help="only these job ids (repeatable)")) -> None:
    """Cancel queued jobs (nothing that hasn't started will run) — all of them, one kind, or specific ids.
    Queued videos become 'proposed' so you can approve some of them later from the Review card in the app."""
    _init()
    n = db.cancel_queued_jobs(kinds=(kind,) if kind else None, job_ids=list(job_id) if job_id else None)
    typer.echo(f"cancelled {n} queued job(s)")


@app.command("eval")
def eval_cmd(live: bool = typer.Option(False, help="Tier 2: use the real models (costs money) instead of the deterministic fakes"),
             baseline: bool = typer.Option(False, help="Freeze this run as evals/baseline-<version>-<git sha>-<model>.json (never overwrites; see --force)"),
             force: bool = typer.Option(False, help="Allow --baseline to overwrite an existing baseline file"),
             compare: Optional[Path] = typer.Option(None, help="Baseline JSON to diff against"),
             out: Optional[Path] = typer.Option(None, help="Write the full report JSON here"),
             keep: bool = typer.Option(False, help="Keep the temporary database (path is printed)"),
             task_model: list[str] = typer.Option([], "--task-model", help="Experiment override task=model, e.g. findings.extract=claude-sonnet-5 (repeatable)"),
             task_thinking: list[str] = typer.Option([], "--task-thinking", help="Override task=disabled|adaptive[:effort], e.g. planner.build=adaptive:high"),
             task_max_tokens: list[str] = typer.Option([], "--task-max-tokens", help="Override task=N"),
             ranking: bool = typer.Option(False, "--ranking", help="Run only the frozen rank.relevance fixture (tests/fixtures/golden/ranking.json) and report ranking quality, tokens, cost and latency"),
             ranking_compare: bool = typer.Option(False, "--ranking-compare", help="E2: rank the frozen fixture with the baseline model and the candidate (both thinking disabled), save both, freeze the baseline if missing, save a side-by-side comparison and print a verdict"),
             findings_compare: bool = typer.Option(False, "--findings-compare", help="E2.2: run the Golden Project findings workload with the baseline model and the candidate (both thinking disabled), save both, freeze the baseline if missing, save a side-by-side comparison and print a verdict"),
             rerank: bool = typer.Option(False, "--rerank", help="I2 (with --retrieval): compare production ordering vs the retrieval.rerank stage on the same candidates under the frozen adoption rule; --live uses Haiku for the reranker and real embeddings"),
             retrieval: bool = typer.Option(False, "--retrieval", help="I1: run the HARD retrieval fixture (golden + tests/fixtures/golden/retrieval: distractors, hard negatives, chunk locators) through production search and report Recall@1/3/5/10, MRR, NDCG@10, ranks, locator accuracy, hard-negative false positives; changes nothing"),
             prefilter: bool = typer.Option(False, "--prefilter", help="H1: run the findings window pre-filter on the labeled window fixture (golden + tests/fixtures/golden/prefilter) and report recall, false negatives, nugget reachability, drop rate, tokens avoided, filter cost, net savings and leverage; whole-window and sampled modes"),
             cache_layout: bool = typer.Option(False, "--cache-layout", help="Rung G: measure the prompt-cache layout under the fake's provider-faithful cache simulation (findings, multi-turn project chat with state changes, new conversation, planner); free, changes nothing"),
             migration_compare: bool = typer.Option(False, "--migration-compare", help="E2.3: every remaining task (chat+repair, export, planner.update; planner.analysis/build with a 5-adaptive arm) 4.6 vs Sonnet 5 on identical frozen inputs, one verdict per task; changes nothing"),
             baseline_model: str = typer.Option(None, "--baseline-model", help="Baseline model for --ranking-compare, --findings-compare and --migration-compare (default claude-sonnet-4-6)"),
             candidate_model: str = typer.Option(None, "--candidate-model", help="Candidate model for --ranking-compare, --findings-compare and --migration-compare (default claude-sonnet-5)")) -> None:
    """Run the Golden Project through the whole pipeline and report quality, tokens, cost and latency (Tier 1 gates).
    With --ranking, run the dedicated rank.relevance fixture instead (independent of ingest/findings)."""
    import os
    import shutil
    import tempfile

    from . import evals
    from .config import settings

    def _key(task: str, what: str) -> str:
        return f"NEUROSEARCH_TASK_{what}_{task.upper().replace('.', '_')}"
    for spec in task_model:
        t, m = spec.split("=", 1); os.environ[_key(t, "MODEL")] = m
    for spec in task_thinking:
        t, v = spec.split("=", 1); th, _, eff = v.partition(":")
        os.environ[_key(t, "THINKING")] = th
        if eff:
            os.environ[_key(t, "EFFORT")] = eff
    for spec in task_max_tokens:
        t, n = spec.split("=", 1); os.environ[_key(t, "MAX_TOKENS")] = n

    tmp = Path(tempfile.mkdtemp(prefix="ns_eval_"))
    settings.data_dir = tmp                      # never touch the real database
    settings.fake_ai = not live
    # L-02 (EXECUTION-LADDER.md): providers.route() decides local-vs-api purely from settings.ai_profile /
    # current_policy() / claude_code.health() -- it never looks at settings.fake_ai. On a machine whose .env
    # sets NEUROSEARCH_AI_PROFILE=local (Kyle's), a Tier-1 eval with fake_ai=True still routes local_capable
    # tasks (e.g. findings.extract under --prefilter) to the REAL claude CLI, so it is not actually free or
    # deterministic. Pin the transport to api_only whenever we're not --live, so the fake anthropic_client
    # serves every call regardless of the developer's local profile; always restore on the way out.
    _pin = evals.pin_api_transport() if not live else None
    try:
            if live and retrieval and rerank:
                if not (settings.openai_api_key and settings.anthropic_api_key):
                    raise typer.BadParameter("--retrieval --rerank --live needs OPENAI_API_KEY (embeddings) and ANTHROPIC_API_KEY (the Haiku reranker)")
            elif live and retrieval:
                if not settings.openai_api_key:
                    raise typer.BadParameter("--retrieval --live needs OPENAI_API_KEY (embeddings only; it makes no Anthropic calls)")
            elif live and not settings.anthropic_api_key:
                raise typer.BadParameter("--live needs ANTHROPIC_API_KEY (and OPENAI_API_KEY for embeddings)")
            db.init_db()
            if retrieval and rerank:
                from . import retrieval_eval as RE
                rep = RE.run_rerank_compare(progress=lambda m: typer.echo("  · " + m))
                typer.echo("")
                typer.echo(rep["text"])
                d = Path("evals") / "retrieval"
                d.mkdir(parents=True, exist_ok=True)
                stamp = time.strftime("%Y%m%d-%H%M%S")
                art = d / f"rerank-compare-{stamp}-{rep['tier']}.json"
                art.write_text(json.dumps({k: v for k, v in rep.items() if k not in ("text", "base_report", "cand_report")}, indent=1, default=str))
                (d / f"rerank-compare-{stamp}-{rep['tier']}.txt").write_text(rep["text"])
                typer.echo(f"artifact: {art}")
                if out:
                    out.write_text(json.dumps({k: v for k, v in rep.items() if k != "text"}, indent=1, default=str))
                shutil.rmtree(tmp, ignore_errors=True)
                raise typer.Exit(code=0 if rep["verdict"] == "ADOPT" else 1)
            if retrieval:
                from . import retrieval_eval as RE
                rep = RE.run(progress=lambda m: typer.echo("  · " + m))
                typer.echo("")
                typer.echo(rep["text"])
                if out:
                    out.write_text(json.dumps({k: v for k, v in rep.items() if k != "text"}, indent=1, default=str))
                if baseline:
                    from . import __version__
                    d = Path("evals") / "retrieval"
                    d.mkdir(parents=True, exist_ok=True)
                    sha = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True).stdout.strip() or "nogit"
                    bp = d / f"baseline-retrieval-{__version__}-{rep['tier']}.json"
                    if bp.exists() and not force:
                        raise typer.BadParameter(f"{bp} exists (use --force)")
                    bp.write_text(json.dumps({**{k: v for k, v in rep.items() if k != "text"}, "app_version": __version__, "git_sha": sha}, indent=1, default=str))
                    typer.echo(f"baseline frozen: {bp}")
                shutil.rmtree(tmp, ignore_errors=True)
                raise typer.Exit(code=0)
            if prefilter:
                from . import prefilter_eval as PE
                rep = PE.run(progress=lambda m: typer.echo("  · " + m))
                typer.echo("")
                typer.echo(rep["text"])
                if out:
                    out.write_text(json.dumps({k: v for k, v in rep.items() if k != "text"}, indent=1, default=str))
                if keep:
                    typer.echo(f"database kept at {tmp}")
                else:
                    shutil.rmtree(tmp, ignore_errors=True)
                raise typer.Exit(code=0 if rep["pass"] else 1)
            if cache_layout:
                from . import cache_layout as CL
                if live:
                    raise typer.BadParameter("--cache-layout is a fake-tier measurement (the provider's cache is simulated exactly); there is no live mode")
                rep = CL.run(progress=lambda m: typer.echo("  · " + m))
                typer.echo("")
                typer.echo(rep["text"])
                if out:
                    out.write_text(json.dumps({k: v for k, v in rep.items() if k != "text"}, indent=1, default=str))
                shutil.rmtree(tmp, ignore_errors=True)
                raise typer.Exit(code=0)
            if migration_compare:
                from . import migration
                cmp = migration.run_migration_compare(live=live, progress=lambda m: typer.echo("  · " + m),
                                                      baseline_model=baseline_model or migration.BASELINE_MODEL,
                                                      candidate_model=candidate_model or migration.CANDIDATE_MODEL)
                typer.echo("")
                typer.echo(cmp["text"])
                if out:
                    out.write_text(json.dumps({k: v for k, v in cmp.items() if k != "text"}, indent=1, default=str))
                if keep:
                    typer.echo(f"database kept at {tmp}")
                else:
                    shutil.rmtree(tmp, ignore_errors=True)
                raise typer.Exit(code=0 if all(v != "FAIL" for v in cmp["summary"].values()) else 1)
            if ranking_compare or findings_compare:
                fn = evals.run_findings_compare if findings_compare else evals.run_ranking_compare
                cmp = fn(live=live, baseline_model=baseline_model or evals.BASELINE_MODEL, candidate_model=candidate_model or evals.CANDIDATE_MODEL,
                         progress=lambda m: typer.echo("  · " + m))
                typer.echo("")
                typer.echo(cmp["text"])
                if out:
                    out.write_text(json.dumps({k: v for k, v in cmp.items() if k != "text"}, indent=1))
                if keep:
                    typer.echo(f"database kept at {tmp}")
                else:
                    shutil.rmtree(tmp, ignore_errors=True)
                raise typer.Exit(code=0 if cmp["verdict"]["verdict"] != "FAIL" else 1)
            if ranking:
                rep = evals.run_ranking(live=live, progress=lambda m: typer.echo("  · " + m))
                typer.echo("")
                typer.echo(evals.format_ranking_report(rep))
            else:
                rep = evals.run(live=live, progress=lambda m: typer.echo("  · " + m))
                typer.echo("")
                typer.echo(evals.format_report(rep))
            if compare:
                base = json.loads(compare.read_text())
                if (base.get("eval") == "ranking") != ranking:
                    typer.echo(f"\nREFUSING to compare: {compare} is a {'ranking' if base.get('eval') == 'ranking' else 'pipeline'} baseline and this is a {'ranking' if ranking else 'pipeline'} run")
                    raise typer.Exit(code=2)
                typer.echo("\nVS BASELINE " + str(compare))
                for line in (evals.compare_ranking if ranking else evals.compare)(rep, base) or ["  no differences"]:
                    typer.echo("  " + line)
            if baseline:
                d = Path("evals"); d.mkdir(exist_ok=True)
                f = d / f"baseline-{'rank-' if ranking else ''}{rep['app_version']}-{rep['git_sha']}-{rep['model'].replace('/', '_').replace('claude-', '')}.json"
                if f.exists() and not force:
                    typer.echo(f"\nREFUSING to overwrite the existing baseline {f} — a baseline is a historical measurement; pass --force if you really mean it")
                    raise typer.Exit(code=2)
                f.write_text(json.dumps(rep, indent=1))
                typer.echo(f"\nbaseline written → {f}")
            if out:
                out.write_text(json.dumps(rep, indent=1))
            if keep:
                typer.echo(f"database kept at {tmp}")
            else:
                shutil.rmtree(tmp, ignore_errors=True)
            raise typer.Exit(code=0 if rep["pass"] else 1)


    finally:
        if _pin is not None:
            evals.unpin_api_transport(*_pin)

@app.command()
def closeout(live: bool = typer.Option(False, help="After the free deterministic phase, run the ONE paid Mission F closeout (findings, ranking, planner.update, discover.quick, Planner V1 vs V3)"),
             no_pytest: bool = typer.Option(False, "--no-pytest", help="Skip the pytest step of the deterministic phase (tests only)"),
             resume: bool = typer.Option(False, "--resume", help="Reuse the completed stages (and the database) of the most recent closeout run; only unfinished or invalidated stages run again")) -> None:
    """Mission F closeout: deterministic gates first (pytest, schema compat, Tier 1 with Planner V1 and V3, rubric), then one narrowly scoped
    live run; ends with Mission F PASS / PASS WITH CAVEAT / FAIL and a separate Planner V3 PROMOTE / DO NOT PROMOTE. Changes nothing."""
    from . import closeout as C
    from .config import settings
    if live and not settings.anthropic_api_key:
        raise typer.BadParameter("--live needs ANTHROPIC_API_KEY (and OPENAI_API_KEY for embeddings)")
    rep = C.run_closeout(live=live, progress=lambda m: typer.echo("  · " + m), run_pytest=not no_pytest, resume=resume)
    typer.echo("")
    typer.echo(rep["text"])
    raise typer.Exit(code=0 if rep["mission"]["verdict"] not in ("FAIL", "INCOMPLETE") else 1)


@app.command()
def contracts() -> None:
    """Show the inference contract of every AI task (with any NEUROSEARCH_TASK_* overrides applied)."""
    from .contracts import all_contracts
    for c in all_contracts():
        d = c.describe()
        typer.echo(f"{c.task:18s} {c.provider:9s} {c.model:30s} thinking={c.thinking}{'/' + c.effort if c.effort else ''}  max_out={c.max_output_tokens}  "
                   f"attempts={c.max_attempts} timeout={c.timeout or 'default'}  {'interactive' if c.interactive else 'background'}"
                   f"{'  batch-ok' if c.batch_allowed else ''}  fallback={c.fallback}  schema={c.schema}"
                   + (f"  local={c.model_for('local')}" if c.local_capable else ""))


@app.command()
def models() -> None:
    """The model decision for every AI task, and why — the engine's whole output in one table.

    The rule: every task runs the cheapest tier unless its contract names an admissible reason
    (capability / evidence / user / irreversible). Anything above the cheapest tier with no reason is a config
    error and release-check refuses it."""
    from .contracts import REASON_STRENGTH, cheapest, policy_report, policy_violations
    rows = [d for d in policy_report() if d["verdict"] != "n/a"]
    typer.echo(f"cheapest tier: {cheapest()}   ·   {sum(1 for d in rows if d['verdict'] == 'cheapest')} of {len(rows)} tasks are on it\n")
    for d in sorted(rows, key=lambda d: (d["verdict"] == "cheapest", d["task"])):
        strength = d.get("strength") or ""
        tag = {"fact": "●", "measured": "●", "debt": "○", "opinion": "○"}.get(strength, " ")
        typer.echo(f"{d['task']:20s} {d['model']:20s} {tag} {d['verdict']:13s} {d['why']}")
        if d.get("settled_by"):
            typer.echo(f"{'':20s} {'':20s}   ↳ {d['settled_by']}")
    bad = policy_violations()
    typer.echo("\n" + ("every task is at the cheapest tier or names an admissible reason"
                        if not bad else "UNJUSTIFIED:\n  " + "\n  ".join(bad)))
    typer.echo(f"reason strength: {REASON_STRENGTH}")


@app.command()
def backup() -> None:
    """Snapshot the database now (also happens automatically on start and hourly) → data/backups/."""
    _init()
    typer.echo(str(db.backup()))


@app.command()
def status() -> None:
    """Knowledge base stats and recent jobs."""
    _init()
    typer.echo(json.dumps(db.source_stats(), indent=1))
    typer.echo(json.dumps(db.health(), indent=1, default=str))
    for j in db.list_jobs(10):
        typer.echo(f"{j['id'][:8]} {j['kind']:14s} {j['status']:8s} {int(j['progress']*100):3d}% {j.get('message') or ''}")


@app.command()
def sources(status: Optional[str] = None, q: Optional[str] = None, project: Optional[str] = typer.Option(None, "-p")) -> None:
    """List sources."""
    from .chunking import fmt_ts

    _init()
    rows = db.list_sources(status=status, query=q, limit=10000)
    pid = _project_id(project)
    if pid:
        ids = set(db.project_source_ids(pid)); rows = [r for r in rows if r["id"] in ids]
    for s in rows:
        typer.echo(f"{s['status']:8s} {fmt_ts(s['duration'] or 0):>8s}  {s['title']}  [{s['id'][:8]}]")


@app.command()
def export(out: Path = Path("neurosearch_sources.csv"), segments: bool = False,
           project: Optional[str] = typer.Option(None, "-p")) -> None:
    """Write the master sheet (one row per source, or per timestamped chunk with --segments)."""
    import csv

    from .chunking import fmt_ts
    from .search import deep_link, source_transcript

    _init()
    rows = db.list_sources(limit=100000)
    pid = _project_id(project)
    if pid:
        ids = set(db.project_source_ids(pid)); rows = [r for r in rows if r["id"] in ids]
    with open(out, "w", newline="") as fh:
        w = csv.writer(fh)
        if segments:
            w.writerow(["source_id", "title", "channel", "published", "timestamp", "link", "text"])
            for r in rows:
                for c in db.get_chunks(r["id"]):
                    w.writerow([r["id"], r["title"], r["channel"], r["published_at"], fmt_ts(c["start"]),
                                deep_link(r["url"], r["platform"], c["start"]), c["text"]])
        else:
            w.writerow(["id", "title", "channel", "platform", "published", "duration", "url", "status", "tags", "transcript"])
            for r in rows:
                w.writerow([r["id"], r["title"], r["channel"], r["platform"], r["published_at"], fmt_ts(r["duration"] or 0),
                            r["url"], r["status"], ",".join(r.get("tags") or []),
                            source_transcript(r["id"], with_timestamps=False) if r["status"] == "ready" else ""])
    typer.echo(f"wrote {out} ({len(rows)} sources)")


@app.command()
def reembed() -> None:
    """Embed any chunks that are missing vectors (e.g. after adding OPENAI_API_KEY)."""
    from .embeddings import embed_pending

    _init()
    typer.echo(f"embedded {embed_pending(limit=10**6)} chunks")


# ------------------------------------------------------------- projects

def _project_id(name_or_id: Optional[str]) -> Optional[str]:
    if not name_or_id:
        return None
    p = db.find_project(name_or_id)
    if not p:
        typer.echo(f"no project '{name_or_id}'", err=True); raise typer.Exit(1)
    return p["id"]


@project_app.command("list")
def project_list() -> None:
    _init()
    for p in db.list_projects():
        typer.echo(f"{p['name']}  ({p['n_sources']} sources)  [{p['id']}]\n   {p.get('brief') or ''}")


@project_app.command("create")
def project_create(name: str, brief: Optional[str] = None, tag: list[str] = typer.Option([], "--tag", "-t")) -> None:
    _init()
    p = db.create_project(name, brief, tag)
    typer.echo(f"created {p['name']} [{p['id']}]")


@project_app.command("add")
def project_add(project: str, source_ids: list[str] = typer.Argument(None),
                collection: list[str] = typer.Option([], "--collection", help="collection id(s)")) -> None:
    """Add sources (by id or id prefix) and/or collections to a project."""
    _init()
    pid = _project_id(project)
    assert pid
    full = []
    for s in source_ids or []:
        row = db.connect().execute("SELECT id FROM sources WHERE id LIKE ?", (s + "%",)).fetchall()
        if len(row) != 1:
            typer.echo(f"ambiguous or unknown source '{s}'", err=True); continue
        full.append(row[0]["id"])
    from . import identity
    for sid in full:
        r = identity.attach_existing(pid, sid)
        typer.echo(f"  {r.state.lower().replace('_', ' ')}: {r.source.get('title') or sid}")
    db.add_project_collections(pid, collection)
    p = db.get_project(pid)
    typer.echo(f"{p['name']} now has {p['n_sources']} sources")  # type: ignore[index]


@project_app.command("findings")
def project_findings(project: str, out: Optional[Path] = None) -> None:
    """Print (or write) the findings document for a project."""
    from .export import findings_markdown

    _init()
    text = findings_markdown(_project_id(project))  # type: ignore[arg-type]
    if out:
        out.write_text(text); typer.echo(f"wrote {out}")
    else:
        typer.echo(text)


@project_app.command("masterplan")
def project_masterplan(project: str, out: Optional[Path] = None, no_synthesize: bool = False) -> None:
    """Export the portable masterplan package (zip) for use in ChatGPT/Claude/other tools."""
    from .export import build_masterplan_zip

    _init()
    pid = _project_id(project)
    assert pid
    data = build_masterplan_zip(pid, synthesize=not no_synthesize)
    out = out or Path(f"{project.replace(' ', '_')}_masterplan.zip")
    out.write_bytes(data)
    typer.echo(f"wrote {out} ({len(data) // 1024} KB)")


@project_app.command("plan")
def project_plan(project: str, build: bool = typer.Option(False, help="(Re)build the plan first"),
                 out: Optional[Path] = None, html: bool = False) -> None:
    """Show or export the Master Plan (markdown, or --html for a shareable page)."""
    from . import planner

    _init()
    pid = _project_id(project)
    assert pid
    if build:
        planner.build_plan(pid)
    row = db.latest_plan(pid)
    if not row:
        typer.echo("no plan yet — run with --build"); raise typer.Exit(1)
    p = db.get_project(pid)
    text = planner.plan_html(row, p) if html else planner.plan_markdown(row, p)  # type: ignore[arg-type]
    if out:
        out.write_text(text); typer.echo(f"wrote {out}")
    else:
        typer.echo(text)


@project_app.command("delete")
def project_delete(project: str) -> None:
    _init()
    pid = _project_id(project)
    assert pid
    db.delete_project(pid)
    typer.echo("deleted")


@project_app.command("rebuild-stale")
def project_rebuild_stale(project: str, tier: str = typer.Option("rebuild_matters", help="rebuild_matters | rebuild_transcript | retry_failed | accept"),
                          at: Optional[str] = typer.Option(None, "--at", help="HH:MM local time — run no earlier than this (today, or tomorrow if that time already passed)"),
                          transport: str = typer.Option("interactive", help="interactive (one job per source) | batch (one background job)")) -> None:
    """L-20 (EXECUTION-LADDER.md P1A): queue a triage tier's stale sources for rebuild, optionally not before a
    given local time. Schedule from the CLI and exit the shell — a worker picks this up later, exactly once,
    whether the host was awake at --at or not. Host-honest by design: this NEVER prints "runs at HH:MM" as a
    promise, because nothing guarantees the machine is awake or the worker is running then (see
    PRODUCT-INTELLIGENCE-MISSION.md's idle-sleep/lid-closure sections) — only that the job will not be claimed
    any EARLIER than that time, and will run at the worker's next eligible start after it."""
    from . import staleness

    _init()
    pid = _project_id(project)
    assert pid
    source_ids = [r["source_id"] for r in staleness.triage(pid)["tiers"].get(tier, {}).get("sources", [])]
    if not source_ids:
        typer.echo(f"nothing to rebuild in tier '{tier}'")
        return
    not_before = None
    if at:
        try:
            hh, mm = (int(x) for x in at.split(":", 1))
        except ValueError:
            typer.echo(f"--at must be HH:MM, got {at!r}"); raise typer.Exit(1)
        now_t = time.localtime()
        target = time.struct_time((now_t.tm_year, now_t.tm_mon, now_t.tm_mday, hh, mm, 0, 0, 0, -1))
        not_before = time.mktime(target)
        if not_before <= time.time():
            not_before += 86400                                    # already passed today — tomorrow instead
    r = staleness.rebuild(pid, ["findings"], source_ids, transport=transport, not_before=not_before)
    if not_before is not None:
        typer.echo(f"queued {r['queued']} job(s) for tier '{tier}' — runs when the worker is next available, "
                  f"no earlier than {time.strftime('%Y-%m-%d %H:%M', time.localtime(not_before))} local time")
    else:
        typer.echo(f"queued {r['queued']} job(s) for tier '{tier}'")


@project_app.command("rescan")
def project_rescan(project: str, collection: Optional[str] = typer.Option(None, "--collection", help="Rescan just this collection id; default rescans every collection the project is attached to"),
                   as_json: bool = typer.Option(False, "--json", help="Emit stable machine-readable JSON")) -> None:
    """CR3/CR4 (PRODUCT-INTELLIGENCE-MISSION.md §13): on-demand known-reservoir rescan. MONITOR only — reads the
    reservoir's current listing and records any not-yet-seen items as cheap Candidate Index rows (never
    ingestion, never a provider/model call). An unchanged reservoir this project has already reconciled costs
    nothing beyond the one listing read. Never scheduled — the user (or the app, on the user's click) runs this."""
    from . import reservoir

    _init()
    pid = _project_id(project)
    assert pid
    results = [reservoir.rescan(pid, collection)] if collection else reservoir.rescan_project(pid)
    if as_json:
        typer.echo(json.dumps(results, indent=1))
        return
    if not results:
        if collection:
            typer.echo("no such collection attached to this project")
        elif not db.project_collection_ids(pid):
            typer.echo("this project is not attached to any collection to rescan")
        else:
            typer.echo("every attached collection is unmonitored (source_role/monitor_policy) -- nothing to "
                      "rescan; see `neurosearch project collection-policy`")
        return
    for r in results:
        col = db.get_collection(r["collection_id"])
        title = (col or {}).get("title") or r["collection_id"]
        if not r["changed"]:
            typer.echo(f"{title}: unchanged since the last rescan — nothing to do")
        else:
            typer.echo(f"{title}: {r['new']} new of {r['total']} listed")


if __name__ == "__main__":
    app()


@app.command("batch-smoke")
def batch_smoke(live: bool = typer.Option(False, help="Submit ONE real Anthropic Message Batch item (pennies); without it the same flow runs against the fakes"),
                timeout_min: float = typer.Option(60.0, "--timeout-min", help="How long to poll for the batch to end before reporting FAIL (the batch is never cancelled)")) -> None:
    """Rung G real-provider smoke test of the Message Batches adapter: one frozen single-window findings item through the
    normal queue (external_pending → poll → raw result persisted → custom_id verified → findings-v2 validation + quote
    validator → findings.materialize transport=batch) in an eval-only database, with token-counted expected vs actual
    batch pricing and zero-schema-event checks. Ends with PASS or FAIL and writes evals/batch-smoke/<stamp>-<sha>-<tier>.{json,txt}."""
    from . import batch_smoke as B
    from .config import settings
    if live and not settings.anthropic_api_key:
        raise typer.BadParameter("--live needs ANTHROPIC_API_KEY in .env")
    rep = B.run(live=live, progress=lambda m: typer.echo("  · " + m), timeout_min=timeout_min)
    typer.echo("")
    typer.echo(rep["text"])
    raise typer.Exit(code=0 if rep["verdict"] == "PASS" else 1)


@app.command()
def doctor(no_smoke: bool = typer.Option(False, "--no-smoke", help="Skip the lightweight fake smoke (ingest → findings → chat in a temp database)")) -> None:
    """Fast operational diagnostic (seconds): install and runtime integrity, database, backups, schema registry, contracts,
    experimental defaults, provider/model configuration, steady-state Health counters, and a small fake smoke. Read-only on
    your data. Run it after installing or whenever Neuro Search feels unhealthy."""
    from . import release
    rep = release.doctor(progress=typer.echo, fake_smoke=not no_smoke)
    raise typer.Exit(code=0 if rep["verdict"] == "PASS" else 1)


@app.command("release-check")
def release_check_cmd(no_pytest: bool = typer.Option(False, "--no-pytest", help="Skip the pytest gates (the other deterministic proofs still run)")) -> None:
    """The heavyweight deterministic release gate (minutes, no live calls): pytest, Tier 1 with frozen numbers, schemas and
    contracts, migration fixtures, crash/recovery matrix + equivalence, retrieval and cache-layout regression baselines, the
    frozen economic gates, a backup → restore round trip, and experimental flags off by default. Writes
    evals/release/release-check-<version>-<sha>-<stamp>.{json,txt}."""
    from . import release
    rep = release.release_check(progress=lambda m: typer.echo("  · " + m if not m.startswith("  ") else m), skip_pytest=no_pytest)
    typer.echo("")
    typer.echo(rep["text"])
    raise typer.Exit(code=0 if rep["verdict"] == "PASS" else 1)


@app.command("repo-check")
def repo_check_cmd(as_json: bool = typer.Option(False, "--json", help="Emit stable machine-readable JSON")) -> None:
    """Report deterministic repository hygiene findings without opening the database or making network calls."""
    from .repo_check import check_repo, render
    typer.echo(render(check_repo(Path.cwd()), as_json=as_json), nl=False)


@app.command("assumptions")
def assumptions_cmd(as_json: bool = typer.Option(False, "--json", help="Emit stable machine-readable JSON")) -> None:
    """T6: list every registered assumption (a constant that encodes a judgement about the data), its current
    live value, whether it has been measured against live data, and how to re-verify it. Read-only; makes no
    database, provider, or network call. Drift is informational only -- see `doctor` for the one-line summary."""
    from . import assumptions
    typer.echo(assumptions.render(as_json=as_json), nl=False)


@t4_app.command("execute")
def t4_execute_cmd(project: str, budget: float = typer.Option(..., "--budget", help="Dollar cap for this call, spent in relevance order"),
                   max_sources: Optional[int] = typer.Option(None, "--max-sources", help="Also cap the number of sources, whichever limit hits first"),
                   floor: Optional[int] = typer.Option(30, "--floor", help="Substance floor for the first-window probe (see findings.suggest_for_source); pass --floor -1 to disable"),
                   min_relevance: Optional[float] = typer.Option(None, "--min-relevance", help="Skip sources scored below this (unscored sources are skipped too, once this is set)"),
                   live: bool = typer.Option(False, "--live", help="Actually enqueue jobs; without this, only prints the plan and estimate"),
                   batch: bool = typer.Option(False, "--batch", help="Use the Message Batches transport (one job for every selected source) instead of one job per source"),
                   paid: bool = typer.Option(False, "--paid", help="Force the metered API path (execution_policy=api_requested) instead of the default free-when-available local execution -- needed to measure real dollar cost (e.g. E5's Sonnet vs Haiku comparison)"),
                   yes: bool = typer.Option(False, "--yes", "-y", help="Skip the confirmation prompt before a --live enqueue")) -> None:
    """T4 E2: the budgeted executor. Ranks this project's sources by relevance (t4.select), then walks them in
    that order enqueuing real findings-extraction work until BUDGET or MAX_SOURCES is hit. Defaults to a dry run
    that prints the plan and enqueues nothing; pass --live to actually enqueue."""
    from . import t4
    pid = _project_id(project)
    if pid is None:
        typer.echo(f"no project matches {project!r}", err=True)
        raise typer.Exit(code=1)
    sub_floor = None if floor is not None and floor < 0 else floor
    exec_policy = "api_requested" if paid else None
    plan = t4.execute(pid, budget_usd=budget, max_sources=max_sources, substance_floor=sub_floor,
                      min_relevance=min_relevance, dry_run=True, transport="batch" if batch else "interactive",
                      execution_policy=exec_policy)
    typer.echo(json.dumps(plan, indent=2))
    if not live:
        return
    if not plan["sources"]:
        typer.echo("nothing to execute: no eligible source within budget")
        return
    if not yes and not typer.confirm(f"Enqueue {plan['count']} source(s), estimated ${plan['total_estimate']:.4f}?"):
        raise typer.Exit(code=0)
    result = t4.execute(pid, budget_usd=budget, max_sources=max_sources, substance_floor=sub_floor,
                        min_relevance=min_relevance, dry_run=False, transport="batch" if batch else "interactive",
                        execution_policy=exec_policy)
    typer.echo(json.dumps(result, indent=2))


# ---------------------------------------------------------------------------------------------------------------
# L-30 / L-41 CLI surface (EXECUTION-LADDER.md Stages 4 and 6). Without these, nightly.run() and
# report.render_text() existed but could only be reached by writing Python -- which made the "human step" for
# those rungs' gates larger than it needed to be, not smaller.
# ---------------------------------------------------------------------------------------------------------------
nightly_app = typer.Typer(help="Nightly envelope: one bounded, preflighted autonomous run per day, and its Morning Report.", no_args_is_help=True)
app.add_typer(nightly_app, name="nightly")


@nightly_app.command("status")
def nightly_status() -> None:
    """Is the nightly envelope on, has it run today, and what did it do? $0, reads only."""
    from . import nightly
    _init()
    on = settings.t4_nightly_budget > 0
    typer.echo(f"nightly envelope: {'ON' if on else 'OFF'} (NEUROSEARCH_T4_NIGHTLY_BUDGET_USD={settings.t4_nightly_budget}, "
               f"NEUROSEARCH_T4_NIGHTLY_HOUR={settings.t4_nightly_hour}, T5 adjudication "
               f"NEUROSEARCH_T5_NIGHTLY_BUDGET_USD={settings.t5_nightly_budget})")
    if not on:
        typer.echo("  set NEUROSEARCH_T4_NIGHTLY_BUDGET_USD to a per-night dollar cap (e.g. 2) to turn it on; the worker's "
                   "housekeeping loop then runs it once per day after the configured local hour")
    last = nightly.last_run()
    if last is None:
        typer.echo("  today: has not run yet" + (f" (due now: {nightly.due()})" if on else ""))
        return
    typer.echo(json.dumps(last, indent=2))


@nightly_app.command("run")
def nightly_run_cmd(budget: Optional[float] = typer.Option(None, "--budget", help="Per-night dollar cap for THIS run (overrides NEUROSEARCH_T4_NIGHTLY_BUDGET_USD for this invocation only)"),
                    t5_budget: Optional[float] = typer.Option(None, "--t5-budget", help="SEPARATE per-night cap for T5 adjudication (Sonnet-tier calls; L-60). Default: NEUROSEARCH_T5_NIGHTLY_BUDGET_USD, 0 = off"),
                    research_refresh_budget: Optional[float] = typer.Option(None, "--research-refresh-budget", help="SEPARATE per-night cap for CR6 research refreshes (Continuous Research). Default: NEUROSEARCH_RESEARCH_REFRESH_NIGHTLY_BUDGET_USD, 0 = off"),
                    force: bool = typer.Option(False, "--force", help="Run even if today's envelope already ran (a second envelope today; never bypasses the budget-off guard)"),
                    yes: bool = typer.Option(False, "--yes", "-y", help="Skip the confirmation prompt")) -> None:
    """Run tonight's envelope now, in the foreground, and print the record. This ENQUEUES REAL PAID WORK up to the
    budget (the worker then executes it) -- so it always states the authorized amount and asks first, unless --yes.
    Preflight (full integrity_check + verified backup, L-10) runs first and refuses on a dirty database."""
    from . import nightly
    from .config import override as _override
    _init()
    invocation_overrides = {}
    if budget is not None:
        invocation_overrides["t4_nightly_budget"] = float(budget)
    if t5_budget is not None:
        invocation_overrides["t5_nightly_budget"] = float(t5_budget)
    if research_refresh_budget is not None:
        invocation_overrides["research_refresh_nightly_budget"] = float(research_refresh_budget)
    # CR8b hardening (2026-09-16): these three used to assign straight onto the shared `settings` singleton with
    # no restore, so a later invocation in the same process (another CLI call, or a test driving this command
    # through CliRunner) silently inherited whatever budget a previous call happened to set -- that's exactly
    # what let CR6's nightly block fire unexpectedly during CR8b's own test suite. `config.override` scopes these
    # three flags to THIS invocation only, restoring the prior values on any exit path, including the early
    # `typer.Exit`s below.
    with _override(**invocation_overrides):
        if settings.t4_nightly_budget <= 0:
            typer.echo("nightly envelope is OFF (budget 0). Pass --budget N or set NEUROSEARCH_T4_NIGHTLY_BUDGET_USD.", err=True)
            raise typer.Exit(code=1)
        if not force and nightly.last_run() is not None:
            typer.echo(f"today's envelope already ran ({nightly._today_key()}); pass --force to run a second one")
            raise typer.Exit(code=0)
        projects = [p for p in db.list_projects() if p.get("n_sources")]
        typer.echo(f"authorizing up to ${settings.t4_nightly_budget:.2f} TOTAL across {len(projects)} active project(s) "
                   f"(shared cap, walked down project by project -- not ${settings.t4_nightly_budget:.2f} each)")
        if settings.t5_nightly_budget > 0:
            typer.echo(f"plus up to ${settings.t5_nightly_budget:.2f} for T5 adjudication of open disagreements (separate cap; each verdict "
                       "lands as a suggested finding, nothing is decided for you)")
        else:
            typer.echo("T5 adjudication: off (pass --t5-budget N to enable)")
        if settings.research_refresh_nightly_budget > 0:
            typer.echo(f"plus up to ${settings.research_refresh_nightly_budget:.2f} for CR6 research refreshes (separate cap; each one only "
                       "STARTS a refresh through the normal ingest path -- nothing is decided for you)")
        else:
            typer.echo("CR6 research refresh: off (pass --research-refresh-budget N to enable)")
        if not yes and not typer.confirm("Run the nightly envelope now?"):
            raise typer.Exit(code=0)
        r = nightly.run(force=force)
        typer.echo(json.dumps(r, indent=2, default=str))
        if not r.get("ran"):
            raise typer.Exit(code=1)


@nightly_app.command("report")
def nightly_report_cmd(date: Optional[str] = typer.Option(None, "--date", help="YYYY-MM-DD of the envelope to report on (default: today)"),
                       as_json: bool = typer.Option(False, "--json", help="Print the underlying data instead of the readable report")) -> None:
    """The Morning Report (L-41) for one night's envelope, readable in under a minute. $0, reads only.
    Honest by construction: never claims 'these are the N things you need to review' (rulings section 7)."""
    from . import nightly, report
    _init()
    envelope_id = f"nightly-{date or nightly._today_key()}"
    rep = report.for_envelope(envelope_id)
    if as_json:
        typer.echo(json.dumps(rep, indent=2, default=str))
        return
    typer.echo(report.render_text(rep), nl=False)
    if not rep.get("found"):
        raise typer.Exit(code=1)


@project_app.command("collection-policy")
def project_collection_policy(project: str, collection: str,
                              role: Optional[str] = typer.Option(None, "--role", help="primary | secondary | unspecified"),
                              monitor: Optional[str] = typer.Option(None, "--monitor", help="auto | on | off"),
                              as_json: bool = typer.Option(False, "--json", help="Emit stable machine-readable JSON")) -> None:
    """CR8 (2026-09-16 product decision): set or show whether THIS project treats a reservoir it's attached to
    as primary (worth watching by default) vs secondary (not, unless explicitly turned on). Pure bookkeeping on
    the project<->collection relationship -- never ingests, never triggers a rescan itself. With neither --role
    nor --monitor, just shows the current stored + effective state."""
    from . import reservoir

    _init()
    pid = _project_id(project)
    assert pid
    if role is None and monitor is None:
        policy = db.get_collection_policy(pid, collection)
    else:
        try:
            policy = db.set_collection_policy(pid, collection, source_role=role, monitor_policy=monitor)
        except ValueError as e:
            typer.echo(str(e)); raise typer.Exit(1)
    if not policy:
        typer.echo("this project is not attached to that collection"); raise typer.Exit(1)
    active = reservoir.effective_monitor_active(policy["source_role"], policy["monitor_policy"])
    if as_json:
        typer.echo(json.dumps({**policy, "effective_monitor_active": active}, indent=1))
        return
    col = db.get_collection(collection)
    title = (col or {}).get("title") or collection
    typer.echo(f"{title}: source_role={policy['source_role']} monitor_policy={policy['monitor_policy']} "
              f"-> {'monitored' if active else 'not monitored'}")


@project_app.command("review-queue")
def project_review_queue(project: str, limit: int = typer.Option(25, "--limit", help="Cap for plan-impact / evidence-weak items; disagreement is never capped"),
                         as_json: bool = typer.Option(False, "--json", help="Print the full data instead of the readable list")) -> None:
    """L-51 (P4 Review at Scale): the exception queue -- the few proposed Claims that actually need you, each
    saying why. $0, reads only, approves nothing."""
    from . import review_queue
    _init()
    pid = _project_id(project)
    if pid is None:
        typer.echo(f"no project matches {project!r}", err=True)
        raise typer.Exit(code=1)
    q = review_queue.build(pid, limit=limit)
    if as_json:
        typer.echo(json.dumps(q, indent=2, default=str))
        return
    c = q["counts"]
    typer.echo(f"{c['shown']} to review out of {c['proposed_total']} proposed "
               f"(disagreement {c['by_reason']['disagreement']}, plan impact {c['by_reason']['plan_impact']}, "
               f"weak evidence {c['by_reason']['evidence_weak']}; hidden by the cap: {c['hidden_total']}, of which "
               f"weak evidence {c['not_shown']['evidence_weak']}, plan impact {c['not_shown']['plan_impact']})")
    for x in q["queue"]:
        m = x["members"]
        typer.echo(f"- [{', '.join(x['reasons'])}] {x['text'][:140]}")
        typer.echo(f"    {x['strength']} · {x['independent_sources']} source(s) · {len(m['note_ids'])} finding(s) folded in"
                   + (f" · {len(m['merged_claim_ids'])} merged" if m["merged_claim_ids"] else "")
                   + (f" · tension: {x['tensions'][0]['kind']} ({x['tensions'][0].get('impact')})" if x["tensions"] else ""))
    if not q["queue"]:
        typer.echo("nothing needs your judgment right now")


@project_app.command("needs")
def project_needs(project: str, limit: int = typer.Option(25, "--limit"),
                  as_json: bool = typer.Option(False, "--json", help="Print the full data instead of the readable list")) -> None:
    """CR1 (P8 Continuous Research): what could use fresh or better evidence right now, in priority order. $0,
    reads only, no provider call."""
    from . import research_needs
    _init()
    pid = _project_id(project)
    if pid is None:
        typer.echo(f"no project matches {project!r}", err=True)
        raise typer.Exit(code=1)
    needs = research_needs.for_project(pid, limit=limit)
    if as_json:
        typer.echo(json.dumps(needs, indent=2, default=str))
        return
    if not needs:
        typer.echo("nothing currently needs fresh evidence")
        return
    for n in needs:
        typer.echo(f"- [{n['kind']}] {(n.get('text') or '')[:140]}")
        typer.echo(f"    {n['reason']}")
        for r in n.get("where_to_look") or []:
            typer.echo(f"    -> {r['creator']}: {r['untapped']} untapped ({'; '.join(r['why'][:2])})")


@project_app.command("plan-impact")
def project_plan_impact(project: str, claim: Optional[str] = typer.Option(None, "--claim"),
                        tension: Optional[str] = typer.Option(None, "--tension"),
                        explain: bool = typer.Option(False, "--explain", help="LP2: add a templated why-sentence per item; still no model call"),
                        as_json: bool = typer.Option(False, "--json", help="Print the full data instead of the readable list")) -> None:
    """LP1 (P10 Living Master Plan): which plan items a Claim (or the tension on it) touches. $0, reads only.
    --explain adds LP2's plain-language why over the same result."""
    from . import plan_impact
    _init()
    pid = _project_id(project)
    if pid is None:
        typer.echo(f"no project matches {project!r}", err=True)
        raise typer.Exit(code=1)
    if not claim and not tension:
        typer.echo("pass --claim or --tension", err=True)
        raise typer.Exit(code=1)
    if explain:
        from . import plan_narrative
        r = plan_narrative.explain(pid, claim_id=claim, tension_id=tension)
    else:
        r = plan_impact.affected_items(pid, claim_id=claim, tension_id=tension)
    if as_json:
        typer.echo(json.dumps(r, indent=2, default=str))
        return
    if not r["known"]:
        typer.echo(f"unknown: {r.get('reason')}")
        return
    if not r["items"]:
        typer.echo("this claim touches nothing in the current plan")
        return
    for it in r["items"]:
        if "why" in it:
            typer.echo(f"- {it['path']} ({it['strength']}): {it['why']}")
        else:
            typer.echo(f"- {it['path']} ({it['strength']}): {it.get('label') or ''}")


@project_app.command("due")
def project_due(project: str, as_json: bool = typer.Option(False, "--json", help="Print the full data instead of the readable list")) -> None:
    """CR2: which of CR1's research needs are worth checking tonight, in ranked categories (critical /
    worth_checking / low), each with an estimated -- never spent -- cost and its basis. $0, reads only; records a
    check-cooldown so a need already surfaced recently is not repeated while budget remains."""
    from . import research_needs
    _init()
    pid = _project_id(project)
    if pid is None:
        typer.echo(f"no project matches {project!r}", err=True)
        raise typer.Exit(code=1)
    due = research_needs.due_tonight(pid)
    if as_json:
        typer.echo(json.dumps(due, indent=2, default=str))
        return
    if not due:
        typer.echo("nothing due right now (or everything was already surfaced recently)")
        return
    for n in due:
        typer.echo(f"- [{n['due_category']}] [{n['kind']}] {(n.get('text') or '')[:120]}")
        typer.echo(f"    ~${n['estimated_cost_usd']:.4f} ({n['cost_basis']})")


@project_app.command("propose-updates")
def project_propose_updates(project: str, claim: Optional[str] = typer.Option(None, "--claim"),
                            tension: Optional[str] = typer.Option(None, "--tension"),
                            as_json: bool = typer.Option(False, "--json", help="Print the full data instead of the readable list")) -> None:
    """LP3: writes pending plan_updates rows from LP2's deterministic why-text (origin='lp3', never collides with
    the existing suggest_updates() queue). $0, no model call. This WRITES (pending rows) -- promoting one still
    goes through the existing `POST /api/plan-updates/{id}` accept route; nothing here auto-accepts anything."""
    from . import plan_narrative
    _init()
    pid = _project_id(project)
    if pid is None:
        typer.echo(f"no project matches {project!r}", err=True)
        raise typer.Exit(code=1)
    if not claim and not tension:
        typer.echo("pass --claim or --tension", err=True)
        raise typer.Exit(code=1)
    updates = plan_narrative.propose_updates(pid, claim_id=claim, tension_id=tension)
    if as_json:
        typer.echo(json.dumps(updates, indent=2, default=str))
        return
    if not updates:
        typer.echo("nothing to propose (no plan, or LP1/LP2 could not resolve this citation)")
        return
    typer.echo(f"wrote {len(updates)} pending plan update(s) (origin=lp3) -- accept or reject via the existing plan-updates route:")
    for u in updates:
        typer.echo(f"- {u['section']}: {u['proposed']}")


@project_app.command("refresh-need")
def project_refresh_need(project: str, claim: Optional[str] = typer.Option(None, "--claim", help="Refresh this claim's need directly, skipping the due-tonight pick"),
                         cap: float = typer.Option(1.0, "--cap", help="Won't start a need estimated above this many dollars")) -> None:
    """CR5: starts one Claim's refresh through the EXISTING ingest path (knowledge.pursue + capture_best) --
    never a second pipeline. Returns immediately; ingest/findings/claim reassessment run on the normal job queue.
    Use `refresh-check --claim` afterward to see what changed, once those jobs have run."""
    from . import research_needs, research_refresh
    _init()
    pid = _project_id(project)
    if pid is None:
        typer.echo(f"no project matches {project!r}", err=True)
        raise typer.Exit(code=1)
    need = None
    if claim:
        need = next((n for n in research_needs.for_project(pid, limit=200) if n.get("claim_id") == claim), None)
        if need is None:
            typer.echo(f"no open research need for claim {claim!r}", err=True)
            raise typer.Exit(code=1)
    r = research_refresh.request_refresh(pid, need=need, cap_usd=cap)
    if not r.get("started") and "reason" in r and "claim_id" not in r:
        typer.echo(r["reason"])
        raise typer.Exit(code=1)
    typer.echo(f"refresh requested for claim {r['claim_id']} (target {r['target_id']}, ~${r.get('estimated_cost_usd') or 0:.4f} estimated); "
              f"{len(r.get('capture') or [])} item(s) started -- check back with `refresh-check --claim {r['claim_id']}`")


@project_app.command("refresh-check")
def project_refresh_check(project: str, claim: str = typer.Option(..., "--claim"), as_json: bool = typer.Option(False, "--json")) -> None:
    """CR5: what actually changed since a `refresh-need` request -- read any time after, never blocking on the
    job queue. "Unchanged" is a normal outcome here, not a failure."""
    from . import research_refresh
    _init()
    pid = _project_id(project)
    if pid is None:
        typer.echo(f"no project matches {project!r}", err=True)
        raise typer.Exit(code=1)
    r = research_refresh.check(pid, claim)
    if as_json:
        typer.echo(json.dumps(r, indent=2, default=str))
        return
    if not r["known"]:
        typer.echo(r["reason"])
        return
    if r["changed"]:
        typer.echo(f"changed: {r['before']} -> {r['after']}")
    else:
        typer.echo(f"unchanged: {r['after']}")


@project_app.command("acquire-evaluate")
def project_acquire_evaluate(project: str, target: Optional[str] = typer.Option(None, "--target", help="Evaluate this Evidence Target directly, skipping the due-tonight pick"),
                             as_json: bool = typer.Option(False, "--json", help="Print the full data instead of the readable line")) -> None:
    """CR8b: starts one open Evidence Target's selective acquisition through the SAME shared mechanism CR5 uses
    (knowledge.pursue + capture_best) -- for the case CR5 itself declines, an open target with no Claim yet.
    Returns immediately; ingest/findings run on the normal job queue like any other acquisition. No paid spend
    happens here beyond what capture_best()'s existing budget machinery already authorizes."""
    from . import research_refresh
    _init()
    pid = _project_id(project)
    if pid is None:
        typer.echo(f"no project matches {project!r}", err=True)
        raise typer.Exit(code=1)
    need = None
    if target:
        need = {"kind": "open_target", "target_id": target}
    r = research_refresh.request_acquisition(pid, need=need)
    if as_json:
        typer.echo(json.dumps(r, indent=2, default=str))
        return
    if not r.get("started"):
        typer.echo(r.get("reason") or "nothing started")
        raise typer.Exit(code=1)
    typer.echo(f"acquisition started for target {r['target_id']}: {len(r.get('capture') or [])} item(s) started, "
              f"{len(r.get('skipped') or [])} skipped -- check `project rescan`/sources once the job queue runs")


@project_app.command("plan-state")
def project_plan_state(project: str, as_json: bool = typer.Option(False, "--json")) -> None:
    """LP4: each plan item's evidence-confidence state (known/assumed/chosen/uncertain/blocked/monitored),
    derived on read from LP1 + Claim strength/freshness + the plan's own dependencies/basis fields. $0, reads
    only, persists nothing -- a different axis from an item's own execution status."""
    from . import plan_state
    _init()
    pid = _project_id(project)
    if pid is None:
        typer.echo(f"no project matches {project!r}", err=True)
        raise typer.Exit(code=1)
    states = plan_state.derive(pid)
    if as_json:
        typer.echo(json.dumps(states, indent=2, default=str))
        return
    if not states:
        typer.echo("no plan yet, or nothing resolvable")
        return
    for key, s in states.items():
        typer.echo(f"- {key}: {s['state']} ({s['why']})")


@project_app.command("discover")
def project_discover(project: str, n: int = typer.Option(5, "--n", help="How many not-yet-resolved candidates to show"),
                     rank_by: str = typer.Option("fit", "--rank-by"), as_json: bool = typer.Option(False, "--json")) -> None:
    """AD1: up to N best not-yet-resolved Candidate Index items, best first. Resolve each with `discover-decide
    <candidate_id> capture|reject`, then run this again -- there is no separate queue or session; a resolved item
    drops out on its own (the same pool `project pool` uses), and an unresolved one is correctly shown again."""
    from . import candidates
    _init()
    pid = _project_id(project)
    if pid is None:
        typer.echo(f"no project matches {project!r}", err=True)
        raise typer.Exit(code=1)
    r = candidates.next_batch(pid, n=n, rank_by=rank_by)
    if as_json:
        typer.echo(json.dumps(r, indent=2, default=str))
        return
    if not r["items"]:
        typer.echo("nothing left to discover" + (f" ({r['remaining']} more beyond this batch)" if r["remaining"] else ""))
        return
    for i in r["items"]:
        typer.echo(f"[{i['id']}] {i['title']} -- {i.get('creator') or 'unknown creator'} (potential {i['potential']}/100)")
        if i.get("why"):
            typer.echo(f"    {'; '.join(i['why'])}")
    typer.echo(f"\n{r['remaining']} more beyond this batch. Resolve with `discover-decide <id> capture|reject`, "
              f"then `discover` again for the next best unresolved ones.")


@project_app.command("discover-decide")
def project_discover_decide(project: str, candidate_id: str, decision: str,
                            reason: Optional[str] = typer.Option(None, "--reason")) -> None:
    """AD1: resolve one candidate from `discover` -- CAPTURE (through the normal ingest lifecycle) or REJECT
    ("not for this project"). No third "keep for later" state: undecided already means "shown again next time"."""
    from . import candidates
    _init()
    pid = _project_id(project)
    if pid is None:
        typer.echo(f"no project matches {project!r}", err=True)
        raise typer.Exit(code=1)
    if decision not in ("capture", "reject"):
        typer.echo("decision must be 'capture' or 'reject'", err=True)
        raise typer.Exit(code=1)
    if decision == "reject":
        candidates.dismiss(pid, candidate_id, reason)
        typer.echo(f"rejected {candidate_id}")
        return
    try:
        r = candidates.capture(candidate_id, pid, reason=reason)
    except LookupError:
        typer.echo(f"no candidate {candidate_id!r}", err=True)
        raise typer.Exit(code=1)
    if r.get("job_id") is None:
        typer.echo(f"captured {candidate_id} -- already owned, attached from the library")
    else:
        typer.echo(f"captured {candidate_id} -- ingest queued (job {r['job_id']})")


@project_app.command("discover-report")
def project_discover_report(project: str, window: str = typer.Option("all", "--window"),
                            as_json: bool = typer.Option(False, "--json")) -> None:
    """AD4A: how Adaptive Discovery has actually performed on this project so far -- capture rate, downstream
    finding/Claim/target yield, review burden, and an honest evidence-sufficiency read. Never a static-vs-adaptive
    comparison (nothing durable records what a batch showed or omitted); see docs/AD4-DECISION-2026-09-15 for why."""
    from . import discovery_measure
    _init()
    pid = _project_id(project)
    if pid is None:
        typer.echo(f"no project matches {project!r}", err=True)
        raise typer.Exit(code=1)
    r = discovery_measure.report(pid, window=window)
    if as_json:
        typer.echo(json.dumps(r, indent=2, default=str))
        return
    u, rv, rb, suf = r["usage"], r["research_value"], r["review_burden"], r["evidence_sufficiency"]
    typer.echo(f"Evidence: {suf['category']} ({suf['decided_total']} genuine decisions) -- {suf['note']}")
    typer.echo(f"Capture rate: {u['capture_rate']} ({u['candidate_decisions']})")
    typer.echo(f"Operational skips (not preference signals): {u['operational_skips']}")
    typer.echo(f"Acquired sources: {rv['acquired_sources']}")
    typer.echo(f"Findings: {rv['findings']['by_status']}  Claims: {rv['claims']['by_status']}")
    typer.echo(f"Evidence targets: {rv['evidence_targets']}")
    typer.echo(f"Novel creators in window: {r['breadth']['novel_creators_in_window']}")
    typer.echo(f"Review burden: {rb}")
    typer.echo(f"\nVerdict: {r['verdict']}")
