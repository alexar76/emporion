"""EMPORION's capabilities: public-record facts for agents that trade.

    emporion.vat.check@v1          $0.002  EU VAT number validity (VIES), with the
                                           consultation number when the caller names
                                           its own VAT number as requester
    emporion.lei.lookup@v1         $0.001  legal entity by LEI or by name (GLEIF, CC0),
                                           with direct and ultimate parents
    emporion.fx.rate@v1            $0.001  ECB euro reference rate for any pair on any
                                           date since 1999, and a conversion
    emporion.sanctions.screen@v1   $0.002  a wallet address or a name against OFAC SDN,
                                           the EU and the UK lists (UN designations through
                                           them, with their UN numbers) — a lookup, not a
                                           compliance determination
    emporion.timestamp.stamp@v1    $0.001  anchor a SHA-256 digest in Bitcoin through
                                           the OpenTimestamps calendars
    emporion.timestamp.verify@v1   $0.001  upgrade and verify an OpenTimestamps proof
                                           against EMPORION's own Bitcoin header chain
    emporion.web.capture@v1        $0.003  a web page as evidence: final URL, redirects, IP,
                                           status, headers, TLS certificate, body SHA-256
                                           (and the body), the record anchored in Bitcoin
    emporion.domain.rdap@v1        $0.001  who registered a domain and when (RDAP, from the
                                           TLD's registry via IANA's bootstrap)
    emporion.company.lookup@v1     $0.001  a company in its national register (NO, FR, CZ, FI;
                                           GB with the operator's Companies House key)
    emporion.eori.check@v1         $0.002  EU EORI number validity (European Commission)
    emporion.calendar.check@v1     $0.001  business days: holidays and weekends of ~250
                                           countries and of markets (TARGET2, NYSE, LSE…)
    emporion.timer.set@v1          $0.002  a signed callback at a time, or a dead man's switch
    emporion.timer.checkin@v1      free    keep a dead man's switch from firing
    emporion.timer.cancel@v1       free    cancel a timer
    emporion.timer.status@v1       free    a timer's state and last delivery
    emporion.sources@v1            free    every source's licence and, for the lists and
                                           rates, the version EMPORION holds now

Every answer carries its evidence (source URL, fetch time, SHA-256 of what came back)
and the gateway's signed receipt. A source that cannot answer is ok:false — the hub
charges nothing for that.
"""

from __future__ import annotations

import os
from typing import Any

from oracle_core import Capability, OracleSpec

from emporion import (__version__, capture, eori, lei, rdap, registries, timestamp, vat,
                      workdays)
from emporion.fx import FxService
from emporion.sanctions import DEFAULT_THRESHOLD, LISTS, SanctionsService
from emporion.sources import SOURCES
from emporion.bitcoin_headers import HeaderChain, HeaderService
from emporion.timers import TimerService

PRODUCT = "emporion"


class Runtime:
    def __init__(self, *, sanctions: SanctionsService | None = None, fx: FxService | None = None,
                 timers: TimerService | None = None, bitcoin: HeaderService | None = None):
        self.sanctions = sanctions or SanctionsService()
        self.fx = fx or FxService()
        self.timers = timers or TimerService()
        self.bitcoin = bitcoin or HeaderService(HeaderChain())


def _evidence_note() -> dict[str, Any]:
    return {"type": "object", "description": "source, url, fetched_at, sha256, attribution, licence"}


