"""S101 — share a whole chat AS IS, with sources, for another AI (Kyle, 2026-09-25).

"I want to be able to share an entire chat, copy pasted AS IS with sources so I can feed to other LLMs for
collaboration. do not remove the other versions of the share chat feature."

The existing Share ▾ retellings (0.60.0) are a MODEL call that rewrites the chat as one piece. This is the opposite:
$0, no model, no retrieval, no rewording — every turn verbatim, oldest first, each answer's own numbered source list
directly under it (so a [n] marker resolves where it is read), the app's ⚠ caveats kept, and a de-duplicated index
of every source at the end. (Sorts after test_s100 — there is none — and after test_core.)
"""
from __future__ import annotations

import os
from pathlib import Path

os.environ["NEUROSEARCH_APP_TOKEN"] = "t0k"
os.environ["NEUROSEARCH_FAKE_AI"] = "1"

import pytest  # noqa: E402

from neurosearch import db, export  # noqa: E402
from neurosearch.config import settings  # noqa: E402

WEB = Path(__file__).resolve().parents[1] / "neurosearch" / "web"
JS = (WEB / "js" / "chats.js").read_text()
HTML = (WEB / "index.html").read_text()
H = {"Authorization": "Bearer t0k"}

CITES = [{"n": 1, "source_id": "s1", "title": "SBA 7(a) explained", "timestamp": "12:34", "link": "https://youtu.be/x?t=754"},
         {"n": 2, "source_id": "s2", "title": "Seller notes", "timestamp": "3:10", "link": "https://youtu.be/y?t=190"}]


@pytest.fixture(autouse=True)
def _fresh(tmp_path, monkeypatch):
    data = tmp_path / "data"; data.mkdir()
    monkeypatch.setattr(settings, "data_dir", data)
    monkeypatch.setattr(settings, "fake_ai", True)
    db._local.conn = None
    db.init_db()
    yield
    db._local.conn = None


def _chat():
    p = db.create_project("as-is", brief="buying a business")
    c = db.create_conversation(p["id"], "SBA questions")
    db.save_message(c["id"], "user", "How much do I have to put in?")
    db.save_message(c["id"], "assistant", "Ten percent equity, and a seller note can cover half of it [1][2].", CITES)
    db.save_message(c["id"], "user", "And the seller note?")
    db.save_message(c["id"], "assistant", "A seller note counts only on full standby [2].", CITES[1:2],
                    meta={"warning": "evidence for [2] is from a single source"})
    return p, c["id"]


def _calls() -> int:
    return db.connect().execute("SELECT COUNT(*) FROM invocations").fetchone()[0]


def test_every_turn_is_kept_verbatim_with_its_own_sources_and_costs_nothing():
    p, cid = _chat()
    md = export.conversation_markdown(cid)
    assert md.startswith("# SBA questions")
    assert "project: as-is" in md and "4 messages" in md
    assert md.count("### You") == 2 and md.count("### Neuro") == 2
    assert "Ten percent equity, and a seller note can cover half of it [1][2]." in md, "the text is not reworded"
    assert "A seller note counts only on full standby [2]." in md
    # each answer's list sits under that answer, numbered with the markers the text uses
    first = md.split("### Neuro")[1].split("### You")[0]
    assert "1. SBA 7(a) explained @ 12:34 — https://youtu.be/x?t=754" in first and "2. Seller notes @ 3:10 — https://youtu.be/y?t=190" in first
    second = md.split("### Neuro")[2]
    assert "2. Seller notes @ 3:10" in second and "SBA 7(a)" not in second.split("## All sources")[0]
    assert "⚠ evidence for [2] is from a single source" in second, "the app's own caveat travels with the answer"
    assert md.index("### You") < md.index("### Neuro"), "oldest first — the order it happened in"
    # the index de-duplicates: two answers cite Seller notes, it appears once
    idx = md.split("## All sources cited")[1]
    assert idx.count("Seller notes") == 1 and idx.count("SBA 7(a)") == 1
    assert _calls() == 0, "$0: no model call, ever"


