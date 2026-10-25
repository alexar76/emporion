"""Web capture and timers: the two capabilities that call a URL the caller chooses."""

from __future__ import annotations

import base64
import contextlib
import hashlib
import ipaddress
import json

import httpx
import pytest

from emporion import capture
from emporion.net import UpstreamError
from emporion.timers import TimerService, event_canonical


class FakeSSL:
    def version(self):
        return "TLSv1.3"

    def getpeercert(self, binary=False):
        if binary:
            return b"der-bytes"
        return {"subject": ((("commonName", "shop.example"),),),
                "issuer": ((("organizationName", "Let's Encrypt"),),),
                "notBefore": "Oct  1 00:00:00 2026 GMT", "notAfter": "Dec 30 00:00:00 2026 GMT",
                "subjectAltName": (("DNS", "shop.example"), ("DNS", "www.shop.example"))}


class FakeStream:
    def get_extra_info(self, name):
        return FakeSSL() if name == "ssl_object" else None


class Web:
    """DNS and pages, by host; records every request with the address it was pinned to."""

    def __init__(self, monkeypatch):
        self.dns: dict[str, list[str]] = {}
        self.pages: dict[str, tuple[int, dict, bytes]] = {}
        self.calls: list[dict] = []
        monkeypatch.setattr(capture, "_resolve", self.resolve)
        monkeypatch.setattr(capture, "open_pinned", self.open)
        capture.LIMITER.seen.clear()

    def resolve(self, host, port):
        with contextlib.suppress(ValueError):
            return [str(ipaddress.ip_address(host))]
        if host not in self.dns:
            raise UpstreamError(f"{host} does not resolve")
        return self.dns[host]

    @contextlib.contextmanager
    def open(self, url, ip, host, headers, timeout, method="GET", content=None):
        self.calls.append({"url": url, "ip": ip, "host": host, "method": method,
                           "content": content, "headers": headers})
        if url not in self.pages:
            raise httpx.ConnectError("refused", request=httpx.Request(method, url))
        status, hdrs, body = self.pages[url]
        yield httpx.Response(status, headers=hdrs, content=body,
                             request=httpx.Request(method, url),
                             extensions={"network_stream": FakeStream()})


@pytest.fixture
def web(monkeypatch):
    return Web(monkeypatch)


PAGE = b"<html><head><title>Widget &amp; Co \xe2\x80\x94 99 EUR</title></head><body>ok</body></html>"


def fake_stamp(digest):
    return {"status": "pending", "proof": "b3Rz", "calendars": ["https://a.pool.opentimestamps.org",
                                                               "https://b.pool.opentimestamps.org"]}


# ── capture ──────────────────────────────────────────────────────────────────


