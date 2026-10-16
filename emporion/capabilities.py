"""EMPORION's capabilities: public-record facts for agents that trade.

    emporion.vat.check@v1          $0.002  EU VAT number validity (VIES), with the
                                           consultation number when the caller names
                                           its own VAT number as requester
    emporion.lei.lookup@v1         $0.001  legal entity by LEI or by name (GLEIF, CC0),
                                           with direct and ultimate parents
    emporion.fx.rate@v1            $0.001  ECB euro reference rate for any pair on any
                                           date since 1999, and a conversion
    emporion.sanctions.screen@v1   $0.002  a wallet address or a name against OFAC SDN,
                                           the EU and the UN lists — a lookup, not a
                                           compliance determination
    emporion.timestamp.stamp@v1    $0.001  anchor a SHA-256 digest in Bitcoin through
                                           the OpenTimestamps calendars
    emporion.timestamp.verify@v1   $0.001  upgrade and verify an OpenTimestamps proof
                                           against Bitcoin headers from two explorers
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

from emporion import __version__, lei, timestamp, vat
from emporion.fx import FxService
from emporion.sanctions import DEFAULT_THRESHOLD, LISTS, SanctionsService
from emporion.sources import SOURCES

PRODUCT = "emporion"


class Runtime:
    def __init__(self, *, sanctions: SanctionsService | None = None, fx: FxService | None = None):
        self.sanctions = sanctions or SanctionsService()
        self.fx = fx or FxService()


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
        "lists": {"type": "array", "items": {"type": "string", "enum": list(LISTS)}},
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
            raise ValueError("lists must be an array of OFAC-SDN, EU, UN")
        return runtime.sanctions.screen(
            address=d.get("address"), name=d.get("name"), kind=d.get("kind"), lists=lists,
            threshold=float(d.get("threshold", DEFAULT_THRESHOLD)),
            limit=int(d.get("limit") or 10))

    def sources_handler(d: dict[str, Any]) -> dict[str, Any]:
        out = {"sources": [{"id": s.source_id, "name": s.name, "licence": s.licence,
                            "basis": s.basis, "attribution": s.attribution,
                            "licence_url": s.licence_url} for s in SOURCES.values()],
               "sanctions": runtime.sanctions.status(), "version": __version__}
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
                        "SDN (incl. ~500 digital-currency addresses), EU and UN lists, with "
                        "each list's publication date and SHA-256. A lookup, not a "
                        "compliance determination; an outdated list is refused, not used.",
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
                        "result equals the Merkle root of a Bitcoin block whose header two "
                        "independent explorers agree on; returns the block, its time and "
                        "the upgraded proof. Pending until then.",
            handler=lambda d: timestamp.verify(str(d.get("digest", "")), str(d.get("proof", "")),
                                               upgrade=bool(d.get("upgrade", True))),
            product_id=PRODUCT, input_schema=VERIFY_IN,
            price_per_call_usd=0.001, p50_latency_ms=3000,
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
        description="EU VAT validity (VIES), legal entities (GLEIF LEI), ECB reference rates, "
                    "sanctions-list lookups (OFAC SDN with wallet addresses, EU, UN) and "
                    "Bitcoin-anchored timestamps (OpenTimestamps) — each answer signed, with "
                    "the source, fetch time and SHA-256 of what the source returned.",
        public_url=url,
        categories=["commerce", "compliance", "kyb", "vat", "lei", "fx", "sanctions",
                    "timestamping", "notary", "bitcoin"],
        capabilities=caps,
        signing_key_path=os.environ.get("EMPORION_SIGNING_KEY_PATH", "data/emporion_signing_key"),
        version=__version__,
        related=["aimarket-hub", "gaia", "histor", "attested"],
    )


__all__ = ["PRODUCT", "Runtime", "build_spec"]
