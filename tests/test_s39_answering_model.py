"""S39 — which model actually answered, and 363 warnings that were mis-readings (0.63.29). (After test_s38.)

Kyle asked why his free local path didn't pick up an overnight job. Chasing it produced a counter reading **363
`model_mismatch` rows for `findings.extract`** — the local CLI apparently serving `claude-haiku-4-5` for a contract
pinned to `claude-sonnet-5` — and a recommendation from me to pin Haiku in his `.env`. **Both were wrong.**

The CLI was probed directly, asking for `--model sonnet` on a request whose answer is the word "OK":

```
claude-haiku-4-5   inputTokens  902   outputTokens 8   cache       0   cost $0.0009
claude-sonnet-5    inputTokens    2   outputTokens 4   cache 113,720   cost $0.1948
```

A CLI session routinely uses more than one model: the pinned model does the work, and the CLI's own scaffolding
(titles, tool suggestions) runs on Haiku. The old rule picked the model with the most `inputTokens + outputTokens`
and **ignored cached tokens** — so Haiku scored 910 to Sonnet's 6 and was reported as the model that answered,
while Sonnet 5 did the work and was 99.5% of the cost.

The tell was in the data all along: the same counter held a row going the OTHER way (`discover.quick` asked for
Haiku and reported Sonnet 5). A provider that downgrades does not also upgrade.

**The rule now: if the model we asked for appears in the map at all, it is the model that answered.** A provider
running the requested model alongside its own helpers has substituted nothing. Only when the requested model is
absent is it a real substitution, and then the busiest is chosen by COST — the one figure that does not depend on
where the tokens sat.

The 363 are not deleted. `snapshot_pre_fix_mismatches` records them once at upgrade, `model_mismatches()` reports
`before_fix` beside `since_fix`, and Health judges the row on `since_fix` — the same rule 0.62.3 set for mis-dated
spend: the number stays and sits next to its explanation.
"""
from __future__ import annotations

import json
import os
import tempfile

os.environ.setdefault("NEUROSEARCH_DATA_DIR", tempfile.mkdtemp(prefix="ns_am_"))
os.environ["NEUROSEARCH_APP_TOKEN"] = "t0k"

import pytest  # noqa: E402

from neurosearch import db  # noqa: E402
from neurosearch.claude_code import _answering_model  # noqa: E402
from neurosearch.config import settings  # noqa: E402

# the real payload, from a live `claude -p --model sonnet --output-format json`
MU = {
    "claude-haiku-4-5-20251001": {"inputTokens": 902, "outputTokens": 8, "cacheReadInputTokens": 0,
                                  "cacheCreationInputTokens": 0, "costUSD": 0.000942,
                                  "canonicalModel": "claude-haiku-4-5"},
    "claude-sonnet-5": {"inputTokens": 2, "outputTokens": 4, "cacheReadInputTokens": 38923,
                        "cacheCreationInputTokens": 74797, "costUSD": 0.1948211,
                        "canonicalModel": "claude-sonnet-5"},
}


@pytest.fixture()
def fresh(tmp_path, monkeypatch):
    data = tmp_path / "data"; data.mkdir()
    monkeypatch.setattr(settings, "data_dir", data)
    monkeypatch.setattr(settings, "fake_ai", True)
    db._local.conn = None
    db.init_db()
    yield
    db._local.conn = None


def test_the_model_we_asked_for_is_the_one_that_answered():
    """The measured case, and the whole bug: Haiku burns 910 uncached tokens of scaffolding, Sonnet 5 does the
    work almost entirely from cache. Asking for Sonnet 5 must report Sonnet 5."""
    assert _answering_model(MU, "claude-sonnet-5") == "claude-sonnet-5"


def test_the_cli_aliases_resolve():
    """`claude --model sonnet` is what the CLI actually takes; it reports a full id."""
    assert _answering_model(MU, "sonnet") == "claude-sonnet-5"
    assert _answering_model(MU, "haiku") == "claude-haiku-4-5-20251001"


def test_asking_for_haiku_reports_haiku_not_the_costlier_model():
    """The reverse direction, which is what proved the old rule was an artefact rather than a downgrade."""
    assert _answering_model(MU, "claude-haiku-4-5") == "claude-haiku-4-5-20251001"


def test_a_genuinely_absent_model_is_still_a_substitution():
    """The detection must not be switched off: if the requested model never ran, say which one did."""
    assert _answering_model(MU, "claude-opus-4") == "claude-sonnet-5"


