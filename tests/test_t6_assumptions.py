"""T6 — assumption ledger: pure, read-only, no database/provider/network path."""
from neurosearch import assumptions
import json


def test_every_registered_assumption_resolves_to_a_real_live_value():
    rows = assumptions.list_assumptions()
    assert len(rows) >= 1
    for row in rows:
        assert not (isinstance(row["value"], str) and row["value"].startswith("ERROR: ")), row


def test_resolution_failure_is_reported_not_raised(monkeypatch):
    bad = assumptions.Assumption(
        name="does-not-exist", module="neurosearch.findings_quality", attr="THIS_ATTR_DOES_NOT_EXIST",
        why="test", measured=False, evidence="test", how_to_verify="test",
    )
    monkeypatch.setattr(assumptions, "REGISTRY", (bad,))
    rows = assumptions.list_assumptions()
    assert len(rows) == 1
    assert rows[0]["value"].startswith("ERROR: ")
    # never raises even with a broken entry
    s = assumptions.summary()
    assert s["resolution_errors"] == 1


def test_summary_counts_measured_vs_unmeasured_and_never_double_counts():
    rows = assumptions.list_assumptions()
    s = assumptions.summary()
    assert s["total"] == len(rows)
    assert s["measured"] + s["unmeasured"] == s["total"]
    assert s["measured"] == sum(1 for r in rows if r["measured"])


def test_render_text_lists_every_assumption_and_shows_verify_hint_only_for_unmeasured():
    text = assumptions.render()
    for row in assumptions.list_assumptions():
        assert row["name"] in text
        if not row["measured"]:
            assert row["how_to_verify"] in text


def test_render_json_round_trips_and_matches_summary():
    text = assumptions.render(as_json=True)
    parsed = json.loads(text)
    assert parsed["summary"] == assumptions.summary()
    assert len(parsed["assumptions"]) == len(assumptions.list_assumptions())


def test_gate_is_informational_only_never_a_pass_fail_verdict():
    # T6's own mission text: "drift warns, never fails a release" -- the ledger has no pass/fail verdict field
    # anywhere in its output shape, unlike repo_check's findings or release.doctor's checks.
    for row in assumptions.list_assumptions():
        assert "verdict" not in row
        assert "pass" not in row


def test_local_and_api_concurrency_defaults_are_registered_and_match_the_live_constants():
    from neurosearch import concurrency
    rows = {r["name"]: r["value"] for r in assumptions.list_assumptions()}
    assert rows["local unit concurrency default"] == concurrency._LOCAL_UNIT_CONCURRENCY_DEFAULT
    assert rows["api unit concurrency default"] == concurrency._API_UNIT_CONCURRENCY_DEFAULT


def test_doctor_reports_the_assumption_ledger_as_informational():
    from neurosearch import release
    rep = release.doctor(progress=lambda *_: None, fake_smoke=False)
    names = [c["check"] for c in rep["checks"]]
    assert any("assumption ledger" in n for n in names)
