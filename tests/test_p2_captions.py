"""Caption recovery for music-only short-form video (Kyle, live 2026-09-09).

"we seem to have an issue with youtube shorts, instagram reels that only have music - there is value in the text
in the video but we are not parsing them." Measured on his library first: 20 ready sources hold under 400 chars of
transcript and 15 produced no findings at all. Some of those already carry their substance in a caption the app
stored and never read, so the cheap half of the fix is to read it — but ONLY when the spoken track is effectively
empty, because feeding every video's marketing blurb into its findings would be a quality regression dressed up as
a feature. That guard is what most of this module tests. (Sorts after test_p1.)"""
from __future__ import annotations

import os
import tempfile

os.environ.setdefault("NEUROSEARCH_DATA_DIR", tempfile.mkdtemp(prefix="ns_cap_"))
os.environ["NEUROSEARCH_APP_TOKEN"] = "t0k"
os.environ["NEUROSEARCH_FAKE_AI"] = "1"

import pytest  # noqa: E402

from neurosearch import api, db, ingest  # noqa: E402
from neurosearch.config import settings  # noqa: E402

CAPTION = ("1) Go to smbmarket.com and find businesses that cash flow $100k a year.\n\n"
           "2) Make a list of 10-20 businesses that fit your criteria and contact every owner directly.\n\n"
           "3) Ask for seller financing on 80% of the purchase price before you approach any bank.")


@pytest.fixture(autouse=True)
def _fresh(tmp_path, monkeypatch):
    data = tmp_path / "data"; data.mkdir(); (data / "media").mkdir()
    monkeypatch.setattr(settings, "data_dir", data)
    monkeypatch.setattr(settings, "fake_ai", True)
    db._local.conn = None
    db.init_db()
    yield
    db._local.conn = None


def _short(ext: str, spoken: str, desc: str, project_id: str | None = None) -> dict:
    s = db.upsert_source(platform="youtube", external_id=ext, url=f"https://www.youtube.com/shorts/{ext}",
                         title="How We Legally Cheat Taxes", description=desc, duration=30,
                         transcript_kind="transcribed", status="ready")
    if spoken:
        db.replace_transcript(s["id"], [{"start": 0.0, "end": 5.0, "text": spoken}], [])
    if project_id:
        db.add_project_sources(project_id, [s["id"]])
    return db.get_source(s["id"])


def test_a_silent_short_gets_its_caption_read():
    s = _short("silent-1", "🔥🔥", CAPTION)
    out = ingest.recover_caption_text(s["id"])
    assert out["recovered"] and out["caption_chars"] == len(CAPTION)

    text = " ".join(x["text"] for x in db.get_segments(s["id"]))
    assert "smbmarket.com" in text and "seller financing" in text          # the substance is now searchable
    assert ingest.CAPTION_MARKER in text                                   # and says where it came from
    assert db.get_source(s["id"])["transcript_kind"] == "transcribed+caption"
    assert db.get_chunks(s["id"])                                          # chunks rebuilt, so retrieval can see it


def test_a_video_that_actually_spoke_is_never_touched():
    """The guard that matters: a normal video's findings must not be diluted by its marketing copy."""
    spoken = "So the first thing you do when buying a business is understand the seller's real motivation. " * 6
    assert len(spoken) >= ingest.SILENT_TRANSCRIPT_CHARS
    s = _short("talks-1", spoken, CAPTION)
    out = ingest.recover_caption_text(s["id"])
    assert out["recovered"] is False and "spoken transcript" in out["reason"]
    text = " ".join(x["text"] for x in db.get_segments(s["id"]))
    assert "smbmarket.com" not in text and ingest.CAPTION_MARKER not in text


def test_a_silent_short_with_only_a_boilerplate_caption_is_left_alone():
    """Hashtag piles and one-line plugs are not content; recovering them would be noise, not evidence."""
    s = _short("silent-2", "", "#business #money 🔥 link in bio")
    out = ingest.recover_caption_text(s["id"])
    assert out["recovered"] is False and "caption text" in out["reason"]


def test_recovery_is_idempotent():
    """It runs on every ingest and can be pressed repeatedly from the UI, so a second pass must add nothing."""
    s = _short("silent-3", "", CAPTION)
    assert ingest.recover_caption_text(s["id"])["recovered"]
    n = len(db.get_segments(s["id"]))
    again = ingest.recover_caption_text(s["id"])
    assert again["recovered"] is False and again["reason"] == "already recovered"
    assert len(db.get_segments(s["id"])) == n


def test_candidates_and_backfill_are_project_scoped():
    p = db.create_project("Shorts", "buying businesses")
    other = db.create_project("Other", "unrelated")
    mine = _short("silent-4", "", CAPTION, project_id=p["id"])
    _short("silent-5", "", CAPTION, project_id=other["id"])
    _short("talks-2", "y" * 800, CAPTION, project_id=p["id"])              # has speech: not a candidate

    cands = ingest.caption_recovery_candidates(p["id"])
    assert [c["id"] for c in cands] == [mine["id"]]
    assert api.api_caption_recovery_preview(p["id"])["count"] == 1
    assert api.api_caption_recovery(p["id"])["queued"] == 1
    # A browser retry after losing the first response returns the same active
    # unit of work instead of creating a second backfill job.
    assert api.api_caption_recovery(p["id"])["queued"] == 1
    j = [x for x in db.list_jobs(limit=50) if x["kind"] == "recover_captions"]
    assert len(j) == 1 and j[0]["lane"] == "low"                           # never displaces work the user watches
    events = db.job_events(j[0]["id"])
    assert any(e["event_type"] == "deduplicated" for e in events)
