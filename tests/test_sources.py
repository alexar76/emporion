"""Network layer, VAT, LEI and FX on real answer shapes, without the network."""

from __future__ import annotations

import hashlib
import io
import json
import zipfile

import pytest

from conftest import FIX
from symmartys import lei, vat
from symmartys.fx import HIST_URL, FxService
from symmartys.net import UpstreamError, fetch

VIES = "https://ec.europa.eu/taxation_customs/vies/rest-api/check-vat-number"
GLEIF = "https://api.gleif.org/api/v1"


# ── net ───────────────────────────────────────────────────────────────────────


def test_a_host_outside_the_source_is_refused(upstream):
    with pytest.raises(UpstreamError, match="not approved for gleif"):
        fetch("https://evil.example.com/x", source_id="gleif")
    with pytest.raises(UpstreamError, match="not approved for gleif"):
        fetch("https://ec.europa.eu/x", source_id="gleif")  # allowed, but for another source
    assert upstream.calls == []


def test_redirects_are_followed_only_to_the_sources_hosts(upstream):
    store = "https://wc2h-sls-prod-public-published.s3.us-gov-west-1.amazonaws.com/Published/x/2026-10-15/y/SDN.CSV?sig=1"
    upstream.on("GET", "https://sanctionslistservice.ofac.treas.gov/", 302, headers={"location": store})
    upstream.on("GET", store.split("?")[0], 200, body="a,b")
    got = fetch("https://sanctionslistservice.ofac.treas.gov/api/x/SDN.CSV", source_id="ofac")
    assert got.body == b"a,b" and got.url == store
    upstream.on("GET", "https://sanctionslistservice.ofac.treas.gov/", 302,
                headers={"location": "https://attacker.example/steal"})
    with pytest.raises(UpstreamError, match="not approved for ofac"):
        fetch("https://sanctionslistservice.ofac.treas.gov/api/x/SDN.CSV", source_id="ofac")


def test_dropped_connections_and_5xx_are_retried(upstream):
    upstream.on("GET", "https://api.gleif.org/", 200, body="{}")
    upstream.drop = 2
    assert fetch(f"{GLEIF}/x", source_id="gleif").body == b"{}"
    upstream.on("GET", "https://api.gleif.org/", 503)
    with pytest.raises(UpstreamError, match="unreachable.*HTTP 503"):
        fetch(f"{GLEIF}/x", source_id="gleif")


def test_a_body_over_the_cap_is_refused(upstream):
    upstream.on("GET", "https://api.gleif.org/", 200, body=b"x" * 2000)
    with pytest.raises(UpstreamError, match="over"):
        fetch(f"{GLEIF}/x", source_id="gleif", max_bytes=1000)


def test_every_answer_carries_its_evidence(upstream):
    upstream.on("GET", "https://api.gleif.org/", 200, body=b"hello")
    ev = fetch(f"{GLEIF}/x?q=1", source_id="gleif").evidence("gleif")
    assert ev["sha256"] == hashlib.sha256(b"hello").hexdigest()
    assert ev["url"] == f"{GLEIF}/x" and ev["licence"] == "CC0 1.0"


# ── VAT ───────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("raw, country, want", [
    ("DE 811.569-869", None, ("DE", "811569869")),
    ("de811569869", None, ("DE", "811569869")),
    ("811569869", "de", ("DE", "811569869")),
    ("GR094014201", None, ("EL", "094014201")),
    ("EL094014201", None, ("EL", "094014201")),
    ("094014201", "GR", ("EL", "094014201")),
    ("XI123456789", None, ("XI", "123456789")),
])
def test_vat_numbers_are_normalised(raw, country, want):
    assert vat.split_vat(raw, country) == want


@pytest.mark.parametrize("raw, msg", [("US123456789", "not a VIES member state"),
                                      ("GB123456789", "not a VIES member state"),
                                      ("DE1", "2-14 letters or digits")])
def test_non_eu_or_malformed_vat_is_refused_locally(raw, msg, upstream):
    with pytest.raises(ValueError, match=msg):
        vat.check(raw)
    assert upstream.calls == []


