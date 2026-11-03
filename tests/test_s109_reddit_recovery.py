"""Reddit failures offer the existing browser scan, including historical failed jobs.

Runs the shipped renderers against the real UI markup. The S95 integration gate separately proves
that the extension's listing → review → selected thread capture path uses canonical ingestion.
"""
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def test_reddit_failure_recovery_workflow():
    # Same committed lockfile as the scanner/screenshot gates; standalone invocation works too.
    js_dir = ROOT / "tests/js"
    if not (js_dir / "node_modules/jsdom").exists():
        setup = subprocess.run(["npm", "ci", "--prefix", str(js_dir)], capture_output=True, text=True, timeout=180)
        assert setup.returncode == 0, setup.stderr
    result = subprocess.run(
        ["node", str(ROOT / "tests/js/run-reddit-recovery.mjs")],
        cwd=ROOT, capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Reddit recovery UI workflow PASS" in result.stdout
