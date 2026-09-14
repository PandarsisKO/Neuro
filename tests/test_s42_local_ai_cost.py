"""S42 — 27% of local wall-clock was spent saying "OK" (0.63.35). (Sorts after test_s41.)

Kyle: *"investigate the local AI errors. we need to focus on fixing as much as possible before new work
is done on the app."* His sidebar read `Claude Code: error — no answer within 240s · API fallback
active`, and every such refusal is a call that moves from a free subscription onto the paid API.

**This is the first investigation in the project driven by the server log**, which only exists because
0.63.31 added it after an undiagnosable hang. Forty-five minutes of real claims extraction:

```
real claims.extract work   n=20   p50 122.3s   p90 146.9s   max 150.8s
liveness probes            n=20   p50  44.1s   max  51.2s   total 890s = 14.8 minutes
                                  => 27% of all local wall-clock
models probed              19x claude-sonnet-5, 7x claude-opus-5
fallbacks to the paid API  2
```

Twenty real calls and twenty probes — **exactly one probe per call**, against a health verdict that is
supposed to be cached for ten minutes. Three faults, each asserted below.

1. **`note_success` repaired the verdict instead of refreshing it.** It only wrote when the state was
   not already `ready`, so `checked_at` never moved while things were working: the TTL expired mid-run
   and each expiry bought a ~45 s probe to re-establish what a 12,000-token schema-valid answer had just
   proved. A probe asks "can you answer?"; a completed contract call *answered*. Nothing a probe returns
   is better evidence, so a success is now a fresh verdict — and during active work the probe stops
   happening at all, which is what makes the CLI's ~45 s startup cost stop mattering.

2. **One `health()` call site never named a model.** `staleness.assess` asked whether "local" was ready
   with no model, so `wait=False` kicked off a background probe of the CLI's bare DEFAULT — opus-5 on
   his subscription — for a verdict about a model no task uses. Fourth appearance of one bug: 0.45.14
   keyed its fix on an override nobody sets, 0.63.30 made health per-model, 0.63.31 fixed the background
   probe, and this is the site all three missed. Hence a gate on the *shape* rather than on this line.

3. **The `claims.extract` timeout sat 1.59x above the observed maximum of the work it bounds.** 240 s
   against a 150.8 s max is inside the tail, and a timeout here costs twice: the whole local attempt is
   discarded AND the work re-runs on the API, which charges. A timeout exists to catch a HUNG process,
   so it belongs far outside the distribution of work that finishes.

What is NOT claimed: that the probe itself can be made fast. ~45 s is the CLI's own startup and is not
ours to fix. The fix is to stop needing it.
"""
from __future__ import annotations

import os
import pathlib
import re
import tempfile
import time

os.environ.setdefault("NEUROSEARCH_DATA_DIR", tempfile.mkdtemp(prefix="ns_localcost_"))

import pytest  # noqa: E402

from neurosearch import claude_code as CC  # noqa: E402
from neurosearch import contracts  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent
RUNTIME = ("providers.py", "jobs.py", "staleness.py", "api.py", "claude_code.py")

# measured on Kyle's machine, 2026-09-11 — the numbers this release is built on
OBSERVED_MAX_WORK_S = 150.8
OBSERVED_P50_WORK_S = 122.3


@pytest.fixture(autouse=True)
def clean_state():
    CC._state["health"] = None
    CC._state["by_model"] = {}
    yield
    CC._state["health"] = None
    CC._state["by_model"] = {}


# ------------------------------------------------------------------ 1. a success is fresh evidence

def test_a_successful_call_refreshes_the_verdict(monkeypatch):
    """The whole 27% came from this. A real answer must move `checked_at`, not just repair a bad state."""
    CC.note_success("claude-sonnet-5")
    first = CC._state["by_model"][CC._hkey("claude-sonnet-5")]["checked_at"]
    assert CC._state["by_model"][CC._hkey("claude-sonnet-5")]["state"] == "ready"
    time.sleep(0.02)
    CC.note_success("claude-sonnet-5")
    second = CC._state["by_model"][CC._hkey("claude-sonnet-5")]["checked_at"]
    assert second > first, "a second success must refresh the verdict, not be discarded as redundant"


