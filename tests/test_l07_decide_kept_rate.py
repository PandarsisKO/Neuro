"""L-07 prep: the kept-rate decision is a script, so L-06's review becomes a one-command decision. Pins the E5
rule exactly (cheaper per KEPT finding AND within 10 points), the refusal on an incomplete review, and that it
never touches the database or .env when given stated costs."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location("decide_kept_rate", Path(__file__).resolve().parents[1] / "tools" / "decide_kept_rate.py")
dk = importlib.util.module_from_spec(SPEC); SPEC.loader.exec_module(dk)  # type: ignore[union-attr]

H, S = "claude-haiku-4-5", "claude-sonnet-5"


def _sample(reviews):
    items, key = [], {}
    for i, (model, keep, acc) in enumerate(reviews, start=1):
        items.append({"sample_id": i, "content": "x", "review": {"accurate": acc, "keep": keep, "why_not": None if keep else "vague"}})
        key[str(i)] = {"note_id": i, "source_id": "s", "model": model}
    return {"project_id": "p", "n_items": len(items), "models_present": [H, S], "review_these": items, "_scoring_key": key}


def test_rule_keeps_haiku_when_cheaper_per_kept_and_within_10_points():
    sample = _sample([(H, True, True)] * 8 + [(H, False, True)] * 2 + [(S, True, True)] * 9 + [(S, False, True)] * 1)
    scored = dk.score(sample, {H: 0.010, S: 0.020})
    assert scored["per_model"][H]["kept_rate"] == 80.0 and scored["per_model"][S]["kept_rate"] == 90.0
    assert scored["per_model"][H]["cost_per_kept"] == pytest.approx(0.0125) and scored["per_model"][S]["cost_per_kept"] == pytest.approx(0.0222, abs=1e-4)
    d = dk.decide(scored, H, S)
    assert d["decision"].startswith("keep Haiku") and d["within_10_points"] and d["cheaper_per_kept"] and d["gap_points"] == 10.0


def test_rule_reverts_when_kept_rate_gap_exceeds_10_points_even_if_cheaper():
    sample = _sample([(H, True, True)] * 7 + [(H, False, True)] * 3 + [(S, True, True)] * 10)
    d = dk.decide(dk.score(sample, {H: 0.010, S: 0.020}), H, S)
    assert d["decision"].startswith("revert") and d["cheaper_per_kept"] and not d["within_10_points"]


def test_rule_reverts_when_not_cheaper_per_kept_even_if_quality_matches():
    sample = _sample([(H, True, True)] * 5 + [(H, False, True)] * 5 + [(S, True, True)] * 10)
    d = dk.decide(dk.score(sample, {H: 0.011, S: 0.020}), H, S)     # 0.022/kept vs 0.020/kept
    assert d["decision"].startswith("revert") and not d["cheaper_per_kept"]


def test_incomplete_review_is_refused_not_decided(tmp_path, capsys):
    sample = _sample([(H, True, True), (S, True, True)])
    sample["review_these"][0]["review"] = {"accurate": None, "keep": None, "why_not": None}
    p = tmp_path / "s.json"; p.write_text(json.dumps(sample))
    assert dk.main(["--sample", str(p), "--cost-per-finding", f"{H}=0.01,{S}=0.02"]) == 3
    assert "REFUSING" in capsys.readouterr().out


def test_stated_costs_need_no_database_and_write_nothing(tmp_path, capsys, monkeypatch):
    import neurosearch.db as db
    monkeypatch.setattr(db, "connect", lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not open a database")))
    sample = _sample([(H, True, True)] * 4 + [(S, True, True)] * 4)
    p = tmp_path / "s.json"; p.write_text(json.dumps(sample))
    before = p.read_text()
    assert dk.main(["--sample", str(p), "--cost-per-finding", f"{H}=0.01,{S}=0.02"]) == 0
    assert "DECISION: keep Haiku" in capsys.readouterr().out
    assert p.read_text() == before