def test_the_substitute_is_chosen_by_cost_not_by_uncached_tokens():
    """Cost is the figure that cannot be gamed by whether the input sat in cache."""
    assert _answering_model(MU, None) == "claude-sonnet-5"


def test_an_empty_or_missing_map_reports_what_was_requested():
    assert _answering_model({}, "claude-sonnet-5") == "claude-sonnet-5"
    assert _answering_model(None, "claude-sonnet-5") == "claude-sonnet-5"
    assert _answering_model(None, None) == "claude-code"


def test_the_old_rule_would_have_got_it_wrong():
    """Kept executable so the regression is recognisable: this is the arithmetic that produced 363 warnings."""
    old = max(MU.items(), key=lambda kv: int(kv[1].get("outputTokens") or 0) + int(kv[1].get("inputTokens") or 0))[0]
    assert old == "claude-haiku-4-5-20251001"
    assert _answering_model(MU, "claude-sonnet-5") != old


# ------------------------------------------------------------------ the 363 are explained, not deleted

def test_pre_fix_counts_are_snapshotted_once_and_separated(fresh):
    db.kv_set("model_mismatch:findings.extract:claude-sonnet-5>claude-haiku-4-5:local", "363")
    with db.tx() as conn:
        conn.execute("DELETE FROM kv WHERE key=?", (db.PRE_FIX_MISMATCH_KEY,))
    db.snapshot_pre_fix_mismatches()
    db.bump_model_mismatch("findings.extract", "claude-sonnet-5", "claude-haiku-4-5", "local")
    row = db.health()["model_routing"]["mismatches"][0]
    assert row["count"] == 364 and row["before_fix"] == 363 and row["since_fix"] == 1


def test_the_snapshot_is_idempotent(fresh):
    db.kv_set("model_mismatch:findings.extract:a>b:local", "5")
    with db.tx() as conn:
        conn.execute("DELETE FROM kv WHERE key=?", (db.PRE_FIX_MISMATCH_KEY,))
    db.snapshot_pre_fix_mismatches()
    db.bump_model_mismatch("findings.extract", "a", "b", "local")
    db.snapshot_pre_fix_mismatches()                       # a later restart must not re-baseline the new one away
    row = db.health()["model_routing"]["mismatches"][0]
    assert row["before_fix"] == 5 and row["since_fix"] == 1


def test_nothing_is_deleted(fresh):
    """The history stays readable — 0.62.3's rule for mis-dated spend, applied to a mis-read model."""
    db.kv_set("model_mismatch:findings.extract:x>y:local", "99")
    with db.tx() as conn:
        conn.execute("DELETE FROM kv WHERE key=?", (db.PRE_FIX_MISMATCH_KEY,))
    db.snapshot_pre_fix_mismatches()
    assert int(db.kv_get("model_mismatch:findings.extract:x>y:local")) == 99
    assert db.health()["model_routing"]["mismatches"][0]["count"] == 99


def test_a_clean_install_has_no_baseline_to_explain(fresh):
    assert db.health()["model_routing"]["mismatches"] == []
    assert json.loads(db.kv_get(db.PRE_FIX_MISMATCH_KEY) or "{}") == {}


# ------------------------------------------------------------------ health is per model (0.63.30)

def test_the_probe_asks_about_the_model_the_task_will_run(monkeypatch):
    """The cause of the $0.59. `_probe` used `settings.claude_code_model or None`, which is None whenever no global
    override is set — the normal case — so it measured the CLI's own cheapest-available model while real work ran
    the CONTRACT's model. A limit or error on a model nobody was using reported the whole local path dead and sent
    every job to the paid API. This is the failure the comment above `_probe` says 0.45.14 fixed; that fix keyed on
    a setting that is usually unset, so it never applied to Kyle."""
    from neurosearch import claude_code as CC
    monkeypatch.setattr(settings, "claude_code_model", None)
    assert CC.local_model_for("findings.extract") == "claude-sonnet-5"
    assert CC.local_model_for(None) is None, "no task and no override means no opinion, not the CLI's default"


def test_a_global_override_still_wins(monkeypatch):
    from neurosearch import claude_code as CC
    monkeypatch.setattr(settings, "claude_code_model", "haiku")
    assert CC.local_model_for("findings.extract") == "haiku"


