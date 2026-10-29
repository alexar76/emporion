"""Outbound HTTP for SYMMARTYS: allowlisted hosts, checked redirects, size caps, evidence.

Every fetch returns the body together with what a buyer needs to trust the answer was
built from it: the final URL, the time it was fetched and the SHA-256 of the bytes.
"""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass
from urllib.parse import urlsplit

import httpx

from symmartys.sources import ALLOWED_HOSTS, DYNAMIC_HOSTS, source

USER_AGENT = "SYMMARTYS/0.5 (+https://modelmarket.dev/; contact@modelmarket.dev)"
RETRIES = 3
MAX_REDIRECTS = 3


class UpstreamError(RuntimeError):
    """The source could not answer. Callers turn this into ok:false — nothing is charged."""


@dataclass(frozen=True)
class Fetched:
    url: str
    status: int
    body: bytes
    fetched_at: str
    sha256: str

    def json(self):
        import json

        try:
            return json.loads(self.body)
        except ValueError as exc:
            raise UpstreamError("upstream answered with invalid JSON") from exc

    def evidence(self, source_id: str) -> dict[str, str]:
        src = source(source_id)
        return {"source": src.name, "url": self.url.split("?")[0], "fetched_at": self.fetched_at,
                "sha256": self.sha256, "attribution": src.attribution, "licence": src.licence}


def _check(url: str, source_id: str) -> str:
    parts = urlsplit(url)
    host = (parts.hostname or "").lower().rstrip(".")
    listed = host in ALLOWED_HOSTS and host in source(source_id).hosts
    if parts.scheme != "https" or not (listed or host in DYNAMIC_HOSTS.get(source_id, ())):
        raise UpstreamError(f"host not approved for {source_id}: {host or url[:40]}")
    return url


def fetch(url: str, *, source_id: str, method: str = "GET", json_body=None,
          content: bytes | None = None,
          headers: dict[str, str] | None = None, timeout: float = 30.0,
          max_bytes: int = 64 << 20, ok_statuses: tuple[int, ...] = (200,)) -> Fetched:
    """One request (retried on transport errors and 5xx), redirects followed by hand."""
    hdrs = {"User-Agent": USER_AGENT, "Accept": "*/*", **(headers or {})}
    last: Exception | None = None
    for _ in range(RETRIES):
        target = _check(url, source_id)
        try:
            for _hop in range(MAX_REDIRECTS + 1):
                with httpx.stream(method, target, headers=hdrs, json=json_body, content=content,
                                  timeout=timeout, follow_redirects=False) as resp:
                    if resp.status_code in (301, 302, 303, 307, 308):
                        location = resp.headers.get("location", "")
                        target = _check(str(httpx.URL(target).join(location)), source_id)
                        if resp.status_code == 303:
                            method, json_body, content = "GET", None, None
                        continue
                    if resp.status_code in (429, 500, 502, 503, 504):
                        last = UpstreamError(f"upstream HTTP {resp.status_code}")
                        break
                    if resp.status_code not in ok_statuses:
                        raise UpstreamError(f"upstream HTTP {resp.status_code}")
                    chunks, size = [], 0
                    for chunk in resp.iter_bytes():
                        size += len(chunk)
                        if size > max_bytes:
                            raise UpstreamError(f"upstream body over {max_bytes >> 20} MB")
                        chunks.append(chunk)
                    body = b"".join(chunks)
                    return Fetched(target, resp.status_code, body,
                                   time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                                   hashlib.sha256(body).hexdigest())
            else:
                raise UpstreamError("too many redirects")
        except httpx.TransportError as exc:
            last = exc
        except UpstreamError:
            raise
        time.sleep(0.2)
    raise UpstreamError(f"upstream unreachable ({type(last).__name__}: {str(last)[:80]})")


__all__ = ["Fetched", "UpstreamError", "fetch", "USER_AGENT"]
