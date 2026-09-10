"""S9 — cost per unit of value (0.59.3).

Kyle, after the overnight run: *"the volume of data is always valuable, just HOW is something we want to keep
checking that we are improving against."* Every spend surface the app had answered a different question — how much,
how much was really charged, how fast — and none of them said whether the money bought anything. So the findings
cap going from 12 to 20 could only be judged on whether the bill rose.

Two properties matter more than any single ratio here, and both are tested:

* **the report reconciles** — `attributed` + `unattributed` is the whole charged bill for the window, so no spend
  can hide behind a flattering ratio; and
* **it refuses to divide when the division would lie.** The live corpus produced $0.0231 per finding on Haiku
  against $0.0071 on Sonnet 5 — Haiku, at a fifth of the token price, apparently three times dearer. Every one of
  those Haiku rows was priced at Sonnet 5's rates, because `record_anthropic`'s local branch prices avoided spend
  at the CONTRACT's model. `price_basis` is what stops that number being printed as a verdict.
"""
from __future__ import annotations

import time

import pytest

from neurosearch import cost_value, db


@pytest.fixture()
def project(monkeypatch):
    db.init_db()
    monkeypatch.setenv("NEUROSEARCH_LOCAL_BILLING", "subscription")
    p = db.create_project("cost-value", brief="does the money buy anything")
    with db.tx() as conn:
        conn.execute("DELETE FROM usage")
        conn.execute("DELETE FROM project_notes WHERE project_id=?", (p["id"],))
        conn.execute("DELETE FROM project_claims WHERE project_id=?", (p["id"],))
    yield p["id"]


def _usage(kind, cost, *, model="claude-sonnet-5", project_id=None, transport="interactive", saved=0.0,
           price_model=None, ago=60.0):
    with db.tx() as conn:
        conn.execute("INSERT INTO usage (ts, kind, model, cost, project_id, transport, saved, price_model) "
                     "VALUES (?,?,?,?,?,?,?,?)",
                     (time.time() - ago, kind, model, cost, project_id, transport, saved, price_model or model))


def _note(project_id, *, status="approved", model="claude-sonnet-5", ago=60.0, source_id="s1"):
    with db.tx() as conn:
        cur = conn.execute("INSERT INTO project_notes (project_id, content, created_at, status, model, source_id) "
                           "VALUES (?,?,?,?,?,?)",
                           (project_id, "a specific finding about 10% seller financing", time.time() - ago,
                            status, model, source_id))
        return int(cur.lastrowid)


def _claim(project_id, *, normalized=1, model="claude-sonnet-4-6", ago=60.0):
    with db.tx() as conn:
        conn.execute("INSERT INTO project_claims (id, project_id, text, normalized, model, created_at, updated_at) "
                     "VALUES (?,?,?,?,?,?,?)",
                     (f"c{time.time_ns()}", project_id, "lenders allow this under conditions", normalized, model,
                      time.time() - ago, time.time() - ago))


# ------------------------------------------------------------------ the arithmetic

def test_dollars_per_finding_divides_findings_spend_by_findings(project):
    _usage("findings", 1.00, project_id=project)
    for _ in range(10):
        _note(project)
    rep = cost_value.unit_costs("today", project)
    row = next(r for r in rep["rows"] if r["unit"] == "finding")
    assert row["cost"] == pytest.approx(1.00)
    assert row["count"] == 10
    assert row["per_unit"] == pytest.approx(0.10)


def test_the_whole_bill_is_never_spread_across_units(project):
    """A finding's ratio must not be diluted by chat, and chat's must not be diluted by findings."""
    _usage("findings", 1.00, project_id=project)
    _usage("answer", 9.00, project_id=project)
    _note(project)
    rep = cost_value.unit_costs("today", project)
    assert next(r for r in rep["rows"] if r["unit"] == "finding")["per_unit"] == pytest.approx(1.00)
    assert next(r for r in rep["rows"] if r["unit"] == "answer")["cost"] == pytest.approx(9.00)


