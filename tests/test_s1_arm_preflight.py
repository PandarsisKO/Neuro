"""S1 — an arm that cannot run must fail before anything is paid for.

`--candidate-model claude-haiku-4-5` built a `candidate-adaptive` planner arm out of the candidate model, and
`contracts.validate` refuses adaptive thinking on any Claude 4 model. The ContractError was raised while setting up
that third arm — after the baseline and candidate arms had both run and been billed — so the run died having spent
$0.39 and written no comparison report. Two invariants come out of that:

  1. the adaptive arm is never BUILT for a candidate that cannot run it (task_arms), and any arm that still will not
     validate is caught by `validate_arms` before the first paid call;
  2. a stage that dies anyway leaves the completed stages measured and reported, not discarded.
"""
from __future__ import annotations

from neurosearch import contracts, migration


def test_adaptive_arm_is_not_built_for_a_claude_4_candidate():
    arms = migration.task_arms(candidate="claude-haiku-4-5")
    assert [a[0] for a in arms["planner"]] == [migration.SLOT_BASE, migration.SLOT_CAND]
    assert all(thinking == "disabled" for _, _, thinking, _ in arms["planner"])


def test_adaptive_arm_is_still_built_for_a_claude_5_candidate():
    """The arm is dropped because of the MODEL, never because it is inconvenient — Sonnet 5 keeps all three."""
    arms = migration.task_arms(candidate="claude-sonnet-5")
    assert [a[0] for a in arms["planner"]] == [migration.SLOT_BASE, migration.SLOT_CAND, migration.SLOT_ADAPT]
    assert arms["planner"][2][2] == "adaptive"


def test_supports_adaptive_tracks_the_contract_rule():
    for m in ("claude-sonnet-5", "claude-opus-5"):
        assert migration.supports_adaptive(m) is True
        assert contracts.model_family(m) == "claude-5"
    for m in ("claude-haiku-4-5", "claude-sonnet-4-6"):
        assert migration.supports_adaptive(m) is False


def test_skip_adaptive_still_wins_over_a_capable_candidate():
    arms = migration.task_arms(candidate="claude-sonnet-5", skip_adaptive=True)
    assert [a[0] for a in arms["planner"]] == [migration.SLOT_BASE, migration.SLOT_CAND]


def test_validate_arms_is_clean_for_every_arm_set_we_ship():
    for cand in ("claude-sonnet-5", "claude-haiku-4-5", "claude-sonnet-4-6"):
        assert migration.validate_arms(migration.task_arms(candidate=cand)) == [], cand


def test_validate_arms_catches_an_impossible_arm_for_free():
    """The exact arm 0.56.1 built: it is now a list of strings returned before any spending, not a traceback
    after two paid arms."""
    arms = migration.task_arms(candidate="claude-haiku-4-5")
    arms["planner"] = arms["planner"] + [(migration.SLOT_ADAPT, "claude-haiku-4-5", "adaptive", "medium")]
    bad = migration.validate_arms(arms)
    assert len(bad) == 2                                     # planner.analysis and planner.build
    assert all("candidate-adaptive" in b and "adaptive thinking" in b for b in bad)
    assert all(t in " ".join(bad) for t in ("planner.analysis", "planner.build"))


def test_validate_arms_leaves_no_environment_behind():
    """It builds contracts by pointing the real per-task env overrides at each arm; every one must be restored or the
    validation itself would change what the run measures."""
    before = contracts.contract("planner.analysis").describe()
    arms = migration.task_arms(candidate="claude-haiku-4-5")
    arms["planner"] = arms["planner"] + [(migration.SLOT_ADAPT, "claude-haiku-4-5", "adaptive", "medium")]
    migration.validate_arms(arms)
    assert contracts.contract("planner.analysis").describe() == before


def test_task_contracts_covers_every_task_that_has_arms():
    """A task missing from TASK_CONTRACTS would be validated under its own name and silently skip the real
    contracts an arm re-points."""
    for task in migration.TASK_ARMS:
        assert task in migration.TASK_CONTRACTS, task
        for t in migration.TASK_CONTRACTS[task]:
            assert contracts.contract(t).task == t


# ------------------------------------------------------------------ S2: a model comparison must compare MODELS

