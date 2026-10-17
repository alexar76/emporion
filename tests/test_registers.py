"""RDAP, company registers, EORI and business days on real answer shapes, without the network."""

from __future__ import annotations

import json

import pytest

from conftest import FIX
from emporion import eori, rdap, registries, sources, workdays
from emporion.net import UpstreamError, fetch

BOOT = {"publication": "2026-09-30T23:00:03Z", "services": [
    [["com", "net"], ["https://rdap.verisign.com/com/v1/"]],
    [["uk"], ["https://rdap.nominet.uk/uk/"]],
    [["kg"], ["http://rdap.cctld.kg/"]],
]}


@pytest.fixture
def boot(upstream, monkeypatch):
    monkeypatch.setitem(sources.DYNAMIC_HOSTS, "iana_rdap", frozenset())
    upstream.on("GET", rdap.BOOTSTRAP_URL, json=BOOT)
    return rdap.Bootstrap()


# ── RDAP ─────────────────────────────────────────────────────────────────────


def test_a_domain_is_looked_up_at_its_registry(upstream, boot):
    upstream.on("GET", "https://rdap.verisign.com/com/v1/domain/example.com",
                body=(FIX / "rdap_example_com.json").read_bytes())
    out = rdap.lookup("https://www.Example.com/path", bootstrap=boot)
    assert out["domain"] == "example.com" and out["registered"] is True
    assert out["created"] == "1995-08-14T04:00:00Z" and out["age_days"] > 11000
    assert out["registrar"] == {"name": "RESERVED-Internet Assigned Numbers Authority",
                                "iana_id": "376"}
    assert out["evidence"]["url"] == "https://rdap.verisign.com/com/v1/domain/example.com"
    # www.example.com was asked first and is unknown; the registrable name answered.
    asked = [u for m, u in upstream.calls if "/domain/" in u]
    assert asked == ["https://rdap.verisign.com/com/v1/domain/www.example.com",
                     "https://rdap.verisign.com/com/v1/domain/example.com"]


def test_an_unregistered_domain_is_an_answer(upstream, boot):
    out = rdap.lookup("free-name-zz9.com", bootstrap=boot)
    assert out == {**out, "registered": False, "domain": "free-name-zz9.com"}


def test_only_hosts_in_ianas_file_are_asked(upstream, boot):
    boot.get()
    assert sources.DYNAMIC_HOSTS["iana_rdap"] == {"rdap.verisign.com", "rdap.nominet.uk"}
    with pytest.raises(UpstreamError, match="not approved"):
        fetch("https://rdap.attacker.example/domain/x.com", source_id="iana_rdap")
    # Dynamic hosts are approved for RDAP only.
    with pytest.raises(UpstreamError, match="not approved"):
        fetch("https://rdap.verisign.com/x", source_id="gleif")
    upstream.on("GET", "https://rdap.verisign.com/com/v1/domain/", 302,
                headers={"location": "https://rdap.attacker.example/"})
    with pytest.raises(UpstreamError, match="not approved"):
        rdap.lookup("example.com", bootstrap=boot)


def test_tlds_without_https_rdap_cost_nothing(boot):
    with pytest.raises(ValueError, match="no RDAP service"):
        rdap.lookup("google.de", bootstrap=boot)
    with pytest.raises(ValueError, match="plain http only"):
        rdap.lookup("example.kg", bootstrap=boot)
    with pytest.raises(ValueError, match="not a registrable domain"):
        rdap.lookup("localhost", bootstrap=boot)


def test_a_bootstrap_outage_keeps_yesterdays_file(upstream, boot, monkeypatch):
    boot.get()
    monkeypatch.setattr(rdap, "BOOTSTRAP_TTL_S", -1)
    upstream.on("GET", rdap.BOOTSTRAP_URL, 503)
    assert "com" in boot.get()


# ── company registers ────────────────────────────────────────────────────────


def test_norway_by_number(upstream):
    upstream.on("GET", f"{registries.BRREG}/923609016",
                body=(FIX / "brreg_923609016.json").read_bytes())
    out = registries.lookup("no", number="923 609 016")
    c = out["companies"][0]
    assert out["found"] and c["name"] == "EQUINOR ASA" and c["status"] == "active"
    assert c["vat"] == "NO923609016MVA" and c["founded"] == "1972-09-18"
    assert c["address"] == "Forusbeen 50, 4035 STAVANGER, Norge"
    assert out["evidence"]["licence"].startswith("Norwegian Licence")