VAT_IN = {
    "type": "object",
    "properties": {
        "vat": {"type": "string", "maxLength": 20, "default": "NL004495445B01",
                "description": "EU VAT number with its country prefix (DE…, FR…, EL… for Greece)"},
        "country": {"type": "string", "maxLength": 2,
                    "description": "optional prefix, if vat carries only the number"},
        "requester_vat": {"type": "string", "maxLength": 20,
                          "description": "YOUR OWN EU VAT number: VIES then issues a "
                                         "consultation number proving the check in your name"},
    },
    "required": ["vat"],
}
LEI_IN = {
    "type": "object",
    "properties": {
        "lei": {"type": "string", "maxLength": 24, "description": "20-character LEI"},
        "name": {"type": "string", "maxLength": 120, "description": "legal name to search"},
        "limit": {"type": "integer", "minimum": 1, "maximum": 10, "default": 5},
        "parents": {"type": "boolean", "default": True},
    },
    "anyOf": [{"required": ["lei"]}, {"required": ["name"]}],
}
FX_IN = {
    "type": "object",
    "properties": {
        "base": {"type": "string", "minLength": 3, "maxLength": 3, "default": "USD"},
        "quote": {"type": "string", "minLength": 3, "maxLength": 3, "default": "EUR"},
        "date": {"type": "string", "description": "YYYY-MM-DD; default the latest ECB day"},
        "amount": {"type": ["number", "string"], "description": "optional amount in base to convert"},
    },
    "required": ["base", "quote"],
}
SCREEN_IN = {
    "type": "object",
    "properties": {
        "address": {"type": "string", "maxLength": 128,
                    "description": "a wallet address (EVM, Bitcoin, Tron, …)"},
        "name": {"type": "string", "maxLength": 200, "description": "a person or entity"},
        "kind": {"type": "string", "enum": ["individual", "entity", "vessel", "aircraft"]},
        "lists": {"type": "array", "items": {"type": "string", "enum": [*LISTS, "UN"]},
                  "description": "default all; UN = the UK and EU entries with a UN number"},
        "threshold": {"type": "number", "minimum": 0.7, "maximum": 1.0,
                      "default": DEFAULT_THRESHOLD},
        "limit": {"type": "integer", "minimum": 1, "maximum": 50, "default": 10},
    },
    "anyOf": [{"required": ["address"]}, {"required": ["name"]}],
}
STAMP_IN = {
    "type": "object",
    "properties": {"digest": {"type": "string", "minLength": 64, "maxLength": 64,
                              "description": "SHA-256 of your document, hex"}},
    "required": ["digest"],
}
VERIFY_IN = {
    "type": "object",
    "properties": {
        "digest": {"type": "string", "minLength": 64, "maxLength": 64},
        "proof": {"type": "string", "description": "base64 of the .ots proof"},
        "upgrade": {"type": "boolean", "default": True},
    },
    "required": ["digest", "proof"],
}

CAPTURE_IN = {
    "type": "object",
    "properties": {
        "url": {"type": "string", "maxLength": 2048, "default": "https://example.com/",
                "description": "an http(s) page on a public host, port 80 or 443"},
        "include_body": {"type": "boolean", "default": True,
                         "description": "return the body (base64) when it is 512 KB or less"},
        "anchor": {"type": "boolean", "default": True,
                   "description": "anchor record_sha256 in Bitcoin (OpenTimestamps)"},
    },
    "required": ["url"],
}
RDAP_IN = {
    "type": "object",
    "properties": {"domain": {"type": "string", "maxLength": 253, "default": "example.com",
                              "description": "a domain name; a URL or subdomain is reduced "
                                             "to the registered name"}},
    "required": ["domain"],
}
COMPANY_IN = {
    "type": "object",
    "properties": {
        "country": {"type": "string", "enum": list(registries.COUNTRIES), "default": "NO"},
        "number": {"type": "string", "maxLength": 20, "default": "923609016",
                   "description": "NO organisation number, FR SIREN or SIRET, CZ IČO, FI "
                                  "Business ID, GB company number"},
        "name": {"type": "string", "maxLength": 120, "description": "or a name to search"},
        "limit": {"type": "integer", "minimum": 1, "maximum": 10, "default": 5},
    },
    "required": ["country"],
    "anyOf": [{"required": ["number"]}, {"required": ["name"]}],
}
EORI_IN = {
    "type": "object",
    "properties": {
        "eori": {"type": "string", "maxLength": 20, "default": "CZ00177041"},
        "eoris": {"type": "array", "items": {"type": "string", "maxLength": 20},
                  "maxItems": eori.MAX_NUMBERS, "description": "or up to 10 numbers at once"},
    },
    "anyOf": [{"required": ["eori"]}, {"required": ["eoris"]}],
}
CALENDAR_IN = {
    "type": "object",
    "properties": {
        "country": {"type": "string", "maxLength": 2, "default": "DE",
                    "description": "ISO 3166 alpha-2"},
        "subdiv": {"type": "string", "maxLength": 10, "description": "region, e.g. BY"},
        "market": {"type": "string", "maxLength": 6,
                   "description": "instead of country: XECB (TARGET2), XNYS, XLON, …"},
        "date": {"type": "string", "description": "YYYY-MM-DD; default today (UTC)"},
        "add_business_days": {"type": "integer", "minimum": -1000, "maximum": 1000},
        "until": {"type": "string", "description": "YYYY-MM-DD: count business days to it"},
        "list_year": {"type": "integer", "minimum": 1950, "maximum": 2100},
        "language": {"type": "string", "maxLength": 8, "description": "holiday names, e.g. en_US"},
    },
}
TIMER_SET_IN = {
    "type": "object",
    "properties": {
        "callback": {"type": "string", "maxLength": 2048,
                     "description": "https URL on a public host; receives a signed POST"},
        "at": {"type": "string", "description": "ISO 8601 time with zone"},
        "after_seconds": {"type": "number", "minimum": 60, "maximum": 90 * 86400},
        "deadman_seconds": {"type": "integer", "minimum": 60, "maximum": 30 * 86400,
                            "description": "fire unless checked in within this many seconds"},
        "payload": {"description": "any JSON, up to 4 KB, delivered as event.payload"},
    },
    "required": ["callback"],
}
TIMER_REF_IN = {
    "type": "object",
    "properties": {"timer_id": {"type": "string", "maxLength": 40},
                   "token": {"type": "string", "maxLength": 64}},
    "required": ["timer_id", "token"],
}


