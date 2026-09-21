"""FRED (Federal Reserve Bank of St. Louis) — a live number for the rates Kyle's deal math actually turns on.

WHY THIS EXISTS. Claims and Evidence Targets already demand that a claim be sourced. For a rate claim the only
sourcing available today is a video: the app can ground "SBA 7(a) is prime plus a spread" in someone saying so
in 2023, and it cannot ground "prime is X" in anything at all. That is exactly backwards -- the policy is the
durable part and the number is the perishable part, and the perishable part is the one with no source.

SBA 7(a) variable rates are pegged to the WSJ prime rate, so `prime()` is the series that matters most here.
Treasuries are the comparison a seller-financing or conventional-debt argument needs. All of it is free, keyed,
and generous: FRED's documented limit is 120 requests per minute, which no caller here comes close to.

WHAT IT DOES NOT DO. It does not compute an SBA maximum rate from a spread table. The allowable spread is SBA
POLICY, it lives in SOP 50 10, and it changes -- baking a spread into this module would turn a policy that
`works.py` is built to version into a constant nobody versions. `max_rate(spread)` takes the spread as an
argument and says in its result where the spread came from, which keeps the policy citable and the arithmetic
here.

BOUNDARIES, mirroring `scholar.py`, `youtube_api.py` and `wayback.py`: every request goes through `safe_fetch`,
no client library, no second boundary. No model call. Nothing here writes to the database. Without a key
`available()` reports off and every caller is expected to carry on without a live rate rather than fail.
"""
from __future__ import annotations

import json
import urllib.parse
from typing import Any

from .config import settings

API = "https://api.stlouisfed.org/fred"
DEADLINE_S = 20.0

# The handful worth naming. A caller may pass any FRED series id; these are the ones the app has a reason to
# ask for, with the plain-language name a citation should show rather than the ticker.
SERIES = {
    "prime":    ("DPRIME", "bank prime loan rate"),
    "sofr":     ("SOFR", "secured overnight financing rate"),
    "fed_funds": ("DFF", "effective federal funds rate"),
    "t1":       ("DGS1", "1-year Treasury constant maturity"),
    "t5":       ("DGS5", "5-year Treasury constant maturity"),
    "t10":      ("DGS10", "10-year Treasury constant maturity"),
    "t30":      ("DGS30", "30-year Treasury constant maturity"),
}


class FredUnavailable(RuntimeError):
    """One exception for every failure mode, so a caller never has to tell 'no observation' from 'it is down'."""

    def __init__(self, reason: str, detail: str = "") -> None:
        super().__init__(f"{reason}: {detail}" if detail else reason)
        self.reason, self.detail = reason, detail


def available() -> dict[str, Any]:
    """Is FRED usable, and the plain reason when not. Reads config, touches no network."""
    key = settings.fred_api_key
    return {"ready": bool(key),
            "why": "keyed — 120 requests/minute, free" if key else
                   "no NEUROSEARCH_FRED_API_KEY set — rate claims stay ungrounded (free key: "
                   "https://fredaccount.stlouisfed.org/apikeys)"}


def _get(endpoint: str, params: dict[str, Any]) -> Any:
    from . import safe_fetch as SF
    key = settings.fred_api_key
    if not key:
        raise FredUnavailable("no_key", "NEUROSEARCH_FRED_API_KEY is not set")
    q = {k: v for k, v in params.items() if v not in (None, "")}
    q.update({"api_key": key, "file_type": "json"})
    url = f"{API}/{endpoint}?" + urllib.parse.urlencode(q)
    try:
        res = SF.safe_fetch(url, content_class="html", headers={"Accept": "application/json"}, deadline_s=DEADLINE_S)
    except SF.FetchBlocked as e:
        raise FredUnavailable("fetch_blocked", getattr(e, "reason", "") or str(e)) from e
    except Exception as e:  # noqa: BLE001
        raise FredUnavailable("unreachable", str(e)[:200]) from e
    body = (res.body or b"").decode("utf-8", "replace")
    if res.status in (400, 403):
        # FRED answers a bad key with 400 and its own message; surfacing that verbatim is more use than "HTTP 400"
        raise FredUnavailable("bad_key" if "api_key" in body.lower() else "bad_request", body[:200])
    if res.status == 429:
        raise FredUnavailable("rate_limited", "FRED's 120/minute limit; try again shortly")
    if res.status >= 400:
        raise FredUnavailable("http_error", f"HTTP {res.status}")
    try:
        return json.loads(body)
    except ValueError as e:
        raise FredUnavailable("bad_json", body[:200]) from e


