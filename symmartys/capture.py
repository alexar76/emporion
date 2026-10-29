"""A web page as evidence: what a URL answered, when, from which server, anchored in Bitcoin.

An agent that buys on a seller's word needs to prove later what the page said: the price,
the delivery terms, the refund policy. SYMMARTYS fetches the URL once, as a browser would,
and returns a record of the answer — the final URL after redirects, every hop, the IP it
connected to, the HTTP status, the headers that matter, the TLS certificate the server
presented, and the SHA-256 of the body — together with the body itself when it is small
enough to carry. The record's own SHA-256 is anchored in Bitcoin through OpenTimestamps,
and the hub's signed receipt covers all of it.

This is the one capability that fetches a URL the caller chooses, so it does not go
through net.py's source allowlist. Instead:

  * http and https only, ports 80 and 443, no user:password@ in the URL;
  * every address the name resolves to must be a public (global) address — no loopback,
    private, link-local, CGNAT, multicast or reserved ranges — and the connection goes to
    the address that was checked (pinned), so DNS cannot be switched between check and
    connect; TLS is still verified against the host name (SNI);
  * every redirect hop is checked the same way, at most MAX_REDIRECTS;
  * the body is capped at MAX_BODY_BYTES and the whole capture at DEADLINE_S;
  * no cookies, no proxy from the environment, an honest User-Agent;
  * at most PER_HOST_PER_MINUTE captures of one host per minute, so SYMMARTYS is no one's
    load generator.

A page that answers 404 or 500 is a capture (the page said that at that moment); a host
that cannot be reached is not, and costs nothing (UpstreamError).
"""

from __future__ import annotations

import base64
import contextlib
import hashlib
import html
import ipaddress
import json
import re
import socket
import threading
import time
from collections import deque
from typing import Any, Iterator
from urllib.parse import urlsplit, urlunsplit

import httpx

from symmartys import timestamp
from symmartys.net import USER_AGENT, UpstreamError

MAX_URL = 2048
MAX_REDIRECTS = 5
MAX_BODY_BYTES = 5 << 20
#: A body up to this size is returned (base64) with the record; above it, only its hash.
MAX_RETURNED_BYTES = 512 << 10
DEADLINE_S = 25.0
PER_HOST_PER_MINUTE = 20
PORTS = {"http": 80, "https": 443}
#: Response headers kept in the record: the ones that say what the page was and when.
KEPT_HEADERS = ("content-type", "content-length", "content-language", "content-encoding",
                "last-modified", "etag", "date", "server", "cache-control", "expires", "age")
_TITLE = re.compile(rb"<title[^>]*>(.*?)</title\s*>", re.I | re.S)
_CHARSET = re.compile(r"charset=([\w.:-]+)", re.I)


class _HostLimiter:
    def __init__(self, per_minute: int):
        self.per_minute = per_minute
        self.seen: dict[str, deque[float]] = {}
        self.lock = threading.Lock()

    def take(self, host: str) -> None:
        now = time.monotonic()
        with self.lock:
            q = self.seen.setdefault(host, deque())
            while q and now - q[0] > 60:
                q.popleft()
            if len(q) >= self.per_minute:
                raise ValueError(f"{host} was captured {self.per_minute} times in the last "
                                 "minute; try again shortly")
            q.append(now)
            if len(self.seen) > 10_000:  # forget idle hosts
                for h in [h for h, v in self.seen.items() if not v or now - v[-1] > 60]:
                    del self.seen[h]


LIMITER = _HostLimiter(PER_HOST_PER_MINUTE)


_NAT64 = ipaddress.ip_network("64:ff9b::/96")


def _public(ip: str) -> bool:
    """Global, and so is any IPv4 address it carries: IPv4-mapped, 6to4 (2002::/16) and
    NAT64 (64:ff9b::/96, where 64:ff9b::a00:5 is 10.0.0.5) all reach that IPv4 address on a
    host that routes them, and Python calls the NAT64 form global."""
    addr = ipaddress.ip_address(ip.split("%")[0])
    if isinstance(addr, ipaddress.IPv6Address):
        embedded = addr.ipv4_mapped or addr.sixtofour
        if embedded is None and addr in _NAT64:
            embedded = ipaddress.IPv4Address(int(addr) & 0xFFFFFFFF)
        if embedded is not None:
            return embedded.is_global and not embedded.is_multicast
    return addr.is_global and not addr.is_multicast


