"""Timers for agents: a signed call at a time, and a dead man's switch.

An agent runs when something calls it. It cannot wake itself in three days to check
that a delivery arrived, or notice that it has itself stopped. EMPORION can:

    once      at a time (or after N seconds), POST the caller's payload to its callback.
    deadman   every check-in pushes the deadline N seconds ahead; when the agent misses
              it, POST the payload — "I am down: release the escrow, page my owner".

Each delivery is a JSON POST of {"event": …, "signature": …}: the event (timer id, kind,
due and fired times, attempt, the caller's payload) signed with EMPORION's own key —
Ed25519 and, when on, ML-DSA-65 — over the event as JSON with sorted keys and compact
separators, so a receiver can tell it came from EMPORION and was not replayed for
another timer. The public key is the one in EMPORION's signed manifest.

Setting a timer returns its id and a token, once; the token (stored only as SHA-256) is
what checks in, cancels and reads the status. A callback is https on port 443 to a public
address, checked when the timer is set and again at every delivery (the address it
resolves to then is the one connected to). A delivery that does not get a 2xx is
retried after 1, 5 and 30 minutes, then the timer is marked failed. Timers live at most
MAX_LIFETIME_DAYS. All of it sits in one SQLite file in EMPORION's data volume.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import logging
import secrets
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Callable

from emporion import capture
from emporion.net import USER_AGENT, UpstreamError

log = logging.getLogger("emporion.timers")

MAX_LIFETIME_DAYS = 90
MIN_DELAY_S = 60
MIN_DEADMAN_S = 60
MAX_DEADMAN_S = 30 * 86400
MAX_PAYLOAD_BYTES = 4096
MAX_ARMED = 50_000
MAX_ARMED_PER_HOST = 1_000
RETRY_AFTER_S = (60, 300, 1800)
DELIVERY_TIMEOUT_S = 10.0
TICK_S = 2.0

_SCHEMA = """
CREATE TABLE IF NOT EXISTS timers (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    token_sha256 TEXT NOT NULL,
    callback TEXT NOT NULL,
    callback_host TEXT NOT NULL,
    payload TEXT NOT NULL,
    interval_s INTEGER,
    due_at REAL NOT NULL,
    next_try REAL NOT NULL,
    created_at REAL NOT NULL,
    expires_at REAL NOT NULL,
    state TEXT NOT NULL,
    attempts INTEGER NOT NULL DEFAULT 0,
    last_error TEXT,
    last_checkin REAL,
    fired_at REAL,
    delivered_status INTEGER
);
CREATE INDEX IF NOT EXISTS timers_next ON timers(state, next_try);
"""


def _iso(t: float | None) -> str | None:
    if t is None:
        return None
    return dt.datetime.fromtimestamp(t, dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _sha(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def event_canonical(event: dict[str, Any]) -> str:
    return json.dumps(event, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def check_callback(url: str) -> str:
    """The callback's host, after the same checks a web capture makes, https only."""
    scheme, host, port = capture.check_url(url)
    if scheme != "https":
        raise ValueError("a callback must be https://")
    capture.pin_address(host, port)
    return host


