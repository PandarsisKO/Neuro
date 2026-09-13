from pathlib import Path

from neurosearch.repo_check import check_repo, render


def _repo(tmp_path: Path) -> Path:
    (tmp_path / "neurosearch").mkdir()
    (tmp_path / "tests").mkdir()
    return tmp_path


def test_duplicate_top_level_definitions_are_reported(tmp_path):
    root = _repo(tmp_path)
    (root / "neurosearch" / "x.py").write_text("def same(): pass\ndef same(): pass\n")
    findings = check_repo(root)
    assert any(f.rule == "duplicate-definition" for f in findings)


def test_nested_repeated_methods_are_not_reported(tmp_path):
    root = _repo(tmp_path)
    (root / "neurosearch" / "x.py").write_text("class A:\n def same(self): pass\nclass B:\n def same(self): pass\n")
    assert not any(f.rule == "duplicate-definition" for f in check_repo(root))


def test_duplicate_routes_are_reported(tmp_path):
    root = _repo(tmp_path)
    (root / "neurosearch" / "x.py").write_text("@app.get('/x')\ndef a(): pass\n@app.get('/x')\ndef b(): pass\n")
    assert any(f.rule == "duplicate-route" for f in check_repo(root))


def test_broken_markdown_link_and_suspicious_name(tmp_path):
    root = _repo(tmp_path)
    (root / "README.md").write_text("[missing](docs/nope.md)\n")
    (root / "neurosearch" / "old_helper.py").write_text("")
    rules = {f.rule for f in check_repo(root)}
    assert {"broken-reference", "suspicious-filename"} <= rules


def test_render_is_stable_and_json_is_structured(tmp_path):
    root = _repo(tmp_path)
    (root / "README.md").write_text("[missing](nope.md)\n")
    findings = check_repo(root)
    assert render(findings) == render(findings)
    assert '"rule": "broken-reference"' in render(findings, as_json=True)


def test_direct_database_connection_outside_db_module_is_reported(tmp_path):
    root = _repo(tmp_path)
    (root / "neurosearch" / "bad.py").write_text("import sqlite3\nsqlite3.connect('x.db')\n")
    assert any(f.rule == "direct-db-connection" and f.severity == "error" for f in check_repo(root))
