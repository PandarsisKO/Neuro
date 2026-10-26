"""S107 — Neuro can use a signed-in YouTube session, and a person can say "try again now".

Kyle, 2026-10-26: "Neuro is still getting rate limited. not sure what I can do. its making the app useless." The S106
back-off stopped the hammering, but YouTube's bot check on his home connection did not clear in four days. YouTube
lets a signed-in session through where an anonymous one is refused. So, opt-in and YouTube-only:
NEUROSEARCH_YT_COOKIES_FROM_BROWSER="chrome:<profile name>" makes yt-dlp read that browser profile's YouTube login
(a separate Google account in its own profile — never his main one). The name may be what he sees in Chrome ("Neuro
YouTube"); it is resolved to the profile directory via Chrome's Local State. Not configured or not found = inert.
An explicit cookie file still wins. POST /api/youtube/retry-now clears the pause and releases the held downloads."""
from __future__ import annotations

import json
import os

os.environ["NEUROSEARCH_APP_TOKEN"] = "t0k"

import pytest  # noqa: E402

from neurosearch import db, media  # noqa: E402
from neurosearch.config import settings  # noqa: E402

H = {"Authorization": "Bearer t0k"}
YT = "https://www.youtube.com/watch?v=abc123def45"


@pytest.fixture(autouse=True)
def _fresh(tmp_path, monkeypatch):
    data = tmp_path / "data"; data.mkdir(); (data / "media").mkdir()
    monkeypatch.setattr(settings, "data_dir", data)
    monkeypatch.setattr(settings, "cookies_file", None)
    monkeypatch.setattr(settings, "yt_cookies_from_browser", None)
    media._spec_cache.clear()
    db._local.conn = None
    db.init_db()
    yt = media._sites["youtube"]
    saved = {k: yt[k] for k in ("until", "strikes", "loaded", "last")}
    yt.update(until=0.0, strikes=0, loaded=True, last=0.0)
    yield
    yt.update(saved)
    media._spec_cache.clear()
    db._local.conn = None


@pytest.fixture
def chrome_home(tmp_path, monkeypatch):
    home = tmp_path / "Chrome"; (home / "Default").mkdir(parents=True); (home / "Profile 3").mkdir()
    (home / "Local State").write_text(json.dumps({"profile": {"info_cache": {
        "Default": {"name": "Kyle"}, "Profile 3": {"name": "Neuro YouTube"}}}}), encoding="utf-8")
    monkeypatch.setattr(media, "_chromium_home", lambda b: home if b == "chrome" else None)
    return home


def test_off_by_default():
    assert media.yt_browser_spec() is None
    assert "cookiesfrombrowser" not in media._base_opts(site_url=YT)
    assert media.rate_limit_status()["signed_in"] is False


def test_display_name_resolves_to_the_profile_directory(chrome_home, monkeypatch):
    monkeypatch.setattr(settings, "yt_cookies_from_browser", "chrome:neuro youtube")
    assert media.yt_browser_spec() == ("chrome", "Profile 3", None, None)
    assert media.rate_limit_status()["signed_in"] is True


def test_directory_name_and_bare_browser_work(chrome_home, monkeypatch):
    monkeypatch.setattr(settings, "yt_cookies_from_browser", "chrome:Profile 3")
    assert media.yt_browser_spec() == ("chrome", "Profile 3", None, None)
    monkeypatch.setattr(settings, "yt_cookies_from_browser", "Chrome")
    assert media.yt_browser_spec() == ("chrome", None, None, None)


def test_unknown_profile_is_inert_and_picked_up_once_it_exists(chrome_home, monkeypatch):
    monkeypatch.setattr(settings, "yt_cookies_from_browser", "chrome:Not There")
    assert media.yt_browser_spec() is None
    assert "cookiesfrombrowser" not in media._base_opts(site_url=YT)
    ls = json.loads((chrome_home / "Local State").read_text())
    ls["profile"]["info_cache"]["Profile 9"] = {"name": "Not There"}
    (chrome_home / "Local State").write_text(json.dumps(ls))
    assert media.yt_browser_spec() == ("chrome", "Profile 9", None, None), "a miss is not cached"


def test_only_youtube_gets_the_login(chrome_home, monkeypatch):
    monkeypatch.setattr(settings, "yt_cookies_from_browser", "chrome:Neuro YouTube")
    assert media._base_opts(site_url=YT)["cookiesfrombrowser"] == ("chrome", "Profile 3", None, None)
    assert "cookiesfrombrowser" not in media._base_opts(site_url="https://www.loom.com/share/x")
    assert "cookiesfrombrowser" not in media._base_opts()


def test_an_explicit_cookie_file_wins(chrome_home, monkeypatch, tmp_path):
    cf = tmp_path / "cookies.txt"; cf.write_text("# Netscape HTTP Cookie File\n")
    monkeypatch.setattr(settings, "yt_cookies_from_browser", "chrome:Neuro YouTube")
    monkeypatch.setattr(settings, "cookies_file", str(cf))
    opts = media._base_opts(site_url=YT)
    assert opts["cookiefile"] == str(cf) and "cookiesfrombrowser" not in opts


def test_reset_clears_pause_and_strikes_and_persists():
    for _ in range(3):
        with pytest.raises(media.RateLimited):
            with media.polite(YT):
                raise Exception("ERROR: Sign in to confirm you’re not a bot")
        media._sites["youtube"]["until"] = 0.0
    with pytest.raises(media.RateLimited):
        with media.polite(YT):
            raise Exception("ERROR: Sign in to confirm you’re not a bot")
    assert media.rate_limit_status()["paused"]
    media.reset_rate_limit("youtube")
    media._sites["youtube"].update(until=0.0, strikes=7, loaded=False)    # fresh process reads the saved state
    st = media.rate_limit_status()
    assert not st["paused"] and st["strikes"] == 0


def test_retry_now_releases_held_downloads(client):
    j = db.create_job("ingest", {"url": YT})
    db.requeue_job(j["id"], delay=3600, message="paused: bot check", wait_reason="rate_limit")
    other = db.create_job("ingest", {"url": "https://www.loom.com/share/x"})
    db.requeue_job(other["id"], delay=3600, message="retry later", wait_reason="retry")
    media._sites["youtube"].update(until=media._time.time() + 3600, strikes=4)
    r = client.post("/api/youtube/retry-now", json={}, headers=H)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["released"] == 1 and body["paused"] is False and body["strikes"] == 0
    held, kept = db.get_job(j["id"]), db.get_job(other["id"])
    assert held["not_before"] is None and held["wait_reason"] is None
    assert kept["wait_reason"] == "retry", "only YouTube rate-limit holds are released"
