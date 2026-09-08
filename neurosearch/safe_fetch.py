"""Rung J1 — `safe_fetch()`: the ONE network boundary for ordinary URL fetching (web pages, documents, PDFs).

Neuro Search follows user-supplied URLs from a machine that can also see local services, so every fetch — the initial
URL and every redirect hop — goes through the same pipeline:

    parse → http/https only → no userinfo → normalise host/port → resolve A + AAAA → reject if ANY answer is unsafe
      → connect to the VALIDATED, PINNED address (Host header and TLS SNI/verification keep the original hostname)
      → stream the body under hard limits (wire bytes, decoded bytes, redirects, total wall clock)

The pinned connection closes the DNS-rebinding / TOCTOU gap: there is no second, uncontrolled resolution between
validation and the socket. Redirects are followed manually and revalidated. No automatic retries. No environment
proxies (trust_env=False equivalent: the stdlib client below never consults proxy variables).

Blocked destinations: loopback, RFC1918/private, link-local (incl. 169.254.169.254 metadata), unspecified, multicast,
reserved/non-global, the IPv6 equivalents, IPv4-mapped IPv6, metadata hostnames. Limits are centralised in LIMITS by
content class (HTML pages vs documents) so callers never invent their own. A blocked fetch raises FetchBlocked with a
typed `reason` (recorded as a validation event + counter for Health) and a user-safe message that never names the
internal address it refused.

yt-dlp (media.py) is NOT routed through here: it speaks to media platforms with its own extractor/cookie/redirect logic
and is documented as a separate, deliberate exception.

Test hooks: RESOLVER (host, port) → [ip...] and CONNECT (ip, port, timeout) → socket let a deterministic local harness
prove the boundary (public-looking name → local server; DNS answer changing public → private after validation cannot
rebind the connection) without probing any real network.
"""
from __future__ import annotations

import http.client
import ipaddress
import logging
import os
import socket
import ssl
import time
import zlib
from dataclasses import dataclass, field
from typing import Any, Callable
from urllib.parse import urljoin, urlsplit, urlunsplit

log = logging.getLogger(__name__)

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36 NeuroSearch/1.0"
HEADERS = {
    "User-Agent": UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,application/pdf;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate",          # never br/zstd: we decode only what we can bound
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document", "Sec-Fetch-Mode": "navigate", "Sec-Fetch-Site": "none", "Sec-Fetch-User": "?1",
}


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, "") or default)
    except ValueError:
        return default


# centralised limits by content class — callers choose a class, never a number
LIMITS: dict[str, dict[str, Any]] = {
    # ordinary web pages: small ceilings; a 5 MB HTML page is already suspicious
    "html": {"max_wire_bytes": _env_int("NEUROSEARCH_FETCH_HTML_MAX_BYTES", 5 * 1024 * 1024), "max_decoded_bytes": _env_int("NEUROSEARCH_FETCH_HTML_MAX_DECODED", 10 * 1024 * 1024)},
    # documents (PDF/DOCX/etc.) linked from pages or pasted directly
    "document": {"max_wire_bytes": _env_int("NEUROSEARCH_FETCH_DOC_MAX_BYTES", 60 * 1024 * 1024), "max_decoded_bytes": _env_int("NEUROSEARCH_FETCH_DOC_MAX_DECODED", 120 * 1024 * 1024)},
}
MAX_REDIRECTS = _env_int("NEUROSEARCH_FETCH_MAX_REDIRECTS", 5)
CONNECT_TIMEOUT_S = 10.0
READ_TIMEOUT_S = 20.0
TOTAL_DEADLINE_S = float(os.environ.get("NEUROSEARCH_FETCH_TOTAL_S", "") or 60.0)
CHUNK = 64 * 1024
DOCUMENT_TYPES = ("application/pdf", "application/msword", "application/vnd.openxmlformats", "application/vnd.ms-", "application/epub", "application/rtf", "text/csv")
METADATA_HOSTS = {"metadata.google.internal", "metadata", "metadata.internal", "instance-data", "instance-data.ec2.internal", "169.254.169.254", "fd00:ec2::254", "100.100.100.200"}

# ------------------------------------------------------------------ hooks (tests replace these; production uses the real ones)
RESOLVER: Callable[[str, int], list[str]] | None = None      # (host, port) -> list of ip strings
CONNECT: Callable[[str, int, float], socket.socket] | None = None   # (ip, port, timeout) -> connected socket


