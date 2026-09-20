"""S74 — extension authentication failures are actionable, not silent.

The extension's background worker intentionally suppresses ordinary offline polling failures. 401/403 is
different: it means the saved credential needs attention, so that distinction must remain visible to the popup.
"""

import json
import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
POPUP = (ROOT / "extension" / "popup.js").read_text()
BACKGROUND = (ROOT / "extension" / "background.js").read_text()
RUN = ROOT / "tests" / "js" / "run-extension-auth.mjs"


def _run(command: str) -> dict:
    node = shutil.which("node")
    if not node:
        pytest.skip("no JavaScript engine available for the extension auth runtime gate")
    proc = subprocess.run([node, str(RUN), command], capture_output=True, text=True, timeout=30)
    if proc.returncode:
        pytest.fail(f"run-extension-auth.mjs {command!r} exited {proc.returncode}:\n{proc.stderr}")
    return json.loads(proc.stdout)


def test_popup_translates_auth_failures_and_surfaces_background_auth_state():
    assert "function authMessage(status)" in POPUP
    assert "status !== 401 && status !== 403" in POPUP
    assert "e.authMessage = authMessage(r.status)" in POPUP
    assert "savedAuthError" in POPUP
    assert "Open Settings → Change app address / password" in POPUP


def test_background_marks_auth_failures_but_keeps_network_polling_quiet():
    assert "e.auth = r.status === 401 || r.status === 403" in BACKGROUND
    assert "if (e.auth) await chrome.storage.local.set({ authError: e.message" in BACKGROUND
    assert "if (!r.ok) throw new Error" not in BACKGROUND


@pytest.mark.parametrize("command, status", [("popup-401", 401), ("popup-403", 403)])
def test_popup_api_executes_actionable_auth_error_for_both_refusals(command, status):
    result = _run(command)
    assert result["threw"] is True
    assert result["status"] == status
    assert result["authMessage"] == result["message"]
    assert "Change app address / password" in result["message"]


def test_popup_keeps_non_auth_server_error_distinct():
    result = _run("popup-500")
    assert result == {"threw": True, "status": 500, "authMessage": None, "message": "server 500"}


def test_popup_clears_a_recovered_auth_error_after_projects_load():
    """A saved 401/403 must disappear once a real authenticated request succeeds, rather than falsely telling
    the user their now-working password is still rejected."""
    assert _run("popup-recovery") == {"storedAuthError": None, "pageMessage": ""}


@pytest.mark.parametrize("command, status", [("background-401", 401), ("form-403", 403)])
def test_background_api_and_upload_mark_auth_refusals_at_runtime(command, status):
    result = _run(command)
    assert result["threw"] is True
    assert result["status"] == status
    assert result["auth"] is True
    assert "saved app password" in result["message"]


def test_background_poll_persists_only_auth_refusals_for_popup_recovery():
    refused = _run("poll-401")
    assert len(refused["writes"]) == 1
    assert "authError" in refused["writes"][0]
    ordinary_failure = _run("poll-500")
    assert ordinary_failure["writes"] == []