def test_norway_unknown_and_deleted(upstream):
    upstream.on("GET", f"{registries.BRREG}/974760673", 404)
    assert registries.lookup("NO", number="974760673")["found"] is False
    upstream.on("GET", f"{registries.BRREG}/974760673", 410,
                json={"organisasjonsnummer": "974760673", "navn": "X AS",
                      "slettedato": "2020-01-01"})
    assert registries.lookup("NO", number="974760673")["companies"][0]["status"] == "deleted"
    with pytest.raises(ValueError, match="check digit"):
        registries.lookup("NO", number="923609017")


def test_france_by_siret_keeps_only_the_exact_siren(upstream):
    data = json.loads((FIX / "fr_search_552032534.json").read_text())
    data["results"].insert(0, {**data["results"][0], "siren": "999999999", "nom_complet": "X"})
    upstream.on("GET", registries.FR_SEARCH, json=data)
    out = registries.lookup("FR", number="552 032 534 00703")
    assert [c["number"] for c in out["companies"]] == ["552032534"]
    c = out["companies"][0]
    assert c["name"] == "DANONE" and c["vat"] == "FR27552032534" and c["status"] == "active"


def test_czechia_by_number_and_by_name(upstream):
    body = (FIX / "ares_00177041.json").read_bytes()
    upstream.on("GET", f"{registries.ARES}/00177041", body=body)
    c = registries.lookup("CZ", number="177041")["companies"][0]
    assert c["name"] == "Škoda Auto a.s." and c["vat"] == "CZ00177041"
    assert c["address"].endswith("29301 Mladá Boleslav") and c["status"] == "active"
    upstream.on("POST", f"{registries.ARES}/vyhledat",
                json={"pocetCelkem": 1, "ekonomickeSubjekty": [{**json.loads(body),
                                                                "datumZaniku": "2024-01-01"}]})
    c = registries.lookup("CZ", name="Škoda")["companies"][0]
    assert c["status"] == "dissolved"


def test_registers_refuse_what_they_cannot_answer():
    with pytest.raises(ValueError, match="no open company register for DE"):
        registries.lookup("DE", number="1")
    with pytest.raises(ValueError, match="number, or a name"):
        registries.lookup("NO", name="x")


# ── EORI ─────────────────────────────────────────────────────────────────────


def test_eori_valid_and_not_valid(upstream):
    upstream.on("POST", eori.URL, body=(FIX / "eos_cz_nl.xml").read_bytes())
    out = eori.check(["cz 00177041", "NL004495445"])
    by = {r["eori"]: r for r in out["results"]}
    assert by["CZ00177041"]["valid"] is True and by["CZ00177041"]["name"] == "Škoda Auto a.s."
    assert by["NL004495445"]["valid"] is False and "name" not in by["NL004495445"]
    assert out["checked_on"] == "17/10/2026" and out["evidence"]["source"].startswith("EU EORI")
    sent = upstream.calls[-1]
    assert sent == ("POST", eori.URL)


def test_eori_faults_and_bad_input(upstream):
    upstream.on("POST", eori.URL, 500)
    with pytest.raises(UpstreamError, match="unreachable"):
        eori.check(["CZ00177041"])
    upstream.on("POST", eori.URL, 200, body='<S:Envelope xmlns:S="http://schemas.xmlsoap.org/'
                'soap/envelope/"><S:Body><S:Fault><faultstring>busy</faultstring></S:Fault>'
                '</S:Body></S:Envelope>')
    with pytest.raises(UpstreamError, match="busy"):
        eori.check(["CZ00177041"])
    with pytest.raises(ValueError, match="not an EORI"):
        eori.check(["<x/>"])
    with pytest.raises(ValueError, match="at most 10"):
        eori.check(["CZ1"] * 11)


# ── business days ────────────────────────────────────────────────────────────


def test_business_days_in_bavaria_over_new_year():
    out = workdays.check(country="DE", subdiv="BY", date="2026-12-24", add_business_days=3,
                         until="2027-01-08")
    assert out["is_business_day"] and out["holiday"] is None
    assert out["next_business_day"] == "2026-12-28"  # 25th and 26th are holidays
    assert out["result_date"] == "2026-12-30"
    assert out["business_days_between"] == 8  # 1 Jan and 6 Jan (Bavaria) excluded
    assert out["evidence"]["licence"] == "MIT"


def test_target2_and_a_friday_saturday_weekend():
    out = workdays.check(market="XECB", date="2026-04-03")
    assert out["is_business_day"] is False and out["holiday"] == "Good Friday"
    assert out["next_business_day"] == "2026-04-07"
    sa = workdays.check(country="SA", date="2026-10-16")  # Saudi Arabia: Friday off
    assert sa["is_business_day"] is False and "Friday" in sa["weekend"]


