"""Bitcoin block headers straight from the Bitcoin network — no explorer, no API terms.

timestamp.verify needs one thing from Bitcoin: the header of the block an OpenTimestamps
proof lands in, to compare the proof's result with that header's Merkle root. SYMMARTYS used
to ask two block explorers for it; their public APIs are free but rate-limited, without
terms for business use. The header chain itself is public consensus data that any Bitcoin
node serves to anyone, so SYMMARTYS keeps its own copy:

* It speaks the Bitcoin P2P protocol to nodes found through the DNS seeds (TCP 8333), asks
  for headers (getheaders), and keeps every header from the genesis block on in one file in
  its data volume (~80 bytes a block, ~75 MB).
* Every header is checked before it is kept: it links to the previous one, its hash meets
  the target its bits name, its bits are the ones the difficulty rule demands (unchanged
  inside a 2016-block period, retargeted from the period's timespan at its start, clamped
  to x4 either way, never easier than the proof-of-work limit), and its time is not more
  than two hours ahead. A chain that fails any check is not kept, whoever sent it.
* A second node, on another network (/16), must serve the same chain: a header is used for
  a verification only up to the height that second node agreed to (`agreed_height`).
* The chain is refreshed every REFRESH_S; a short reorganisation (a longer branch from one
  of the last REORG_DEPTH blocks) replaces the old tip.

Until the first sync finishes, a verification answers ok:false and costs nothing.
"""

from __future__ import annotations

import hashlib
import ipaddress
import logging
import os
import random
import socket
import struct
import threading
import time
from pathlib import Path
from typing import Any, Callable, Iterable

from symmartys.net import UpstreamError

log = logging.getLogger("symmartys.bitcoin_headers")

MAGIC = bytes.fromhex("f9beb4d9")
PORT = 8333
PROTOCOL_VERSION = 70016
USER_AGENT = b"/SYMMARTYS:0.3/"
GENESIS = bytes.fromhex(
    "0100000000000000000000000000000000000000000000000000000000000000000000003ba3edfd7a7b12b27a"
    "c72c3e67768f617fc81bc3888a51323a9fb8aa4b1e5e4a29ab5f49ffff001d1dac2b7c")
GENESIS_HASH = "000000000019d6689c085ae165831e934ff763ae46a2a6c172b3f1b60a8ce26f"
POW_LIMIT = 0x00000000FFFF << 208
RETARGET = 2016
TARGET_TIMESPAN = 14 * 24 * 3600
MAX_FUTURE_S = 2 * 3600
REORG_DEPTH = 100
REFRESH_S = 10 * 60
SEEDS = ("seed.bitcoin.sipa.be", "dnsseed.bluematt.me", "seed.bitcoin.jonasschnelli.ch",
         "seed.btc.petertodd.net", "seed.bitcoin.sprovoost.nl", "dnsseed.emzy.de",
         "seed.bitcoin.wiz.biz")
MAX_HEADERS_PER_MSG = 2000
MAX_PAYLOAD = 4 << 20
#: Nodes differ a hundredfold: one answers 2000 headers in 0.1 s, another in 30 s. A node
#: slower than this for one batch is left for the next one; what it sent is kept.
SLOW_BATCH_S = 3.0
MAX_PEERS_TRIED = 80
#: Nodes probed in parallel at a time; the fastest handshakes are asked first.
RACE = 8


def dsha(b: bytes) -> bytes:
    return hashlib.sha256(hashlib.sha256(b).digest()).digest()


def block_hash(header: bytes) -> str:
    return dsha(header)[::-1].hex()


def bits_to_target(bits: int) -> int:
    exp, mant = bits >> 24, bits & 0x007FFFFF
    return mant >> (8 * (3 - exp)) if exp <= 3 else mant << (8 * (exp - 3))


def target_to_bits(target: int) -> int:
    size = (target.bit_length() + 7) // 8
    compact = target << (8 * (3 - size)) if size <= 3 else target >> (8 * (size - 3))
    if compact & 0x00800000:
        compact >>= 8
        size += 1
    return compact | (size << 24)