def _vies(**kw):
    base = {"countryCode": "NL", "vatNumber": "004495445B01", "requestDate": "2026-10-16T05:13:58Z",
            "valid": True, "requestIdentifier": "", "name": "OPENJONGERENVERENIGING DE KOORNBEURS",
            "address": "\nVOLDERSGRACHT 00001\n2611ET DELFT\n"}
    return {**base, **kw}


def test_a_valid_number_with_the_consultation_number(upstream):
    sent = {}

    def handler(url, body):
        sent.update(body)
        import httpx
        return httpx.Response(200, json=_vies(requestIdentifier="WAPIAAAAZ1x"),
                              request=httpx.Request("POST", url))

    upstream.handle("POST", VIES, handler)
    out = vat.check("NL004495445B01", requester_vat="DE811569869")
    assert sent == {"countryCode": "NL", "vatNumber": "004495445B01",
                    "requesterMemberStateCode": "DE", "requesterNumber": "811569869"}
    assert out["valid"] and out["consultation_number"] == "WAPIAAAAZ1x"
    assert out["address"] == "VOLDERSGRACHT 00001, 2611ET DELFT"
    assert out["requester_vat"] == "DE811569869"
    assert out["evidence"]["source"].startswith("EU VIES")


def test_an_invalid_number_is_an_answer(upstream):
    upstream.on("POST", VIES, json=_vies(valid=False, name="---", address="---"))
    out = vat.check("NL000000000B01")
    assert out["valid"] is False and out["name"] is None and out["consultation_number"] is None
    assert "pass requester_vat" in out["note"]


@pytest.mark.parametrize("error", ["MS_UNAVAILABLE", "MS_MAX_CONCURRENT_REQ", "TIMEOUT"])
def test_a_registry_that_does_not_answer_costs_nothing(upstream, error):
    upstream.on("POST", VIES, json=_vies(valid=False, userError=error))
    with pytest.raises(UpstreamError, match=f"did not answer \\({error}\\); nothing charged"):
        vat.check("NL004495445B01")


def test_vies_refusing_the_format_is_explained(upstream):
    upstream.on("POST", VIES, 400, json={"actionSucceed": False,
                                          "errorWrappers": [{"error": "INVALID_INPUT"}]})
    with pytest.raises(ValueError, match="refused the input.*INVALID_INPUT"):
        vat.check("DE12345")


# ── LEI ───────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("code, ok", [("7LTWFZYICNSX8D621K86", True),
                                      ("7LTWFZYICNSX8D621K87", False),
                                      ("529900J2KCFIPEYJIE34", True),
                                      ("7LTWFZYICNSX8D621K8", False),
                                      ("7ltwfzyicnsx8d621k86", False)])
def test_lei_check_digits(code, ok):
    assert lei.lei_checksum_ok(code) is ok


def test_a_typo_in_an_lei_is_caught_without_a_request(upstream):
    with pytest.raises(ValueError, match="not a valid LEI.*typo"):
        lei.lookup(lei="7LTWFZYICNSX8D621K87")
    assert upstream.calls == []


def test_lookup_by_lei_with_parents(upstream):
    record = json.loads((FIX / "gleif_record_deutsche_bank.json").read_text())
    # Routes are tried newest first: the record's prefix also prefixes its parent URLs.
    upstream.on("GET", f"{GLEIF}/lei-records/7LTWFZYICNSX8D621K86", json=record)
    upstream.on("GET", f"{GLEIF}/lei-records/7LTWFZYICNSX8D621K86/", 404)
    out = lei.lookup(lei="7ltw fzyi cnsx 8d62 1k86".upper())
    rec = out["record"]
    assert out["found"] and rec["legal_name"] == "DEUTSCHE BANK AKTIENGESELLSCHAFT"
    assert rec["jurisdiction"] == "DE" and rec["registration_status"] == "ISSUED"
    assert rec["direct_parent"] is None and rec["ultimate_parent"] is None
    assert out["evidence"]["attribution"].endswith("CC0")