def test_a_years_holidays_and_refusals():
    fr = workdays.check(country="FR", list_year=2027, language="en_US")["holidays"]
    assert {"date": "2027-07-14", "name": "National Day"} in fr
    for kwargs, why in [({}, "either country"), ({"country": "ZZ"}, "no calendar"),
                        ({"country": "DE", "subdiv": "XX"}, "no subdivision"),
                        ({"market": "NOPE"}, "unknown market"),
                        ({"country": "DE", "add_business_days": 5000}, "within"),
                        ({"country": "DE", "date": "17.10.2026"}, "YYYY-MM-DD")]:
        with pytest.raises(ValueError, match=why):
            workdays.check(**kwargs)


# ── Finland and the United Kingdom ───────────────────────────────────────────


def test_finland_by_business_id(upstream):
    upstream.on("GET", f"{registries.PRH}?businessId=0112038-9",
                body=(FIX / "prh_0112038-9.json").read_bytes())
    c = registries.lookup("FI", number="01120389")["companies"][0]
    assert c["name"] == "Nokia Oyj" and c["status"] == "active" and c["vat"] == "FI01120389"
    assert c["legal_form"] == "Public limited company"
    assert c["address"] == "Karakaari 7, 02610 ESPOO, Finland"
    with pytest.raises(ValueError, match="check digit"):
        registries.lookup("FI", number="0112038-8")


def test_finland_name_search_is_ranked_and_reads_situations(upstream):
    nokia = json.loads((FIX / "prh_0112038-9.json").read_text())["companies"][0]
    nokian = {**nokia, "businessId": {"value": "0205709-4"},
              "names": [{"name": "Nokian Vuokrakodit Oy", "type": "1"}]}
    bankrupt = {**nokia, "businessId": {"value": "0101120-3"},
                "names": [{"name": "Nokia Old Oy", "type": "1", "endDate": "2001-01-01"}],
                "companySituations": [{"type": "KONK", "registrationDate": "2000-01-01"}]}
    upstream.on("GET", f"{registries.PRH}?name=nokia",
                json={"totalResults": 3, "companies": [bankrupt, nokian, nokia]})
    got = registries.lookup("FI", name="nokia")["companies"]
    assert [c["name"] for c in got] == ["Nokia Oyj", "Nokia Old Oy", "Nokian Vuokrakodit Oy"]
    assert got[1]["status"] == "bankrupt"


GB_COMPANY = {"company_name": "TESCO PLC", "company_number": "00445790",
              "company_status": "active", "type": "plc", "date_of_creation": "1947-11-27",
              "registered_office_address": {"address_line_1": "Tesco House", "locality":
                                            "Welwyn Garden City", "postal_code": "AL7 1GA"},
              "sic_codes": ["47110"], "jurisdiction": "england-wales"}


def test_britain_is_offered_only_with_the_operators_key(upstream, monkeypatch):
    monkeypatch.delenv("COMPANIES_HOUSE_API_KEY", raising=False)
    assert "GB" not in registries.available()
    with pytest.raises(ValueError, match="Companies House API key"):
        registries.lookup("GB", number="445790")
    assert upstream.calls == []
    monkeypatch.setenv("COMPANIES_HOUSE_API_KEY", "test-key")
    assert "GB" in registries.available()
    upstream.on("GET", f"{registries.CH}/company/00445790", json=GB_COMPANY)
    c = registries.lookup("GB", number="445790")["companies"][0]
    assert c["name"] == "TESCO PLC" and c["status"] == "active" and c["founded"] == "1947-11-27"
    assert c["address"] == "Tesco House, Welwyn Garden City, AL7 1GA"
    upstream.on("GET", f"{registries.CH}/company/SC000001", 404)
    assert registries.lookup("GB", number="sc000001")["found"] is False
    with pytest.raises(ValueError, match="UK company number"):
        registries.lookup("GB", number="12-34")


def test_the_key_goes_in_a_header_never_into_the_evidence(upstream, monkeypatch):
    monkeypatch.setenv("COMPANIES_HOUSE_API_KEY", "secret-key-123")
    upstream.on("GET", f"{registries.CH}/company/00445790", json=GB_COMPANY)
    out = registries.lookup("GB", number="00445790")
    assert "secret-key-123" not in json.dumps(out)
    assert registries._ch_headers()["Authorization"] == "Basic c2VjcmV0LWtleS0xMjM6"
