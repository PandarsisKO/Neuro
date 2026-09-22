"""Rung J1 — the network boundary, proven mechanically against a local deterministic HTTP server.

No real network, no probing of any address: the RESOLVER hook answers DNS the way each scenario needs (a public-looking
name that maps to the test server, a name whose answer flips from public to private after validation), and the CONNECT
hook records which address safe_fetch asked to connect to — then connects to the local server so the round trip completes.
The server on 127.0.0.1 is only ever reached THROUGH the hook: a direct 127.0.0.1 URL is blocked, as it must be.
"""
from __future__ import annotations

import gzip
import os
import socket
import tempfile
import threading
import time
import zlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

os.environ.setdefault("NEUROSEARCH_DATA_DIR", tempfile.mkdtemp(prefix="ns_sf_"))
os.environ["NEUROSEARCH_FAKE_AI"] = "1"

import pytest  # noqa: E402

from neurosearch import db, safe_fetch as SF  # noqa: E402
from neurosearch.safe_fetch import FetchBlocked, safe_fetch  # noqa: E402

PUBLIC_A = "93.184.216.34"          # public unicast (documentation site); never contacted: CONNECT redirects to the local server
PUBLIC_B = "8.8.8.8"
BOMB = gzip.compress(b"\0" * (30 * 1024 * 1024), compresslevel=6)         # ~30 KB on the wire → 30 MB decoded (built once)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):  # noqa: D401
        pass

    def _send(self, status: int, body: bytes = b"", ctype: str = "text/html; charset=utf-8", extra: dict | None = None, length: bool = True) -> None:
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        if length:
            self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if body:
            self.wfile.write(body)

    def do_GET(self):  # noqa: C901
        p = self.path
        host = self.headers.get("Host", "")
        if p == "/html":
            self._send(200, f"<html><head><title>Public page</title></head><body>{'hello world. ' * 40}<p>Host was {host}</p></body></html>".encode())
        elif p == "/pdf":
            self._send(200, b"%PDF-1.4 " + b"x" * 5000, ctype="application/pdf")
        elif p == "/redirect-private":
            self._send(302, extra={"Location": "http://127.0.0.1:1/secret"})
        elif p == "/redirect-metadata":
            self._send(302, extra={"Location": "http://169.254.169.254/latest/meta-data/"})
        elif p == "/redirect-scheme":
            self._send(302, extra={"Location": "file:///etc/passwd"})
        elif p.startswith("/loop"):
            n = int(p.split("/loop")[1] or 0)
            self._send(302, extra={"Location": f"http://public.test/loop{n + 1}"})
        elif p == "/redirect-ok":
            self._send(301, extra={"Location": "http://public.test/html"})
        elif p == "/redirect-rebind":
            self._send(302, extra={"Location": "http://rebind.test/html"})
        elif p == "/big-length":
            self._send(200, b"", extra={"Content-Length": str(500 * 1024 * 1024)}, length=False)
        elif p == "/chunked-big":
            self.send_response(200); self.send_header("Content-Type", "text/html"); self.send_header("Transfer-Encoding", "chunked"); self.end_headers()
            piece = b"a" * 65536
            for _ in range(200):                                    # 12.8 MB, no Content-Length
                try:
                    self.wfile.write(f"{len(piece):x}\r\n".encode() + piece + b"\r\n")
                except (BrokenPipeError, ConnectionResetError):
                    return
            self.wfile.write(b"0\r\n\r\n")
        elif p == "/gzip-bomb":
            self._send(200, BOMB, extra={"Content-Encoding": "gzip"})
        elif p == "/gzip-ok":
            self._send(200, gzip.compress(b"<html><body>" + b"fine " * 500 + b"</body></html>"), extra={"Content-Encoding": "gzip"})
        elif p == "/deflate-ok":
            self._send(200, zlib.compress(b"<html><body>" + b"deflated " * 300 + b"</body></html>"), extra={"Content-Encoding": "deflate"})
        elif p == "/brotli":
            self._send(200, b"xxxx", extra={"Content-Encoding": "br"})
        elif p == "/slow":
            self.send_response(200); self.send_header("Content-Type", "text/html"); self.send_header("Content-Length", "20"); self.end_headers()
            self.wfile.write(b"0123456789"); self.wfile.flush()
            time.sleep(3.0)
            try:
                self.wfile.write(b"0123456789")
            except (BrokenPipeError, ConnectionResetError):
                pass
        elif p == "/forbidden":
            self._send(403, b"nope")
        else:
            self._send(404, b"not found")


@pytest.fixture(scope="module")
def server():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    srv.daemon_threads = True
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield srv
    srv.shutdown()