class FetchBlocked(RuntimeError):
    """The boundary refused the fetch. `reason` is typed (for Health/job diagnostics); str() is safe for the UI."""
    REASONS = ("scheme", "userinfo", "host", "port", "dns", "private_address", "metadata", "redirect_limit", "redirect_target",
               "too_large", "decoded_too_large", "encoding", "timeout", "connect", "status", "protocol")

    def __init__(self, reason: str, message: str, host: str | None = None, hop: int = 0) -> None:
        assert reason in self.REASONS, reason
        super().__init__(message)
        self.reason, self.host, self.hop = reason, host, hop


@dataclass
class FetchResult:
    url: str                       # final URL after redirects
    status: int
    content_type: str
    body: bytes
    headers: dict[str, str] = field(default_factory=dict)
    hops: int = 0
    pinned: list[str] = field(default_factory=list)   # the validated address connected to at each hop (diagnostics; never shown to users)
    content_class: str = "html"


# ------------------------------------------------------------------ validation

def is_unsafe_ip(ip: str) -> str | None:
    """None when the address is a public unicast address; else the typed reason."""
    try:
        a = ipaddress.ip_address(ip)
    except ValueError:
        return "host"
    if isinstance(a, ipaddress.IPv6Address) and a.ipv4_mapped is not None:
        a = a.ipv4_mapped                                       # ::ffff:127.0.0.1 is 127.0.0.1
    if isinstance(a, ipaddress.IPv6Address) and a.sixtofour is not None:
        a = a.sixtofour
    if str(a) in ("169.254.169.254", "100.100.100.200") or (isinstance(a, ipaddress.IPv6Address) and a == ipaddress.ip_address("fd00:ec2::254")):
        return "metadata"
    if a.is_loopback or a.is_private or a.is_link_local or a.is_unspecified or a.is_multicast or a.is_reserved or not a.is_global:
        return "private_address"
    return None


def normalise(url: str, hop: int = 0) -> tuple[str, str, str, int, str]:
    """→ (normalised url, scheme, host, port, path+query). Raises FetchBlocked for anything outside http(s) to a plain host."""
    try:
        parts = urlsplit(url.strip())
    except ValueError as e:
        raise FetchBlocked("host", "That address could not be parsed.", hop=hop) from e
    scheme = (parts.scheme or "").lower()
    if scheme not in ("http", "https"):
        raise FetchBlocked("scheme", f"Only http and https links can be fetched (got '{scheme or 'none'}').", hop=hop)
    if parts.username is not None or parts.password is not None or "@" in (parts.netloc or ""):
        raise FetchBlocked("userinfo", "Links with embedded credentials are not fetched.", hop=hop)
    host = (parts.hostname or "").strip().rstrip(".").lower()
    if not host:
        raise FetchBlocked("host", "That link has no host name.", hop=hop)
    try:
        host.encode("idna")
    except UnicodeError as e:
        raise FetchBlocked("host", "That link's host name is not valid.", hop=hop) from e
    try:
        port = parts.port
    except ValueError as e:
        raise FetchBlocked("port", "That link's port is not valid.", hop=hop) from e
    if port is None:
        port = 443 if scheme == "https" else 80
    if not (1 <= port <= 65535):
        raise FetchBlocked("port", "That link's port is not valid.", hop=hop)
    if host in METADATA_HOSTS or (host.endswith(".internal") and "metadata" in host):
        raise FetchBlocked("metadata", "That address cannot be fetched (private or internal network).", host=host, hop=hop)
    if host == "localhost" or host.endswith(".localhost") or host.endswith(".local"):
        raise FetchBlocked("private_address", "That address cannot be fetched (private or internal network).", host=host, hop=hop)
    path = parts.path or "/"
    target = path + (f"?{parts.query}" if parts.query else "")
    netloc = f"[{host}]" if ":" in host else host
    if (scheme == "http" and port != 80) or (scheme == "https" and port != 443):
        netloc += f":{port}"
    return urlunsplit((scheme, netloc, path, parts.query, "")), scheme, host, port, target


def resolve(host: str, port: int, hop: int = 0) -> list[str]:
    """Every A/AAAA answer for the host (a literal address resolves to itself). Any unsafe answer blocks the fetch."""
    literal = host
    try:
        # inet_aton accepts every shorthand a browser would (127.1, 0177.0.0.1, 2130706433): canonicalise BEFORE classifying
        if host and host[0].isdigit() and ":" not in host:
            literal = socket.inet_ntoa(socket.inet_aton(host))
    except OSError:
        pass
    try:
        ipaddress.ip_address(literal)
        answers = [literal]
    except ValueError:
        try:
            if RESOLVER is not None:
                answers = list(RESOLVER(host, port))
            else:
                seen = {ai[4][0] for ai in socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)}
                answers = sorted(seen, key=lambda a: (":" in a, a))    # IPv4 first for connectivity; ALL answers are validated
        except (socket.gaierror, OSError) as e:
            raise FetchBlocked("dns", "That host name could not be resolved.", host=host, hop=hop) from e
    if not answers:
        raise FetchBlocked("dns", "That host name could not be resolved.", host=host, hop=hop)
    for ip in answers:
        why = is_unsafe_ip(ip)
        if why:
            raise FetchBlocked(why, "That address cannot be fetched (private or internal network).", host=host, hop=hop)
    return answers


