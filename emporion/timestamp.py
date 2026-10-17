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
        allowlist are asked), and every Bitcoin attestation is checked against EMPORION's
        own copy of the Bitcoin header chain (bitcoin_headers.py: fetched from the Bitcoin
        P2P network, every header's proof of work and difficulty checked, agreed by a
        second node on another network): the header at that height must have the proof's
        result as its Merkle root. Then the digest is proven to exist no later than that
        block's time. No block explorer is asked.

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

from emporion.bitcoin_headers import HeaderChain
from emporion.net import UpstreamError, fetch
from emporion.sources import source

CALENDARS = (
    "https://a.pool.opentimestamps.org",
    "https://b.pool.opentimestamps.org",
    "https://a.pool.eternitywall.com",
    "https://ots.btc.catallaxy.com",
)
MIN_CALENDARS = 2
#: The header chain verify reads; main() sets it to the one its HeaderService keeps current.
HEADERS: HeaderChain | None = None
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


def verify(hex_digest: str, proof_b64: str, *, upgrade: bool = True,
           headers: HeaderChain | None = None) -> dict[str, Any]:
    digest = _digest(hex_digest)
    chain = headers or HEADERS
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
        if chain is None:
            raise UpstreamError("EMPORION's Bitcoin header chain is not loaded; nothing "
                                "charged, retry shortly")
        block = chain.block(int(att.height))
        if block["merkle_root"] != msg:
            raise ValueError(f"the proof's result does not match block {att.height}'s Merkle "
                             "root: the proof is not valid")
        confirmations.append({
            "height": block["height"], "block_hash": block["block_hash"],
            "block_time": datetime.fromtimestamp(block["time"], timezone.utc)
            .strftime("%Y-%m-%dT%H:%M:%SZ"),
            "headers": "Bitcoin P2P network, proof of work checked, agreed by two nodes",
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


__all__ = ["CALENDARS", "HEADERS", "MIN_CALENDARS", "stamp", "verify"]