def _resolve(host: str, port: int) -> list[str]:
    """Every address the name has (A and AAAA). Patched in tests."""
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise UpstreamError(f"{host} does not resolve ({exc.strerror or exc})") from exc
    return list(dict.fromkeys(i[4][0] for i in infos))


def check_url(url: str) -> tuple[str, str, int]:
    """(scheme, host, port) of a URL a caller may capture, or ValueError saying why not."""
    url = str(url or "").strip()
    if not url or len(url) > MAX_URL:
        raise ValueError(f"url must be 1-{MAX_URL} characters")
    parts = urlsplit(url)
    scheme = parts.scheme.lower()
    if scheme not in PORTS:
        raise ValueError("only http:// and https:// pages can be captured")
    if parts.username is not None or parts.password is not None:
        raise ValueError("a URL with user:password@ cannot be captured")
    host = (parts.hostname or "").lower().rstrip(".")
    if not host:
        raise ValueError("the URL has no host")
    try:
        port = parts.port or PORTS[scheme]
    except ValueError as exc:
        raise ValueError("the URL's port is not a number") from exc
    if port not in PORTS.values():
        raise ValueError("only ports 80 and 443 can be captured")
    if host == "localhost" or host.endswith((".localhost", ".local", ".internal", ".lan",
                                             ".home.arpa")):
        raise ValueError(f"{host} is not a public host")
    return scheme, host, port


def pin_address(host: str, port: int) -> str:
    """The address to connect to, after checking that every address of the name is public."""
    addrs = _resolve(host, port)
    if not addrs:
        raise UpstreamError(f"{host} has no address")
    bad = [a for a in addrs if not _public(a)]
    if bad:
        raise ValueError(f"{host} resolves to a non-public address ({bad[0]}); only public "
                         "pages can be captured")
    return addrs[0]


@contextlib.contextmanager
def open_pinned(url: str, ip: str, host: str, headers: dict[str, str], timeout: float,
          method: str = "GET", content: bytes | None = None) -> Iterator[httpx.Response]:
    """Request url, connected to ip, with TLS verified against host. Patched in tests."""
    parts = urlsplit(url)
    netloc = f"[{ip}]" if ":" in ip else ip
    if parts.port:
        netloc += f":{parts.port}"
    target = urlunsplit((parts.scheme, netloc, parts.path or "/", parts.query, ""))
    # The Host header names the site, not the address connected to.
    headers = {**headers, "Host": host if not parts.port else f"{host}:{parts.port}"}
    with httpx.Client(verify=True, trust_env=False, follow_redirects=False,
                      timeout=httpx.Timeout(timeout, connect=10.0)) as client:
        with client.stream(method, target, headers=headers, content=content,
                           extensions={"sni_hostname": host}) as resp:
            yield resp


def _tls(resp: httpx.Response) -> dict[str, Any] | None:
    stream = resp.extensions.get("network_stream")
    ssl_obj = stream.get_extra_info("ssl_object") if stream is not None else None
    if ssl_obj is None:
        return None
    der = ssl_obj.getpeercert(True) or b""
    cert = ssl_obj.getpeercert() or {}

    def name(field: str) -> dict[str, str]:
        return {k: v for rdn in cert.get(field, ()) for k, v in rdn}

    subject, issuer = name("subject"), name("issuer")
    return {
        "protocol": ssl_obj.version(),
        "subject": subject.get("commonName"),
        "issuer": issuer.get("organizationName") or issuer.get("commonName"),
        "not_before": cert.get("notBefore"),
        "not_after": cert.get("notAfter"),
        "names": [v for k, v in cert.get("subjectAltName", ()) if k == "DNS"][:20],
        "certificate_sha256": hashlib.sha256(der).hexdigest() if der else None,
    }


def _title(body: bytes, content_type: str) -> str | None:
    if "html" not in content_type.lower():
        return None
    m = _TITLE.search(body[:256 << 10])
    if not m:
        return None
    m_cs = _CHARSET.search(content_type)
    charset = m_cs.group(1) if m_cs else "utf-8"
    try:
        text = m.group(1).decode(charset, "replace")
    except LookupError:
        text = m.group(1).decode("utf-8", "replace")
    return " ".join(html.unescape(text).split())[:300] or None