@pytest.fixture
def harness(server, monkeypatch):
    """DNS + connect hooks: public.test → PUBLIC_A; the CONNECT hook records the pinned address it was asked for and
    connects to the local server instead. Everything else resolves for real (and is blocked by the boundary)."""
    connects: list[tuple[str, int]] = []
    answers = {"public.test": [PUBLIC_A], "dual.test": [PUBLIC_A, "2606:2800:220:1:248:1893:25c8:1946"], "mixed.test": [PUBLIC_A, "10.0.0.7"],
               "sixloop.test": ["::1"], "sixlink.test": ["fe80::1"], "sixula.test": ["fd12::1"], "mapped.test": ["::ffff:127.0.0.1"], "mapped10.test": ["::ffff:10.1.2.3"],
               "meta.test": ["169.254.169.254"], "metav6.test": ["fd00:ec2::254"]}
    rebind_calls = {"n": 0}

    def resolver(host, port):
        if host == "rebind.test":
            rebind_calls["n"] += 1
            return [PUBLIC_B] if rebind_calls["n"] == 1 else ["127.0.0.1"]     # public first, private afterwards
        if host in answers:
            return answers[host]
        raise socket.gaierror("no such host in the harness")

    def connect(ip, port, timeout):
        connects.append((ip, port))
        return socket.create_connection(server.server_address, timeout=timeout)

    monkeypatch.setattr(SF, "RESOLVER", resolver)
    monkeypatch.setattr(SF, "CONNECT", connect)
    monkeypatch.setattr(SF, "LIMITS", {"html": {"max_wire_bytes": 1024 * 1024, "max_decoded_bytes": 2 * 1024 * 1024},
                                       "document": {"max_wire_bytes": 3 * 1024 * 1024, "max_decoded_bytes": 6 * 1024 * 1024}})
    db.init_db()
    return {"connects": connects, "rebind_calls": rebind_calls}


def _blocked(url: str, **kw) -> FetchBlocked:
    with pytest.raises(FetchBlocked) as ei:
        safe_fetch(url, **kw)
    return ei.value


# ---------------------------------------------------------------- destinations that must never be contacted

@pytest.mark.parametrize("url,reason", [
    ("http://127.0.0.1/", "private_address"), ("http://localhost/", "private_address"), ("http://127.1/", "private_address"),
    ("http://10.0.0.1/", "private_address"), ("http://172.16.5.5/", "private_address"), ("http://192.168.1.1/", "private_address"),
    ("http://0.0.0.0/", "private_address"), ("http://224.0.0.1/", "private_address"), ("http://240.0.0.1/", "private_address"),
    ("http://[::1]/", "private_address"), ("http://[fe80::1]/", "private_address"), ("http://[fd12::1]/", "private_address"), ("http://[::]/", "private_address"),
    ("http://[::ffff:127.0.0.1]/", "private_address"), ("http://[::ffff:10.1.2.3]/", "private_address"), ("http://[::ffff:c0a8:0101]/", "private_address"),
    ("http://169.254.169.254/latest/meta-data/", "metadata"), ("http://[fd00:ec2::254]/", "metadata"), ("http://metadata.google.internal/", "metadata"), ("http://100.100.100.200/", "metadata"),
    ("http://sixloop.test/", "private_address"), ("http://sixlink.test/", "private_address"), ("http://sixula.test/", "private_address"),
    ("http://mapped.test/", "private_address"), ("http://mapped10.test/", "private_address"), ("http://meta.test/", "metadata"), ("http://metav6.test/", "metadata"),
    ("http://mixed.test/", "private_address"),                                  # ONE private answer among public ones blocks the whole host
])
def test_private_and_metadata_destinations_are_blocked(harness, url, reason):
    e = _blocked(url)
    assert e.reason == reason and harness["connects"] == []                     # nothing was ever connected to
    assert "127" not in str(e) and "10." not in str(e) and "169.254" not in str(e)  # the user-facing message names no internal address


@pytest.mark.parametrize("url,reason", [
    ("file:///etc/passwd", "scheme"), ("ftp://public.test/x", "scheme"), ("gopher://public.test/", "scheme"), ("data:text/html,hi", "scheme"),
    ("javascript:alert(1)", "scheme"), ("public.test/html", "scheme"), ("http://user:pw@public.test/", "userinfo"), ("http://public.test@127.0.0.1/", "userinfo"),
    ("http:///html", "host"), ("http://public.test:99999/", "port"), ("http://public.test:abc/", "port"), ("http://nosuch.test/", "dns"),
])
def test_bad_urls_are_blocked_before_any_network(harness, url, reason):
    e = _blocked(url)
    assert e.reason == reason and harness["connects"] == []


# ---------------------------------------------------------------- the pinned connection and redirects