def fields(header: bytes) -> dict[str, Any]:
    version, prev, merkle, t, bits, nonce = struct.unpack("<i32s32sIII", header)
    return {"version": version, "prev": prev, "merkle_root": merkle, "time": t, "bits": bits,
            "nonce": nonce}


class InvalidChain(ValueError):
    pass


class HeaderChain:
    """Every header from an anchor on (the genesis block in production), checked."""

    def __init__(self, path: str | Path | None = None, *, anchor_height: int = 0,
                 anchor: bytes = GENESIS, clock: Callable[[], float] = time.time):
        if anchor_height % RETARGET:
            raise ValueError("an anchor must start a difficulty period")
        self.path = Path(path) if path else None
        self.base = anchor_height
        self.raw = bytearray(anchor)
        self.clock = clock
        self.lock = threading.RLock()
        self.agreed_height = -1
        self.peers: dict[str, int] = {}

    # ── reading ─────────────────────────────────────────────────────────────

    @property
    def height(self) -> int:
        return self.base + len(self.raw) // 80 - 1

    def header(self, height: int) -> bytes:
        i = height - self.base
        if i < 0 or height > self.height:
            raise KeyError(height)
        return bytes(self.raw[i * 80:(i + 1) * 80])

    def hash_at(self, height: int) -> bytes:
        return dsha(self.header(height))

    def locator(self) -> list[bytes]:
        heights, step, h = [], 1, self.height
        while h > self.base:
            heights.append(h)
            if len(heights) >= 10:
                step *= 2
            h -= step
        heights.append(self.base)
        return [self.hash_at(x) for x in heights]

    # ── checking ────────────────────────────────────────────────────────────

    def _expected_bits(self, height: int, prev_bits: int) -> int:
        if height % RETARGET:
            return prev_bits
        first = fields(self.header(height - RETARGET))["time"]
        last = fields(self.header(height - 1))
        span = min(max(last["time"] - first, TARGET_TIMESPAN // 4), TARGET_TIMESPAN * 4)
        target = min(bits_to_target(last["bits"]) * span // TARGET_TIMESPAN, POW_LIMIT)
        return target_to_bits(target)

    def _check(self, header: bytes, height: int, prev_hash: bytes, prev_bits: int) -> None:
        if len(header) != 80:
            raise InvalidChain("a header is 80 bytes")
        f = fields(header)
        if f["prev"] != prev_hash:
            raise InvalidChain(f"header {height} does not link to {height - 1}")
        expected = self._expected_bits(height, prev_bits)
        if f["bits"] != expected:
            raise InvalidChain(f"header {height} names difficulty {f['bits']:#x}, the rule "
                               f"says {expected:#x}")
        if int.from_bytes(dsha(header), "little") > bits_to_target(f["bits"]):
            raise InvalidChain(f"header {height} does not meet its target")
        if f["time"] > self.clock() + MAX_FUTURE_S:
            raise InvalidChain(f"header {height} is dated in the future")

    def extend(self, headers: list[bytes]) -> int:
        """Check and append headers that continue the tip, or replace a short branch.

        Returns how many were appended. Raises InvalidChain without changing anything when
        a header fails; a branch that is not longer than the tip it would replace is ignored.
        """
        if not headers:
            return 0
        with self.lock:
            first_prev = fields(headers[0])["prev"]
            fork = None
            for back in range(0, min(REORG_DEPTH, self.height - self.base) + 1):
                if self.hash_at(self.height - back) == first_prev:
                    fork = self.height - back
                    break
            if fork is None:
                raise InvalidChain("the headers do not join the chain SYMMARTYS holds")
            new_tip = fork + len(headers)
            if new_tip <= self.height:
                # Either headers SYMMARTYS already has (a node behind or level) or a shorter
                # branch: both leave the chain as it is.
                return 0
            saved = bytes(self.raw[(fork + 1 - self.base) * 80:])
            del self.raw[(fork + 1 - self.base) * 80:]
            try:
                for i, h in enumerate(headers):
                    height = fork + 1 + i
                    prev = self.header(height - 1)
                    self._check(h, height, dsha(prev), fields(prev)["bits"])
                    self.raw += h
            except InvalidChain:
                del self.raw[(fork + 1 - self.base) * 80:]
                self.raw += saved
                raise
            if saved:
                log.warning("bitcoin reorganisation: %d block(s) replaced from height %d",
                            len(saved) // 80, fork + 1)
                self.agreed_height = min(self.agreed_height, fork)
            self._save(fork)
            return len(headers)

    def agreement(self, headers: list[bytes]) -> int:
        """How far a second node's chain agrees with ours, from its answer to our locator.

        Headers that are all ours (a node level with us answers none; one behind answers
        ours up to its tip) agree up to the last of them; headers that continue past our
        tip are appended (after the checks) and agree to the end. Anything else is a
        different chain: -1.
        """
        with self.lock:
            if not headers:
                return self.height
            first_prev = fields(headers[0])["prev"]
            start = None
            for back in range(0, min(REORG_DEPTH * 5, self.height - self.base) + 1):
                if self.hash_at(self.height - back) == first_prev:
                    start = self.height - back + 1
                    break
            if start is None:
                return -1
            for i, h in enumerate(headers):
                height = start + i
                if height > self.height:
                    try:
                        self.extend(headers[i:])
                    except InvalidChain:
                        return height - 1
                    return self.height
                if self.header(height) != h:
                    return -1
            return start + len(headers) - 1

    # ── the file ────────────────────────────────────────────────────────────

    def _save(self, from_height: int) -> None:
        if self.path is None or self.base:
            return
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            if not self.path.exists() or self.path.stat().st_size < (from_height + 1) * 80:
                from_height = -1  # a new (or short) file gets everything, genesis first
            with open(self.path, "r+b" if self.path.exists() else "wb") as f:
                f.seek((from_height + 1) * 80)
                f.write(self.raw[(from_height + 1) * 80:])
                f.truncate()
        except OSError as exc:
            log.warning("bitcoin headers not saved: %s", exc)

    def load(self) -> int:
        """Re-check the saved chain header by header; keep it up to the first that fails."""
        if self.path is None or not self.path.is_file():
            return self.height
        data = self.path.read_bytes()
        if data[:80] != GENESIS:
            log.warning("saved bitcoin headers do not start at the genesis block; ignored")
            return self.height
        batch = [data[i:i + 80] for i in range(80, len(data) - len(data) % 80, 80)]
        for start in range(0, len(batch), 10_000):
            part = batch[start:start + 10_000]
            try:
                self.extend(part)
            except InvalidChain:
                # The batch is all-or-nothing; keep its headers up to the one that fails.
                for one in part:
                    try:
                        self.extend([one])
                    except InvalidChain as exc:
                        log.warning("saved bitcoin headers kept up to %d: %s", self.height, exc)
                        return self.height
        return self.height

    # ── what verify asks ────────────────────────────────────────────────────

    def block(self, height: int) -> dict[str, Any]:
        with self.lock:
            if height > self.agreed_height:
                raise UpstreamError(
                    f"block {height} is not yet in the header chain two Bitcoin nodes agreed "
                    f"on (it reaches {self.agreed_height}); nothing charged, retry shortly")
            header = self.header(height)
        f = fields(header)
        return {"height": height, "block_hash": block_hash(header),
                "merkle_root": f["merkle_root"], "time": f["time"]}

    def status(self) -> dict[str, Any]:
        return {"height": self.height, "agreed_height": self.agreed_height,
                "peers": dict(self.peers)}


# ── The Bitcoin P2P protocol, the little of it needed ────────────────────────


def _msg(cmd: str, payload: bytes = b"") -> bytes:
    return (MAGIC + cmd.encode().ljust(12, b"\0") + struct.pack("<I", len(payload))
            + dsha(payload)[:4] + payload)


def _varint(n: int) -> bytes:
    if n < 0xFD:
        return bytes([n])
    if n <= 0xFFFF:
        return b"\xfd" + struct.pack("<H", n)
    return b"\xfe" + struct.pack("<I", n)


def _read_varint(b: bytes, i: int) -> tuple[int, int]:
    first = b[i]
    if first < 0xFD:
        return first, i + 1
    size = {0xFD: 2, 0xFE: 4, 0xFF: 8}[first]
    return int.from_bytes(b[i + 1:i + 1 + size], "little"), i + 1 + size


def _version_payload() -> bytes:
    addr = struct.pack("<Q", 0) + bytes(10) + b"\xff\xff" + bytes(4) + struct.pack(">H", PORT)
    return (struct.pack("<iQq", PROTOCOL_VERSION, 0, int(time.time())) + addr + addr
            + struct.pack("<Q", random.getrandbits(64)) + _varint(len(USER_AGENT)) + USER_AGENT
            + struct.pack("<i", 0) + b"\x00")  # start height 0, relay false: no transactions


def parse_headers(payload: bytes) -> list[bytes]:
    n, i = _read_varint(payload, 0)
    if n > MAX_HEADERS_PER_MSG:
        raise InvalidChain("more headers than a node may send at once")
    out = []
    for _ in range(n):
        out.append(payload[i:i + 80])
        _txs, i = _read_varint(payload, i + 80)
    return out


class Peer:
    def __init__(self, ip: str, timeout: float = 10.0):
        self.ip = ip
        self.sock = socket.create_connection((ip, PORT), timeout=timeout)
        self.buf = b""
        self.sock.sendall(_msg("version", _version_payload()))
        got_version = got_verack = False
        deadline = time.monotonic() + timeout
        while not (got_version and got_verack):
            if time.monotonic() > deadline:
                raise OSError("handshake timed out")
            cmd, _payload = self._read()
            if cmd == "version":
                got_version = True
                self.sock.sendall(_msg("verack"))
            elif cmd == "verack":
                got_verack = True

    def _recv(self, n: int) -> bytes:
        while len(self.buf) < n:
            chunk = self.sock.recv(65536)
            if not chunk:
                raise OSError("peer closed the connection")
            self.buf += chunk
        out, self.buf = self.buf[:n], self.buf[n:]
        return out

    def _read(self) -> tuple[str, bytes]:
        head = self._recv(24)
        if head[:4] != MAGIC:
            raise OSError("not a Bitcoin mainnet peer")
        cmd = head[4:16].rstrip(b"\0").decode("ascii", "replace")
        length = struct.unpack("<I", head[16:20])[0]
        if length > MAX_PAYLOAD:
            raise OSError("message too large")
        payload = self._recv(length)
        if dsha(payload)[:4] != head[20:24]:
            raise OSError("bad checksum")
        if cmd == "ping":
            self.sock.sendall(_msg("pong", payload))
        return cmd, payload

    def getheaders(self, locator: list[bytes]) -> list[bytes]:
        payload = (struct.pack("<I", PROTOCOL_VERSION) + _varint(len(locator))
                   + b"".join(locator) + bytes(32))
        self.sock.sendall(_msg("getheaders", payload))
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            cmd, body = self._read()
            if cmd == "headers":
                return parse_headers(body)
        raise OSError("no headers answer")

    def close(self) -> None:
        try:
            self.sock.close()
        except OSError:
            pass


def discover(seeds: Iterable[str] = SEEDS) -> list[str]:
    ips: set[str] = set()
    for seed in seeds:
        try:
            for info in socket.getaddrinfo(seed, PORT, socket.AF_INET, socket.SOCK_STREAM):
                ip = info[4][0]
                if ipaddress.ip_address(ip).is_global:
                    ips.add(ip)
        except OSError:
            continue
    out = list(ips)
    random.shuffle(out)
    return out


def _net16(ip: str) -> str:
    return ".".join(ip.split(".")[:2])


class HeaderService:
    """Keeps a HeaderChain current from the network, in a background thread."""

    def __init__(self, chain: HeaderChain, *, connect: Callable[[str], Any] = Peer,
                 discover_peers: Callable[[], list[str]] = discover):
        self.chain = chain
        self.connect = connect
        self.discover_peers = discover_peers
        self.error: str | None = None
        self.synced_at: float | None = None
        self._thread: threading.Thread | None = None

    def _sync_from(self, ip: str) -> bool:
        """Fetch headers from one node until it has no more (True) or turns slow (False)."""
        peer = self.connect(ip)
        try:
            while True:
                started = time.monotonic()
                got = peer.getheaders(self.chain.locator())
                slow = time.monotonic() - started > SLOW_BATCH_S
                if not got:
                    break
                added = self.chain.extend(got)
                if added == 0 or len(got) < MAX_HEADERS_PER_MSG:
                    break
                if slow:
                    return False
        finally:
            peer.close()
        self.chain.peers[ip] = self.chain.height
        return True

    def _confirm_with(self, ip: str) -> int:
        peer = self.connect(ip)
        try:
            return self.chain.agreement(peer.getheaders(self.chain.locator()))
        finally:
            peer.close()

    def _fastest_first(self, ips: list[str], n: int = RACE) -> list[str]:
        """Order the first n nodes by how fast each completes a handshake (in parallel);
        nodes that do not answer go last. Real peers only: the fake connect in tests has
        no handshake to time, so the order is kept."""
        if self.connect is not Peer:
            return ips
        timings: dict[str, float] = {}

        def probe(ip: str) -> None:
            started = time.monotonic()
            try:
                Peer(ip, timeout=4.0).close()
                timings[ip] = time.monotonic() - started
            except OSError:
                pass

        threads = [threading.Thread(target=probe, args=(ip,), daemon=True) for ip in ips[:n]]
        for t in threads:
            t.start()
        for t in threads:
            t.join(6.0)
        fast = sorted(timings, key=timings.get)
        return fast + [ip for ip in ips if ip not in timings]

    def refresh(self) -> dict[str, Any]:
        ips = self.discover_peers()
        if len(ips) < 2:
            raise UpstreamError("fewer than two Bitcoin nodes found")
        primary = None
        tried = 0
        while ips and tried < MAX_PEERS_TRIED and primary is None:
            batch, ips = self._fastest_first(ips[:RACE]), ips[RACE:]
            for ip in batch:
                tried += 1
                try:
                    if self._sync_from(ip):
                        primary = ip
                        break
                    log.info("bitcoin node %s slow; continuing at %d with another", ip,
                             self.chain.height)
                except (OSError, InvalidChain) as exc:
                    log.info("bitcoin node %s not used: %s", ip, exc)
        if primary is None:
            raise UpstreamError("no Bitcoin node served a valid header chain")
        others = [x for x in self.discover_peers() if _net16(x) != _net16(primary)]
        for ip in self._fastest_first(others)[:RACE]:
            try:
                agreed = self._confirm_with(ip)
            except (OSError, InvalidChain) as exc:
                log.info("bitcoin node %s not used for agreement: %s", ip, exc)
                continue
            if agreed >= 0:
                with self.chain.lock:
                    self.chain.agreed_height = max(min(agreed, self.chain.height),
                                                   self.chain.agreed_height)
                self.chain.peers[ip] = agreed
                self.synced_at = time.time()
                self.error = None
                return self.chain.status()
        raise UpstreamError("no second Bitcoin node agreed with the chain")

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return

        def loop():
            self.chain.load()
            while True:
                try:
                    self.refresh()
                    log.info("bitcoin headers: %s", self.chain.status())
                    wait = REFRESH_S
                except Exception as exc:  # noqa: BLE001 — keep trying
                    self.error = f"{type(exc).__name__}: {str(exc)[:160]}"
                    log.warning("bitcoin headers not refreshed: %s", self.error)
                    wait = 60
                time.sleep(wait)

        self._thread = threading.Thread(target=loop, name="symmartys-btc-headers", daemon=True)
        self._thread.start()

    def status(self) -> dict[str, Any]:
        return {**self.chain.status(), "synced_at": self.synced_at, "error": self.error,
                "source": "Bitcoin P2P network (two nodes on different networks)"}


__all__ = ["GENESIS", "GENESIS_HASH", "HeaderChain", "HeaderService", "InvalidChain", "Peer",
           "bits_to_target", "block_hash", "discover", "parse_headers", "target_to_bits"]
