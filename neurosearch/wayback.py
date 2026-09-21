"""The Internet Archive's Wayback Machine — free, no key, and the only thing that can answer two questions the
app currently asks and then gives up on.

WHAT IT IS FOR. `works.py` already knows when a document has been superseded: `ensure_version` sets the old
version's status to `superseded` the moment a newer one supersedes it, and `version_freshness` hands the G6
freshness rule a typed verdict. What it cannot do is show what the superseded version actually SAID. An SOP
50 10 7 finding cites a page that now serves 50 10 8; the finding is not wrong, it is dated, and there is no
way to see the text it was true of. A capture from before the successor's effective date is exactly that text.

The second use is duller and more common: a finding cites a URL that 404s now. The claim may be perfectly
sound and the evidence simply moved. `rescue()` turns a dead link into the nearest capture rather than making
someone decide between deleting a good finding and keeping an unverifiable one.

BOUNDARIES, mirroring `scholar.py` and `youtube_api.py`. Every request goes through `safe_fetch` — the one
fetch path — with no client library and no second boundary. No model call anywhere. Nothing here writes to the
database or attaches anything to a project; callers decide. No key and no account, so unlike `youtube_api`
there is no `ready` flag gating it: the only failure modes are the network and the archive itself, and both
surface as `WaybackUnavailable` rather than as a silent empty result. Nothing here ever fetches the ARCHIVED
page's own subresources — it returns URLs and metadata, and any actual page fetch is the caller's, through the
same boundary.

WHAT IT DOES NOT DO. It does not SAVE pages to the archive (`/save/` is a write to somebody else's service and
is rate-limited against the caller's IP; if the app ever wants it, that is a deliberate separate decision). It
does not diff two captures — `works.py` has its own change vocabulary and inventing a second one here would be
the drift the design ratchets exist to catch.
"""
from __future__ import annotations

import json
import re
import urllib.parse
from typing import Any

CDX = "http://web.archive.org/cdx/search/cdx"
AVAILABLE = "https://archive.org/wayback/available"
WEB = "https://web.archive.org/web"
DEADLINE_S = 20.0
MAX_ROWS = 200                 # a URL with thousands of captures is a menu, not an answer


class WaybackUnavailable(RuntimeError):
    """One exception for every failure mode, so a caller never has to tell 'never archived' from 'it is down'.
    `never_archived` is the one reason that is an ANSWER rather than an outage, and callers check for it."""

    def __init__(self, reason: str, detail: str = "") -> None:
        super().__init__(f"{reason}: {detail}" if detail else reason)
        self.reason, self.detail = reason, detail


def available() -> dict[str, Any]:
    """Shape-compatible with `youtube_api.available()` so callers can treat the two the same way. Always ready:
    there is no key to configure and no quota to spend."""
    return {"ready": True, "why": "the Wayback Machine needs no key and has no quota"}


def _get(url: str) -> bytes:
    from . import safe_fetch as SF
    try:
        res = SF.safe_fetch(url, content_class="html", headers={"Accept": "application/json"}, deadline_s=DEADLINE_S)
    except SF.FetchBlocked as e:
        raise WaybackUnavailable("fetch_blocked", getattr(e, "reason", "") or str(e)) from e
    except Exception as e:  # noqa: BLE001
        raise WaybackUnavailable("unreachable", str(e)[:200]) from e
    if res.status == 429:
        raise WaybackUnavailable("rate_limited", "the archive asked us to slow down; try again in a minute")
    if res.status >= 400:
        raise WaybackUnavailable("http_error", f"HTTP {res.status}")
    return res.body or b""


# ------------------------------------------------------------------ timestamps (pure; tested offline)

_TS = re.compile(r"^\d{4}(\d{2}(\d{2}(\d{2}(\d{2}(\d{2})?)?)?)?)?$")


def to_timestamp(date: str | None) -> str | None:
    """A date the app already stores -- 'YYYY-MM-DD', or an ISO datetime -- as the archive's own 14-digit
    stamp. Partial stamps are legal to the API and mean 'nearest within this year/month', so a caller that only
    knows a year is not forced to invent a day."""
    if not date:
        return None
    d = str(date).strip()
    if _TS.match(d):
        return d
    m = re.match(r"^(\d{4})-(\d{2})(?:-(\d{2}))?", d)
    if not m:
        return None
    return m.group(1) + m.group(2) + (m.group(3) or "")


