"""SYMMARTYS's own Bitcoin header chain, on real mainnet headers, without the network."""

from __future__ import annotations

import struct

import pytest

from conftest import FIX
from symmartys import bitcoin_headers as bh
from symmartys.bitcoin_headers import (GENESIS, GENESIS_HASH, HeaderChain, HeaderService,
                                      InvalidChain, bits_to_target, block_hash,
                                      parse_headers, target_to_bits)
from symmartys.net import UpstreamError

FIRST_100 = (FIX / "btc_headers_0_100.bin").read_bytes()
RETARGET = (FIX / "btc_headers_30240_32300.bin").read_bytes()  # the first difficulty change


def split(raw: bytes) -> list[bytes]:
    return [raw[i:i + 80] for i in range(0, len(raw), 80)]


def retarget_chain() -> tuple[HeaderChain, list[bytes]]:
    hs = split(RETARGET)
    return HeaderChain(anchor_height=30240, anchor=hs[0]), hs[1:]


def with_field(header: bytes, offset: int, fmt: str, value: int) -> bytes:
    b = bytearray(header)
    struct.pack_into(fmt, b, offset, value)
    return bytes(b)


def test_genesis_and_compact_targets():
    assert block_hash(GENESIS) == GENESIS_HASH == block_hash(FIRST_100[:80])
    for bits in (0x1D00FFFF, 0x1D00D86A, 0x1703A30C, 0x1B0404CB):
        assert target_to_bits(bits_to_target(bits)) == bits


def test_real_headers_through_the_first_retarget_are_accepted():
    chain, hs = retarget_chain()
    assert chain.extend(hs) == len(hs)
    assert chain.height == 32300
    # 32256 is the first block whose difficulty changed, as the rule computes it.
    assert bh.fields(chain.header(32255))["bits"] == 0x1D00FFFF
    assert bh.fields(chain.header(32256))["bits"] == 0x1D00D86A


@pytest.mark.parametrize("change, why", [
    (lambda h: with_field(h, 76, "<I", struct.unpack_from("<I", h, 76)[0] ^ 1), "target"),
    (lambda h: with_field(h, 72, "<I", 0x1D00FFFF), "difficulty"),          # old bits after retarget
    (lambda h: with_field(h, 4, "<I", 0), "link"),
])
def test_a_forged_header_at_the_retarget_is_refused_and_nothing_changes(change, why):
    chain, hs = retarget_chain()
    hs = list(hs)
    i = 32256 - 30241
    hs[i] = change(hs[i])
    with pytest.raises(InvalidChain, match=why):
        chain.extend(hs)
    assert chain.height == 30240


def test_a_header_from_the_future_is_refused():
    chain = HeaderChain(clock=lambda: 1_231_000_000.0)  # before block 1 was mined
    with pytest.raises(InvalidChain, match="future"):
        chain.extend(split(FIRST_100)[1:3])


def test_headers_that_do_not_join_are_refused_and_known_ones_ignored():
    chain, hs = retarget_chain()
    with pytest.raises(InvalidChain, match="do not join"):
        chain.extend(hs[10:20])
    chain.extend(hs[:50])
    assert chain.extend(hs[:20]) == 0 and chain.height == 30290  # a node behind us


def test_agreement_with_a_second_node():
    chain, hs = retarget_chain()
    chain.extend(hs[:1000])
    tip = chain.height
    assert chain.agreement([]) == tip                         # level with us
    assert chain.agreement(hs[500:600]) == 30240 + 600        # behind us: agrees to its tip
    assert chain.agreement(hs[900:1200]) == 30240 + 1200      # ahead: extends us
    assert chain.height == 30240 + 1200
    other = [with_field(h, 76, "<I", 0) for h in hs[1100:1101]]
    assert chain.agreement(other) == -1                       # another chain


def test_blocks_are_served_only_up_to_the_agreed_height():
    chain, hs = retarget_chain()
    chain.extend(hs)
    with pytest.raises(UpstreamError, match="two Bitcoin nodes agreed"):
        chain.block(32000)
    chain.agreed_height = 32100
    b = chain.block(32000)
    assert b["block_hash"] == block_hash(chain.header(32000)) and b["height"] == 32000
    assert len(b["merkle_root"]) == 32
    with pytest.raises(UpstreamError):
        chain.block(32101)


def test_the_chain_is_saved_genesis_first_and_rechecked_on_load(tmp_path):
    path = tmp_path / "h.bin"
    chain = HeaderChain(path)
    chain.extend(split(FIRST_100)[1:])
    assert path.read_bytes() == FIRST_100
    again = HeaderChain(path)
    assert again.load() == 100
    # A tampered file is kept only up to the first header that fails.
    raw = bytearray(FIRST_100)
    raw[60 * 80 + 79] ^= 1
    path.write_bytes(bytes(raw))
    assert HeaderChain(path).load() == 59


def test_parse_headers_message():
    hs = split(FIRST_100)[1:4]
    payload = bytes([3]) + b"".join(h + b"\x00" for h in hs)
    assert parse_headers(payload) == hs


class FakePeer:
    def __init__(self, answers):
        self.answers = list(answers)

    def getheaders(self, locator):
        return self.answers.pop(0) if self.answers else []

    def close(self):
        pass


def test_the_service_syncs_from_one_node_and_needs_a_second_to_agree():
    chain, hs = retarget_chain()
    peers = {"1.1.0.1": FakePeer([hs[:2000], hs[2000:]]),
             "1.1.0.2": FakePeer([[]]),                # same /16 as the first: not asked
             "2.2.0.1": FakePeer([[]])}
    svc = HeaderService(chain, connect=lambda ip: peers[ip],
                        discover_peers=lambda: ["1.1.0.1", "1.1.0.2", "2.2.0.1"])
    st = svc.refresh()
    assert st["height"] == 32300 and st["agreed_height"] == 32300
    assert set(st["peers"]) == {"1.1.0.1", "2.2.0.1"}


def test_without_a_second_node_nothing_is_agreed():
    chain, hs = retarget_chain()
    svc = HeaderService(chain, connect=lambda ip: FakePeer([hs]),
                        discover_peers=lambda: ["1.1.0.1", "1.1.0.2"])
    with pytest.raises(UpstreamError, match="no second Bitcoin node"):
        svc.refresh()
    assert chain.agreed_height == -1
