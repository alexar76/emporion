"""The app: manifest, prices, signed receipts, provider signatures, refusals that cost nothing."""

from __future__ import annotations

import base64
import io
import json
import re
import sys
import tomllib
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from symmartys import __version__
from symmartys.app import build_app
from symmartys.capabilities import Runtime
from symmartys.fx import HIST_URL
from symmartys.middleware import bound_response_canonical

ROOT = Path(__file__).resolve().parents[1]
PRICES = {
    "symmartys.vat.check@v1": 0.002, "symmartys.lei.lookup@v1": 0.001,
    "symmartys.fx.rate@v1": 0.001, "symmartys.sanctions.screen@v1": 0.002,
    "symmartys.timestamp.stamp@v1": 0.001, "symmartys.timestamp.verify@v1": 0.001,
    "symmartys.web.capture@v1": 0.003, "symmartys.domain.rdap@v1": 0.001,
    "symmartys.company.lookup@v1": 0.001, "symmartys.eori.check@v1": 0.002,
    "symmartys.calendar.check@v1": 0.001, "symmartys.timer.set@v1": 0.002,
    "symmartys.timer.checkin@v1": 0.0, "symmartys.timer.cancel@v1": 0.0,
    "symmartys.timer.status@v1": 0.0, "symmartys.sources@v1": 0.0,
}


@pytest.fixture
def client(tmp_path, monkeypatch, upstream):
    monkeypatch.setenv("SYMMARTYS_SIGNING_KEY_PATH", str(tmp_path / "k"))
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("h.csv", "Date, USD, \n2026-10-15,1.1208,\n")
    upstream.on("GET", HIST_URL, body=buf.getvalue())
    return TestClient(build_app(Runtime(), public_url="http://symmartys.test"))


def test_the_version_matches_the_package():
    meta = tomllib.loads((ROOT / "pyproject.toml").read_text())
    assert meta["project"]["version"] == __version__


def test_every_capability_is_listed_at_its_price(client):
    manifest = client.get("/ai-market/v2/manifest").json()
    tools = {t["capability_id"]: t for t in manifest["tools"]}
    assert {k: tools[k]["price_per_call_usd"] for k in tools} == PRICES
    assert manifest["signature"]
    for t in tools.values():
        assert len(t["description"]) <= 600 and t["input_schema"]["type"] == "object"


def test_a_paid_answer_is_signed_twice(client):
    r = client.post("/ai-market/v2/invoke", json={
        "capability_id": "symmartys.fx.rate@v1", "input": {"base": "EUR", "quote": "USD"}})
    body = r.json()
    assert r.status_code == 200 and body["ok"] and body["output"]["rate"] == "1.1208"
    assert body["receipt"]["price_usd"] == 0.001 and body["receipt"]["signature"]
    assert r.headers["x-provider-signature"]


def test_a_source_that_cannot_answer_is_ok_false_and_unsigned(client, upstream):
    upstream.on("POST", "https://ec.europa.eu/", json={"valid": False, "userError": "MS_UNAVAILABLE"})
    body = client.post("/ai-market/v2/invoke", json={
        "capability_id": "symmartys.vat.check@v1", "input": {"vat": "DE811569869"}}).json()
    assert body["ok"] is False and "nothing charged" in body["error"] and "receipt" not in body


def test_screening_before_the_lists_load_costs_nothing(client):
    body = client.post("/ai-market/v2/invoke", json={
        "capability_id": "symmartys.sanctions.screen@v1", "input": {"address": "0xabc"}}).json()
    assert body["ok"] is False and "not loaded yet" in body["error"]


def test_gb_is_in_the_manifest_only_with_a_companies_house_key(client, tmp_path, monkeypatch):
    def countries(c):
        tools = {t["capability_id"]: t for t in c.get("/ai-market/v2/manifest").json()["tools"]}
        return tools["symmartys.company.lookup@v1"]["input_schema"]["properties"]["country"]["enum"]

    monkeypatch.delenv("COMPANIES_HOUSE_API_KEY", raising=False)
    assert countries(client) == ["NO", "FR", "CZ", "FI"]
    monkeypatch.setenv("COMPANIES_HOUSE_API_KEY", "k")
    keyed = TestClient(build_app(Runtime(), public_url="http://symmartys.test"))
    assert countries(keyed) == ["NO", "FR", "CZ", "FI", "GB"]


def test_sources_and_health(client):
    out = client.post("/ai-market/v2/invoke", json={
        "capability_id": "symmartys.sources@v1", "input": {}}).json()["output"]
    ids = {s["id"] for s in out["sources"]}
    assert ids == {"vies", "gleif", "ecb", "ofac", "eu_fsf", "uk_fcdo", "opentimestamps",
                   "bitcoin_headers", "eos", "brreg", "recherche_entreprises", "ares",
                   "prh", "companies_house", "iana_rdap", "web", "holidays"}
    assert 200 < out["calendars"]["countries"] < 300 and "XECB" in out["calendars"]["markets"]
    assert out["timers"] == {}
    assert out["ecb_latest"] == "2026-10-15"
    health = client.get("/health").json()
    assert health["status"] == "ok" and health["capabilities"] == len(PRICES)
    assert client.get("/").json()["capabilities"][0]["id"] == "symmartys.vat.check@v1"


def _hub_canonical():
    """The hub's own _bound_response_canonical, lifted out of its source with ast and run
    alone (it needs only json and hashlib) — a comparison with the hub, not with a copy."""
    import ast

    hub = ROOT.parent / "aimarket-hub" / "aimarket_hub" / "supply_security.py"
    if not hub.exists():
        pytest.skip("standalone checkout without the hub")
    tree = ast.parse(hub.read_text())
    fn = next(n for n in tree.body
              if isinstance(n, ast.FunctionDef) and n.name == "_bound_response_canonical")
    module = ast.Module(body=[ast.Import(names=[ast.alias(name="json")]), fn], type_ignores=[])
    scope: dict = {}
    exec(compile(ast.fix_missing_locations(module), str(hub), "exec"), scope)
    return scope["_bound_response_canonical"]


@pytest.mark.parametrize("cap, product, inp, result", [
    ("symmartys.fx.rate@v1", "symmartys", {"quote": "USD", "base": "EUR"}, {"rate": "1.1208"}),
    ("symmartys.vat.check@v1", "", None, {"name": "Société Générale — Zürich", "n": [1, 2.5]}),
    ("symmartys.sources@v1", "symmartys", {}, {"nested": {"b": 1, "a": [None, True]}}),
])
def test_the_signed_canonical_is_the_hubs_own(cap, product, inp, result):
    assert bound_response_canonical(cap, product, inp, result) == \
        _hub_canonical()(cap, product, inp, result)


def test_the_middleware_is_gaias():
    gaia = ROOT.parent / "gaia" / "gaia" / "middleware.py"
    if not gaia.exists():
        pytest.skip("standalone checkout")
    mine = (ROOT / "symmartys" / "middleware.py").read_text().split("\n", 1)[1]
    assert mine == gaia.read_text().split("\n", 1)[1]
