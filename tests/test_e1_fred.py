"""E1 -- a live number for the rates the deal math turns on.

THE ASYMMETRY THIS FIXES. Claims and Evidence Targets demand that a claim be sourced. For a rate claim, the
only sourcing the app can offer is a video: it can ground "SBA 7(a) is prime plus a spread" in someone saying
so in 2023, and it cannot ground "prime is X" in anything. That is backwards -- the policy is the durable half
and the number is the perishable half, and the perishable half had no source at all.

Two design decisions are pinned here because both are easy to get quietly wrong:

1. FRED writes '.' for a day with no observation -- a weekend, a bank holiday. Read as a number that is 0.0,
   and a prime rate of zero is not an error anyone would catch downstream. Every read walks backwards to the
   most recent REAL value.

2. `max_rate` does NOT know the SBA spread. The spread is policy, it lives in SOP 50 10, and it changes -- a
   constant here would be a second, unversioned copy of a document `works.py` exists to version. The caller
   supplies it and the result says so in as many words.
"""
from __future__ import annotations

import json

import pytest

from neurosearch import fred


class _Res:
    def __init__(self, body: bytes, status: int = 200) -> None:
        self.body, self.status, self.content_type, self.headers = body, status, "application/json", {}


@pytest.fixture()
def keyed(monkeypatch):
    from neurosearch.config import settings
    monkeypatch.setattr(type(settings), "fred_api_key", property(lambda self: "testkey"), raising=False)


@pytest.fixture()
def fetched(monkeypatch, keyed):
    seen: list[str] = []
    answers: dict = {"body": b"{}", "status": 200}

    def fake(url, **kw):
        seen.append(url)
        return _Res(answers["body"], answers["status"])

    from neurosearch import safe_fetch as SF
    monkeypatch.setattr(SF, "safe_fetch", fake)
    return seen, answers


def _obs(rows: list[tuple[str, str]]) -> bytes:
    return json.dumps({"observations": [{"date": d, "value": v} for d, v in rows]}).encode()


# ---------------------------------------------------------------- pure

def test_series_id_accepts_a_friendly_name_or_a_raw_id():
    assert fred.series_id("prime") == "DPRIME"
    assert fred.series_id("DPRIME") == "DPRIME"
    assert fred.series_id("UNRATE") == "UNRATE", "an unnamed series must still be reachable"


def test_series_label_never_returns_an_empty_string():
    assert fred.series_label("prime") == "bank prime loan rate"
    assert fred.series_label("DGS10") == "10-year Treasury constant maturity"
    assert fred.series_label("UNRATE") == "UNRATE"


def test_missing_observations_are_skipped_not_read_as_zero():
    """FRED's '.' means 'no observation that day'. A prime rate of 0.0 would sail through every check below."""
    hit = fred._latest_real([{"date": "2026-09-18", "value": "7.5"},
                             {"date": "2026-09-19", "value": "."},
                             {"date": "2026-09-20", "value": "."}])
    assert hit == {"value": 7.5, "date": "2026-09-18"}


def test_all_missing_is_none_rather_than_zero():
    assert fred._latest_real([{"date": "2026-09-19", "value": "."}]) is None
    assert fred._latest_real([]) is None


# ---------------------------------------------------------------- availability

def test_available_without_a_key_says_where_to_get_one(monkeypatch):
    from neurosearch.config import settings
    monkeypatch.setattr(type(settings), "fred_api_key", property(lambda self: None), raising=False)
    a = fred.available()
    assert a["ready"] is False and "fredaccount.stlouisfed.org" in a["why"]


def test_no_key_raises_before_any_network(monkeypatch):
    from neurosearch import safe_fetch as SF
    from neurosearch.config import settings
    monkeypatch.setattr(type(settings), "fred_api_key", property(lambda self: None), raising=False)
    monkeypatch.setattr(SF, "safe_fetch", lambda *a, **k: pytest.fail("must not reach the network"))
    with pytest.raises(fred.FredUnavailable) as ei:
        fred.prime()
    assert ei.value.reason == "no_key"


# ---------------------------------------------------------------- reads

def test_prime_returns_a_citable_observation(fetched):
    seen, answers = fetched
    # no date asked for -> the module requests sort_order=desc, so FRED answers NEWEST FIRST
    answers["body"] = _obs([("2026-09-18", "7.5"), ("2026-09-17", "7.25")])
    out = fred.prime()
    assert out["value"] == 7.5 and out["date"] == "2026-09-18"
    assert out["series"] == "DPRIME" and out["label"] == "bank prime loan rate"
    assert out["url"] == "https://fred.stlouisfed.org/series/DPRIME"
    assert out["source"].startswith("Federal Reserve Bank of St. Louis")
    assert "api_key=testkey" in seen[0] and "file_type=json" in seen[0]
    assert "sort_order=desc" in seen[0]


