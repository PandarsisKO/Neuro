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
    db.init_db()


@app.command()
def serve(host: str = "0.0.0.0", port: int = 8000, reload: bool = False) -> None:
    """Run the web app + API + MCP endpoint (background workers included)."""
    import uvicorn

    uvicorn.run("neurosearch.api:app", host=host, port=port, reload=reload)


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
        j = jobs.enqueue("ingest_url", {"url": u, "tags": tag, "project_id": pid, "force": force})
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
def status() -> None:
    """Knowledge base stats and recent jobs."""
    _init()
    typer.echo(json.dumps(db.source_stats(), indent=1))
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