def test_public_html_and_pdf_succeed_through_the_pinned_address(harness):
    r = safe_fetch("http://public.test/html")
    assert r.status == 200 and b"Public page" in r.body and "Host was public.test" in r.body.decode()   # Host header = original hostname
    assert r.pinned == [PUBLIC_A] and harness["connects"] == [(PUBLIC_A, 80)] and r.content_class == "html" and r.hops == 0
    r2 = safe_fetch("http://public.test/pdf")
    assert r2.content_class == "document" and r2.body.startswith(b"%PDF") and r2.content_type.startswith("application/pdf")
    r3 = safe_fetch("http://public.test/gzip-ok")
    assert b"fine fine" in r3.body
    r4 = safe_fetch("http://public.test/deflate-ok")
    assert b"deflated" in r4.body


def test_redirect_to_private_metadata_or_other_scheme_is_blocked_at_the_hop(harness):
    for path, reason in (("/redirect-private", "private_address"), ("/redirect-metadata", "metadata"), ("/redirect-scheme", "scheme")):
        e = _blocked(f"http://public.test{path}")
        assert e.reason == reason and e.hop == 1
    assert all(c == (PUBLIC_A, 80) for c in harness["connects"])                # only the public hop was ever connected


def test_redirect_chain_limit_and_valid_redirect(harness):
    e = _blocked("http://public.test/loop0", max_redirects=3)
    assert e.reason == "redirect_limit" and e.hop == 3
    r = safe_fetch("http://public.test/redirect-ok")
    assert r.status == 200 and r.hops == 1 and r.url == "http://public.test/html" and r.pinned == [PUBLIC_A, PUBLIC_A]


def test_dns_rebinding_cannot_move_the_connection(harness):
    """rebind.test answers PUBLIC_B the first time and 127.0.0.1 afterwards. The connection MUST go to the address that
    was validated — the resolver is consulted exactly once per hop and the socket is opened to that answer."""
    r = safe_fetch("http://rebind.test/html")
    assert r.status == 200 and harness["rebind_calls"]["n"] == 1                # one resolution, no re-resolution before connect
    assert harness["connects"] == [(PUBLIC_B, 80)] and r.pinned == [PUBLIC_B]  # connected to the validated public answer, never to 127.0.0.1
    # a redirect back to the same name re-resolves (second answer: private) and is blocked — the hop is validated afresh
    harness["connects"].clear()
    e = _blocked("http://public.test/redirect-rebind")
    assert e.reason == "private_address" and e.hop == 1 and harness["connects"] == [(PUBLIC_A, 80)]


# ---------------------------------------------------------------- size, decompression, time

def test_oversized_content_length_is_rejected_before_reading(harness):
    e = _blocked("http://public.test/big-length")
    assert e.reason == "too_large" and "MB" in str(e)


def test_chunked_body_beyond_the_limit_is_cut_off(harness):
    e = _blocked("http://public.test/chunked-big")
    assert e.reason == "too_large"


def test_decompression_bomb_stops_at_the_decoded_ceiling(harness):
    e = _blocked("http://public.test/gzip-bomb")
    assert e.reason == "decoded_too_large"


def test_unsupported_encoding_is_refused(harness):
    e = _blocked("http://public.test/brotli")
    assert e.reason == "encoding"


def test_slow_body_hits_the_total_deadline(harness):
    t0 = time.time()
    e = _blocked("http://public.test/slow", deadline_s=1.0)
    assert e.reason == "timeout" and time.time() - t0 < 2.5


def test_limits_are_central_and_per_content_class(harness, monkeypatch):
    monkeypatch.setitem(SF.LIMITS, "document", {"max_wire_bytes": 100, "max_decoded_bytes": 100})
    assert _blocked("http://public.test/pdf").reason == "too_large"            # the document class now caps at 100 bytes…
    assert safe_fetch("http://public.test/html").status == 200                # …the html class is unaffected
    assert _blocked("http://public.test/html", content_class="document").reason == "too_large"   # a caller can pin the class, never a number


# ---------------------------------------------------------------- diagnostics + callers

def test_blocked_fetches_are_recorded_for_health_without_leaking_addresses(harness):
    before = int(db.kv_get("evidence:fetch_blocked") or 0)
    _blocked("http://192.168.0.9/admin")
    _blocked("http://public.test/redirect-private")
    assert int(db.kv_get("evidence:fetch_blocked") or 0) == before + 2
    rows = db.connect().execute("SELECT detail FROM validation_events WHERE kind='fetch_blocked' ORDER BY id DESC LIMIT 2").fetchall()
    assert rows and all('"reason"' in r["detail"] for r in rows)


