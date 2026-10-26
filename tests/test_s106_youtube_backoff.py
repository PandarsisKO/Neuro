"""S106 — YouTube bot-check back-off escalates instead of retrying every 20 minutes forever.

Kyle, 2026-10-23: "youtube is rate limiting Neuro search and I cant do anything with it." Measured live: 20 ingest
jobs, each claimed and paused 60 times — a flat 20-minute pause retried every 20 minutes for 20 hours. A "confirm
you're not a bot" check does not clear in 20 minutes, and knocking every 20 minutes keeps the connection looking
automated. Now each consecutive bot-check doubles the pause (capped), the first success resets it, and the state is
persisted so a restart no longer means an immediate retry."""
from __future__ import annotations

import os

os.environ["NEUROSEARCH_APP_TOKEN"] = "t0k"

import pytest  # noqa: E402

from neurosearch import db, media  # noqa: E402
from neurosearch.config import settings  # noqa: E402

YT = "https://www.youtube.com/watch?v=abc123def45"
BOT = "ERROR: Sign in to confirm you’re not a bot"


@pytest.fixture(autouse=True)
def _fresh(tmp_path, monkeypatch):
    data = tmp_path / "data"; data.mkdir(); (data / "media").mkdir()
    monkeypatch.setattr(settings, "data_dir", data)
    monkeypatch.setattr(settings, "yt_delay", 0.0)
    monkeypatch.setattr(settings, "yt_backoff_minutes", 20)
    db._local.conn = None
    db.init_db()
    yt = media._sites["youtube"]
    saved = {k: yt[k] for k in ("until", "strikes", "loaded", "last")}
    yt.update(until=0.0, strikes=0, loaded=True, last=0.0)
    yield
    yt.update(saved)
    db._local.conn = None


def _bot_check():
    with pytest.raises(media.RateLimited) as e:
        with media.polite(YT):
            raise Exception(BOT)
    return str(e.value)


def _clear_pause():
    media._sites["youtube"]["until"] = 0.0          # pretend the pause elapsed; strikes stay


def test_each_consecutive_bot_check_doubles_the_pause():
    expect = [20, 40, 80, 160, 320, 640]
    for n, mins in enumerate(expect, 1):
        msg = _bot_check()
        left = media.rate_limit_status()["seconds_left"]
        assert abs(left - mins * 60) <= 2, f"strike {n}: expected ~{mins} min, got {left}s"
        assert f"{n} in a row" in msg
        assert media.rate_limit_status()["strikes"] == n
        _clear_pause()


def test_the_pause_is_capped():
    for _ in range(12):
        _bot_check(); _clear_pause()
    _bot_check()
    assert media.rate_limit_status()["seconds_left"] <= media.BACKOFF_CAP_MIN * 60 + 2
    assert media._backoff_minutes(50) == media.BACKOFF_CAP_MIN


def test_a_successful_request_resets_the_escalation():
    for _ in range(4):
        _bot_check(); _clear_pause()
    assert media.rate_limit_status()["strikes"] == 4
    with media.polite(YT):
        pass                                        # got through: the block has cleared
    assert media.rate_limit_status()["strikes"] == 0
    _bot_check()
    assert abs(media.rate_limit_status()["seconds_left"] - 20 * 60) <= 2, "back to the base pause"


def test_the_pause_survives_a_restart():
    _bot_check(); _clear_pause(); _bot_check()      # 2 strikes, 40-minute pause now active
    left_before = media.rate_limit_status()["seconds_left"]
    yt = media._sites["youtube"]
    yt.update(until=0.0, strikes=0, loaded=False)   # a fresh process: in-memory state gone
    st = media.rate_limit_status()                  # reloads from the database
    assert st["paused"] and st["strikes"] == 2
    assert abs(st["seconds_left"] - left_before) <= 3
    with pytest.raises(media.RateLimited):
        with media.polite(YT):
            pass                                    # still refused: a restart is not a retry


def test_non_youtube_is_never_blocked():
    _bot_check()
    with media.polite("https://www.loom.com/share/x"):
        pass
