"""CR8b hardening (2026-09-16, HANDOFF.md "Execution -- CR8b hardening: fix the nightly-settings mutation at
its source"): `config.override()` is the scoped mechanism that replaces `cli.py`'s `nightly run` command's old
direct, unrestored mutation of the shared `settings` singleton. That old mutation is exactly what caused CR8b's
own full-suite-only test flake (a prior CLI-driven invocation left `research_refresh_nightly_budget` nonzero for
the rest of the process, so CR6's nightly block fired unexpectedly and consumed the `due_tonight()` TTL-dedup key
CR8b's block needed). These tests prove the mechanism itself, prove the CLI command actually uses it end to end,
and prove the specific CR8b symptom it used to cause is now impossible at the source (not just papered over by
test-fixture isolation, which stays in test_s58_selective_acquisition.py's own fixture as defense in depth)."""
from __future__ import annotations

import pytest
from typer.testing import CliRunner

from neurosearch import candidates, db, knowledge, nightly, research_refresh, t4
from neurosearch.cli import app
from neurosearch.config import override, settings

runner = CliRunner()


@pytest.fixture
def s59_db(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path / "data")
    settings.data_dir.mkdir()
    monkeypatch.setattr(settings, "fake_ai", True)
    monkeypatch.setattr(settings, "daily_budget", 1000)
    monkeypatch.setattr(settings, "t4_nightly_budget", 0.0)
    monkeypatch.setattr(settings, "t4_nightly_hour", 0)
    monkeypatch.setattr(settings, "t5_nightly_budget", 0.0)
    monkeypatch.setattr(settings, "research_refresh_nightly_budget", 0.0)
    monkeypatch.setattr(settings, "cr8b_enabled", False)
    monkeypatch.setattr(t4, "_source_estimate", lambda pid, sid, **k: 0.01)
    db._local.conn = None
    db.init_db()
    yield
    db.close_thread_connection()


def _project_with_source(name="s59"):
    p = db.create_project(name, brief="find the durable facts")
    sid = db.upsert_source(platform="manual", external_id=f"{name}-s0", url=f"manual://{name}", title=name, status="ready")["id"]
    db.connect().execute("INSERT INTO project_sources (project_id,source_id,excluded) VALUES (?,?,0)", (p["id"], sid))
    db.connect().commit()
    return p, sid


def _candidate_row(cid, creator, title, project_id, duration=600):
    db.connect().execute(
        "INSERT INTO candidates (id, platform, external_id, url, title, creator, duration, first_seen_at, last_seen_at, availability) "
        "VALUES (?,?,?,?,?,?,?,?,?, 'available')",
        (cid, "youtube", cid, f"u/{cid}", title, creator, duration, db.now(), db.now()))
    db.connect().execute("INSERT INTO candidate_projects (project_id, candidate_id, state, first_seen_at, updated_at) VALUES (?,?,?,?,?)",
                         (project_id, cid, "available", db.now(), db.now()))
    db.connect().commit()


def _open_target_with_linked_candidate(pid, cid):
    tg = knowledge.add_target(pid, "acme pricing rollout issues explained for Q1 customers")
    _candidate_row(cid, "acme channel", tg["question"], project_id=pid)
    knowledge.pursue(tg["id"], external=False)
    return tg


# ------------------------------------------------------------- 1-3: config.override itself


def test_override_is_visible_inside_the_block_and_restored_on_normal_exit(s59_db):
    baseline = settings.t4_nightly_budget
    assert baseline == 0.0
    with override(t4_nightly_budget=99.0):
        assert settings.t4_nightly_budget == 99.0
    assert settings.t4_nightly_budget == baseline


def test_override_restores_baseline_even_when_the_block_raises(s59_db):
    baseline = settings.research_refresh_nightly_budget
    with pytest.raises(RuntimeError, match="boom"):
        with override(research_refresh_nightly_budget=5.0):
            assert settings.research_refresh_nightly_budget == 5.0
            raise RuntimeError("boom")
    assert settings.research_refresh_nightly_budget == baseline


def test_override_multiple_keys_restore_independently(s59_db):
    b4, b5, brr = settings.t4_nightly_budget, settings.t5_nightly_budget, settings.research_refresh_nightly_budget
    with override(t4_nightly_budget=1.0, t5_nightly_budget=2.0, research_refresh_nightly_budget=3.0):
        assert (settings.t4_nightly_budget, settings.t5_nightly_budget, settings.research_refresh_nightly_budget) == (1.0, 2.0, 3.0)
    assert (settings.t4_nightly_budget, settings.t5_nightly_budget, settings.research_refresh_nightly_budget) == (b4, b5, brr)


def test_override_rejects_an_unknown_settings_attribute(s59_db):
    with pytest.raises(AttributeError):
        with override(this_setting_does_not_exist=1):
            pass


# ------------------------------------------------------------- 4: the CLI command actually uses it, visibly, during execution


def test_nightly_run_cli_override_is_visible_to_nightly_run_during_execution(s59_db, monkeypatch):
    _project_with_source()
    seen: list[tuple[float, float, float]] = []
    real_run = nightly.run

    def _spy(*a, **k):
        seen.append((settings.t4_nightly_budget, settings.t5_nightly_budget, settings.research_refresh_nightly_budget))
        return real_run(*a, **k)
    monkeypatch.setattr(nightly, "run", _spy)

    r = runner.invoke(app, ["nightly", "run", "--budget", "2", "--t5-budget", "1", "--research-refresh-budget", "3", "--yes"])
    assert r.exit_code == 0, r.output
    assert seen == [(2.0, 1.0, 3.0)], "nightly.run() must see the overridden values while it's actually executing"
    assert (settings.t4_nightly_budget, settings.t5_nightly_budget, settings.research_refresh_nightly_budget) == (0.0, 0.0, 0.0)


