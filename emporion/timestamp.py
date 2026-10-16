"""Bitcoin-anchored timestamps (OpenTimestamps): prove a digest existed by a block's time.

An agent that produced a report, a contract or a dataset can prove later that it
existed at a moment, without trusting EMPORION or anyone else: the proof ends in a
Bitcoin block header.

stamp   The caller's SHA-256 digest gets a random 16-byte nonce appended and is hashed
        again (calendars never see the caller's digest), then submitted to the public
        OpenTimestamps calendars; at least two must accept. The answer is a standard
        .ots proof (base64) with pending attestations — Bitcoin confirmation follows in
        a few hours, when the calendars' aggregate transaction is mined.

verify  The proof is upgraded at each calendar it names (only calendars on the
        allowlist are asked), and every Bitcoin attestation is checked: the block hash
        at that height from two independent explorers must agree, the header must hash
        to that block hash, and its Merkle root must equal the proof's result. Then the
        digest is proven to exist no later than that block's time.

Proof format and operations come from the OpenTimestamps reference library; all HTTP
is EMPORION's own (allowlisted, size-capped).
"""

from __future__ import annotations

import base64
import hashlib
import io
import os
import time
from datetime import datetime, timezone
from typing import Any, Iterator
from urllib.parse import urlsplit

from opentimestamps.core.notary import BitcoinBlockHeaderAttestation, PendingAttestation
from opentimestamps.core.op import OpAppend, OpSHA256
from opentimestamps.core.serialize import (
    DeserializationError,
    StreamDeserializationContext,
    StreamSerializationContext,
)
from opentimestamps.core.timestamp import DetachedTimestampFile, Timestamp

from emporion.net import UpstreamError, fetch
from emporion.sources import source

CALENDARS = (
    "https://a.pool.opentimestamps.org",
    "https://b.pool.opentimestamps.org",
    "https://a.pool.eternitywall.com",
    "https://ots.btc.catallaxy.com",
)
MIN_CALENDARS = 2
EXPLORERS = ("https://mempool.space/api", "https://blockstream.info/api")
_OTS_HEADERS = {"Accept": "application/vnd.opentimestamps.v1"}
MAX_PROOF_BYTES = 64 << 10


def _digest(hex_digest: str) -> bytes:
    h = str(hex_digest or "").strip().lower()
    if len(h) != 64 or any(c not in "0123456789abcdef" for c in h):
        raise ValueError("digest must be a SHA-256 in hex (64 characters)")
    return bytes.fromhex(h)


def _serialize(dtf: DetachedTimestampFile) -> bytes:
    buf = io.BytesIO()
    dtf.serialize(StreamSerializationContext(buf))
    return buf.getvalue()


def _deserialize_proof(proof_b64: str) -> DetachedTimestampFile:
    try:
        raw = base64.b64decode(str(proof_b64), validate=True)
    except ValueError as exc:
        raise ValueError("proof must be base64 of a .ots file") from exc
    if len(raw) > MAX_PROOF_BYTES:
        raise ValueError("proof is larger than any .ots file EMPORION issues")
    try:
        return DetachedTimestampFile.deserialize(StreamDeserializationContext(io.BytesIO(raw)))
    except (DeserializationError, ValueError, EOFError, TypeError) as exc:
        raise ValueError(f"not a valid .ots proof ({type(exc).__name__})") from exc


def _walk(ts: Timestamp) -> Iterator[Timestamp]:
    yield ts
    for child in ts.ops.values():
        yield from _walk(child)


def _calendar_allowed(uri: str) -> bool:
    host = (urlsplit(uri).hostname or "").lower()
    return uri.startswith("https://") and host in source("opentimestamps").hosts


def stamp(hex_digest: str, *, calendars: tuple[str, ...] = CALENDARS) -> dict[str, Any]:
    digest = _digest(hex_digest)
    dtf = DetachedTimestampFile(OpSHA256(), Timestamp(digest))
    nonce = dtf.timestamp.ops.add(OpAppend(os.urandom(16)))
    root = nonce.ops.add(OpSHA256())
    accepted, refused = [], {}
    for cal in calendars:
        try:
            got = fetch(f"{cal}/digest", source_id="opentimestamps", method="POST",
                        content=root.msg, max_bytes=MAX_PROOF_BYTES, timeout=20,
                        headers={**_OTS_HEADERS, "Content-Type": "application/octet-stream"})
            root.merge(Timestamp.deserialize(StreamDeserializationContext(io.BytesIO(got.body)),
                                             root.msg))
            accepted.append(cal)
        except (UpstreamError, DeserializationError, ValueError) as exc:
            refused[cal] = f"{type(exc).__name__}: {str(exc)[:100]}"
    if len(accepted) < MIN_CALENDARS:
        raise UpstreamError(f"only {len(accepted)} calendar(s) accepted the digest "
                            f"(need {MIN_CALENDARS}); nothing charged: {refused}")
    proof = _serialize(dtf)
    return {
        "digest": digest.hex(),
        "status": "pending",
        "proof": base64.b64encode(proof).decode(),
        "proof_sha256": hashlib.sha256(proof).hexdigest(),
        "calendars": accepted,
        "submitted_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "next": "call emporion.timestamp.verify@v1 with digest and proof after a few hours "
                "to receive the Bitcoin-confirmed proof",
        "note": "the calendars saw only sha256(digest || 16 random bytes), never the digest",
    }


