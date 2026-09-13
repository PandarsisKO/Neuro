"""S51 — no test may reach the live database. (Sorts after test_s50.)

On 2026-09-12 a focused run of one module wrote ten projects into Kyle's production database and queued jobs the
live server executed with real providers. `tests/conftest.py` now hard-sets `NEUROSEARCH_DATA_DIR` before any
module imports; this file makes sure nothing weakens that and that the resolved data dir is never the repo's own.
"""
from pathlib import Path
import os, re, tempfile

TESTS = Path(__file__).resolve().parent
REPO_DATA = (TESTS.parent / "data").resolve()


def test_conftest_hard_sets_the_data_dir_before_any_module():
    src = (TESTS / "conftest.py").read_text(encoding="utf-8")
    assert re.search(r'^os\.environ\["NEUROSEARCH_DATA_DIR"\]\s*=\s*tempfile\.mkdtemp', src, re.M), \
        "conftest.py must hard-set NEUROSEARCH_DATA_DIR (not setdefault) — a developer .env otherwise wins"


def test_no_module_relies_on_setdefault_for_the_data_dir():
    # setdefault is harmless now that conftest wins, but a future removal of the conftest line would silently
    # re-open the hole; keep the ratchet visible so it only ever goes down from the current 71-module baseline.
    offenders = sorted(p.name for p in TESTS.glob("test_*.py")
                       if p.name != Path(__file__).name and 'setdefault("NEUROSEARCH_DATA_DIR"' in p.read_text(encoding="utf-8"))
    assert len(offenders) <= 71, f"new module uses setdefault for the data dir: {offenders}"


def test_resolved_data_dir_is_a_private_temp_dir_not_the_repo():
    d = Path(os.environ["NEUROSEARCH_DATA_DIR"]).resolve()
    assert d != REPO_DATA and REPO_DATA not in d.parents, f"tests resolved to the live data dir: {d}"
    assert Path(tempfile.gettempdir()).resolve() in d.parents or "ns_" in d.name, f"unexpected data dir: {d}"
    from neurosearch.config import settings
    assert Path(settings.data_dir).resolve() == d, "settings.data_dir disagrees with the environment"
