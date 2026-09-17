"""S69 — a UI edit is a browser refresh, never a server restart (P0.5, docs/SPEED-AUDIT-2026-09-17.md).

server.log, 2026-09-17: `WatchFiles detected changes in 'neurosearch/web/index.html'. Reloading...` at 13:59 and
14:22 — one per UI fix Codex landed — each followed by `worker drain exceeded shutdown timeout`, `re-queued 4
interrupted jobs` (local model calls of 40–150 s thrown away and re-run), and a cold `/api/sources` pass on every
open tab because every in-process cache had been wiped. Nothing about serving the UI needed the restart: the
page, the stylesheet and `/js/*` are read from disk per request. This gate pins both halves: the reload watch is
Python-only, and a changed `index.html` is served on the next request by the SAME process.
"""
from __future__ import annotations

import pathlib
import re

from neurosearch import api

ROOT = pathlib.Path(__file__).resolve().parent.parent


def test_the_dev_reload_watch_is_python_only():
    src = (ROOT / "neurosearch" / "cli.py").read_text()
    m = re.search(r"reload_includes=\[([^\]]*)\]", src)
    assert m, "serve(--reload) must declare reload_includes explicitly"
    patterns = re.findall(r"\"([^\"]+)\"", m.group(1))
    assert patterns == ["*.py"], f"only Python may restart the process, got {patterns}"


def test_an_edited_index_html_is_served_by_the_running_process(client, monkeypatch, tmp_path):
    web = tmp_path / "web"; (web / "js").mkdir(parents=True)
    (web / "index.html").write_text("<!doctype html><title>one</title>")
    (web / "login.html").write_text("<!doctype html><title>login</title>")
    (web / "styles.css").write_text("body{}")
    monkeypatch.setattr(api, "WEB_DIR", web)
    from neurosearch.config import settings
    h = {"Authorization": f"Bearer {settings.app_token}"} if settings.app_token else {}
    assert "one" in client.get("/", headers=h).text
    (web / "index.html").write_text("<!doctype html><title>two</title>")       # the UI edit
    r = client.get("/", headers=h)
    assert "two" in r.text, "index.html must be read from disk on every request, so a refresh is enough"
    assert r.headers.get("cache-control", "").startswith("no-store")
