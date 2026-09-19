"""S74 — extension authentication failures are actionable, not silent.

The extension's background worker intentionally suppresses ordinary offline polling failures. 401/403 is
different: it means the saved credential needs attention, so that distinction must remain visible to the popup.
"""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
POPUP = (ROOT / "extension" / "popup.js").read_text()
BACKGROUND = (ROOT / "extension" / "background.js").read_text()


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
