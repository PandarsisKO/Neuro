"""S103 — the ★ Priority button answers the click (Kyle, 2026-09-30: "Neuro seems to not do anything").

Measured live: the PUT succeeded in 0.4 s, but the star only changed after the whole 2,000-row source list was
refetched (10–15 s; longer under load; coalesced behind any poll already running) and there was no toast. The
flag now flips on screen immediately from the list the page already holds, the server is told, and only a
failed write rolls it back. The endpoint itself is unchanged and is pinned here so the two stay in step."""
from __future__ import annotations

import os
import pathlib
import tempfile

os.environ.setdefault("NEUROSEARCH_DATA_DIR", tempfile.mkdtemp(prefix="ns_s103_"))
os.environ["NEUROSEARCH_APP_TOKEN"] = "t0k"
os.environ["NEUROSEARCH_FAKE_AI"] = "1"

import pytest  # noqa: E402

from neurosearch import db  # noqa: E402
from neurosearch.config import settings  # noqa: E402

JS = (pathlib.Path(__file__).resolve().parents[1] / "neurosearch" / "web" / "js" / "sources.js").read_text()


@pytest.fixture(autouse=True)
def _fresh(tmp_path, monkeypatch):
    data = tmp_path / "data"; data.mkdir(); (data / "media").mkdir()
    monkeypatch.setattr(settings, "data_dir", data)
    db._local.conn = None
    db.init_db()
    yield
    db._local.conn = None


def test_set_priority_is_written_and_readable_for_a_collection_reached_source():
    p = db.create_project("Acq", "buying a business")
    src = db.upsert_source(platform="youtube", external_id="prio0001", url="https://www.youtube.com/watch?v=prio0001",
                           status="ready", title="A CIM walkthrough")
    assert db.set_source_priority(p["id"], [src["id"]], True) == 1
    assert src["id"] in db.priority_source_ids(p["id"])
    assert db.set_source_priority(p["id"], [src["id"]], False) == 1
    assert src["id"] not in db.priority_source_ids(p["id"])


def test_the_button_flips_on_screen_before_the_server_answers():
    body = JS.split("globalThis.setPriority = async function setPriority", 1)[1].split("\n}\n", 1)[0]
    assert "row.priority = flag; renderSourcesView();" in body, "optimistic flip from the list already on screen"
    assert body.index("renderSourcesView()") < body.index("await put("), "the flip happens before the network call"
    assert "row.priority = before; renderSourcesView();" in body, "a failed write rolls the star back"
    assert "toast(" in body, "the click is acknowledged"
    assert "loadSources()" not in body, "no 2,000-row refetch just to move one star"