def test_the_reader_is_told_how_to_read_the_markers():
    _, cid = _chat()
    md = export.conversation_markdown(cid)
    assert "a marker like [3] points at entry 3 of the Sources list directly under that answer" in md


def test_without_sources_the_text_and_markers_stay_but_the_lists_go():
    _, cid = _chat()
    md = export.conversation_markdown(cid, sources=False)
    assert "[1][2]" in md and "Sources" not in md and "youtu.be" not in md and "## All sources" not in md


def test_citation_shapes_that_are_not_video_moments_do_not_crash_it():
    p = db.create_project("shapes", brief="x")
    c = db.create_conversation(p["id"], "shapes")
    db.save_message(c["id"], "assistant", "Web says so [1]; the old one [2].",
                    [{"n": 1, "title": "A web page", "url": "https://example.com/a"},
                     {"n": 2, "title": "Gone", "timestamp": "1:00", "link": "https://youtu.be/z", "removed": True}])
    md = export.conversation_markdown(c["id"])
    assert "1. A web page — https://example.com/a" in md
    assert "2. [source removed] Gone @ 1:00 — https://youtu.be/z" in md


def test_turns_held_in_an_outside_ai_are_labelled():
    p = db.create_project("ext", brief="x")
    c = db.create_conversation(p["id"], "ext")
    db.save_message(c["id"], "user", "hi from chatgpt", meta={"kind": "external_transcript", "client": "ChatGPT"})
    md = export.conversation_markdown(c["id"])
    assert "### You (in ChatGPT)" in md


def test_the_endpoint_serves_markdown_inline_or_as_a_download(client):
    _, cid = _chat()
    r = client.get(f"/api/conversations/{cid}/transcript.md", headers=H)
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/markdown")
    assert "content-disposition" not in {k.lower() for k in r.headers}
    assert "### Neuro" in r.text and "1. SBA 7(a) explained" in r.text
    r2 = client.get(f"/api/conversations/{cid}/transcript.md", params={"sources": "false"}, headers=H)
    assert "youtu.be" not in r2.text
    r3 = client.get(f"/api/conversations/{cid}/transcript.md", params={"download": "true"}, headers=H)
    assert r3.headers["content-disposition"].startswith("attachment; filename=chat-")
    assert client.get("/api/conversations/nope/transcript.md", headers=H).status_code == 404


# ------------------------------------------------------------------ the menu

def test_the_verbatim_options_lead_the_menu_and_the_retellings_survive():
    menu = JS.split("globalThis.shareChatMenu =")[1].split("globalThis.shareChat =")[0]
    assert "'asis|sources', '⧉ Whole chat, as is + sources'" in menu
    assert "'asis|bare', '⧉ Whole chat, as is — no source lists'" in menu
    assert "'asis|download', '⬇ Download whole chat (.md)'" in menu
    for kept in ("'long|plain'", "'medium|plain'", "'long|cited'"):
        assert kept in menu, "the retellings are not removed"
    assert menu.index("'asis|sources'") < menu.index("'long|plain'")


def test_the_verbatim_path_never_touches_the_model_endpoint():
    fn = JS.split("globalThis.shareChatAsIs =")[1].split("globalThis.copyMsg =")[0]
    assert "/transcript.md?sources=" in fn and "/share" not in fn.replace("/transcript.md", "")
    assert "await uiFetch(url)" in fn, "first-party fetch, version-guarded like every other request"
    assert "toClipboard(text)" in fn and "&download=true" in fn
    assert "if (length === 'asis') return shareChatAsIs(mode);" in JS


def test_the_button_says_what_it_now_does():
    assert 'Copy the whole chat exactly as it happened' in HTML and 'onclick="shareChatMenu(this)"' in HTML