def test_webpage_fetch_goes_through_the_boundary(harness):
    from neurosearch import webpage
    with pytest.raises(FetchBlocked):
        webpage.fetch("http://127.0.0.1/")
    with pytest.raises(webpage.Blocked):
        webpage.fetch("http://public.test/forbidden")
    final, ctype, body = webpage.fetch("http://public.test/redirect-ok")
    assert final == "http://public.test/html" and ctype.startswith("text/html") and b"Public page" in body
    page = webpage.read_page("http://public.test/html")
    assert page["kind"] == "webpage" and page["title"] == "Public page"


def test_https_connection_pins_the_address_and_keeps_sni(monkeypatch):
    """The HTTPS path: the socket goes to the pinned address, the TLS handshake is told the ORIGINAL hostname."""
    import ssl
    seen = {}

    class Ctx(ssl.SSLContext):
        def wrap_socket(self, sock, server_hostname=None, **kw):
            seen["sni"] = server_hostname
            return sock

    monkeypatch.setattr(SF, "CONNECT", lambda ip, port, timeout: seen.setdefault("connect", (ip, port)) and socket.socket())
    c = SF._PinnedHTTPS("example.com", 443, PUBLIC_A, timeout=1.0, context=Ctx(ssl.PROTOCOL_TLS_CLIENT))
    c.connect()
    assert seen["connect"] == (PUBLIC_A, 443) and seen["sni"] == "example.com" and c.host == "example.com"
    c.close()


def test_unsafe_ip_classification():
    for ip in ("127.0.0.1", "10.0.0.1", "172.31.255.255", "192.168.0.1", "169.254.1.1", "0.0.0.0", "224.0.0.1", "255.255.255.255", "100.64.0.1", "198.18.0.1",
               "::1", "::", "fe80::1", "fc00::1", "fd00::1", "ff02::1", "::ffff:192.168.1.1", "2002:7f00:0001::1"):
        assert SF.is_unsafe_ip(ip) in ("private_address", "metadata"), ip
    assert SF.is_unsafe_ip("169.254.169.254") == "metadata" and SF.is_unsafe_ip("fd00:ec2::254") == "metadata"
    for ip in ("93.184.216.34", "8.8.8.8", "2606:4700::1111", "1.1.1.1"):
        assert SF.is_unsafe_ip(ip) is None, ip
    assert SF.is_unsafe_ip("not-an-ip") == "host"


# ---------------------------------------------------------------- P11: external file references use THIS boundary

def test_p11_file_references_are_fetched_only_through_the_boundary(harness):
    """Kyle's review, 2026-09-22: conversation sync must not become a second URL fetcher. The immediate fetch of a client
    file reference (intake._fetch_now) is driven here through the real harness — pinned resolution, private/link-local
    and metadata refusal, redirect re-validation at every hop, size ceilings — and then content-sniffed."""
    from neurosearch import access, intake
    data, ctype, final = intake._fetch_now({"url": "http://public.test/pdf"})
    assert data.startswith(b"%PDF") and intake._validate("x.pdf", data, ctype) == "pdf" and harness["connects"][-1] == (PUBLIC_A, 80)
    cases = {"http://public.test/redirect-private": "private", "http://public.test/redirect-metadata": "private",
             "http://public.test/redirect-scheme": "", "http://meta.test/x": "", "http://sixlink.test/x": "private",
             "http://mixed.test/x": "", "http://public.test/big-length": "MB", "http://127.0.0.1/x": "private"}
    for url, words in cases.items():
        with pytest.raises(access.AccessError) as e:
            intake._fetch_now({"url": url})
        assert e.value.code == "invalid" and "could not fetch" in e.value.message, url
        assert words.lower() in e.value.message.lower(), (url, e.value.message)
    # DNS rebinding cannot move the connection: the hop is pinned to the address that was validated
    data, _, _ = intake._fetch_now({"url": "http://public.test/redirect-rebind"})
    assert data and harness["connects"][-1][0] == PUBLIC_B
    assert all(ip == PUBLIC_A or ip == PUBLIC_B for ip, _ in harness["connects"])      # nothing private was ever connected


def test_p11_modules_have_no_second_fetch_path():
    import ast
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent / "neurosearch"
    fetchers = {"urllib.request", "httpx", "requests", "aiohttp", "urllib3", "http.client", "socket"}
    for name in ("intake.py", "convsync.py", "external.py", "idp.py", "oauth.py", "access.py", "mcp_external.py", "api_external.py", "facts.py"):
        tree = ast.parse((root / name).read_text())
        for node in ast.walk(tree):
            mods = [a.name for a in node.names] if isinstance(node, ast.Import) else ([node.module or ""] if isinstance(node, ast.ImportFrom) else [])
            for m in mods:
                assert m not in fetchers and not any(m.startswith(f + ".") for f in fetchers), f"{name} imports {m}"
    for name in ("intake.py", "idp.py", "oauth.py"):
        assert "safe_fetch.safe_fetch(" in (root / name).read_text(), name
