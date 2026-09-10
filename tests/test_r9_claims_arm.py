"""0.56.0 — the comparison arm that can pay `claims.extract`'s debt.

Under the model decision engine (0.54.0), `claims.extract` is held at Sonnet 5 for the reason `irreversible`,
which is explicitly a **debt**: it means *we have not compared it*. It is also the most expensive held task —
$33.03 of a $103.51 month. This is the arm that settles it.

The useful discovery while building it: **five of the six held tasks already had a comparison harness.**
`findings.extract` has `--findings-compare`, `rank.relevance` has `--ranking-compare`, and chat, repair and the
planner family are covered by `--migration-compare`. Only claim normalization had none. So the measurement
infrastructure was one arm short of complete, not three.

The arm invents no rubric. `claims.run_evaluation` already measures what normalization is FOR — qualifiers
preserved, hedges kept, over-generalizations, merges — because that is the bounded evaluation the rung had to pass
to earn adoption. Judging a model by the product's own definition of good is the point; a rubric written
alongside a candidate is a rubric written to flatter it. (Sorts after test_r8.)"""
from __future__ import annotations

import os
import tempfile

os.environ.setdefault("NEUROSEARCH_DATA_DIR", tempfile.mkdtemp(prefix="ns_arm_"))
os.environ["NEUROSEARCH_APP_TOKEN"] = "t0k"
os.environ["NEUROSEARCH_FAKE_AI"] = "1"

import pytest  # noqa: E402

from neurosearch import db, migration  # noqa: E402
from neurosearch.config import settings  # noqa: E402


@pytest.fixture(autouse=True)
def _fresh(tmp_path, monkeypatch):
    data = tmp_path / "data"; data.mkdir(); (data / "media").mkdir()
    monkeypatch.setattr(settings, "data_dir", data)
    monkeypatch.setattr(settings, "fake_ai", True)
    monkeypatch.setattr(settings, "daily_budget", 1000)
    db._local.conn = None
    db.init_db()
    yield
    db._local.conn = None


def test_the_arm_is_wired_into_the_one_command_with_its_own_cost_line():
    assert "claims.extract" in migration.TASK_ARMS
    spend = migration.expected_spend()
    assert any(k.startswith("claims.extract") for k in spend["items"])
    # the whole comparison stays a few dollars — the point is that it is cheap next to the $33/month it settles
    assert spend["estimate"] < 6 and spend["maximum"] < 9


def test_the_verdict_fails_when_qualifiers_are_lost():
    """The failure mode that matters. A claim stripped of "in California, for loans under $500k" is not a shorter
    claim — it is a different and wronger one, and nothing downstream can tell."""
    base = {"qualifier_rate": 0.9, "hedge_rate": 0.9, "n_over_generalized": 0, "over_generalized": [], "normalized": 40,
            "cohort": 40, "merged": 2, "targets_proposed": 3, "seconds": 10.0, "usage": {"cost": 0.18},
            "invocations": {"returned_model": migration.BASELINE_MODEL}}
    cand = {**base, "qualifier_rate": 0.5, "usage": {"cost": 0.05},
            "invocations": {"returned_model": migration.CANDIDATE_MODEL}}
    metas = {"4.6": {"model": migration.BASELINE_MODEL}, "5-disabled": {"model": migration.CANDIDATE_MODEL}}
    v = migration.claims_verdict({"4.6": base, "5-disabled": cand}, metas)
    assert v["verdict"] == "FAIL" and any("qualifiers preserved" in f for f in v["fails"])
    assert "50%" in v["fails"][0] and "90%" in v["fails"][0], "the verdict must show both numbers, not just a word"


