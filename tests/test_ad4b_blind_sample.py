"""AD4B — the blind sample must stay blind.

tools/ad4b_blind_sample.py is only worth running if the reviewable half of the file leaks nothing about what the
algorithm decided. Kyle bulk-approves; shown the score he would agree with the score, and the measurement would
report his deference back to him as agreement. So the blindness invariant is the test, not a detail of it.

These run against synthetic rows through the tool's own build_sample(), so they need no project database.
"""
from __future__ import annotations

import importlib.util
import json
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def _load(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def sampler():
    return _load("ad4b_blind_sample", "tools/ad4b_blind_sample.py")


@pytest.fixture()
def conn():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.executescript("""
        CREATE TABLE candidates (id TEXT PRIMARY KEY, title TEXT, description TEXT, creator TEXT,
                                 duration REAL, published_at TEXT, url TEXT, content_type TEXT);
        CREATE TABLE candidate_projects (candidate_id TEXT, project_id TEXT, state TEXT, relevance INT, relevance_why TEXT);
    """)
    for i in range(100):
        score = [10, 27, 40, 47][i % 4]
        c.execute("INSERT INTO candidates VALUES (?,?,?,?,?,?,?,?)",
                  (f"c{i}", f"Title {i}", f"desc {i}", f"Creator {i % 7}", 1800.0, "2026-01-01", f"http://x/{i}", "video"))
        c.execute("INSERT INTO candidate_projects VALUES (?,?,?,?,?)",
                  (f"c{i}", "P", "skipped_low_relevance", score, f"why {i}"))
    # decoys: none of these may ever appear in a sample
    c.execute("INSERT INTO candidates VALUES ('d1','Decoy','d','C',1.0,'2026','u','video')")
    c.execute("INSERT INTO candidate_projects VALUES ('d1','P','acquired',90,'w')")              # wrong state
    c.execute("INSERT INTO candidates VALUES ('d2','Decoy2','d','C',1.0,'2026','u','video')")
    c.execute("INSERT INTO candidate_projects VALUES ('d2','P','skipped_low_relevance',NULL,'w')")  # unscored
    c.execute("INSERT INTO candidates VALUES ('d3','Decoy3','d','C',1.0,'2026','u','video')")
    c.execute("INSERT INTO candidate_projects VALUES ('d3','OTHER','skipped_low_relevance',44,'w')")  # other project
    c.commit()
    return c


def test_samples_only_scored_rejections_of_this_project(sampler, conn):
    rep = sampler.build_sample(conn, "P", per_band=10, seed=44)
    assert rep["population"]["total_rejected_and_scored"] == 100
    assert set(rep["population"]["by_band"]) == {"0-19", "20-34", "35-44", "45-49"}
    assert rep["sampling"]["sampled"] == 40
    assert all(t.startswith("Title ") for t in (r["title"] for r in rep["review_these"]))   # no decoy titles


def test_the_reviewable_half_leaks_nothing_about_the_verdict(sampler, conn):
    rep = sampler.build_sample(conn, "P", per_band=10, seed=44)
    blob = json.dumps(rep["review_these"])
    for leak in ("score", "band", "model_said", "relevance", "candidate_id", "_scoring_key", "http://x/"):
        assert leak not in blob, f"blindness broken: {leak!r} appears in review_these"
    assert all(set(r["review"]) == {"keep", "why"} for r in rep["review_these"])
    assert all(r["review"]["keep"] is None for r in rep["review_these"])


def test_order_does_not_leak_the_band(sampler, conn):
    rep = sampler.build_sample(conn, "P", per_band=10, seed=44)
    seq = [k["band"] for k in sorted(rep["_scoring_key"], key=lambda k: k["item"])]
    assert len(set(seq[:8])) > 1, f"items are grouped by band, so position reveals the score: {seq[:8]}"


def test_key_is_complete_correctly_paired_and_consistent(sampler, conn):
    rep = sampler.build_sample(conn, "P", per_band=10, seed=44)
    assert len(rep["_scoring_key"]) == len(rep["review_these"])
    assert {k["item"] for k in rep["_scoring_key"]} == {r["item"] for r in rep["review_these"]}
    for k in rep["_scoring_key"]:
        assert k["band"] == sampler._band(k["score"])


def test_sampling_is_reproducible_by_seed(sampler, conn):
    a = sampler.build_sample(conn, "P", 10, 44)["_scoring_key"]
    assert sampler.build_sample(conn, "P", 10, 44)["_scoring_key"] == a
    assert sampler.build_sample(conn, "P", 10, 99)["_scoring_key"] != a


def test_a_band_with_fewer_items_than_asked_for_is_fine(sampler, conn):
    conn.execute("DELETE FROM candidate_projects WHERE relevance=47 AND candidate_id NOT IN ('c3','c7')")
    conn.commit()
    rep = sampler.build_sample(conn, "P", per_band=10, seed=44)
    assert rep["population"]["by_band"]["45-49"] == 2
    assert sum(1 for k in rep["_scoring_key"] if k["band"] == "45-49") == 2


def _score(tmp_path: Path, filled: dict) -> str:
    p = tmp_path / "rubric.json"
    p.write_text(json.dumps(filled))
    r = subprocess.run([sys.executable, str(ROOT / "tools/ad4b_score.py"), "--in", str(p)],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return r.stdout


@pytest.mark.parametrize("keep_every, expect_rate, expect_verdict", [
    (None, "0%", "AD4B closes"),          # kept nothing -> the filter is doing its job
    (1, "100%", "costing you real"),      # kept everything -> the filter is costing material
    (5, "20%", "between"),                # in the middle -> the in-between reading
])
def test_scorer_headline_and_verdict(sampler, conn, tmp_path, keep_every, expect_rate, expect_verdict):
    rep = sampler.build_sample(conn, "P", per_band=10, seed=44)
    for i, r in enumerate(rep["review_these"]):
        r["review"]["keep"] = False if keep_every is None else (i % keep_every == 0)
    out = _score(tmp_path, rep)
    assert f"{expect_rate} of what the filter rejected" in out
    assert expect_verdict in out


def test_scorer_warns_instead_of_crashing_on_a_half_filled_rubric(sampler, conn, tmp_path):
    rep = sampler.build_sample(conn, "P", per_band=10, seed=44)
    for r in rep["review_these"][:10]:
        r["review"]["keep"] = True
    out = _score(tmp_path, rep)
    assert "WARNING" in out and "10 of 40" in out
