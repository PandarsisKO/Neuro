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