def test_the_verdict_fails_on_over_generalization_and_on_dropped_hedges():
    base = {"qualifier_rate": 0.9, "hedge_rate": 0.9, "n_over_generalized": 1, "over_generalized": ["a"], "normalized": 40,
            "cohort": 40, "merged": 2, "targets_proposed": 3, "seconds": 10.0, "usage": {"cost": 0.18},
            "invocations": {"returned_model": migration.BASELINE_MODEL}}
    metas = {"4.6": {"model": migration.BASELINE_MODEL}, "5-disabled": {"model": migration.CANDIDATE_MODEL}}
    over = {**base, "n_over_generalized": 5, "over_generalized": ["a", "b", "c", "d", "e"],
            "invocations": {"returned_model": migration.CANDIDATE_MODEL}}
    assert migration.claims_verdict({"4.6": base, "5-disabled": over}, metas)["verdict"] == "FAIL"
    hedge = {**base, "hedge_rate": 0.4, "invocations": {"returned_model": migration.CANDIDATE_MODEL}}
    v = migration.claims_verdict({"4.6": base, "5-disabled": hedge}, metas)
    assert v["verdict"] == "FAIL" and any("hedge" in f for f in v["fails"])


def test_being_cheaper_and_faster_never_buys_a_pass():
    """Cost and latency are caveats, never verdicts — the whole reason this project measures at all."""
    base = {"qualifier_rate": 0.9, "hedge_rate": 0.9, "n_over_generalized": 0, "over_generalized": [], "normalized": 40,
            "cohort": 40, "merged": 2, "targets_proposed": 3, "seconds": 40.0, "usage": {"cost": 0.60},
            "invocations": {"returned_model": migration.BASELINE_MODEL}}
    cand = {**base, "qualifier_rate": 0.4, "seconds": 3.0, "usage": {"cost": 0.02},
            "invocations": {"returned_model": migration.CANDIDATE_MODEL}}
    metas = {"4.6": {"model": migration.BASELINE_MODEL}, "5-disabled": {"model": migration.CANDIDATE_MODEL}}
    v = migration.claims_verdict({"4.6": base, "5-disabled": cand}, metas)
    assert v["verdict"] == "FAIL", "20x cheaper and 13x faster, and still a fail — quality decides"


def test_an_equal_candidate_passes_and_the_saving_is_reported():
    base = {"qualifier_rate": 0.9, "hedge_rate": 0.9, "n_over_generalized": 1, "over_generalized": ["a"], "normalized": 40,
            "cohort": 40, "merged": 2, "targets_proposed": 3, "seconds": 40.0, "usage": {"cost": 0.60},
            "invocations": {"returned_model": migration.BASELINE_MODEL}}
    cand = {**base, "usage": {"cost": 0.20}, "seconds": 20.0,
            "invocations": {"returned_model": migration.CANDIDATE_MODEL}}
    metas = {"4.6": {"model": migration.BASELINE_MODEL}, "5-disabled": {"model": migration.CANDIDATE_MODEL}}
    v = migration.claims_verdict({"4.6": base, "5-disabled": cand}, metas)
    assert v["verdict"] in ("PASS", "PASS WITH CAVEAT") and not v["fails"]
    assert v["production_default_changed"] is False, "a comparison changes nothing by itself — a human moves the contract"


def test_resetting_between_arms_restores_the_INPUT_not_the_output():
    """Arm two must see the same candidates arm one saw. If normalization survived, arm two would grade the first
    model's output and report a flattering nothing-changed."""
    from neurosearch import claims, evals
    pid = evals.load_golden()["project_id"]
    c = claims.add_claim(pid, "Lenders may allow 15% equity injection in some California deals", origin="user")
    before = {"claims": {c["id"]: {"text": c["text"], "type": "other", "topic": None, "freshness": "slow_changing"}}}
    db.connect().execute("UPDATE project_claims SET normalized=1, extraction_hash='abc', text='Lenders allow 15%' WHERE id=?", (c["id"],))
    db.connect().commit()
    migration._reset_normalization(pid, [c["id"]], before)
    row = db.connect().execute("SELECT normalized, extraction_hash, text FROM project_claims WHERE id=?", (c["id"],)).fetchone()
    assert row["normalized"] == 0 and row["extraction_hash"] is None
    assert row["text"] == "Lenders may allow 15% equity injection in some California deals", "the ORIGINAL text is restored"