def canonical(record: dict[str, Any]) -> bytes:
    """The bytes record_sha256 is computed over: sorted keys, compact, UTF-8."""
    return json.dumps(record, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def capture(url: str, *, include_body: bool = True, anchor: bool = True,
            stamp=None) -> dict[str, Any]:
    scheme, host, port = check_url(url)
    LIMITER.take(host)
    started = time.monotonic()
    captured_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    headers = {"User-Agent": f"{USER_AGENT} web-capture",
               "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
               "Accept-Language": "en;q=0.9,*;q=0.5"}
    hops: list[dict[str, Any]] = []
    current = url.strip()
    for _hop in range(MAX_REDIRECTS + 1):
        scheme, host, port = check_url(current)
        ip = pin_address(host, port)
        left = DEADLINE_S - (time.monotonic() - started)
        if left <= 1:
            raise UpstreamError("the page took too long to answer; nothing charged")
        try:
            with open_pinned(current, ip, host, headers, min(left, 20.0)) as resp:
                status = resp.status_code
                if status in (301, 302, 303, 307, 308):
                    location = resp.headers.get("location", "")
                    if not location:
                        raise UpstreamError(f"HTTP {status} without a Location")
                    hops.append({"url": current, "status": status, "ip": ip})
                    current = str(httpx.URL(current).join(location))
                    continue
                tls = _tls(resp) if scheme == "https" else None
                kept = {k: resp.headers[k] for k in KEPT_HEADERS if k in resp.headers}
                chunks, size = [], 0
                for chunk in resp.iter_bytes():
                    size += len(chunk)
                    if size > MAX_BODY_BYTES:
                        raise ValueError(f"the page is larger than {MAX_BODY_BYTES >> 20} MB; "
                                         "nothing charged")
                    if time.monotonic() - started > DEADLINE_S:
                        raise UpstreamError("the page took too long to send; nothing charged")
                    chunks.append(chunk)
                body = b"".join(chunks)
        except httpx.TransportError as exc:
            raise UpstreamError(f"{host} could not be reached ({type(exc).__name__}: "
                                f"{str(exc)[:120]}); nothing charged") from exc
        break
    else:
        raise UpstreamError(f"more than {MAX_REDIRECTS} redirects; nothing charged")

    record: dict[str, Any] = {
        "url": url.strip(),
        "final_url": current,
        "redirects": hops,
        "ip": ip,
        "captured_at": captured_at,
        "status": status,
        "headers": kept,
        "tls": tls,
        "body_sha256": hashlib.sha256(body).hexdigest(),
        "body_bytes": len(body),
        "title": _title(body, kept.get("content-type", "")),
    }
    record_sha256 = hashlib.sha256(canonical(record)).hexdigest()
    out: dict[str, Any] = {"record": record, "record_sha256": record_sha256}
    if include_body and len(body) <= MAX_RETURNED_BYTES:
        out["body_b64"] = base64.b64encode(body).decode()
    else:
        out["body_b64"] = None
        out["body_note"] = ("not returned: include_body was false" if not include_body else
                            f"not returned: {len(body)} bytes is over {MAX_RETURNED_BYTES} — "
                            "body_sha256 still covers all of it")
    if anchor:
        try:
            got = (stamp or timestamp.stamp)(record_sha256)
            out["anchor"] = {"status": got["status"], "proof": got["proof"],
                             "calendars": got["calendars"],
                             "next": "symmartys.timestamp.verify@v1 with digest=record_sha256 "
                                     "and this proof, after a few hours"}
        except UpstreamError as exc:
            out["anchor"] = {"status": "unavailable", "reason": str(exc)[:200],
                             "next": "the record is still signed by the hub's receipt; anchor "
                                     "record_sha256 later with symmartys.timestamp.stamp@v1"}
    else:
        out["anchor"] = None
    out["how_to_verify"] = ("sha256 of base64-decoded body_b64 equals record.body_sha256; "
                            "sha256 of the record as JSON with sorted keys, separators (',', "
                            "':') and UTF-8 equals record_sha256; the anchor proof commits "
                            "record_sha256 to a Bitcoin block")
    out["note"] = ("what this server answered SYMMARTYS at captured_at — a capture, not a "
                   "statement that the content is true; another visitor may be shown "
                   "another page")
    return out


__all__ = ["DEADLINE_S", "LIMITER", "MAX_BODY_BYTES", "MAX_REDIRECTS", "MAX_RETURNED_BYTES",
           "canonical", "capture", "check_url", "open_pinned", "pin_address"]
