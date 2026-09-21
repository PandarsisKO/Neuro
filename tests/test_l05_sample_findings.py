"""L-05's fixed, blind E5 cohort must not drift with unrelated project history."""
from __future__ import annotations

import importlib.util
import sqlite3
from pathlib import Path

import pytest


SPEC = importlib.util.spec_from_file_location("sample_findings", Path(__file__).resolve().parents[1] / "tools" / "sample_findings.py")
sf = importlib.util.module_from_spec(SPEC); SPEC.loader.exec_module(sf)  # type: ignore[union-attr]


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.execute("CREATE TABLE project_notes (id TEXT, project_id TEXT, source_id TEXT, model TEXT, importance INTEGER, title TEXT, content TEXT, citations TEXT)")
    for source_id, model in sf.E5_COHORT:
        for importance in range(1, 9):
            c.execute("INSERT INTO project_notes VALUES (?,?,?,?,?,?,?,?)", (f"{source_id}-{importance}", sf.PROJECT_ID, source_id, model, importance, "title", "content", None))
        # A historic/null-model note may share this source, but cannot enter this comparison.
        c.execute("INSERT INTO project_notes VALUES (?,?,?,?,?,?,?,?)", (f"{source_id}-legacy", sf.PROJECT_ID, source_id, None, 99, "legacy", "legacy", None))
    for i in range(12):
        c.execute("INSERT INTO project_notes VALUES (?,?,?,?,?,?,?,?)", (f"other-{i}", sf.PROJECT_ID, f"other-source-{i}", "claude-sonnet-5", 5, "other", "other", None))
    return c


def test_fixed_cohort_is_balanced_and_importance_stratified(conn):
    out = sf.build_sample(conn)
    key = out["_scoring_key"]
    assert out["n_items"] == 40 and out["n_sources"] == 8
    # 2026-09-21: the dated id, not the bare alias. `project_notes` stamps API-resolved Haiku findings with the
    # snapshot they actually resolved to ("claude-haiku-4-5-20251001"), while Sonnet's local-provider findings
    # carry the bare "claude-sonnet-5" -- which is why only the Haiku half of this cohort ever hit "0 modeled
    # findings". E5_COHORT was corrected to filter on the exact stored string; this is its test half, which was
    # left behind, so the fixture built rows the assertion rejected.
    assert {v["model"] for v in key.values()} == {"claude-haiku-4-5-20251001", "claude-sonnet-5"}
    assert sum(v["model"] == "claude-haiku-4-5-20251001" for v in key.values()) == 20
    assert sum(v["model"] == "claude-sonnet-5" for v in key.values()) == 20
    assert {v["source_id"] for v in key.values()} == {source_id for source_id, _ in sf.E5_COHORT}
    selected = sorted(int(v["note_id"].rsplit("-", 1)[1]) for v in key.values() if v["source_id"] == sf.E5_COHORT[0][0])
    assert selected == [1, 3, 5, 7, 8]


def test_refuses_when_any_fixed_e5_source_lacks_the_required_modeled_findings(conn):
    source_id, model = sf.E5_COHORT[0]
    conn.execute("DELETE FROM project_notes WHERE source_id=? AND model=?", (source_id, model))
    with pytest.raises(ValueError, match="E5 source"):
        sf.build_sample(conn)
