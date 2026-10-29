"""Sanctions lists (real OFAC/EU/UK excerpts) and OpenTimestamps (the reference example proof)."""

from __future__ import annotations

import base64
import hashlib
import io
import time

import httpx
import pytest

from conftest import FIX
from symmartys import timestamp
from symmartys.names import similarity
from symmartys.net import Fetched, UpstreamError
from symmartys.sanctions import (
    SanctionsService,
    Snapshot,
    norm_address,
    parse_eu,
    parse_ofac,
    parse_uk,
)


def _fetched(name: str, url: str = "https://x/Published/a/2026-10-15/b/SDN.CSV") -> Fetched:
    body = (FIX / name).read_bytes()
    return Fetched(url, 200, body, "2026-10-16T08:00:00Z", hashlib.sha256(body).hexdigest())


@pytest.fixture(scope="module")
def snaps() -> dict[str, Snapshot]:
    return {
        "OFAC-SDN": parse_ofac(_fetched("ofac_sdn_excerpt.csv"), _fetched("ofac_alt_excerpt.csv"),
                               _fetched("ofac_comments_excerpt.csv")),
        "EU": parse_eu(_fetched("eu_fsf_excerpt.xml")),
        "UK": parse_uk(_fetched("uk_excerpt.xml")),
    }


@pytest.fixture
def svc(snaps) -> SanctionsService:
    s = SanctionsService(loaders={k: (lambda v=v: v) for k, v in snaps.items()})
    s.refresh()
    return s


# ── parsing ───────────────────────────────────────────────────────────────────


def test_ofac_rows_carry_kind_programs_aliases_and_wallets(snaps):
    ofac = {e.name: e for e in snaps["OFAC-SDN"].entries}
    assert snaps["OFAC-SDN"].published == "2026-10-15"
    lazarus = ofac["LAZARUS GROUP"]
    assert lazarus.kind == "entity" and lazarus.programs and lazarus.addresses
    assert all(asset and addr for asset, addr in lazarus.addresses)
    assert ofac["MAR AZUL"].kind == "vessel"
    assert ofac["PUTIN, Vladimir Vladimirovich"].kind == "individual"
    assert sum(len(e.addresses) for e in ofac.values()) >= 6


def test_ofac_remarks_continue_in_the_comments_file(snaps):
    # Real rows (2026-10-24): SOUTHFRONT's last address is only in SDN_COMMENTS.CSV, and
    # GARANTEX EUROPE's is cut in two between the files (GCVE-110-PYPI-2026-021807).
    ofac = {e.name: e for e in snaps["OFAC-SDN"].entries}
    assert ("BCH", "qq3vlashthktqpeppuv7trmw070e3mydgq63zq348v") in ofac["SOUTHFRONT"].addresses
    garantex = [x for _, x in ofac["GARANTEX EUROPE OU"].addresses]
    assert "TFwjPScaJRCbSWVAywE1S1WgaUgSnyYUbD" in garantex
    assert "TFwjPScaJRCbSWVAywE1S1WgaU" not in garantex
    assert {"TJkBr9TZ1xBeJoF7RNWqyEMbYqVJ6fXXHR", "TNDjh6WGLYyWmkh8vfu42bXVHUqFNQ3rDq"} <= set(garantex)
    assert len(snaps["OFAC-SDN"].fetched) == 3


def test_a_wallet_only_in_the_comments_file_is_a_hit(svc):
    got = svc.screen(address="TFwjPScaJRCbSWVAywE1S1WgaUgSnyYUbD")
    assert [h["entry"]["name"] for h in got["hits"]] == ["GARANTEX EUROPE OU"], got


def test_eu_entities_carry_names_aliases_and_programmes(snaps):
    eu = snaps["EU"]
    assert eu.published == "2026-10-15" and len(eu.entries) == 2
    putin = next(e for e in eu.entries if "PUTIN" in e.name.upper())
    assert putin.kind == "individual" and len(putin.aliases) >= 3 and putin.programs
    assert any("ПУ" in a for a in putin.aliases)  # the EU lists the Cyrillic spelling too
    assert any(e.kind == "entity" for e in eu.entries)