# ------------------------------------------------------------- 5: two sequential invocations, no leakage


def test_two_sequential_nightly_run_invocations_do_not_leak_into_each_other(s59_db):
    _project_with_source("s59-a")
    r1 = runner.invoke(app, ["nightly", "run", "--budget", "2", "--t5-budget", "1", "--research-refresh-budget", "3"], input="n\n")
    assert r1.exit_code == 0, r1.output
    assert "plus up to $1.00 for T5 adjudication" in r1.output
    assert "plus up to $3.00 for CR6 research refreshes" in r1.output
    assert (settings.t4_nightly_budget, settings.t5_nightly_budget, settings.research_refresh_nightly_budget) == (0.0, 0.0, 0.0)

    # a second, unrelated invocation with only --budget must see T5/research-refresh at their real (off) default --
    # not whatever the first invocation happened to set.
    r2 = runner.invoke(app, ["nightly", "run", "--budget", "5"], input="n\n")
    assert r2.exit_code == 0, r2.output
    assert "authorizing up to $5.00 TOTAL" in r2.output
    assert "T5 adjudication: off" in r2.output
    assert "CR6 research refresh: off" in r2.output


# ------------------------------------------------------------- 6: exception during the command still restores


def test_exception_inside_nightly_run_still_restores_settings(s59_db, monkeypatch):
    _project_with_source()

    def _boom(*a, **k):
        raise RuntimeError("simulated failure mid-envelope")
    monkeypatch.setattr(nightly, "run", _boom)

    r = runner.invoke(app, ["nightly", "run", "--budget", "2", "--t5-budget", "1", "--research-refresh-budget", "3", "--yes"])
    assert r.exit_code != 0
    assert isinstance(r.exception, RuntimeError)
    assert (settings.t4_nightly_budget, settings.t5_nightly_budget, settings.research_refresh_nightly_budget) == (0.0, 0.0, 0.0), \
        "settings must be restored even when the command raises"


# ------------------------------------------------------------- 7: the actual CR8b symptom is fixed at the source


def test_prior_cli_invocation_no_longer_causes_cr6_to_consume_cr8bs_due_tonight_key(s59_db, monkeypatch):
    """This is the exact real-world sequence that used to break: a nightly run with --research-refresh-budget
    left the setting on for the rest of the process, so a LATER, unrelated nightly.run() call (e.g. CR8b's own
    nightly block) saw CR6's block fire and silently consume the due_tonight() TTL key an open-target need
    needed. Proven fixed at the source (config.override), not merely worked around in test_s58's fixture."""
    monkeypatch.setattr(t4, "_source_estimate", lambda pid, sid, **k: 0.01)
    p_cr6, _ = _project_with_source("s59-cr6-project")
    runner.invoke(app, ["nightly", "run", "--budget", "2", "--research-refresh-budget", "5", "--yes"])
    assert (settings.t4_nightly_budget, settings.research_refresh_nightly_budget) == (0.0, 0.0)

    # A second, later project with an open target + linked candidate, exercised the way CR8b's own nightly
    # block exercises it -- directly through nightly.run(), no CLI overrides in play at all. nightly.run() is
    # gated end to end by t4_nightly_budget (the whole envelope's off switch, independent of CR8b's own flag),
    # so this needs its own explicit (non-CLI) budget to actually execute -- matching how CR8b's own nightly
    # tests in test_s58_selective_acquisition.py set it up.
    monkeypatch.setattr(settings, "t4_nightly_budget", 2.0)
    monkeypatch.setattr(settings, "cr8b_enabled", True)
    p_cr8b, _ = _project_with_source("s59-cr8b-project")
    tg = _open_target_with_linked_candidate(p_cr8b["id"], "s59cand1")

    r = nightly.run(force=True)  # the CLI invocation above already recorded today's envelope as run
    cr8b = r["cr8b_acquisition"]
    assert cr8b["ran"] is True
    assert any(x["project_id"] == p_cr8b["id"] and x["target_id"] == tg["id"] for x in cr8b["requested"]), \
        "CR8b's own due_tonight() call must not find its target's TTL key already consumed by the earlier CLI invocation"


# ------------------------------------------------------------- 8: existing CLI behavior is unchanged


def test_existing_disclosure_and_declined_confirmation_behavior_is_unchanged(s59_db):
    _project_with_source()
    r = runner.invoke(app, ["nightly", "run", "--budget", "2"], input="n\n")
    assert r.exit_code == 0, r.output
    assert "authorizing up to $2.00 TOTAL" in r.output
    assert "shared cap" in r.output
    assert "T5 adjudication: off" in r.output
    assert "CR6 research refresh: off" in r.output
    assert nightly.last_run() is None
    assert db.connect().execute("SELECT COUNT(*) n FROM jobs").fetchone()["n"] == 0


def test_existing_off_by_default_refusal_is_unchanged(s59_db):
    r = runner.invoke(app, ["nightly", "run"])
    assert r.exit_code == 1
    assert "OFF" in r.output
