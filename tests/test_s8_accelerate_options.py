"""S8 — two buttons must never buy the same thing (0.59.2).

Kyle: *"two of the spend options in the progress box are identical and worthless. the 'most valuable first' option
and the 'do all' option are the same making 'do most valuable option' pointless."*

He was right, for two compounding reasons:
  1. `order="value"` SORTS the set it is handed, so when the count is every queued job the sort changes nothing;
  2. the value score came from `sources_value.compute(project_id)`, which is empty with no project in scope — so on
     a subset the ordering was frequently a no-op as well.

An option is now a SET with a stated criterion and its own price, and identical sets are collapsed, so the dialog
cannot offer the same purchase twice under two names.

Also covered: why a long queue feels serialised. `start_workers` partitions the AI workers by execution policy and
ordinary findings work is created `local_preferred`, so the API worker is idle BY CONSTRUCTION until something is
accelerated. That was true before and simply never said anywhere.
"""
from __future__ import annotations

import pytest

from neurosearch import db, jobs


@pytest.fixture()
def queued():
    db.init_db()
    with db.tx() as conn:
        conn.execute("UPDATE jobs SET status='done' WHERE status IN ('queued','running')")
    ids = []
    for i in range(30):
        j = db.create_job("suggest_findings", {"project_id": "p", "source_ids": [f"s{i}"]},
                          execution_policy="local_preferred", dedupe_key=f"s8-{i}")
        ids.append(j["id"] if isinstance(j, dict) else j)
    return ids


def test_no_two_options_buy_the_same_set(queued):
    opts = jobs.accelerate_options(None)
    sets = [tuple(o["job_ids"]) for o in opts]
    assert len(sets) == len(set(sets)), [o["key"] for o in opts]


def test_every_option_names_its_criterion_and_its_price(queued):
    for o in jobs.accelerate_options(None):
        assert o["label"] and o["why"] and o["n"] == len(o["job_ids"])
        assert isinstance(o["api_cost"], float)


def test_the_subset_options_are_genuinely_subsets(queued):
    opts = {o["key"]: o for o in jobs.accelerate_options(None)}
    assert "all" in opts and opts["all"]["n"] == 30
    for key, o in opts.items():
        if key != "all":
            assert o["n"] < opts["all"]["n"], f"{key} is not a subset — this is the bug being fixed"
            assert set(o["job_ids"]) < set(opts["all"]["job_ids"])


def test_options_are_offered_cheapest_first(queued):
    costs = [o["api_cost"] for o in jobs.accelerate_options(None)]
    assert costs == sorted(costs)


def test_a_short_queue_offers_only_all(queued):
    """With five or fewer jobs there is no meaningful subset to offer, so one honest button beats three."""
    with db.tx() as conn:
        conn.execute("UPDATE jobs SET status='done' WHERE status='queued'")
    for i in range(3):
        db.create_job("suggest_findings", {"project_id": "p", "source_ids": [f"tiny{i}"]},
                      execution_policy="local_preferred", dedupe_key=f"tiny-{i}")
    opts = jobs.accelerate_options(None)
    assert [o["key"] for o in opts] == ["all"]


def test_an_empty_queue_offers_nothing():
    db.init_db()
    with db.tx() as conn:
        conn.execute("UPDATE jobs SET status='done' WHERE status IN ('queued','running')")
    assert jobs.accelerate_options(None) == []


# ------------------------------------------------------------------ buying exactly what the button said

def test_accelerating_an_option_moves_exactly_that_set(queued):
    opts = {o["key"]: o for o in jobs.accelerate_options(None)}
    target = opts.get("most_valuable") or opts["all"]
    out = jobs.accelerate(None, option=target["key"])
    assert out["moved"] == target["n"]
    assert sorted(out["job_ids"]) == target["job_ids"]        # no re-derivation, no drift from the estimate
    assert out["api_cost"] == target["api_cost"]
    for jid in out["job_ids"]:
        assert db.get_job(jid)["execution_policy"] == "api_requested"


def test_an_unknown_option_is_refused_rather_than_guessed(queued):
    with pytest.raises(ValueError):
        jobs.accelerate(None, option="whatever")


def test_accelerating_leaves_the_rest_on_the_local_pool(queued):
    opts = {o["key"]: o for o in jobs.accelerate_options(None)}
    if "most_valuable" not in opts:
        pytest.skip("no subset option for this queue shape")
    out = jobs.accelerate(None, option="most_valuable")
    assert out["remaining"] == 30 - out["moved"]
    left = [j for j in jobs.backlog(None)["jobs"]]
    assert len(left) == out["remaining"]                      # still local, still $0


# ------------------------------------------------------------------ why it feels serialised

def test_the_backlog_explains_that_the_api_worker_cannot_help(queued, monkeypatch):
    from neurosearch.config import settings
    monkeypatch.setattr(settings, "ai_profile", "local", raising=False)
    b = jobs.backlog(None)
    p = b["pools"]
    assert p["local_queued"] == 30 and p["api_queued"] == 0
    assert p["api_workers"] == 1 and p["local_workers"] >= 1
    assert p["api_idle_by_construction"] is True
    assert "local_preferred" in p["why"] and "accelerating" in p["why"]


def test_accelerating_gives_the_api_worker_something_to_claim(queued, monkeypatch):
    from neurosearch.config import settings
    monkeypatch.setattr(settings, "ai_profile", "local", raising=False)
    assert jobs.backlog(None)["pools"]["api_idle_by_construction"] is True
    jobs.accelerate(None, option="all")
    p = jobs.backlog(None)["pools"]
    assert p["api_queued"] == 30 and p["local_queued"] == 0
    assert p["api_idle_by_construction"] is False