def test_a_current_read_takes_the_newest_not_the_first_row(fetched):
    """FRED answers a desc request newest-first. Reading row order wrong here returns a stale rate that looks
    entirely plausible -- the failure mode with no downstream symptom."""
    _, answers = fetched
    answers["body"] = _obs([("2026-09-20", "."), ("2026-09-18", "7.5"), ("2026-09-11", "7.25")])
    assert fred.prime()["date"] == "2026-09-18"


def test_asking_for_a_date_never_returns_a_later_rate(fetched):
    """The rate 'in effect on' a date is the last one published up to it -- the window walks backwards only."""
    seen, answers = fetched
    answers["body"] = _obs([("2026-08-20", "7.0"), ("2026-08-28", "7.25")])
    out = fred.observation("prime", on="2026-08-31")
    assert out["value"] == 7.25 and out["date"] == "2026-08-28"
    assert "observation_end=2026-08-31" in seen[0]
    assert "observation_start=2026-08-01" in seen[0], "a 30-day window back from the date asked for"


def test_a_weekend_still_answers(fetched):
    _, answers = fetched
    answers["body"] = _obs([("2026-09-18", "7.5"), ("2026-09-19", "."), ("2026-09-20", ".")])
    assert fred.observation("prime", on="2026-09-20")["value"] == 7.5


def test_no_observation_in_the_window_is_none_not_an_error(fetched):
    _, answers = fetched
    answers["body"] = _obs([])
    assert fred.prime() is None


def test_a_bad_date_is_refused_before_the_request(fetched):
    seen, _ = fetched
    with pytest.raises(fred.FredUnavailable) as ei:
        fred.observation("prime", on="last August")
    assert ei.value.reason == "bad_request" and seen == []


def test_a_bad_key_is_named_as_such(fetched):
    _, answers = fetched
    answers["status"] = 400
    answers["body"] = b'{"error_message": "Bad Request. The value for variable api_key is not registered."}'
    with pytest.raises(fred.FredUnavailable) as ei:
        fred.prime()
    assert ei.value.reason == "bad_key", "a bad key must not read as a bad request the caller can fix by retrying"


def test_rate_limit_is_typed(fetched):
    _, answers = fetched
    answers["status"] = 429
    with pytest.raises(fred.FredUnavailable) as ei:
        fred.prime()
    assert ei.value.reason == "rate_limited"


def test_one_bad_series_does_not_lose_the_others(monkeypatch, keyed):
    calls: list[str] = []

    def fake_obs(name, on=None, window_days=30):
        calls.append(name)
        if name == "bogus":
            raise fred.FredUnavailable("bad_request", "no such series")
        return {"series": fred.series_id(name), "value": 7.5, "date": "2026-09-18"}

    monkeypatch.setattr(fred, "observation", fake_obs)
    out = fred.rates(["prime", "bogus", "t10"])
    assert out["bogus"] is None and out["prime"]["value"] == 7.5 and out["t10"]["value"] == 7.5
    assert calls == ["prime", "bogus", "t10"]


# ---------------------------------------------------------------- max_rate keeps the policy out of the code

def test_max_rate_shows_its_arithmetic_and_both_halves(fetched):
    _, answers = fetched
    answers["body"] = _obs([("2026-09-18", "7.5")])
    out = fred.max_rate(2.75, spread_source="SOP 50 10 8")
    assert out["rate"] == 10.25
    assert out["base"]["date"] == "2026-09-18" and out["spread"] == 2.75
    assert "SOP 50 10 8" in out["basis"] and "7.5% on 2026-09-18" in out["basis"]


def test_max_rate_says_when_the_spread_is_unsourced(fetched):
    _, answers = fetched
    answers["body"] = _obs([("2026-09-18", "7.5")])
    out = fred.max_rate(3.0)
    assert "not by FRED" in out["basis"], "an unsourced spread must never look like part of the FRED answer"


def test_the_module_defines_no_sba_spread():
    """The allowable spread is SOP 50 10's, and SOPs get superseded. A constant here would be a second,
    unversioned copy of a document works.py exists to version."""
    import inspect
    src = inspect.getsource(fred)
    body = "\n".join(l for l in src.splitlines() if not l.strip().startswith("#") and '"""' not in l)
    assert "2.75" not in body and "3.0" not in body and "SBA_SPREAD" not in body


def test_max_rate_is_none_when_prime_is_unavailable(fetched):
    _, answers = fetched
    answers["body"] = _obs([])
    assert fred.max_rate(2.75) is None