def from_timestamp(ts: str | None) -> str | None:
    """The archive's 14-digit stamp back to the 'YYYY-MM-DD' the schema stores."""
    t = (ts or "").strip()
    if len(t) < 8 or not t[:8].isdigit():
        return None
    return f"{t[:4]}-{t[4:6]}-{t[6:8]}"


def archived_url(url: str, timestamp: str) -> str:
    """The stable, citable URL for one capture. `id_` asks the archive for the page as it was CAPTURED rather
    than rewritten for browsing, which is what anyone quoting it wants."""
    return f"{WEB}/{timestamp}id_/{url}"


def viewer_url(url: str, timestamp: str) -> str:
    """The same capture with the archive's own navigation, which is the one to put in front of a person."""
    return f"{WEB}/{timestamp}/{url}"


# ------------------------------------------------------------------ lookups

def _capture(url: str, row_ts: str, status: str | None = None) -> dict[str, Any]:
    return {"url": url, "timestamp": row_ts, "date": from_timestamp(row_ts), "status": status,
            "archived_url": archived_url(url, row_ts), "viewer_url": viewer_url(url, row_ts)}


def nearest(url: str, *, at: str | None = None) -> dict[str, Any] | None:
    """The capture closest to `at` (a date, an ISO datetime, or an archive timestamp; None = the newest).
    Returns None when the archive has never captured this URL -- an answer, not a failure."""
    q = {"url": url}
    ts = to_timestamp(at)
    if ts:
        q["timestamp"] = ts
    body = _get(AVAILABLE + "?" + urllib.parse.urlencode(q))
    try:
        data = json.loads(body.decode("utf-8", "replace"))
    except ValueError as e:
        raise WaybackUnavailable("bad_json", body[:200].decode("utf-8", "replace")) from e
    snap = ((data.get("archived_snapshots") or {}).get("closest") or {})
    if not snap.get("timestamp"):
        return None
    return _capture(url, snap["timestamp"], snap.get("status"))


def captures(url: str, *, limit: int = 50, since: str | None = None, until: str | None = None,
             ok_only: bool = True) -> list[dict[str, Any]]:
    """Every capture of a URL in a window, oldest first. `ok_only` drops captures the archive itself recorded as
    an error page, because a 404 the archive preserved is not evidence of what the page said."""
    limit = max(1, min(int(limit or 50), MAX_ROWS))
    q = {"url": url, "output": "json", "fl": "timestamp,statuscode,digest", "collapse": "digest",
         "limit": str(limit)}
    if to_timestamp(since):
        q["from"] = to_timestamp(since)
    if to_timestamp(until):
        q["to"] = to_timestamp(until)
    if ok_only:
        q["filter"] = "statuscode:200"
    body = _get(CDX + "?" + urllib.parse.urlencode(q))
    text = body.decode("utf-8", "replace").strip()
    if not text:
        return []                      # the CDX endpoint answers "nothing archived" with an empty body
    try:
        rows = json.loads(text)
    except ValueError as e:
        raise WaybackUnavailable("bad_json", text[:200]) from e
    if not rows or len(rows) < 2:
        return []
    header = [str(h) for h in rows[0]]
    out: list[dict[str, Any]] = []
    for r in rows[1:]:
        row = dict(zip(header, [str(x) for x in r]))
        if not row.get("timestamp"):
            continue
        c = _capture(url, row["timestamp"], row.get("statuscode"))
        c["digest"] = row.get("digest")
        out.append(c)
    return out


def before(url: str, date: str) -> dict[str, Any] | None:
    """The last capture taken STRICTLY BEFORE a date -- what `works.py` wants when it knows the date a version
    was superseded and needs the text that was live until then. `nearest` is not good enough here: its closest
    match to an effective date is frequently the capture just AFTER it, which is the new text, not the old."""
    ts = to_timestamp(date)
    if not ts:
        return None
    rows = captures(url, until=ts, limit=MAX_ROWS)
    rows = [r for r in rows if r["timestamp"] < ts.ljust(14, "0")]
    return rows[-1] if rows else None


def rescue(url: str, *, at: str | None = None) -> dict[str, Any] | None:
    """A dead link -> the nearest capture, or None if it was never archived. Deliberately does NOT check
    whether the URL is actually dead: that is a live fetch the caller has already done or has decided not to
    do, and doing it here would mean fetching the same URL twice on every call."""
    try:
        return nearest(url, at=at)
    except WaybackUnavailable as e:
        if e.reason == "never_archived":
            return None
        raise