def test_a_success_keeps_the_probe_from_running_at_all(monkeypatch):
    """The behavioural consequence, which is the point: while work is succeeding, no probe happens.

    The profile has to be `local` or `health()` short-circuits to `disabled` before it considers
    probing at all — which is correct behaviour, and is what the first version of this test tripped on."""
    from neurosearch.config import settings
    monkeypatch.setattr(settings, "ai_profile", "local")
    probes = []
    monkeypatch.setattr(CC, "_probe", lambda model=None: probes.append(model) or {"state": "ready", "detail": "probed", "checked_at": time.time(), "probed_model": CC._hkey(model)})
    CC.note_success("claude-sonnet-5")
    for _ in range(5):
        h = CC.health(model="claude-sonnet-5", wait=True)
        assert h["state"] == "ready"
    assert probes == [], f"a fresh success must satisfy health() without probing; probed {probes}"


def test_a_success_on_one_model_does_not_vouch_for_another():
    """0.63.30's separation must survive this change — one model answering says nothing about another."""
    CC.note_success("claude-sonnet-5")
    assert CC._state["by_model"].get(CC._hkey("claude-haiku-4-5")) is None


def test_a_failure_still_wins_over_a_stale_success():
    """Refreshing on success must not make a real failure unreportable."""
    CC.note_success("claude-sonnet-5")
    CC.note_failure(CC.LocalUnavailable("timeout", "no answer within 480s"), model="claude-sonnet-5")
    assert CC._state["by_model"][CC._hkey("claude-sonnet-5")]["state"] != "ready"


# ------------------------------------------------------------------ 2. every asker names its model

def test_no_runtime_module_asks_about_health_without_naming_a_model():
    """Fourth appearance of one bug, so the gate is on the shape and not on the line that was wrong.
    `release.py` is exempt: `doctor` deliberately asks about the CLI's bare default and blocks for it,
    which is a diagnostic about the install rather than a routing decision."""
    offenders = []
    for name in RUNTIME:
        src = (ROOT / "neurosearch" / name).read_text()
        for m in re.finditer(r"(?:claude_code|CC)\.health\(([^)]*)\)", src):
            if "model=" not in m.group(1):
                line = src[: m.start()].count("\n") + 1
                offenders.append(f"{name}:{line}")
    assert not offenders, ("health() must name the model it is asking about, or it probes the CLI's bare "
                           f"default for a verdict nobody uses: {offenders}")


def test_staleness_asks_about_the_model_that_would_do_the_rebuild():
    src = (ROOT / "neurosearch" / "staleness.py").read_text()
    assert "local_model_for(claude_code.DOMINANT_LOCAL_TASK)" in src


# ------------------------------------------------------------------ 3. the timeout is outside the tail

def test_the_claims_timeout_sits_far_outside_the_measured_distribution():
    c = [x for x in contracts._base().values() if x.task == "claims.extract"][0]
    assert c.timeout >= OBSERVED_MAX_WORK_S * 2.5, (
        f"timeout {c.timeout}s is only {c.timeout / OBSERVED_MAX_WORK_S:.2f}x the observed max real work "
        f"({OBSERVED_MAX_WORK_S}s). A timeout catches a HUNG process; inside the tail it just converts "
        "finished free work into a paid API call.")
    assert contracts.CLAIMS_TIMEOUT_BEFORE == 240.0, "keep the previous value legible"
    assert c.timeout > contracts.CLAIMS_TIMEOUT_BEFORE


def test_the_timeout_is_revertible_without_a_code_change(monkeypatch):
    """Every limit in this codebase reads the environment: a number that needs a code edit is not a
    setting, it is a decision nobody can revisit (0.63.14)."""
    monkeypatch.setenv("NEUROSEARCH_CLAIMS_TIMEOUT", "240")
    import importlib
    reloaded = importlib.reload(contracts)
    try:
        assert reloaded.CLAIMS_TIMEOUT == 240.0
    finally:
        monkeypatch.delenv("NEUROSEARCH_CLAIMS_TIMEOUT", raising=False)
        importlib.reload(contracts)


def test_a_junk_timeout_falls_back_to_the_default(monkeypatch):
    monkeypatch.setenv("NEUROSEARCH_CLAIMS_TIMEOUT", "not-a-number")
    import importlib
    try:
        reloaded = importlib.reload(contracts)
        assert reloaded.CLAIMS_TIMEOUT == 480.0
    except ValueError:
        pytest.fail("a typo in .env must not stop the app from importing its contracts")
    finally:
        monkeypatch.delenv("NEUROSEARCH_CLAIMS_TIMEOUT", raising=False)
        importlib.reload(contracts)