def test_the_router_probes_the_task_model(monkeypatch):
    """`route` must ask about the model it is about to run, or the verdict is about something else."""
    from neurosearch import claude_code as CC
    from neurosearch import providers
    monkeypatch.setattr(settings, "ai_profile", "local")
    monkeypatch.setattr(settings, "claude_code_model", None)
    asked: list[str | None] = []

    def fake_health(force=False, wait=True, model=None):
        asked.append(model)
        return {"state": "ready"}

    monkeypatch.setattr(CC, "health", fake_health)
    monkeypatch.setattr(providers, "current_policy", lambda: "local_preferred")
    target, _reason = providers.route("findings.extract")
    assert target == "local" and asked == ["claude-sonnet-5"]


def test_one_models_failure_does_not_refuse_work_on_another(monkeypatch):
    """The amplification, and why the cache is keyed. `note_failure` was global, so a structured-output failure on
    one model marked the whole local path unavailable — and every refusal that follows is a paid API call."""
    from neurosearch import claude_code as CC
    monkeypatch.setattr(settings, "ai_profile", "local")
    with CC._lock:
        CC._state["by_model"] = {}
    CC.note_success(model="claude-sonnet-5")
    CC.note_failure(CC.LocalUnavailable("error", "error_max_structured_output_retries"), model="claude-haiku-4-5")
    states = CC.states_by_model()
    assert states["claude-sonnet-5"]["state"] == "ready"
    assert states["claude-haiku-4-5"]["state"] == "error"


def test_a_success_clears_only_its_own_model(monkeypatch):
    from neurosearch import claude_code as CC
    monkeypatch.setattr(settings, "ai_profile", "local")
    with CC._lock:
        CC._state["by_model"] = {}
    CC.note_failure(CC.LocalUnavailable("error", "boom"), model="claude-sonnet-5")
    CC.note_failure(CC.LocalUnavailable("error", "boom"), model="claude-haiku-4-5")
    CC.note_success(model="claude-sonnet-5")
    states = CC.states_by_model()
    assert states["claude-sonnet-5"]["state"] == "ready" and states["claude-haiku-4-5"]["state"] == "error"


def test_the_verdict_says_which_model_it_is_about(monkeypatch):
    """A health line that does not name its model cannot be read: it was the source of the whole confusion."""
    from neurosearch import claude_code as CC
    monkeypatch.setattr(settings, "ai_profile", "local")
    with CC._lock:
        CC._state["by_model"] = {}
    CC.note_failure(CC.LocalUnavailable("error", "boom"), model="claude-sonnet-5")
    assert CC.states_by_model()["claude-sonnet-5"]["probed_model"] == "claude-sonnet-5"


def test_the_background_probe_fills_the_cache_it_was_asked_about(monkeypatch):
    """0.63.31, and it was my own 0.63.30 bug: `_probe_bg` took a model and called `_probe()` without it, writing
    only the global slot. So the Health console's verdict was about the CLI's bare default however specific the
    caller was, and the per-model cache the router reads stayed empty. A parameter accepted and not used is worse
    than one that was never added."""
    import time as _t

    from neurosearch import claude_code as CC
    monkeypatch.setattr(settings, "ai_profile", "local")
    monkeypatch.setattr(settings, "claude_code_model", None)
    seen: list[str | None] = []
    monkeypatch.setattr(CC, "_probe", lambda model=None: (seen.append(model) or
                                                          {"state": "ready", "probed_model": CC._hkey(model)}))
    with CC._lock:
        CC._state["health"] = None
        CC._state["by_model"] = {}
    CC.health(wait=False, model="claude-sonnet-5")          # what every Health render does
    for _ in range(40):                                     # the probe runs in its own thread
        if CC.states_by_model().get("claude-sonnet-5"):
            break
        _t.sleep(0.05)
    assert seen == ["claude-sonnet-5"], "the background probe must measure the model it was handed"
    assert CC.states_by_model()["claude-sonnet-5"]["state"] == "ready"


def test_the_start_scripts_keep_the_servers_output_on_disk():
    """Kyle's app hung and there was NOTHING to read — no log anywhere, so a startup crash, a worker traceback and
    a silent deadlock all look identical from outside. The rule this codebase applies to every ladder rung applies
    to its own front door. Bounded, so the log cannot become the problem it exists to diagnose."""
    import pathlib
    root = pathlib.Path(__file__).resolve().parent.parent
    for name in ("start", "start.command"):
        src = (root / name).read_text()
        assert "data/server.log" in src, name
        assert "tee -a" in src, name
        assert "5000000" in src, f"{name}: the log must be bounded"
        assert "exec .venv/bin/neurosearch start" not in src, f"{name}: exec cannot pipe to tee"
