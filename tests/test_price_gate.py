"""The price gate: EMPORION answers a priced call a trusted hub signed, or 402.

Seen 2026-10-16: an unpaid POST to https://modelmarket.dev/providers/emporion/ai-market/v2/invoke
got a full `emporion.vat.check@v1` answer while the hub that sells it answered 402. The gate
lives in oracle-core (oracle_core/price_gate.py); these pin it for EMPORION's own shape:
served under a path prefix, with upstreams that must not be called for a refused request.
"""

from __future__ import annotations

import base64
import io
import json
import zipfile

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient

gate_mod = pytest.importorskip("oracle_core.price_gate")  # a vendored core older than 0.5 has none

from oracle_core.signing import Signer  # noqa: E402

from emporion.app import build_app  # noqa: E402
from emporion.capabilities import Runtime  # noqa: E402
from emporion.fx import HIST_URL  # noqa: E402
from emporion.middleware import bound_response_canonical  # noqa: E402

PUBLIC = "https://modelmarket.dev/providers/emporion"
HUB = "https://modelmarket.dev"
_HUB_SK = Ed25519PrivateKey.from_private_bytes(b"\x11" * 32)
HUB_KEY = base64.b64encode(_HUB_SK.public_key().public_bytes_raw()).decode()


def _hub_sign(canonical: str) -> str:
    return base64.b64encode(_HUB_SK.sign(canonical.encode())).decode()


def _signed(capability_id, input_payload):
    return gate_mod.sign_request(
        _hub_sign, hub_url=HUB, audience=f"{PUBLIC}/ai-market/v2/invoke",
        capability_id=capability_id, input_payload=input_payload,
    )


@pytest.fixture
def gated(tmp_path, monkeypatch, upstream):
    monkeypatch.setenv("EMPORION_SIGNING_KEY_PATH", str(tmp_path / "k"))
    monkeypatch.setenv("ORACLE_TRUSTED_HUBS", f"{HUB}={HUB_KEY}")
    monkeypatch.delenv("ORACLE_PRICE_GATE", raising=False)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("h.csv", "Date, USD, \n2026-10-15,1.1208,\n")
    upstream.on("GET", HIST_URL, body=buf.getvalue())
    return TestClient(build_app(Runtime(), public_url=PUBLIC))


def test_an_unpaid_direct_call_is_402_and_no_upstream_is_asked(gated, upstream):
    r = gated.post("/ai-market/v2/invoke", json={
        "capability_id": "emporion.vat.check@v1", "input": {"vat": "DE811569869"}})
    assert r.status_code == 402, r.text
    body = r.json()
    assert body["needed"] == 0.002 and body["payment_ways"][0]["hub_url"] == HUB
    assert body["payment_ways"][0]["source_hub"] == PUBLIC
    assert "x-provider-signature" not in r.headers
    assert upstream.calls == [], "VIES was asked for a call nobody paid for"


def test_a_call_the_hub_signed_is_served_and_still_signed_by_emporion(gated):
    payload = {"base": "EUR", "quote": "USD"}
    r = gated.post("/ai-market/v2/invoke", headers=_signed("emporion.fx.rate@v1", payload),
                   json={"capability_id": "emporion.fx.rate@v1", "input": payload})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] and body["output"]["rate"] == "1.1208"
    pub = gated.get("/.well-known/ai-market.json").json()["signer_public_key"]
    canonical = bound_response_canonical("emporion.fx.rate@v1", "", payload, body["output"])
    assert Signer.verify(canonical, r.headers["x-provider-signature"], pub)


def test_a_signature_for_another_input_does_not_buy_this_one(gated, upstream):
    headers = _signed("emporion.vat.check@v1", {"vat": "DE000000000"})
    r = gated.post("/ai-market/v2/invoke", headers=headers, json={
        "capability_id": "emporion.vat.check@v1", "input": {"vat": "DE811569869"}})
    assert r.status_code == 401 and r.json()["error"] == "hub_signature_invalid"
    assert upstream.calls == []


def test_the_free_source_list_stays_open(gated):
    r = gated.post("/ai-market/v2/invoke", json={"capability_id": "emporion.sources@v1", "input": {}})
    assert r.status_code == 200 and r.json()["ok"] is True


def test_the_well_known_says_where_to_buy(gated):
    doc = gated.get("/.well-known/ai-market.json").json()
    assert doc["price_gate"] == {"mode": "enforce", "hubs": [HUB], "scheme": gate_mod.DOMAIN}
    index = gated.get("/").json()
    assert {c["id"] for c in index["capabilities"]} >= {"emporion.vat.check@v1"}


def test_without_a_trusted_hub_it_behaves_as_before(tmp_path, monkeypatch, upstream):
    monkeypatch.setenv("EMPORION_SIGNING_KEY_PATH", str(tmp_path / "k"))
    monkeypatch.delenv("ORACLE_TRUSTED_HUBS", raising=False)
    monkeypatch.delenv("ORACLE_PRICE_GATE", raising=False)
    upstream.on("POST", "https://ec.europa.eu/", json={"valid": False, "userError": "MS_UNAVAILABLE"})
    c = TestClient(build_app(Runtime(), public_url=PUBLIC))
    r = c.post("/ai-market/v2/invoke", json={
        "capability_id": "emporion.vat.check@v1", "input": {"vat": "DE811569869"}})
    assert r.status_code == 200 and json.loads(r.text)["ok"] is False
    assert "price_gate" not in c.get("/.well-known/ai-market.json").json()