def test_a_capture_records_the_page_and_anchors_the_record(web):
    web.dns["shop.example"] = ["93.184.216.34"]
    web.pages["http://shop.example/item"] = (301, {"location": "https://shop.example/item"}, b"")
    web.pages["https://shop.example/item"] = (
        200, {"content-type": "text/html; charset=utf-8", "etag": '"v1"', "set-cookie": "s=1"}, PAGE)
    out = capture.capture("http://shop.example/item", stamp=fake_stamp)
    rec = out["record"]
    assert rec["final_url"] == "https://shop.example/item" and rec["status"] == 200
    assert rec["redirects"] == [{"url": "http://shop.example/item", "status": 301,
                                 "ip": "93.184.216.34"}]
    assert rec["title"] == "Widget & Co — 99 EUR"
    assert rec["headers"]["etag"] == '"v1"' and "set-cookie" not in rec["headers"]
    assert rec["tls"]["subject"] == "shop.example" and rec["tls"]["issuer"] == "Let's Encrypt"
    assert rec["tls"]["certificate_sha256"] == hashlib.sha256(b"der-bytes").hexdigest()
    assert base64.b64decode(out["body_b64"]) == PAGE
    assert rec["body_sha256"] == hashlib.sha256(PAGE).hexdigest()
    # The record hash is reproducible from the record alone, as how_to_verify says.
    again = json.dumps(rec, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    assert hashlib.sha256(again).hexdigest() == out["record_sha256"]
    assert out["anchor"]["status"] == "pending" and out["anchor"]["proof"] == "b3Rz"
    # Connected to the checked address, with the site's name as Host and SNI.
    assert all(c["ip"] == "93.184.216.34" and c["host"] == "shop.example" for c in web.calls)


@pytest.mark.parametrize("url, why", [
    ("ftp://shop.example/", "only http"),
    ("http://user:pw@shop.example/", "user:password"),
    ("http://shop.example:8080/", "ports 80 and 443"),
    ("http://localhost/", "not a public host"),
    ("http://printer.local/", "not a public host"),
])
def test_urls_that_cannot_be_captured(web, url, why):
    with pytest.raises(ValueError, match=why):
        capture.capture(url, anchor=False)
    assert web.calls == []


@pytest.mark.parametrize("addr", ["127.0.0.1", "10.1.2.3", "169.254.169.254", "100.64.0.1",
                                  "::1", "fd00::1", "::ffff:192.168.1.1", "224.0.0.1",
                                  # NAT64 (Python calls it global) and 6to4 forms of private IPv4
                                  "64:ff9b::7f00:1", "64:ff9b::a00:5", "2002:a9fe:a9fe::"])
def test_a_name_resolving_to_a_private_address_is_refused(web, addr):
    web.dns["rebind.example"] = ["93.184.216.34", addr]
    with pytest.raises(ValueError, match="non-public address"):
        capture.capture("https://rebind.example/", anchor=False)
    assert web.calls == []


def test_a_redirect_into_the_private_network_is_refused(web):
    web.dns["shop.example"] = ["93.184.216.34"]
    web.dns["internal.example"] = ["10.0.0.5"]
    web.pages["https://shop.example/"] = (302, {"location": "https://internal.example/admin"}, b"")
    with pytest.raises(ValueError, match="non-public"):
        capture.capture("https://shop.example/", anchor=False)
    assert [c["url"] for c in web.calls] == ["https://shop.example/"]


def test_too_many_redirects_and_unreachable_hosts_cost_nothing(web):
    web.dns["loop.example"] = ["93.184.216.34"]
    web.pages["https://loop.example/"] = (302, {"location": "/"}, b"")
    with pytest.raises(UpstreamError, match="redirects"):
        capture.capture("https://loop.example/", anchor=False)
    web.dns["down.example"] = ["93.184.216.35"]
    with pytest.raises(UpstreamError, match="could not be reached"):
        capture.capture("https://down.example/", anchor=False)


def test_a_404_is_a_capture_and_a_big_body_is_hashed_not_returned(web, monkeypatch):
    web.dns["shop.example"] = ["93.184.216.34"]
    web.pages["https://shop.example/gone"] = (404, {"content-type": "text/plain"}, b"gone")
    out = capture.capture("https://shop.example/gone", anchor=False)
    assert out["record"]["status"] == 404 and out["anchor"] is None
    monkeypatch.setattr(capture, "MAX_RETURNED_BYTES", 10)
    web.pages["https://shop.example/big"] = (200, {}, b"x" * 100)
    out = capture.capture("https://shop.example/big", anchor=False)
    assert out["body_b64"] is None and out["record"]["body_bytes"] == 100
    monkeypatch.setattr(capture, "MAX_BODY_BYTES", 50)
    with pytest.raises(ValueError, match="larger than"):
        capture.capture("https://shop.example/big", anchor=False)


def test_a_calendar_outage_leaves_the_capture_signed_but_unanchored(web):
    web.dns["shop.example"] = ["93.184.216.34"]
    web.pages["https://shop.example/"] = (200, {}, b"hi")

    def down(digest):
        raise UpstreamError("only 1 calendar(s) accepted")

    out = capture.capture("https://shop.example/", stamp=down)
    assert out["anchor"]["status"] == "unavailable" and out["record"]["status"] == 200


def test_one_host_is_not_captured_more_than_the_limit_per_minute(web, monkeypatch):
    web.dns["shop.example"] = ["93.184.216.34"]
    web.pages["https://shop.example/"] = (200, {}, b"hi")
    monkeypatch.setattr(capture.LIMITER, "per_minute", 2)
    capture.capture("https://shop.example/", anchor=False)
    capture.capture("https://shop.example/", anchor=False)
    with pytest.raises(ValueError, match="2 times in the last minute"):
        capture.capture("https://shop.example/", anchor=False)


# ── timers ───────────────────────────────────────────────────────────────────


class Clock:
    def __init__(self, t=1_800_000_000.0):
        self.t = t

    def __call__(self):
        return self.t


class Signer:
    def sign_payload(self, canonical):
        return {"algorithm": "test", "value": hashlib.sha256(canonical.encode()).hexdigest()}


@pytest.fixture
def timers(web, tmp_path):
    web.dns["agent.example"] = ["93.184.216.40"]
    clock = Clock()
    svc = TimerService(tmp_path / "timers.sqlite", signer=Signer(), clock=clock)
    svc.clock_ = clock
    return svc


HOOK = "https://agent.example/hook"


def test_a_timer_fires_once_with_a_signed_event(timers, web):
    web.pages[HOOK] = (204, {}, b"")
    t = timers.set(callback=HOOK, after_seconds=120, payload={"order": 42})
    assert t["kind"] == "once" and t["token"] and t["timer_id"].startswith("tm_")
    assert timers.tick() == 0
    timers.clock_.t += 121
    assert timers.tick() == 1
    sent = json.loads(web.calls[-1]["content"])
    assert web.calls[-1]["method"] == "POST" and web.calls[-1]["ip"] == "93.184.216.40"
    assert sent["event"]["payload"] == {"order": 42} and sent["event"]["timer_id"] == t["timer_id"]
    assert sent["signature"]["value"] == hashlib.sha256(
        event_canonical(sent["event"]).encode()).hexdigest()
    st = timers.status(t["timer_id"], t["token"])
    assert st["state"] == "fired" and st["delivered_status"] == 204
    timers.clock_.t += 3600
    assert timers.tick() == 0  # fired once, never again


def test_a_deadman_fires_only_when_checkins_stop(timers, web):
    web.pages[HOOK] = (200, {}, b"ok")
    t = timers.set(callback=HOOK, deadman_seconds=600, payload={"release": "escrow-7"})
    for _ in range(5):
        timers.clock_.t += 500
        timers.checkin(t["timer_id"], t["token"])
        assert timers.tick() == 0
    timers.clock_.t += 601
    assert timers.tick() == 1
    assert json.loads(web.calls[-1]["content"])["event"]["kind"] == "deadman"
    with pytest.raises(ValueError, match="fired"):
        timers.checkin(t["timer_id"], t["token"])


def test_failed_deliveries_are_retried_then_marked_failed(timers, web):
    t = timers.set(callback=HOOK, after_seconds=60)
    timers.clock_.t += 61
    web.pages[HOOK] = (500, {}, b"")
    timers.tick()
    assert timers.status(t["timer_id"], t["token"])["state"] == "retrying"
    for wait in (60, 300, 1800):
        timers.clock_.t += wait - 1
        assert timers.tick() == 0  # not yet
        timers.clock_.t += 1
        assert timers.tick() == 1
    st = timers.status(t["timer_id"], t["token"])
    assert st["state"] == "failed" and st["attempts"] == 4 and st["last_error"] == "HTTP 500"


def test_a_checkin_during_retries_stops_the_alarm(timers, web):
    t = timers.set(callback=HOOK, deadman_seconds=60)
    timers.clock_.t += 61
    timers.tick()  # no page: connection refused
    assert timers.status(t["timer_id"], t["token"])["state"] == "retrying"
    timers.checkin(t["timer_id"], t["token"])
    st = timers.status(t["timer_id"], t["token"])
    assert st["state"] == "armed" and st["attempts"] == 0


def test_cancel_and_tokens(timers, web):
    t = timers.set(callback=HOOK, at="2027-01-15T09:00:00Z")
    with pytest.raises(ValueError, match="no timer with that id and token"):
        timers.cancel(t["timer_id"], "wrong")
    assert timers.cancel(t["timer_id"], t["token"])["state"] == "cancelled"
    timers.clock_.t += 90 * 86400
    assert timers.tick() == 0 and web.calls == []
    row = timers.db.execute("SELECT * FROM timers").fetchone()
    assert t["token"] not in json.dumps(dict(row))  # only its hash is kept


@pytest.mark.parametrize("kwargs, why", [
    ({"callback": "http://agent.example/hook", "after_seconds": 120}, "https"),
    ({"callback": "https://10.0.0.1/hook", "after_seconds": 120}, "non-public"),
    ({"callback": HOOK}, "exactly one"),
    ({"callback": HOOK, "after_seconds": 120, "deadman_seconds": 600}, "exactly one"),
    ({"callback": HOOK, "after_seconds": 5}, "at least 60"),
    ({"callback": HOOK, "after_seconds": 100 * 86400}, "within 90 days"),
    ({"callback": HOOK, "at": "2027-01-15T09:00:00"}, "time zone"),
    ({"callback": HOOK, "deadman_seconds": 10}, "deadman_seconds must be"),
    ({"callback": HOOK, "after_seconds": 120, "payload": {"x": "y" * 5000}}, "4096 bytes"),
])
def test_timers_that_cannot_be_set(timers, kwargs, why):
    with pytest.raises(ValueError, match=why):
        timers.set(**kwargs)


def test_a_deadman_checked_in_to_its_lifetime_expires_quietly(timers, web):
    web.pages[HOOK] = (200, {}, b"")
    t = timers.set(callback=HOOK, deadman_seconds=30 * 86400)
    for _ in range(3):
        timers.clock_.t += 29 * 86400
        timers.checkin(t["timer_id"], t["token"])
    timers.clock_.t += 3 * 86400 + 1  # past the 90-day lifetime, before the deadline
    timers.tick()
    assert timers.status(t["timer_id"], t["token"])["state"] == "expired" and web.calls == []