def test_uk_designations_carry_their_un_numbers(snaps):
    uk = snaps["UK"]
    assert uk.published == "2026-10-16" and len(uk.entries) == 4
    by = {e.ref: e for e in uk.entries}
    akhund = by["AFG0006"]
    assert akhund.name == "MOHAMMAD HASSAN AKHUND" and akhund.kind == "individual"
    assert akhund.un_ref == "TAi.002" and akhund.listed_on == "2001-01-25" and akhund.programs
    assert by["AFG0001"].un_ref == "TAe.010" and by["AFG0001"].kind == "entity"
    assert len(by["AFG0001"].aliases) >= 5
    assert by["RUS0251"].un_ref is None                      # a UK designation, not a UN one
    assert by["DPR0075"].kind == "vessel"


def test_the_un_view_screens_only_entries_with_a_un_number(svc):
    hit = svc.screen(name="Mohammad Hassan Akhund", lists=["UN"])
    assert hit["listed"] and hit["hits"][0]["entry"]["un_ref"] == "TAi.002"
    assert [m["list"] for m in hit["lists"]] == ["UK", "EU"]
    # Putin is on the UK list, but not by a UN decision.
    assert svc.screen(name="Vladimir Putin", lists=["UN"])["listed"] is False
    assert svc.screen(name="Vladimir Putin", lists=["UN", "UK"])["listed"] is True


# ── screening ─────────────────────────────────────────────────────────────────


def test_a_listed_wallet_is_found_whatever_its_case(svc, snaps):
    asset, addr = next((a, x) for e in snaps["OFAC-SDN"].entries for a, x in e.addresses
                       if x.lower().startswith("0x"))
    for variant in (addr, addr.lower(), "0x" + addr[2:].upper()):
        r = svc.screen(address=variant)
        assert r["listed"] and r["hits"][0]["score"] == 1.0
        assert r["hits"][0]["matched"] == "digital currency address"


def test_a_clean_wallet_is_not_listed_and_says_what_was_checked(svc):
    r = svc.screen(address="0x000000000000000000000000000000000000dEaD")
    assert r["listed"] is False and r["hits"] == []
    assert [m["list"] for m in r["lists"]] == ["OFAC-SDN", "EU", "UK"]
    assert all(len(m["sha256"][0]) == 64 for m in r["lists"])
    assert "not a compliance determination" in r["note"]


@pytest.mark.parametrize("name, min_score", [
    ("Vladimir Putin", 0.85), ("putin vladimir", 0.85), ("PUTIN, Vladimir Vladimirovich", 1.0),
    ("Владимир Путин", 0.85),
])
def test_names_match_across_order_case_and_script(svc, name, min_score):
    r = svc.screen(name=name, kind="individual")
    assert r["listed"] and r["hits"][0]["score"] >= min_score
    assert "EU" in {h["entry"]["list"] for h in r["hits"]}


def test_a_typo_plus_a_missing_patronymic_is_below_the_default_bar(svc):
    # A deliberate trade-off between recall and false alarms, documented here: the typo
    # still finds the short names (OFAC's alias, the UK's primary name), the EU's full name
    # needs a lower threshold.
    default = svc.screen(name="Vladimir Puttin", kind="individual")
    assert {h["entry"]["list"] for h in default["hits"]} == {"OFAC-SDN", "UK"}
    lower = svc.screen(name="Vladimir Puttin", kind="individual", threshold=0.8)
    assert {"OFAC-SDN", "EU"} <= {h["entry"]["list"] for h in lower["hits"]}


def test_a_typo_never_scores_as_the_exact_name():
    assert similarity("Vladimir Puttin", "PUTIN, Vladimir") < similarity("Vladimir Putin",
                                                                         "PUTIN, Vladimir")


def test_unrelated_names_are_not_hits(svc):
    for name in ("John Smith", "Deutsche Bank", "Maria Garcia"):
        assert svc.screen(name=name)["listed"] is False


def test_lists_and_kind_narrow_the_screen(svc):
    only_uk = svc.screen(name="Vladimir Putin", lists=["UK"])
    assert only_uk["listed"] is True and [m["list"] for m in only_uk["lists"]] == ["UK"]
    assert svc.screen(name="Vladimir Putin", kind="entity")["listed"] is False