def test_the_report_reconciles_against_the_bill(project):
    """attributed + unattributed == total_charged. Without this, any ratio can be made to look good by leaving
    spend out of the denominator's neighbourhood."""
    _usage("findings", 2.00, project_id=project)
    _usage("discover", 0.50, project_id=project)
    _usage("plan", 0.25, project_id=project)
    rep = cost_value.unit_costs("today", project)
    assert rep["total_charged"] == pytest.approx(2.75)
    assert rep["attributed"] + rep["unattributed"]["total"] == pytest.approx(rep["total_charged"])
    assert set(rep["unattributed"]["by_kind"]) == {"discover", "plan"}


def test_kept_is_a_different_number_from_written(project):
    """This is the one that judges the cap. Raising it moves rows from reserve to suggested for no extra money, so
    $/written stays flat while $/kept falls — and only the second is a measure of value."""
    _usage("findings", 1.00, project_id=project)
    for _ in range(4):
        _note(project, status="approved")
    for _ in range(6):
        _note(project, status="reserve")
    rep = cost_value.unit_costs("today", project)
    written = next(r for r in rep["rows"] if r["unit"] == "finding")
    kept = next(r for r in rep["rows"] if r["unit"] == "kept_finding")
    assert written["count"] == 10 and written["per_unit"] == pytest.approx(0.10)
    assert kept["count"] == 4 and kept["per_unit"] == pytest.approx(0.25)


def test_a_note_pinned_by_hand_is_not_in_the_denominator(project):
    """Only a machine-written finding was paid for. A note pinned in chat has no model and must not make the
    ratio look better than it is."""
    _usage("findings", 1.00, project_id=project)
    _note(project)
    with db.tx() as conn:
        conn.execute("INSERT INTO project_notes (project_id, content, created_at, status) VALUES (?,?,?,?)",
                     (project, "kyle pinned this himself", time.time(), "approved"))
    assert next(r for r in cost_value.unit_costs("today", project)["rows"]
                if r["unit"] == "finding")["count"] == 1


def test_harvested_claims_are_free_and_the_report_says_so(project):
    """`claims.harvest` builds Claims from findings for $0; only `claims.extract` costs anything. So $/Claim
    tracked and $/Claim normalized are different questions and both are reported."""
    _usage("claims", 1.00, project_id=project)
    for _ in range(2):
        _claim(project, normalized=1)
    for _ in range(8):
        _claim(project, normalized=0)
    rep = cost_value.unit_costs("today", project)
    assert next(r for r in rep["rows"] if r["unit"] == "claim")["per_unit"] == pytest.approx(0.10)
    assert next(r for r in rep["rows"] if r["unit"] == "normalized_claim")["per_unit"] == pytest.approx(0.50)


# ------------------------------------------------------------------ refusing to divide

def test_spend_with_no_output_is_not_a_cost_of_infinity(project):
    _usage("findings", 5.00, project_id=project)
    row = next(r for r in cost_value.unit_costs("today", project)["rows"] if r["unit"] == "finding")
    assert row["per_unit"] is None
    assert "nothing to show for it" in row["per_unit_unavailable"]


def test_output_with_no_spend_is_free_not_unknown(project):
    _note(project)
    row = next(r for r in cost_value.unit_costs("today", project)["rows"] if r["unit"] == "finding")
    assert row["per_unit"] == pytest.approx(0.0)


# ------------------------------------------------------------------ charged, not recorded

def test_a_billed_local_call_counts_as_spend(project, monkeypatch):
    """The 0.59.0 rule, in the denominator's numerator: a local row books its dollars in `saved`, and if the CLI
    is billing an API key those dollars were charged. Dividing recorded-only spend by output would price every
    local finding at $0 — the same error that hid $200."""
    monkeypatch.setenv("NEUROSEARCH_LOCAL_BILLING", "api_key")
    _usage("findings", 0.0, transport="local", saved=2.00, project_id=project)
    for _ in range(10):
        _note(project)
    rep = cost_value.unit_costs("today", project)
    assert rep["local_billed"] is True
    assert next(r for r in rep["rows"] if r["unit"] == "finding")["per_unit"] == pytest.approx(0.20)
    assert rep["estimated"]["share"] == pytest.approx(1.0)


