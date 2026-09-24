"""P11 EA-9: the tunnel LaunchAgent wrapper — per-profile identity, and not starting before Neuro.

Two failures on 2026-09-23 motivated every assertion here, and both were silent:

1. `CONTROL_PLANE_TUNNEL_ID` in the environment beats the profile's own `tunnel_id`. Because the wrapper loads
   all of `.env`, Kyle's value reached Gio's process and her daemon served HIS tunnel while `--profile gio` was
   on its command line.
2. tunnel-client fetches Neuro's protected-resource metadata once at startup and never retries. Kyle's tunnel
   started 2m31s before Neuro, cached the failure, and sat at `/readyz` 503 for two and a half hours.

A third is guarded pre-emptively: `tunnel-client init` knows nothing about Neuro, so a re-init drops the
`X-Neuro-Tunnel` header and Neuro silently falls back to the FIRST configured resource — someone else's.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))
import tunnel_agent as ta  # noqa: E402

PROFILE = """config_version: 1
control_plane:
  tunnel_id: "tunnel_abc123"
  api_key: "env:CONTROL_PLANE_API_KEY"
health:
  listen_addr: "127.0.0.1:8099"
mcp:
  server_urls:
    - channel: main
      url: "http://localhost:8000/ext/mcp/"
"""


@pytest.fixture
def profile_dir(tmp_path, monkeypatch):
    d = tmp_path / "tunnel-client"
    d.mkdir()
    (d / "p.yaml").write_text(PROFILE)
    monkeypatch.setattr(ta, "PROFILE_DIR", d)
    return d


def test_the_header_is_added_corrected_and_never_rewritten_for_nothing(profile_dir):
    p = profile_dir / "p.yaml"

    assert ta.ensure_tunnel_header("p") == "tunnel_abc123"
    text = p.read_text()
    assert 'X-Neuro-Tunnel: "tunnel_abc123"' in text
    assert "extra_headers:" in text and "discovery_extra_headers:" in text
    assert "server_urls:" in text and "http://localhost:8000/ext/mcp/" in text   # nothing else disturbed

    unchanged = p.read_text()                        # idempotent: a second call must not touch the file
    assert ta.ensure_tunnel_header("p") == "tunnel_abc123"
    assert p.read_text() == unchanged

    # only the HEADER goes stale; tunnel_id stays put, which is what a re-pointed profile actually looks like
    p.write_text(unchanged.replace('X-Neuro-Tunnel: "tunnel_abc123"', 'X-Neuro-Tunnel: "tunnel_STALE"'))
    assert 'tunnel_id: "tunnel_abc123"' in p.read_text()
    assert ta.ensure_tunnel_header("p") == "tunnel_abc123"
    assert p.read_text().count('X-Neuro-Tunnel: "tunnel_abc123"') == 2
    assert "tunnel_STALE" not in p.read_text()


def test_a_profile_that_cannot_carry_the_header_is_refused_not_guessed(profile_dir):
    assert ta.ensure_tunnel_header("does-not-exist") is None
    (profile_dir / "noid.yaml").write_text("config_version: 1\nmcp:\n  server_urls: []\n")
    assert ta.ensure_tunnel_header("noid") is None
    (profile_dir / "nomcp.yaml").write_text('config_version: 1\ncontrol_plane:\n  tunnel_id: "tunnel_x1"\n')
    assert ta.ensure_tunnel_header("nomcp") is None


def test_the_agent_waits_for_neuro_instead_of_caching_a_failed_discovery(monkeypatch):
    import urllib.error

    calls = []

    class Answer:
        def read(self, _n=None):
            return b"x"

    def refuse_then_answer(url, timeout=None):
        calls.append(url)
        if len(calls) < 3:
            raise OSError("connection refused")
        return Answer()

    monkeypatch.setattr(ta.urllib.request, "urlopen", refuse_then_answer)
    monkeypatch.setattr(ta.time, "sleep", lambda _s: None)
    assert ta.wait_for_neuro("http://127.0.0.1:8000/", 60) is True
    assert len(calls) == 3

    def never(url, timeout=None):
        raise OSError("connection refused")

    monkeypatch.setattr(ta.urllib.request, "urlopen", never)
    assert ta.wait_for_neuro("http://127.0.0.1:8000/", 0) is False   # gives up -> EX_TEMPFAIL -> KeepAlive retries

    def http_error(url, timeout=None):
        raise urllib.error.HTTPError(url, 401, "Unauthorized", {}, None)

    monkeypatch.setattr(ta.urllib.request, "urlopen", http_error)
    assert ta.wait_for_neuro("http://127.0.0.1:8000/", 5) is True    # answering at all is enough; 401 is Neuro