def build_spec(runtime: Runtime, public_url: str | None = None) -> OracleSpec:
    url = public_url or os.environ.get("EMPORION_PUBLIC_URL", "http://localhost:9351")

    def vat_handler(d: dict[str, Any]) -> dict[str, Any]:
        return vat.check(str(d.get("vat", "")), country=d.get("country"),
                         requester_vat=d.get("requester_vat"))

    def lei_handler(d: dict[str, Any]) -> dict[str, Any]:
        return lei.lookup(d.get("lei"), d.get("name"), limit=int(d.get("limit") or 5),
                          parents=bool(d.get("parents", True)))

    def fx_handler(d: dict[str, Any]) -> dict[str, Any]:
        return runtime.fx.rate(str(d.get("base", "")), str(d.get("quote", "")), d.get("date"),
                               d.get("amount"))

    def screen_handler(d: dict[str, Any]) -> dict[str, Any]:
        lists = d.get("lists")
        if lists is not None and not isinstance(lists, list):
            raise ValueError("lists must be an array of OFAC-SDN, EU, UK, UN")
        return runtime.sanctions.screen(
            address=d.get("address"), name=d.get("name"), kind=d.get("kind"), lists=lists,
            threshold=float(d.get("threshold", DEFAULT_THRESHOLD)),
            limit=int(d.get("limit") or 10))

    # GB is offered only where the operator holds a Companies House key.
    company_in = {**COMPANY_IN, "properties": {
        **COMPANY_IN["properties"],
        "country": {**COMPANY_IN["properties"]["country"], "enum": registries.available()}}}
    countries = {"NO": "Norway (Brønnøysund)", "FR": "France (SIRENE/RNE)",
                 "CZ": "Czech Republic (ARES)", "FI": "Finland (PRH)",
                 "GB": "United Kingdom (Companies House)"}
    company_where = ", ".join(countries[c] for c in registries.available())

    def sources_handler(d: dict[str, Any]) -> dict[str, Any]:
        out = {"sources": [{"id": s.source_id, "name": s.name, "licence": s.licence,
                            "basis": s.basis, "attribution": s.attribution,
                            "licence_url": s.licence_url} for s in SOURCES.values()],
               "sanctions": runtime.sanctions.status(), "calendars": workdays.supported(),
               "timers": runtime.timers.counts(), "bitcoin_headers": runtime.bitcoin.status(),
               "version": __version__}
        try:
            out["ecb_latest"] = runtime.fx.table().latest.isoformat()
        except Exception as exc:  # noqa: BLE001 — a status page reports, it does not fail
            out["ecb_latest"] = f"unavailable ({type(exc).__name__})"
        return out

    caps = [
        Capability(
            capability_id="emporion.vat.check@v1",
            description="Is this EU VAT number valid today? Asks VIES (the member state's "
                        "registry): valid, registered name and address, check time. Pass "
                        "requester_vat (your own EU VAT number) to get VIES's consultation "
                        "number — official proof of the check in your name. A registry that "
                        "is down costs nothing.",
            handler=vat_handler, product_id=PRODUCT, input_schema=VAT_IN,
            price_per_call_usd=0.002, p50_latency_ms=1500,
        ),
        Capability(
            capability_id="emporion.lei.lookup@v1",
            description="Who is this legal entity? GLEIF LEI record by LEI (check digits "
                        "verified locally) or by name (ranked candidates): legal name, "
                        "jurisdiction, legal form, status, addresses, registration and "
                        "renewal, direct and ultimate parents. CC0.",
            handler=lei_handler, product_id=PRODUCT, input_schema=LEI_IN,
            price_per_call_usd=0.001, p50_latency_ms=1200,
        ),
        Capability(
            capability_id="emporion.fx.rate@v1",
            description="ECB euro reference rate for any pair on any date since 1999 (the "
                        "latest ECB day on or before it, named), cross rates through the "
                        "euro in Decimal, optional amount rounded to the currency's minor "
                        "units. Reference rate, not a dealing rate.",
            handler=fx_handler, product_id=PRODUCT, input_schema=FX_IN,
            price_per_call_usd=0.001, p50_latency_ms=20,
        ),
        Capability(
            capability_id="emporion.sanctions.screen@v1",
            description="Is this wallet address or name on a public sanctions list? OFAC "
                        "SDN (incl. ~500 digital-currency addresses), EU and UK lists — UN "
                        "designations through them, each hit with its UN number — with each "
                        "list's date and SHA-256. A lookup, not a compliance determination.",
            handler=screen_handler, product_id=PRODUCT, input_schema=SCREEN_IN,
            price_per_call_usd=0.002, p50_latency_ms=40,
        ),
        Capability(
            capability_id="emporion.timestamp.stamp@v1",
            description="Prove a document existed: anchor its SHA-256 in Bitcoin through "
                        "the public OpenTimestamps calendars (at least two). Returns a "
                        "standard .ots proof; calendars see only a salted hash, never your "
                        "digest. Confirmation follows in a few hours.",
            handler=lambda d: timestamp.stamp(str(d.get("digest", ""))),
            product_id=PRODUCT, input_schema=STAMP_IN,
            price_per_call_usd=0.001, p50_latency_ms=4000,
        ),
        Capability(
            capability_id="emporion.timestamp.verify@v1",
            description="Upgrade and verify an OpenTimestamps proof: confirmed when its "
                        "result equals the Merkle root of the Bitcoin block header EMPORION "
                        "holds from the Bitcoin network itself (proof of work checked, agreed "
                        "by two nodes); returns the block, its time and the upgraded proof.",
            handler=lambda d: timestamp.verify(str(d.get("digest", "")), str(d.get("proof", "")),
                                               upgrade=bool(d.get("upgrade", True)),
                                               headers=runtime.bitcoin.chain),
            product_id=PRODUCT, input_schema=VERIFY_IN,
            price_per_call_usd=0.001, p50_latency_ms=3000,
        ),
        Capability(
            capability_id="emporion.web.capture@v1",
            description="A web page as evidence: EMPORION fetches the URL once and returns "
                        "the final URL, every redirect, the IP, status, key headers, the TLS "
                        "certificate and the SHA-256 of the body (and the body, up to 512 KB); "
                        "the record's SHA-256 is anchored in Bitcoin. Public hosts only. An "
                        "unreachable host costs nothing.",
            handler=lambda d: capture.capture(str(d.get("url", "")),
                                              include_body=bool(d.get("include_body", True)),
                                              anchor=bool(d.get("anchor", True))),
            product_id=PRODUCT, input_schema=CAPTURE_IN,
            price_per_call_usd=0.003, p50_latency_ms=3000,
        ),
        Capability(
            capability_id="emporion.domain.rdap@v1",
            description="Who registered this domain and when? RDAP from the TLD's own "
                        "registry (found through IANA's bootstrap): created, updated, "
                        "expires, age in days, registrar, status, nameservers, DNSSEC. Or "
                        "registered: false. A TLD without RDAP costs nothing.",
            handler=lambda d: rdap.lookup(str(d.get("domain", ""))),
            product_id=PRODUCT, input_schema=RDAP_IN,
            price_per_call_usd=0.001, p50_latency_ms=800,
        ),
        Capability(
            capability_id="emporion.company.lookup@v1",
            description="Is this company real and alive? Its national register by number "
                        f"or name: {company_where}. Name, status, legal form, founding date, "
                        "address, VAT number where published, plus the register's own fields.",
            handler=lambda d: registries.lookup(str(d.get("country", "")),
                                                number=d.get("number"), name=d.get("name"),
                                                limit=int(d.get("limit") or 5)),
            product_id=PRODUCT, input_schema=company_in,
            price_per_call_usd=0.001, p50_latency_ms=700,
        ),
        Capability(
            capability_id="emporion.eori.check@v1",
            description="Is this EORI number valid for EU customs? The European Commission's "
                        "EOS service, up to 10 numbers per call; name and address where the "
                        "operator consented to publication. A service that is down costs "
                        "nothing.",
            handler=lambda d: eori.check(list(d.get("eoris") or []) or [str(d.get("eori", ""))]),
            product_id=PRODUCT, input_schema=EORI_IN,
            price_per_call_usd=0.002, p50_latency_ms=1000,
        ),
        Capability(
            capability_id="emporion.calendar.check@v1",
            description="Business days: is this date a working day in a country (or region) "
                        "or on a market (TARGET2, NYSE, LSE…), the holiday's name, next and "
                        "previous business day, date + N business days, business days "
                        "between two dates, a year's holidays. Offline, python-holidays.",
            handler=lambda d: workdays.check(
                country=d.get("country") if not d.get("market") else None,
                market=d.get("market"), subdiv=d.get("subdiv"), date=d.get("date"),
                add_business_days=d.get("add_business_days"), until=d.get("until"),
                list_year=d.get("list_year"), language=d.get("language")),
            product_id=PRODUCT, input_schema=CALENDAR_IN,
            price_per_call_usd=0.001, p50_latency_ms=5,
        ),
        Capability(
            capability_id="emporion.timer.set@v1",
            description="Wake me later: a signed POST to your https callback at a time (or "
                        "after N seconds), or a dead man's switch that fires unless you check "
                        "in every N seconds. Returns timer_id and a token, once. Retried "
                        "after 1, 5 and 30 minutes; at most 90 days.",
            handler=lambda d: runtime.timers.set(
                callback=str(d.get("callback", "")), at=d.get("at"),
                after_seconds=d.get("after_seconds"), deadman_seconds=d.get("deadman_seconds"),
                payload=d.get("payload")),
            product_id=PRODUCT, input_schema=TIMER_SET_IN,
            price_per_call_usd=0.002, p50_latency_ms=300,
        ),
        Capability(
            capability_id="emporion.timer.checkin@v1",
            description="Free. Check in to a dead man's switch: its deadline moves "
                        "deadman_seconds ahead. Needs the timer's token.",
            handler=lambda d: runtime.timers.checkin(str(d.get("timer_id", "")),
                                                     str(d.get("token", ""))),
            product_id=PRODUCT, input_schema=TIMER_REF_IN,
            price_per_call_usd=0.0, p50_latency_ms=5,
        ),
        Capability(
            capability_id="emporion.timer.cancel@v1",
            description="Free. Cancel a timer before it fires. Needs the timer's token.",
            handler=lambda d: runtime.timers.cancel(str(d.get("timer_id", "")),
                                                    str(d.get("token", ""))),
            product_id=PRODUCT, input_schema=TIMER_REF_IN,
            price_per_call_usd=0.0, p50_latency_ms=5,
        ),
        Capability(
            capability_id="emporion.timer.status@v1",
            description="Free. A timer's state (armed, retrying, fired, failed, cancelled, "
                        "expired), its deadline and its last delivery. Needs the token.",
            handler=lambda d: runtime.timers.status(str(d.get("timer_id", "")),
                                                    str(d.get("token", ""))),
            product_id=PRODUCT, input_schema=TIMER_REF_IN,
            price_per_call_usd=0.0, p50_latency_ms=5,
        ),
        Capability(
            capability_id="emporion.sources@v1",
            description="Free. Every EMPORION source with its licence and attribution, the "
                        "sanctions lists it holds now (publication date, entries, SHA-256, "
                        "age) and the latest ECB rate day.",
            handler=sources_handler, product_id=PRODUCT,
            price_per_call_usd=0.0, p50_latency_ms=5,
        ),
    ]
    return OracleSpec(
        name="EMPORION — public-record facts for agents that trade",
        product_id=PRODUCT,
        description="EU VAT validity (VIES), legal entities (GLEIF LEI), national company "
                    "registers, EORI numbers, domain registrations (RDAP), ECB reference "
                    "rates, sanctions-list lookups (OFAC SDN with wallet addresses, EU, UK with "
                    "UN designations), "
                    "business-day calendars, Bitcoin-anchored timestamps (OpenTimestamps), web "
                    "pages captured as evidence, and timers with a dead man's switch — each "
                    "answer signed, with the source, fetch time and SHA-256 of what the source "
                    "returned.",
        public_url=url,
        categories=["commerce", "compliance", "kyb", "vat", "lei", "fx", "sanctions",
                    "timestamping", "notary", "bitcoin", "eori", "rdap", "company-registry",
                    "business-days", "web-capture", "scheduling"],
        capabilities=caps,
        signing_key_path=os.environ.get("EMPORION_SIGNING_KEY_PATH", "data/emporion_signing_key"),
        version=__version__,
        related=["aimarket-hub", "gaia", "histor", "attested"],
    )


__all__ = ["PRODUCT", "Runtime", "build_spec"]