def test_a_subscription_local_call_is_free(project, monkeypatch):
    monkeypatch.setenv("NEUROSEARCH_LOCAL_BILLING", "subscription")
    _usage("findings", 0.0, transport="local", saved=2.00, project_id=project)
    _note(project)
    rep = cost_value.unit_costs("today", project)
    assert rep["local_billed"] is False
    assert next(r for r in rep["rows"] if r["unit"] == "finding")["cost"] == pytest.approx(0.0)


def test_the_estimated_share_is_reported(project, monkeypatch):
    """A local row's dollars are priced from tokens, not invoiced. A ratio built partly on estimates is worth
    having; it has to say how much of it is estimated."""
    monkeypatch.setenv("NEUROSEARCH_LOCAL_BILLING", "api_key")
    _usage("findings", 0.0, transport="local", saved=3.00, project_id=project)
    _usage("findings", 1.00, project_id=project)
    assert cost_value.unit_costs("today", project)["estimated"]["share"] == pytest.approx(0.75)


# ------------------------------------------------------------------ per model: the price basis

def test_a_model_priced_at_another_models_rates_is_not_comparable(project, monkeypatch):
    """The live bug, frozen. 513 local Haiku calls priced at Sonnet 5's rates made Haiku look 3x dearer per
    finding than Sonnet 5. The row still carries its cost and its count; what it must never carry is a per_unit
    that reads as a verdict."""
    monkeypatch.setenv("NEUROSEARCH_LOCAL_BILLING", "api_key")
    _usage("findings", 0.0, model="claude-haiku-4-5", transport="local", saved=9.00,
           price_model="claude-sonnet-5", project_id=project)
    for _ in range(30):
        _note(project, model="claude-haiku-4-5")
    rep = cost_value.by_model("finding", "today", project)
    haiku = next(r for r in rep["rows"] if r["model"] == "claude-haiku-4-5")
    assert haiku["cost"] == pytest.approx(9.00) and haiku["count"] == 30
    assert haiku["per_unit"] is None and haiku["comparable"] is False
    assert "another model's rates" in haiku["per_unit_unavailable"]
    assert haiku["price_basis"] == {"claude-sonnet-5": pytest.approx(9.00)}


def test_an_unrecorded_basis_on_the_local_path_is_treated_as_unknown(project, monkeypatch):
    """Rows written before 0.59.3 have no `price_model`, and on the local path the basis genuinely cannot be
    reconstructed — the contract's model was never stored. Unknown must not silently become the row's own model."""
    monkeypatch.setenv("NEUROSEARCH_LOCAL_BILLING", "api_key")
    with db.tx() as conn:
        conn.execute("INSERT INTO usage (ts, kind, model, cost, project_id, transport, saved) "
                     "VALUES (?,?,?,?,?,?,?)",
                     (time.time(), "findings", "claude-haiku-4-5", 0.0, project, "local", 4.0))
    _note(project, model="claude-haiku-4-5")
    row = next(r for r in cost_value.by_model("finding", "today", project)["rows"]
               if r["model"] == "claude-haiku-4-5")
    assert row["comparable"] is False
    assert "not recorded" in row["per_unit_unavailable"]


def test_two_models_on_their_own_rates_do_compare(project):
    _usage("findings", 1.00, model="claude-sonnet-5", project_id=project)
    _usage("findings", 1.00, model="claude-haiku-4-5", project_id=project)
    for _ in range(10):
        _note(project, model="claude-sonnet-5")
    for _ in range(50):
        _note(project, model="claude-haiku-4-5")
    rep = cost_value.by_model("finding", "today", project)
    assert rep["comparable_models"] == 2
    assert rep["rows"][0]["model"] == "claude-haiku-4-5"          # cheapest per finding sorts first
    assert rep["rows"][0]["per_unit"] == pytest.approx(0.02)
    assert "claude-haiku-4-5 is the cheapest" in rep["verdict"]