# ------------------------------------------------------------------ the pinned connection

def _connect(ip: str, port: int, timeout: float) -> socket.socket:
    if CONNECT is not None:
        return CONNECT(ip, port, timeout)
    return socket.create_connection((ip, port), timeout=timeout)


class _PinnedHTTP(http.client.HTTPConnection):
    """HTTP to a validated address; the Host header is the original hostname."""

    def __init__(self, host: str, port: int, pinned_ip: str, timeout: float) -> None:
        super().__init__(host, port, timeout=timeout)
        self.pinned_ip = pinned_ip

    def connect(self) -> None:
        self.sock = _connect(self.pinned_ip, self.port, self.timeout)


class _PinnedHTTPS(http.client.HTTPSConnection):
    """HTTPS to a validated address; TLS SNI and certificate verification use the original hostname."""

    def __init__(self, host: str, port: int, pinned_ip: str, timeout: float, context: ssl.SSLContext | None = None) -> None:
        super().__init__(host, port, timeout=timeout, context=context or ssl.create_default_context())
        self.pinned_ip = pinned_ip

    def connect(self) -> None:
        sock = _connect(self.pinned_ip, self.port, self.timeout)
        self.sock = self._context.wrap_socket(sock, server_hostname=self.host)


# ------------------------------------------------------------------ the fetch

def content_class_of(content_type: str, url: str) -> str:
    ct = (content_type or "").lower()
    if any(ct.startswith(t) for t in DOCUMENT_TYPES) or url.lower().split("?")[0].endswith((".pdf", ".docx", ".doc", ".epub", ".rtf", ".csv", ".xlsx")):
        return "document"
    return "html"


def _record_block(e: FetchBlocked, url: str) -> None:
    try:
        from . import db
        db.validation_event("fetch_blocked", {"reason": e.reason, "host": e.host, "hop": e.hop}, )
        db.kv_bump("evidence:fetch_blocked")
    except Exception:  # noqa: BLE001
        pass
    log.warning("fetch blocked (%s) at hop %d for %s", e.reason, e.hop, (e.host or url)[:80])


def safe_fetch(url: str, *, content_class: str | None = None, max_redirects: int | None = None, deadline_s: float | None = None,
               headers: dict[str, str] | None = None, method: str = "GET") -> FetchResult:
    """GET a public URL under the boundary. `content_class` fixes the limits up front ('html' | 'document'); when None the
    class is chosen from the response Content-Type (documents get the larger ceiling, pages the smaller)."""
    t_start = time.monotonic()
    deadline = t_start + (deadline_s or TOTAL_DEADLINE_S)
    hops_max = MAX_REDIRECTS if max_redirects is None else max_redirects
    current, hop, pinned = url, 0, []
    hdrs = {k: v for k, v in {**HEADERS, **(headers or {})}.items() if v is not None}   # a None value drops a default header
    try:
        while True:
            norm, scheme, host, port, target = normalise(current, hop)
            answers = resolve(host, port, hop)
            ip = answers[0]                                     # validated; every answer passed, we pin the first
            pinned.append(ip)
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise FetchBlocked("timeout", "That page took too long to fetch.", host=host, hop=hop)
            conn_cls = _PinnedHTTPS if scheme == "https" else _PinnedHTTP
            conn = conn_cls(host, port, ip, timeout=min(CONNECT_TIMEOUT_S, remaining))
            try:
                try:
                    conn.request(method, target, headers=hdrs)
                    conn.sock.settimeout(min(READ_TIMEOUT_S, max(0.1, deadline - time.monotonic())))
                    resp = conn.getresponse()
                except (socket.timeout, TimeoutError) as e:
                    raise FetchBlocked("timeout", "That page took too long to respond.", host=host, hop=hop) from e
                except (OSError, ssl.SSLError, http.client.HTTPException) as e:
                    raise FetchBlocked("connect", "That page could not be reached.", host=host, hop=hop) from e
                status = resp.status
                rh = {k.lower(): v for k, v in resp.getheaders()}
                if status in (301, 302, 303, 307, 308):
                    loc = rh.get("location")
                    if not loc:
                        raise FetchBlocked("redirect_target", "That page redirected nowhere.", host=host, hop=hop)
                    if hop >= hops_max:
                        raise FetchBlocked("redirect_limit", f"That page redirected more than {hops_max} times.", host=host, hop=hop)
                    resp.close()
                    current = urljoin(norm, loc)
                    hop += 1
                    if status == 303:
                        method = "GET"
                    continue                                    # the new target goes through the same validation
                ctype = rh.get("content-type", "").lower()
                cls = content_class or content_class_of(ctype, norm)
                lim = LIMITS[cls]
                cl = rh.get("content-length")
                if cl is not None:
                    try:
                        if int(cl) > lim["max_wire_bytes"]:
                            raise FetchBlocked("too_large", f"That {'document' if cls == 'document' else 'page'} is too large to import ({int(cl) // (1024 * 1024)} MB).", host=host, hop=hop)
                    except ValueError:
                        pass                                    # untrusted anyway: the stream counts
                body = _read_bounded(resp, conn.sock, rh.get("content-encoding", "").lower(), lim, deadline, host, hop, cls)
                return FetchResult(url=norm, status=status, content_type=ctype, body=body, headers=rh, hops=hop, pinned=pinned, content_class=cls)
            finally:
                try:
                    conn.close()
                except Exception:  # noqa: BLE001
                    pass
    except FetchBlocked as e:
        _record_block(e, url)
        raise


