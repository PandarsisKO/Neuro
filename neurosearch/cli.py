"""Command line interface.  `neurosearch --help`"""
from __future__ import annotations

import json
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
                                         help="Extract here, store on this server URL (when the cloud can't reach YouTube)"),
    token: Optional[str] = typer.Option(None, envvar="NEUROSEARCH_REMOTE_TOKEN", help="App token for --remote"),
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
             migration_compare: bool = typer.Option(False, "--migration-compare", help="E2.3: every remaining task (chat+repair, export, planner.update; planner.analysis/build with a 5-adaptive arm) 4.6 vs Sonnet 5 on identical frozen inputs, one verdict per task; changes nothing"),
             baseline_model: str = typer.Option(None, "--baseline-model", help="Baseline model for --ranking-compare (default claude-sonnet-4-6)"),
             candidate_model: str = typer.Option(None, "--candidate-model", help="Candidate model for --ranking-compare (default claude-sonnet-5)")) -> None:
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
    if live and not settings.anthropic_api_key:
        raise typer.BadParameter("--live needs ANTHROPIC_API_KEY (and OPENAI_API_KEY for embeddings)")
    db.init_db()
    if migration_compare:
        from . import migration
        cmp = migration.run_migration_compare(live=live, progress=lambda m: typer.echo("  · " + m))
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
                   f"{'  batch-ok' if c.batch_allowed else ''}{'  fallback-ok' if c.fallback_allowed else ''}  schema={c.schema}")


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
    db.add_project_sources(pid, full)
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


if __name__ == "__main__":
    app()