def test_by_model_is_refused_for_units_that_do_not_record_a_model(project):
    rep = cost_value.by_model("source", "today")
    assert rep["supported"] is False and "record the model" in rep["reason"]


# ------------------------------------------------------------------ scope and shape

def test_source_cost_is_a_whole_app_number_and_is_omitted_per_project(project):
    """Transcription and embedding rows carry no project, so a per-project $/source would be a guess. It is left
    out with the reason in `caveats` rather than shown as zero."""
    _usage("whisper", 1.00, model="whisper-1")
    assert not any(r["unit"] == "source" for r in cost_value.unit_costs("today", project)["rows"])
    assert any(r["unit"] == "source" for r in cost_value.unit_costs("today")["rows"])


def test_corroboration_is_only_offered_when_asked_for(project):
    """The corroboration index is a ~4 s clustering pass over the whole project. It is cached, but it is not run
    for a money report unless the caller says it wants it."""
    _usage("findings", 1.00, project_id=project)
    _note(project)
    assert not any(r["unit"] == "corroborated_finding"
                   for r in cost_value.unit_costs("today", project)["rows"])
    rep = cost_value.unit_costs("today", project, include_quality=True)
    assert any(r["unit"] == "corroborated_finding" for r in rep["rows"])


def test_corroborated_findings_in_a_window_are_counted_from_the_whole_corpus(project):
    """Two sources saying the same thing is corroboration (0.59.0), and it is a property of the corpus rather than
    of the window: a finding written today can become corroborated tomorrow with no new spend."""
    from neurosearch import findings_quality
    text = "an SBA lender pre-screens the buyer before the seller signs anything at all"
    with db.tx() as conn:
        for sid in ("sA", "sB"):
            conn.execute("INSERT INTO project_notes (project_id, content, created_at, status, model, source_id) "
                         "VALUES (?,?,?,?,?,?)", (project, text, time.time(), "approved", "claude-sonnet-5", sid))
    ids = findings_quality.corroborated_ids(project)
    assert len(ids) == 2
    assert cost_value.corroborated_in_window(project, 0.0)["count"] == 2


def test_the_trend_gives_one_row_per_day(project):
    _usage("findings", 1.00, project_id=project, ago=0)
    _usage("findings", 3.00, project_id=project, ago=86400 * 2)
    _note(project, ago=0)
    _note(project, ago=86400 * 2)
    rows = cost_value.trend("kept_finding", 7, project)["rows"]
    assert len(rows) == 2
    assert rows[0]["day"] > rows[1]["day"]                        # newest first
    assert rows[0]["per_unit"] == pytest.approx(1.00)


def test_windows_are_ordered_and_bounded(project):
    assert cost_value.window_start("today") >= cost_value.window_start("week")
    assert cost_value.window_start("week") >= cost_value.window_start("month") - 1
    assert cost_value.window_start("all") == 0.0
    assert cost_value.window_start("month", days=3) > cost_value.window_start("week")


def test_the_headline_survives_an_empty_ledger(project):
    h = cost_value.headline()
    assert h["month"]["per_kept_finding"] is None or isinstance(h["month"]["per_kept_finding"], float)
    assert "week_vs_month" in h


def test_health_carries_the_headline_and_never_raises(project):
    _usage("findings", 1.00, project_id=project)
    _note(project)
    cv = db.health()["cost_value"]
    assert "error" not in cv
    # the headline is deliberately WHOLE-APP (Health is not project-scoped), so this asserts the shape and that a
    # number arrives, not a figure the shared test database can be made to agree on
    assert isinstance(cv["month"]["per_kept_finding"], float) and cv["month"]["per_kept_finding"] > 0
    assert cv["week_vs_month"] in (None, "cheaper", "dearer", "flat")


def test_every_unit_declares_what_it_is(project):
    for unit, spec in cost_value.UNITS.items():
        assert spec["kinds"] and spec["label"] and spec["what"], unit