def _read_bounded(resp: Any, sock: Any, encoding: str, lim: dict[str, Any], deadline: float, host: str, hop: int, cls: str) -> bytes:
    """Stream the body counting wire bytes AND decoded bytes; a chunked response with no Content-Length is bounded the
    same way; gzip/deflate are decoded incrementally with a ceiling (a decompression bomb stops at the ceiling)."""
    if encoding and encoding not in ("gzip", "deflate", "identity"):
        raise FetchBlocked("encoding", "That page used an unsupported transfer encoding.", host=host, hop=hop)
    dec = None
    if encoding == "gzip":
        dec = zlib.decompressobj(16 + zlib.MAX_WBITS)
    elif encoding == "deflate":
        dec = zlib.decompressobj()
    wire = 0
    out = bytearray()
    what = "document" if cls == "document" else "page"
    while True:
        if time.monotonic() > deadline:
            raise FetchBlocked("timeout", "That page took too long to download.", host=host, hop=hop)
        try:
            if sock is not None:
                sock.settimeout(min(READ_TIMEOUT_S, max(0.1, deadline - time.monotonic())))
            chunk = resp.read(CHUNK)
        except (socket.timeout, TimeoutError) as e:
            raise FetchBlocked("timeout", "That page took too long to download.", host=host, hop=hop) from e
        except (OSError, http.client.HTTPException) as e:
            raise FetchBlocked("protocol", "That page's response was cut off.", host=host, hop=hop) from e
        if not chunk:
            break
        wire += len(chunk)
        if wire > lim["max_wire_bytes"]:
            raise FetchBlocked("too_large", f"That {what} is too large to import (over {lim['max_wire_bytes'] // (1024 * 1024)} MB).", host=host, hop=hop)
        if dec is not None:
            room = lim["max_decoded_bytes"] - len(out) + 1
            try:
                piece = dec.decompress(chunk, room)
            except zlib.error as e:
                raise FetchBlocked("encoding", "That page's compressed response was corrupt.", host=host, hop=hop) from e
            out += piece
            if len(out) > lim["max_decoded_bytes"] or dec.unconsumed_tail:
                raise FetchBlocked("decoded_too_large", f"That {what} expands to more than {lim['max_decoded_bytes'] // (1024 * 1024)} MB and was not imported.", host=host, hop=hop)
        else:
            out += chunk
            if len(out) > lim["max_decoded_bytes"]:
                raise FetchBlocked("decoded_too_large", f"That {what} is too large to import.", host=host, hop=hop)
    if dec is not None:
        try:
            tail = dec.flush()
        except zlib.error as e:
            raise FetchBlocked("encoding", "That page's compressed response was corrupt.", host=host, hop=hop) from e
        out += tail
        if len(out) > lim["max_decoded_bytes"]:
            raise FetchBlocked("decoded_too_large", f"That {what} expands to more than {lim['max_decoded_bytes'] // (1024 * 1024)} MB and was not imported.", host=host, hop=hop)
    return bytes(out)