@pytest.mark.parametrize("kw, msg", [
    ({}, "pass address"), ({"name": "x", "lists": ["OFAC"]}, "unknown list"),
    ({"name": "x", "threshold": 0.5}, "threshold must be"), ({"name": "--"}, "no searchable words"),
])
def test_bad_screens_are_refused(svc, kw, msg):
    with pytest.raises(ValueError, match=msg):
        svc.screen(**kw)


def test_no_screen_before_the_lists_load():
    with pytest.raises(UpstreamError, match="not loaded yet.*nothing charged"):
        SanctionsService(loaders={}).screen(name="x")


def test_an_outdated_list_is_refused_not_used(svc, monkeypatch):
    # monkeypatch, not assignment: the snapshot is the module-wide fixture's, and an aged EU
    # list left behind made every later screen of all three lists refuse.
    monkeypatch.setattr(svc._index.snapshots["EU"], "loaded_at", time.time() - 49 * 3600)
    with pytest.raises(UpstreamError, match="older than 48 h: EU"):
        svc.screen(name="Vladimir Putin")
    assert svc.screen(name="Vladimir Putin", lists=["OFAC-SDN"])["listed"]


def test_status_reports_only_what_a_screen_can_use(snaps, monkeypatch):
    """Lists fetched but not yet indexed are not "loaded": /health used to say all three were
    while screens refused them."""
    import symmartys.sanctions as mod

    s = SanctionsService(loaders={k: (lambda v=v: v) for k, v in snaps.items()})
    seen = {}
    build = mod._Index

    def index_being_built(snapshots):
        seen["lists"] = s.status()["lists"]
        with pytest.raises(UpstreamError, match="not loaded yet"):
            s.screen(name="Vladimir Putin")
        return build(snapshots)

    monkeypatch.setattr(mod, "_Index", index_being_built)
    s.refresh()
    assert seen["lists"] == {"OFAC-SDN": None, "EU": None, "UK": None}
    assert all(s.status()["lists"].values())
    assert s.screen(name="Vladimir Putin")["listed"]


def test_a_failed_refresh_keeps_the_last_good_list(snaps):
    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        if calls["n"] > 1:
            raise UpstreamError("down")
        return snaps["UK"]

    s = SanctionsService(loaders={"UK": flaky})
    assert s.refresh() == {}
    assert "UK" in s.refresh()
    assert s.status()["lists"]["UK"]["entries"] == 4 and "down" in s.status()["errors"]["UK"]


def _down():
    raise UpstreamError("upstream HTTP 500")


def test_a_restart_during_an_outage_keeps_the_last_good_lists(snaps, tmp_path):
    """The EU file server answered 500 on 2026-10-16 right after a redeploy: the new
    process must screen with the list the old one saved, under its original evidence."""
    first = SanctionsService(loaders={k: (lambda v=v: v) for k, v in snaps.items()},
                             cache_dir=tmp_path)
    first.refresh()
    before = first.status()["lists"]

    after_restart = SanctionsService(loaders={k: _down for k in snaps}, cache_dir=tmp_path)
    assert sorted(after_restart.load_cache()) == sorted(snaps)
    assert set(after_restart.refresh()) == set(snaps)        # every source is down …
    hit = after_restart.screen(address="0x252a8bd2319d8a555b872990601221b3a2053bce")
    assert hit["listed"]                                       # … and screens still answer
    now = after_restart.status()["lists"]
    for name in snaps:                                         # with the same evidence
        assert now[name]["sha256"] == before[name]["sha256"]
        assert now[name]["fetched_at"] == before[name]["fetched_at"]
    raw = (tmp_path / "sanctions-OFAC-SDN.json.gz").read_bytes()
    assert raw[:2] == b"\x1f\x8b"                             # gzip of JSON, not a pickle


def test_a_cached_list_past_48_hours_is_not_picked_up(snaps, tmp_path, monkeypatch):
    SanctionsService(loaders={"UK": lambda: snaps["UK"]}, cache_dir=tmp_path).refresh()
    later = time.time() + 49 * 3600
    monkeypatch.setattr(time, "time", lambda: later)
    s = SanctionsService(loaders={"UK": _down}, cache_dir=tmp_path)
    assert s.load_cache() == []
    with pytest.raises(UpstreamError, match="not loaded yet: UK"):
        s.screen(name="x", lists=["UK"])