class TimerService:
    def __init__(self, path: str | Path = ":memory:", *, signer=None,
                 clock: Callable[[], float] = time.time):
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.path, check_same_thread=False, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(_SCHEMA)
        self.lock = threading.RLock()
        self.signer = signer
        self.clock = clock
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    # ── what callers do ──────────────────────────────────────────────────────

    def set(self, *, callback: str, at: str | None = None, after_seconds: float | None = None,
            deadman_seconds: float | None = None, payload: Any = None) -> dict[str, Any]:
        given = [x is not None and x != "" for x in (at, after_seconds, deadman_seconds)]
        if sum(given) != 1:
            raise ValueError("give exactly one of at, after_seconds, deadman_seconds")
        now = self.clock()
        host = check_callback(callback)
        body = json.dumps(payload if payload is not None else {}, sort_keys=True,
                          separators=(",", ":"), ensure_ascii=False)
        if len(body.encode()) > MAX_PAYLOAD_BYTES:
            raise ValueError(f"payload is over {MAX_PAYLOAD_BYTES} bytes as JSON")
        expires = now + MAX_LIFETIME_DAYS * 86400
        interval = None
        if deadman_seconds is not None:
            interval = int(float(deadman_seconds))
            if not MIN_DEADMAN_S <= interval <= MAX_DEADMAN_S:
                raise ValueError(f"deadman_seconds must be {MIN_DEADMAN_S}-{MAX_DEADMAN_S}")
            kind, due = "deadman", now + interval
        else:
            kind = "once"
            if at:
                try:
                    when = dt.datetime.fromisoformat(str(at).replace("Z", "+00:00"))
                except ValueError as exc:
                    raise ValueError("at must be an ISO 8601 time, e.g. 2026-11-01T09:00:00Z") from exc
                if when.tzinfo is None:
                    raise ValueError("at must carry a time zone (Z or +hh:mm)")
                due = when.timestamp()
            else:
                due = now + float(after_seconds)
            if due < now + MIN_DELAY_S:
                raise ValueError(f"a timer fires at least {MIN_DELAY_S} s from now")
            if due > expires:
                raise ValueError(f"a timer fires within {MAX_LIFETIME_DAYS} days")
        timer_id = "tm_" + secrets.token_hex(12)
        token = secrets.token_urlsafe(24)
        with self.lock:
            armed = self.db.execute("SELECT COUNT(*) FROM timers WHERE state='armed'").fetchone()[0]
            if armed >= MAX_ARMED:
                raise UpstreamError("EMPORION holds as many timers as it will; nothing charged, "
                                    "retry later")
            per_host = self.db.execute(
                "SELECT COUNT(*) FROM timers WHERE state='armed' AND callback_host=?",
                (host,)).fetchone()[0]
            if per_host >= MAX_ARMED_PER_HOST:
                raise ValueError(f"{host} already has {MAX_ARMED_PER_HOST} armed timers")
            self.db.execute(
                "INSERT INTO timers (id, kind, token_sha256, callback, callback_host, payload, "
                "interval_s, due_at, next_try, created_at, expires_at, state) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?, 'armed')",
                (timer_id, kind, _sha(token), callback.strip(), host, body, interval, due, due,
                 now, expires))
        out = {"timer_id": timer_id, "token": token, "kind": kind, "callback": callback.strip(),
               "due_at": _iso(due), "expires_at": _iso(expires),
               "note": "keep the token: it alone checks in, cancels and reads this timer, and "
                       "EMPORION cannot show it again"}
        if kind == "deadman":
            out["deadman_seconds"] = interval
            out["next"] = ("call emporion.timer.checkin@v1 with timer_id and token before "
                           "due_at; each check-in moves due_at deadman_seconds ahead")
        return out

    def _row(self, timer_id: str, token: str) -> sqlite3.Row:
        row = self.db.execute("SELECT * FROM timers WHERE id=?", (str(timer_id),)).fetchone()
        if row is None or not secrets.compare_digest(row["token_sha256"], _sha(str(token))):
            raise ValueError("no timer with that id and token")
        return row

    def checkin(self, timer_id: str, token: str) -> dict[str, Any]:
        with self.lock:
            row = self._row(timer_id, token)
            if row["kind"] != "deadman":
                raise ValueError("only a deadman timer takes check-ins")
            # A check-in while a missed deadline is still being retried stops the alarm:
            # the agent is back.
            if row["state"] not in ("armed", "retrying"):
                raise ValueError(f"the timer is {row['state']}; set a new one")
            now = self.clock()
            if now >= row["expires_at"]:
                raise ValueError("the timer has reached its lifetime; set a new one")
            # A deadline beyond the lifetime is not kept: the timer then expires quietly.
            due = now + row["interval_s"]
            self.db.execute("UPDATE timers SET state='armed', due_at=?, next_try=?, "
                            "last_checkin=?, attempts=0, last_error=NULL WHERE id=?",
                            (due, due, now, row["id"]))
        return {"timer_id": row["id"], "state": "armed", "due_at": _iso(due),
                "checked_in_at": _iso(now)}

    def cancel(self, timer_id: str, token: str) -> dict[str, Any]:
        with self.lock:
            row = self._row(timer_id, token)
            if row["state"] in ("armed", "retrying"):
                self.db.execute("UPDATE timers SET state='cancelled' WHERE id=?", (row["id"],))
                return {"timer_id": row["id"], "state": "cancelled"}
            return {"timer_id": row["id"], "state": row["state"],
                    "note": "already finished; nothing to cancel"}

    def status(self, timer_id: str, token: str) -> dict[str, Any]:
        row = self._row(timer_id, token)
        return {"timer_id": row["id"], "kind": row["kind"], "state": row["state"],
                "callback": row["callback"], "due_at": _iso(row["due_at"]),
                "deadman_seconds": row["interval_s"], "created_at": _iso(row["created_at"]),
                "expires_at": _iso(row["expires_at"]), "last_checkin": _iso(row["last_checkin"]),
                "attempts": row["attempts"], "fired_at": _iso(row["fired_at"]),
                "delivered_status": row["delivered_status"], "last_error": row["last_error"]}

    def counts(self) -> dict[str, int]:
        return {r[0]: r[1] for r in
                self.db.execute("SELECT state, COUNT(*) FROM timers GROUP BY state")}

    # ── delivery ─────────────────────────────────────────────────────────────

    def _deliver(self, row: sqlite3.Row, now: float) -> tuple[bool, int | None, str | None]:
        event = {"timer_id": row["id"], "kind": row["kind"], "due_at": _iso(row["due_at"]),
                 "fired_at": _iso(now), "attempt": row["attempts"] + 1,
                 "payload": json.loads(row["payload"]), "issuer": "emporion"}
        signature = self.signer.sign_payload(event_canonical(event)) if self.signer else None
        body = json.dumps({"event": event, "signature": signature}, ensure_ascii=False).encode()
        try:
            scheme, host, port = capture.check_url(row["callback"])
            ip = capture.pin_address(host, port)
            headers = {"User-Agent": f"{USER_AGENT} timer", "Content-Type": "application/json",
                       "X-Emporion-Timer": row["id"]}
            with capture.open_pinned(row["callback"], ip, host, headers, DELIVERY_TIMEOUT_S,
                                     method="POST", content=body) as resp:
                status = resp.status_code
                for _ in resp.iter_bytes():  # drain a little, never keep it
                    break
        except (ValueError, UpstreamError) as exc:
            return False, None, str(exc)[:200]
        except Exception as exc:  # noqa: BLE001 — a dead callback must not stop the loop
            return False, None, f"{type(exc).__name__}: {str(exc)[:160]}"
        if 200 <= status < 300:
            return True, status, None
        return False, status, f"HTTP {status}"

    def tick(self) -> int:
        """Deliver what is due now; returns how many deliveries were attempted."""
        now = self.clock()
        with self.lock:
            # A deadman checked in to the end of its lifetime expires without firing.
            self.db.execute("UPDATE timers SET state='expired' WHERE state='armed' AND "
                            "kind='deadman' AND expires_at<=? AND due_at>expires_at", (now,))
            rows = self.db.execute(
                "SELECT * FROM timers WHERE state IN ('armed','retrying') AND next_try<=? "
                "ORDER BY next_try LIMIT 20", (now,)).fetchall()
        for row in rows:
            ok, status, error = self._deliver(row, now)
            attempts = row["attempts"] + 1
            with self.lock:
                current = self.db.execute("SELECT state, due_at FROM timers WHERE id=?",
                                          (row["id"],)).fetchone()
                # A check-in or a cancel while delivering wins.
                if current["state"] not in ("armed", "retrying") or current["due_at"] != row["due_at"]:
                    continue
                if ok:
                    self.db.execute("UPDATE timers SET state='fired', attempts=?, fired_at=?, "
                                    "delivered_status=?, last_error=NULL WHERE id=?",
                                    (attempts, now, status, row["id"]))
                elif attempts > len(RETRY_AFTER_S):
                    self.db.execute("UPDATE timers SET state='failed', attempts=?, fired_at=?, "
                                    "delivered_status=?, last_error=? WHERE id=?",
                                    (attempts, now, status, error, row["id"]))
                else:
                    self.db.execute("UPDATE timers SET state='retrying', attempts=?, next_try=?, "
                                    "delivered_status=?, last_error=? WHERE id=?",
                                    (attempts, now + RETRY_AFTER_S[attempts - 1], status, error,
                                     row["id"]))
        return len(rows)

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return

        def loop():
            while not self._stop.wait(TICK_S):
                try:
                    self.tick()
                except Exception:  # noqa: BLE001 — keep the clock running
                    log.exception("timer tick failed")

        self._thread = threading.Thread(target=loop, name="emporion-timers", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()


__all__ = ["MAX_LIFETIME_DAYS", "TimerService", "check_callback", "event_canonical"]
