"""0.54.0 — the model decision engine. "haiku unless XYZ proven by ABC" (Kyle, 2026-09-09).

Model choice had drifted: fourteen tasks sat on `claude-sonnet-4-6` — **$3/$15, dearer AND older than
`claude-sonnet-5` at $2/$10** — not by decision but because HARDENING.md line 211 records the comparison that
would have moved them being skipped ("E2.3 live comparison NOT RUN — by decision, 0.18.0"). Nothing in the code
noticed, because nothing in the code was responsible for noticing.

Now something is. Every task runs the cheapest tier unless its contract names one of four reasons, and a task
above the cheapest tier with no reason is a config error that release-check refuses. That refusal is the whole
point: the expensive choice has to justify itself in code, every time, or it does not ship.

The reasons are deliberately ranked, and the weakest two say so. `capability` and `evidence` are facts about the
model or a recorded measurement; `irreversible` and `user` are a debt and an opinion, both of which a comparison
would settle. (Sorts after test_r5.)"""
from __future__ import annotations

import os
import tempfile

os.environ.setdefault("NEUROSEARCH_DATA_DIR", tempfile.mkdtemp(prefix="ns_pol_"))
os.environ["NEUROSEARCH_APP_TOKEN"] = "t0k"
os.environ["NEUROSEARCH_FAKE_AI"] = "1"

import pytest  # noqa: E402

from neurosearch import contracts as C  # noqa: E402
from neurosearch import db, release, usage  # noqa: E402
from neurosearch.config import settings  # noqa: E402


@pytest.fixture(autouse=True)
def _fresh(tmp_path, monkeypatch):
    data = tmp_path / "data"; data.mkdir(); (data / "media").mkdir()
    monkeypatch.setattr(settings, "data_dir", data)
    monkeypatch.setattr(settings, "fake_ai", True)
    db._local.conn = None
    db.init_db()
    yield
    db._local.conn = None


# ---------------------------------------------------------------- the ladder is a COST ladder

def test_the_tier_order_is_this_repos_own_prices():
    """Not a capability ranking — a price one, taken from usage.PRICES. This is what makes 4.6 above 5."""
    prices = [usage.PRICES[t if t in usage.PRICES else t.rsplit("-", 2)[0]] for t in C.TIERS]
    assert prices == sorted(prices), f"TIERS must be ordered cheapest-first: {list(zip(C.TIERS, prices))}"
    assert C.tier_of("claude-sonnet-4-6") > C.tier_of("claude-sonnet-5"), "4.6 is dearer than 5 and must rank above it"
    assert C.cheapest() == "claude-haiku-4-5"
    assert C.tier_of("some-model-nobody-registered") == len(C.TIERS), "an unknown model must justify itself, not slip in"


# ---------------------------------------------------------------- the rule

def test_every_contract_is_at_the_cheapest_tier_or_names_a_reason():
    assert C.policy_violations() == []
    for d in C.policy_report():
        assert d["verdict"] in ("n/a", "cheapest", *C.REASON_KINDS), d


def test_the_dearer_older_sonnet_is_gone_entirely():
    """The specific drift that started this: fourteen tasks paying 50% more for an older model."""
    assert not [c.task for c in C.all_contracts() if c.model == "claude-sonnet-4-6"]


def test_an_unjustified_expensive_contract_is_a_config_error():
    bad = C.InferenceContract("x.expensive", "anthropic", "claude-opus")
    d = C.decision(bad)
    assert d["verdict"] == "UNJUSTIFIED" and "no recorded reason" in d["why"]
    # ... and release-check is where that actually stops a release
    rep = release.doctor(progress=lambda *a: None, fake_smoke=False)
    line = next(c for c in rep["checks"] if "names a reason" in c["check"])
    assert line["result"] == "PASS"


def test_only_the_four_reason_kinds_count_and_they_are_ranked():
    assert C.policy_reason_ok(None) and C.policy_reason_ok("irreversible")
    assert C.policy_reason_ok("evidence:evals/findings-compare/20260906/") and C.policy_reason_ok("user:Kyle 2026-09-09 — because")
    assert not C.policy_reason_ok("because I said so")
    assert not C.policy_reason_ok("evidence:"), "citing evidence means citing WHERE"
    assert not C.policy_reason_ok("irreversible:something"), "the debt takes no argument"
    # the weakest two are labelled weak, and both say a comparison would settle them
    assert C.REASON_STRENGTH["evidence"] == "measured" and C.REASON_STRENGTH["capability"] == "fact"
    assert C.REASON_STRENGTH["irreversible"] == "debt" and C.REASON_STRENGTH["user"] == "opinion"
    for c in C.all_contracts():
        d = C.decision(c)
        if d["verdict"] in ("irreversible", "user"):
            assert d["settled_by"], f"{c.task} spends on an opinion or a debt and must say what would settle it"
        if d["verdict"] in ("capability", "evidence"):
            assert d["settled_by"] is None


def test_the_debt_cannot_be_claimed_by_something_reversible():
    """`irreversible` is the one reason that is a property of the task, so it must match the task's own flag."""
    liar = C.InferenceContract("x.liar", "anthropic", "claude-opus", tier_reason="irreversible", reversible=True)
    assert any("claims the 'irreversible' debt" in v for v in C._violations_for([liar]))


# ---------------------------------------------------------------- what "reversible" has to mean

def test_reversible_means_the_consequences_are_undoable_not_that_the_call_is_cheap():
    """rank.relevance taught this, and its own frozen tests caught the mistake: re-ranking costs pennies, but by
    then the 20 videos it chose are already downloaded, transcribed, embedded and extracted into the corpus."""
    assert C.contract("rank.relevance").reversible is False
    assert C.decision(C.contract("rank.relevance"))["verdict"] == "irreversible"
    for task in ("findings.extract", "claims.extract"):
        assert C.contract(task).reversible is False, f"{task} writes once into the corpus"
    # everything at the cheapest tier must be genuinely reversible — that is what makes cheap safe
    for c in C.all_contracts():
        if c.provider == "anthropic" and C.decision(c)["verdict"] == "cheapest":
            assert c.reversible, f"{c.task} is cheap but its consequences are not undoable"


def test_the_users_own_holds_are_recorded_as_opinions_not_evidence():
    """Kyle held chat and the planner. That is legitimate and it is his product — but it must never later read as
    a measurement, so it is stored with who and when, and labelled 'opinion'."""
    for task in ("answer.chat", "planner.build"):
        c = C.contract(task)
        assert c.tier_reason.startswith("user:") and "Kyle" in c.tier_reason
        assert C.decision(c)["strength"] == "opinion"
        assert c.model == C.HELD_MODEL, "a held task waits at the cheapest tier ABOVE the default, never on 4.6"


def test_a_local_declaration_is_separate_from_the_tier():
    """0.52.0 and 0.54.0 must not collide: which model runs LOCALLY is its own field, and defaults to no change."""
    for c in C.all_contracts():
        if c.local_capable:
            assert c.model_for("local") == c.model