def test_a_missing_list_is_retried_in_minutes_not_hours(snaps):
    from symmartys.sanctions import REFRESH_S, RETRY_S

    s = SanctionsService(loaders={"OFAC-SDN": lambda: snaps["OFAC-SDN"], "EU": _down})
    assert s.next_wait() == RETRY_S                            # nothing loaded yet
    s.refresh()
    assert s.next_wait() == RETRY_S                            # EU failed
    s.loaders["EU"] = lambda: snaps["EU"]
    s.refresh()
    assert s.next_wait() == REFRESH_S                          # all good again


def test_address_normalisation():
    assert norm_address(" 0xABCdef ") == "0xabcdef"
    assert norm_address("BC1QXYZ") == "bc1qxyz"
    assert norm_address("1BoatSLRHtKNngkdXEeobR76b53LETtpyT") == "1BoatSLRHtKNngkdXEeobR76b53LETtpyT"


# ── OpenTimestamps ────────────────────────────────────────────────────────────

HELLO_DIGEST = hashlib.sha256((FIX / "hello-world.txt").read_bytes()).hexdigest()
HELLO_PROOF = base64.b64encode((FIX / "hello-world.txt.ots").read_bytes()).decode()
BLOCK_HASH = (FIX / "btc_358391_hash.txt").read_text().strip()
#: Real mainnet headers 356832 (a difficulty period's first block) to 358391, the block the
#: reference proof lands in.
HEADERS_358 = (FIX / "btc_headers_356832_358391.bin").read_bytes()


def _chain(agreed: int = 358391):
    from symmartys.bitcoin_headers import HeaderChain

    hs = [HEADERS_358[i:i + 80] for i in range(0, len(HEADERS_358), 80)]
    chain = HeaderChain(anchor_height=356832, anchor=hs[0])
    chain.extend(hs[1:])
    chain.agreed_height = agreed
    return chain


def test_the_reference_proof_is_confirmed_by_the_header_chain():
    out = timestamp.verify(HELLO_DIGEST, HELLO_PROOF, upgrade=False, headers=_chain())
    assert out["status"] == "confirmed" and out["existed_by"] == "2015-05-28T15:41:18Z"
    assert out["bitcoin"][0]["height"] == 358391 and out["bitcoin"][0]["block_hash"] == BLOCK_HASH
    assert "agreed by two nodes" in out["bitcoin"][0]["headers"]
    assert out["proof_changed"] is False


def test_a_block_two_nodes_have_not_agreed_on_decides_nothing():
    with pytest.raises(UpstreamError, match="two Bitcoin nodes agreed"):
        timestamp.verify(HELLO_DIGEST, HELLO_PROOF, upgrade=False, headers=_chain(358390))


def test_no_header_chain_no_verdict(monkeypatch):
    monkeypatch.setattr(timestamp, "HEADERS", None)
    with pytest.raises(UpstreamError, match="not loaded"):
        timestamp.verify(HELLO_DIGEST, HELLO_PROOF, upgrade=False)


@pytest.mark.parametrize("digest, proof, msg", [
    ("00" * 32, HELLO_PROOF, "different digest"),
    ("xyz", HELLO_PROOF, "SHA-256 in hex"),
    (HELLO_DIGEST, "not base64!", "base64"),
    (HELLO_DIGEST, base64.b64encode(b"garbage").decode(), "not a valid .ots"),
])
def test_bad_proofs_are_refused_with_a_reason(digest, proof, msg):
    with pytest.raises(ValueError, match=msg):
        timestamp.verify(digest, proof, upgrade=False)


