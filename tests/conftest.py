"""A fake upstream: answers by (method, URL prefix), counts calls, never touches the network."""

from __future__ import annotations

import contextlib
from pathlib import Path
from typing import Any, Callable

import httpx
import pytest

FIX = Path(__file__).parent / "fixtures"


class Upstream:
    def __init__(self):
        self.routes: list[tuple[str, str, Callable[[str, Any], httpx.Response]]] = []
        self.calls: list[tuple[str, str]] = []
        self.drop = 0

    def on(self, method: str, prefix: str, status: int = 200, body: bytes | str | None = None,
           json: Any = None, headers: dict[str, str] | None = None):
        def handler(url, sent):
            req = httpx.Request(method, url)
            if json is not None:
                return httpx.Response(status, json=json, request=req, headers=headers)
            content = body.encode() if isinstance(body, str) else (body or b"")
            return httpx.Response(status, content=content, request=req, headers=headers)
        self.routes.insert(0, (method, prefix, handler))

    def handle(self, method: str, prefix: str, fn: Callable[[str, Any], httpx.Response]):
        self.routes.insert(0, (method, prefix, fn))

    def stream(self, method, url, headers=None, json=None, content=None, timeout=None,
               follow_redirects=False):
        url = str(url)
        self.calls.append((method, url))
        if self.drop:
            self.drop -= 1
            raise httpx.ConnectError("connection reset", request=httpx.Request(method, url))
        for m, prefix, fn in self.routes:
            if m == method and url.startswith(prefix):
                return contextlib.nullcontext(fn(url, json if json is not None else content))
        return contextlib.nullcontext(httpx.Response(404, request=httpx.Request(method, url)))


@pytest.fixture
def upstream(monkeypatch):
    up = Upstream()
    import emporion.net as net

    monkeypatch.setattr(net.httpx, "stream", up.stream)
    monkeypatch.setattr(net.time, "sleep", lambda s: None)
    return up