def _block(height: int) -> dict[str, Any]:
    """Block hash and header at height, agreed by both explorers and self-consistent."""
    seen: dict[str, tuple[str, str]] = {}
    for base in EXPLORERS:
        bh = fetch(f"{base}/block-height/{height}", source_id="bitcoin_headers",
                   max_bytes=256, timeout=15).body.decode().strip()
        header = fetch(f"{base}/block/{bh}/header", source_id="bitcoin_headers",
                       max_bytes=512, timeout=15).body.decode().strip()
        seen[base] = (bh, header)
    hashes = {v[0] for v in seen.values()}
    headers = {v[1] for v in seen.values()}
    if len(hashes) != 1 or len(headers) != 1:
        raise UpstreamError(f"explorers disagree about block {height}; not deciding")
    block_hash, header_hex = next(iter(seen.values()))
    raw = bytes.fromhex(header_hex)
    if len(raw) != 80:
        raise UpstreamError("a Bitcoin header is 80 bytes")
    if hashlib.sha256(hashlib.sha256(raw).digest()).digest()[::-1].hex() != block_hash:
        raise UpstreamError(f"header does not hash to block {block_hash}")
    return {"height": height, "block_hash": block_hash, "merkle_root": raw[36:68],
            "time": int.from_bytes(raw[68:72], "little")}


def verify(hex_digest: str, proof_b64: str, *, upgrade: bool = True) -> dict[str, Any]:
    digest = _digest(hex_digest)
    dtf = _deserialize_proof(proof_b64)
    if not isinstance(dtf.file_hash_op, OpSHA256):
        raise ValueError("EMPORION verifies SHA-256 proofs")
    if dtf.file_digest != digest:
        raise ValueError("the proof is for a different digest")
    before = _serialize(dtf)
    upgraded_from: list[str] = []
    asked: dict[str, str] = {}
    if upgrade:
        for ts in list(_walk(dtf.timestamp)):
            for att in list(ts.attestations):
                if not isinstance(att, PendingAttestation):
                    continue
                uri = att.uri
                if not _calendar_allowed(uri):
                    asked[uri] = "not on the allowlist; not asked"
                    continue
                try:
                    got = fetch(f"{uri}/timestamp/{ts.msg.hex()}", source_id="opentimestamps",
                                headers=_OTS_HEADERS, max_bytes=MAX_PROOF_BYTES, timeout=20,
                                ok_statuses=(200, 404))
                except UpstreamError as exc:
                    asked[uri] = str(exc)[:100]
                    continue
                if got.status == 404:
                    asked[uri] = "pending (not yet in a Bitcoin block)"
                    continue
                ts.merge(Timestamp.deserialize(StreamDeserializationContext(io.BytesIO(got.body)),
                                               ts.msg))
                upgraded_from.append(uri)
                asked[uri] = "upgraded"
    confirmations = []
    for msg, att in dtf.timestamp.all_attestations():
        if not isinstance(att, BitcoinBlockHeaderAttestation):
            continue
        block = _block(int(att.height))
        if block["merkle_root"] != msg:
            raise ValueError(f"the proof's result does not match block {att.height}'s Merkle "
                             "root: the proof is not valid")
        confirmations.append({
            "height": block["height"], "block_hash": block["block_hash"],
            "block_time": datetime.fromtimestamp(block["time"], timezone.utc)
            .strftime("%Y-%m-%dT%H:%M:%SZ"),
            "explorers": [e.split("/")[2] for e in EXPLORERS],
        })
    confirmations.sort(key=lambda c: c["height"])
    after = _serialize(dtf)
    pending = sorted({a.uri for _m, a in dtf.timestamp.all_attestations()
                      if isinstance(a, PendingAttestation)})
    out: dict[str, Any] = {
        "digest": digest.hex(),
        "status": "confirmed" if confirmations else "pending",
        "bitcoin": confirmations,
        "existed_by": confirmations[0]["block_time"] if confirmations else None,
        "pending_calendars": pending,
        "calendars_asked": asked,
        "proof": base64.b64encode(after).decode(),
        "proof_changed": after != before,
    }
    if not confirmations:
        out["note"] = ("not in a Bitcoin block yet; calendars usually confirm within a few "
                       "hours — keep the proof and verify again later")
    return out


__all__ = ["CALENDARS", "EXPLORERS", "MIN_CALENDARS", "stamp", "verify"]