def _calendar_reply(uri: str):
    """What a calendar answers to POST /digest: a timestamp of the submitted message that
    ends in a pending attestation naming the calendar that will hold it."""
    from opentimestamps.core.notary import PendingAttestation
    from opentimestamps.core.op import OpAppend, OpSHA256
    from opentimestamps.core.serialize import StreamSerializationContext
    from opentimestamps.core.timestamp import Timestamp

    def handler(url, sent):
        ts = Timestamp(sent)
        leaf = ts.ops.add(OpAppend(b"\x01" * 4)).ops.add(OpSHA256())
        leaf.attestations.add(PendingAttestation(uri))
        buf = io.BytesIO()
        ts.serialize(StreamSerializationContext(buf))
        return httpx.Response(200, content=buf.getvalue(), request=httpx.Request("POST", url))
    return handler


def test_stamping_needs_two_calendars_and_hides_the_digest(upstream):
    seen = []
    for cal, uri in (("https://a.pool.opentimestamps.org", "https://alice.btc.calendar.opentimestamps.org"),
                     ("https://b.pool.opentimestamps.org", "https://bob.btc.calendar.opentimestamps.org")):
        h = _calendar_reply(uri)
        upstream.handle("POST", f"{cal}/digest",
                        lambda url, sent, h=h: (seen.append(sent), h(url, sent))[1])
    digest = hashlib.sha256(b"a contract").hexdigest()
    out = timestamp.stamp(digest)
    assert out["status"] == "pending" and len(out["calendars"]) == 2
    assert all(s != bytes.fromhex(digest) and len(s) == 32 for s in seen)  # salted
    upstream.on("GET", "https://alice.btc.calendar.opentimestamps.org/timestamp/", 404)
    upstream.on("GET", "https://bob.btc.calendar.opentimestamps.org/timestamp/", 404)
    again = timestamp.verify(digest, out["proof"])
    assert again["status"] == "pending"
    assert again["pending_calendars"] == ["https://alice.btc.calendar.opentimestamps.org",
                                          "https://bob.btc.calendar.opentimestamps.org"]
    assert set(again["calendars_asked"].values()) == {"pending (not yet in a Bitcoin block)"}


def test_stamping_with_one_calendar_is_refused(upstream):
    upstream.handle("POST", "https://a.pool.opentimestamps.org/digest",
                    _calendar_reply("https://alice.btc.calendar.opentimestamps.org"))
    with pytest.raises(UpstreamError, match="only 1 calendar.*nothing charged"):
        timestamp.stamp(hashlib.sha256(b"x").hexdigest())


def test_a_proof_naming_an_unknown_calendar_is_not_followed(upstream):
    upstream.handle("POST", "https://a.pool.opentimestamps.org/digest",
                    _calendar_reply("https://evil.example.com"))
    upstream.handle("POST", "https://b.pool.opentimestamps.org/digest",
                    _calendar_reply("https://evil.example.com"))
    digest = hashlib.sha256(b"y").hexdigest()
    out = timestamp.verify(digest, timestamp.stamp(digest)["proof"])
    assert out["calendars_asked"] == {"https://evil.example.com": "not on the allowlist; not asked"}
    assert not any("evil" in url for _m, url in upstream.calls)


def test_an_ofac_list_cached_before_the_comments_file_is_not_served(snaps, tmp_path):
    """0.4.0 saved OFAC from two files; after an upgrade that snapshot must not screen for up
    to 48 h while the three-file refresh fails (independent review of -021807)."""
    old = Snapshot("OFAC-SDN", snaps["OFAC-SDN"].entries, snaps["OFAC-SDN"].fetched[:2],
                   snaps["OFAC-SDN"].published, time.time())
    SanctionsService(loaders={"OFAC-SDN": lambda: old}, cache_dir=tmp_path).refresh()
    s = SanctionsService(loaders={"OFAC-SDN": _down}, cache_dir=tmp_path)
    assert s.load_cache() == []


def test_a_byte_order_mark_does_not_drop_the_first_continuation():
    sdn = (FIX / "ofac_sdn_excerpt.csv").read_bytes()
    comments = "\ufeff".encode() + (FIX / "ofac_comments_excerpt.csv").read_bytes()
    def f(body: bytes) -> Fetched:
        return Fetched("https://x/2026-10-15/a.csv", 200, body, "t", "h")
    ofac = {e.name: e for e in parse_ofac(f(sdn), None, f(comments)).entries}
    assert ("BCH", "qq3vlashthktqpeppuv7trmw070e3mydgq63zq348v") in ofac["SOUTHFRONT"].addresses