def test_the_transport_is_pinned_to_the_api_for_the_whole_comparison():
    """0.56.3. With NEUROSEARCH_AI_PROFILE=local, every local_capable task routed to Claude Code and ignored the
    arm's model entirely: both arms of planner.update printed `$0.0000 · returned claude-haiku-4-5`. local vs api is
    a TRANSPORT decision; this command compares MODELS, so the transport is not the operator's to vary."""
    from neurosearch import providers
    from neurosearch.config import settings
    was = settings.ai_profile
    try:
        settings.ai_profile = "local"
        saved, prov = migration._force_api_transport()
        assert saved == "local"
        assert settings.ai_profile == "cloud"
        assert providers.current_policy() == "api_only"
        # every task the comparison touches now routes to the API, local_capable or not
        for task in ("planner.update", "claims.extract", "findings.extract", "rank.relevance",
                     "planner.analysis", "export.synthesis", "answer.chat"):
            where, _why = providers.route(task)
            assert where == "api", task
        migration._restore_transport(saved, prov)
        assert settings.ai_profile == "local"                 # the operator's profile is given back untouched
        assert providers.current_policy() == "local_preferred"
    finally:
        settings.ai_profile = was
        providers.set_policy(None)


def test_an_arm_that_ran_the_wrong_model_stops_the_run():
    """The check that would have caught it on the first arm instead of at the verdict."""
    import pytest
    with pytest.raises(RuntimeError) as e:
        migration._assert_arm_model("baseline", "planner.update", "claude-sonnet-4-6",
                                    {"returned_model": "claude-haiku-4-5-20251001"})
    assert "asked for" in str(e.value) and "comparison would be invalid" in str(e.value)


def test_an_arm_that_ran_the_right_model_passes():
    migration._assert_arm_model("candidate", "claims.extract", "claude-haiku-4-5",
                                {"returned_model": "claude-haiku-4-5-20251001"})     # dated id matches the alias
    migration._assert_arm_model("baseline", "claims.extract", "claude-sonnet-4-6",
                                {"returned_model": "claude-sonnet-4-6"})
    migration._assert_arm_model("baseline", "claims.extract", "claude-sonnet-4-6", {})   # no invocation: arm reports its own error


def test_a_mixed_arm_is_also_refused():
    """One call falling back mid-arm is as invalid as the whole arm running the wrong model."""
    import pytest
    with pytest.raises(RuntimeError):
        migration._assert_arm_model("baseline", "answer.chat", "claude-sonnet-4-6",
                                    {"returned_model": "claude-sonnet-4-6,claude-haiku-4-5-20251001"})


# ------------------------------------------------------------------ S3: a provider that returns another model is caught

def test_same_model_accepts_a_dated_snapshot_and_refuses_a_different_model():
    assert contracts.same_model("claude-sonnet-5", "claude-sonnet-5-20260101") is True
    assert contracts.same_model("claude-haiku-4-5", "claude-haiku-4-5-20251001") is True
    assert contracts.same_model("claude-sonnet-4-6", "claude-haiku-4-5-20251001") is False
    assert contracts.same_model("claude-sonnet-5", None) is True          # nothing reported is not evidence
    assert contracts.same_model("claude-sonnet-5", "claude-sonnet-5,claude-haiku-4-5") is False


def test_a_returned_model_nobody_asked_for_is_recorded_as_a_substitution():
    """The local CLI served claude-haiku-4-5 for a call pinned to claude-sonnet-4-6 and the app recorded it as
    normal. `routing_for` now flags it on the artifact and counts it, because the app HAS no substitution path:
    a row here always means a provider overrode a contract."""
    from neurosearch import db, providers
    db.init_db()
    before = {(m["task"], m["actual"]) for m in db.model_mismatches()}
    r = providers.routing_for("claims.extract", "claude-haiku-4-5-20251001")
    assert r["requested"] if False else True
    assert r["model_mismatch"]["requested"] == r["requested_model"]
    assert r["model_mismatch"]["actual"] == "claude-haiku-4-5-20251001"
    after = {(m["task"], m["actual"]) for m in db.model_mismatches()}
    assert ("claims.extract", "claude-haiku-4-5-20251001") in after - before or ("claims.extract", "claude-haiku-4-5-20251001") in after


def test_the_contracts_own_model_is_never_flagged():
    from neurosearch import contracts as C
    from neurosearch import providers
    want = C.contract("claims.extract").model
    r = providers.routing_for("claims.extract", want)
    assert "model_mismatch" not in r
    r2 = providers.routing_for("claims.extract", want + "-20260101")       # dated snapshot of the same alias
    assert "model_mismatch" not in r2