# ------------------------------------------------------------------ pure (tested without a key)

def series_id(name: str) -> str:
    """A friendly name ('prime') or a raw FRED id ('DPRIME'), to the id. Unknown names pass through unchanged
    so a caller is never blocked from a series this module has not thought to name."""
    n = (name or "").strip()
    return SERIES.get(n.lower(), (n.upper(), ""))[0] or n.upper()


def series_label(name: str) -> str:
    """The plain-language name a citation should show. Falls back to the id, never to an empty string."""
    n = (name or "").strip()
    hit = SERIES.get(n.lower())
    if hit and hit[1]:
        return hit[1]
    for sid, label in SERIES.values():
        if sid == n.upper() and label:
            return label
    return n.upper()


def _latest_real(observations: list[dict[str, Any]]) -> dict[str, Any] | None:
    """FRED writes '.' for a day with no observation -- a bank holiday, a weekend. Those are not zeros and must
    never be read as a rate; the most recent REAL value is the answer."""
    for obs in reversed(observations or []):
        v = str(obs.get("value", "")).strip()
        if v in ("", "."):
            continue
        try:
            return {"value": float(v), "date": obs.get("date")}
        except ValueError:
            continue
    return None


# ------------------------------------------------------------------ reads

def observation(name: str, *, on: str | None = None, window_days: int = 30) -> dict[str, Any] | None:
    """The current value of a series, or the one in effect on a date. Returns None when FRED has the series but
    no observation in the window -- an answer, not a failure.

    `window_days` exists because a daily series is not published every day: asking for exactly one date and
    getting '.' would read as 'no such rate' on any weekend. The window is walked BACKWARDS, so the result is
    always the rate that was in effect on the date asked for, never a later one.
    """
    sid = series_id(name)
    params: dict[str, Any] = {"series_id": sid, "sort_order": "asc"}
    if on:
        import datetime as _dt
        try:
            end = _dt.date.fromisoformat(str(on)[:10])
        except ValueError as e:
            raise FredUnavailable("bad_request", f"{on!r} is not a date") from e
        params["observation_start"] = (end - _dt.timedelta(days=max(1, window_days))).isoformat()
        params["observation_end"] = end.isoformat()
    else:
        params["limit"] = str(max(1, window_days))
        params["sort_order"] = "desc"
    data = _get("series/observations", params)
    obs = data.get("observations") or []
    if params.get("sort_order") == "desc":
        obs = list(reversed(obs))
    hit = _latest_real(obs)
    if not hit:
        return None
    return {"series": sid, "label": series_label(name), "value": hit["value"], "date": hit["date"],
            "units": "percent per year",
            "source": "Federal Reserve Bank of St. Louis (FRED)",
            "url": f"https://fred.stlouisfed.org/series/{sid}"}


def prime(*, on: str | None = None) -> dict[str, Any] | None:
    """The WSJ-equivalent bank prime loan rate -- what an SBA 7(a) variable rate is pegged to."""
    return observation("prime", on=on)


def rates(names: list[str] | None = None, *, on: str | None = None) -> dict[str, dict[str, Any] | None]:
    """Several series at once. One request each -- FRED has no batch endpoint -- which is well inside its
    120/minute limit for any list this app would ask for. A series that errors is None rather than an
    exception, so one bad id cannot lose the others."""
    out: dict[str, dict[str, Any] | None] = {}
    for n in (names or ["prime", "t10"]):
        try:
            out[n] = observation(n, on=on)
        except FredUnavailable:
            out[n] = None
    return out


def max_rate(spread: float, *, on: str | None = None, spread_source: str | None = None) -> dict[str, Any] | None:
    """prime + a spread the CALLER supplies, with the arithmetic shown and both halves citable.

    The spread is not defined here on purpose. It is SBA policy, it lives in SOP 50 10, and it changes -- which
    is precisely the kind of thing `works.py` exists to version. A constant in this file would be a second,
    unversioned copy of it. Pass `spread_source` (an SOP label, a finding id, a URL) and it is carried into the
    result, so anything built on this can say where each half of the number came from.
    """
    base = prime(on=on)
    if not base:
        return None
    return {"rate": round(base["value"] + float(spread), 4), "base": base, "spread": float(spread),
            "spread_source": spread_source,
            "basis": f"{base['label']} {base['value']}% on {base['date']} plus a {float(spread)}% spread"
                     + (f" ({spread_source})" if spread_source else " (spread supplied by the caller, not by FRED)")}