def test_a_well_formed_lei_gleif_does_not_hold(upstream):
    upstream.on("GET", f"{GLEIF}/lei-records/529900J2KCFIPEYJIE34", 404)
    assert lei.lookup(lei="529900J2KCFIPEYJIE34", parents=False)["found"] is False


def test_name_search_ranks_the_active_full_name_first(upstream):
    upstream.on("GET", f"{GLEIF}/fuzzycompletions",
                json=json.loads((FIX / "gleif_fuzzy_deutsche_bank.json").read_text()))
    upstream.on("GET", f"{GLEIF}/lei-records?filter[entity.names]",
                json=json.loads((FIX / "gleif_names_deutsche_bank.json").read_text()))
    upstream.on("GET", f"{GLEIF}/lei-records?filter[lei]", json={"data": []})
    out = lei.lookup(name="Deutsche Bank", limit=3)
    top = out["candidates"][0]
    assert top["entity_status"] == "ACTIVE" and "BANK" in top["legal_name"].upper()
    assert top["match_score"] >= 0.98
    assert all(c["match_score"] <= top["match_score"] for c in out["candidates"])


# ── FX ────────────────────────────────────────────────────────────────────────


def _ecb_zip() -> bytes:
    csv_text = ("Date, USD, JPY, RUB, GBP, CHF, \n"
                "2026-10-15,1.1208,177.06,N/A,0.8590,0.9400,\n"
                "2026-10-14,1.1200,176.50,N/A,0.8600,0.9410,\n"
                "2026-10-09,1.1100,175.00,N/A,0.8550,0.9390,\n"
                "2022-02-28,1.1240,129.77,117.0,0.8384,1.0328,\n"
                "1999-01-04,1.1789,133.73,25.2,0.7111,1.6168,\n")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("eurofxref-hist.csv", csv_text)
    return buf.getvalue()


@pytest.fixture
def fx(upstream):
    upstream.on("GET", HIST_URL, body=_ecb_zip())
    return FxService()


def test_a_cross_rate_goes_through_the_euro(fx):
    out = fx.rate("USD", "JPY", amount="100")
    assert out["rate"] == str((__import__("decimal").Decimal("177.06") /
                               __import__("decimal").Decimal("1.1208")).quantize(
        __import__("decimal").Decimal("1e-8")).normalize())
    assert out["converted"] == "15798" and out["via"] == "EUR"  # yen has no minor units
    assert out["ecb_date"] == "2026-10-15" and out["evidence"]["source"].startswith("ECB")


def test_a_weekend_date_names_the_ecb_day_used(fx):
    out = fx.rate("EUR", "USD", on="2026-10-11")  # a Sunday
    assert out["ecb_date"] == "2026-10-09" and out["rate"] == "1.11"


def test_a_currency_the_ecb_stopped_quoting_is_refused(fx):
    with pytest.raises(ValueError, match="no ECB RUB rate within two weeks"):
        fx.rate("RUB", "EUR")
    assert fx.rate("RUB", "EUR", on="2022-02-28")["rate"] == str(
        (__import__("decimal").Decimal(1) / __import__("decimal").Decimal("117.0")).quantize(
            __import__("decimal").Decimal("1e-8")).normalize())


@pytest.mark.parametrize("args, msg", [
    (("USD", "XAU"), "does not publish XAU"),
    (("US", "EUR"), "ISO 4217"),
    (("USD", "EUR", "1998-12-31"), "start on 1999-01-04"),
    (("USD", "EUR", "15/10/2026"), "YYYY-MM-DD"),
])
def test_fx_refuses_with_a_reason(fx, args, msg):
    with pytest.raises(ValueError, match=msg):
        fx.rate(*args)


def test_fx_amount_must_be_a_number(fx):
    with pytest.raises(ValueError, match="amount must be"):
        fx.rate("USD", "EUR", amount="lots")


def test_a_failed_refresh_keeps_the_last_table(fx, upstream, monkeypatch):
    fx.table()
    import symmartys.fx as fxmod

    monkeypatch.setattr(fxmod, "REFRESH_S", -1)
    upstream.on("GET", HIST_URL, 404)
    assert fx.rate("EUR", "USD")["rate"] == "1.1208"
