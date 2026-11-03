"""Typed Reddit recovery handoff reuses extension scan state, popup and walker."""
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def test_app_to_extension_prepared_scan_workflow():
    js_dir = ROOT / 'tests/js'
    if not (js_dir / 'node_modules/jsdom').exists():
        setup = subprocess.run(['npm', 'ci', '--prefix', str(js_dir)], capture_output=True, text=True, timeout=180)
        assert setup.returncode == 0, setup.stderr
    result = subprocess.run(['node', str(js_dir / 'run-reddit-handoff.mjs')], cwd=ROOT,
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'Reddit extension handoff workflow PASS' in result.stdout
