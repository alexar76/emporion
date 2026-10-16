"""Where EMPORION's facts come from, under which licence, from which hosts.

A positive registry, like GAIA's source_policy: a source missing here cannot be
fetched (net.py refuses its host), and every answer carries the attribution of the
source it relays. Hosts are exact names; redirects are followed only to a host listed
for the same source (OFAC and the UN publish through presigned storage URLs).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Source:
    source_id: str
    name: str
    licence: str
    basis: str
    attribution: str
    hosts: tuple[str, ...]
    licence_url: str = ""


SOURCES: dict[str, Source] = {
    "vies": Source(
        "vies", "EU VIES — VAT Information Exchange System (European Commission)",
        "European Commission reuse policy (Decision 2011/833/EU)",
        "A public verification service of the European Commission; the answer is what "
        "the member state's registry returned at request time. EMPORION stores nothing.",
        "European Commission, VIES",
        ("ec.europa.eu",),
        "https://ec.europa.eu/taxation_customs/vies/#/help",
    ),
    "gleif": Source(
        "gleif", "GLEIF — Global LEI Index", "CC0 1.0",
        "LEI reference data are published under CC0; no restriction on commercial use.",
        "Global Legal Entity Identifier Foundation (GLEIF), CC0",
        ("api.gleif.org",),
        "https://www.gleif.org/en/meta/lei-data-terms-of-use",
    ),
    "ecb": Source(
        "ecb", "ECB euro foreign exchange reference rates", "ECB reuse with source acknowledgement",
        "Reproduction is authorised provided the source is acknowledged. Reference rates "
        "are for information only, not dealing rates.",
        "Source: European Central Bank (euro foreign exchange reference rates)",
        ("www.ecb.europa.eu",),
        "https://www.ecb.europa.eu/services/disclaimer/html/index.en.html",
    ),
    "ofac": Source(
        "ofac", "U.S. Treasury OFAC — Specially Designated Nationals (SDN) list",
        "U.S. Government work (public domain)",
        "A U.S. federal government publication, free of copyright.",
        "U.S. Department of the Treasury, Office of Foreign Assets Control (SDN list)",
        ("sanctionslistservice.ofac.treas.gov",
         "wc2h-sls-prod-public-published.s3.us-gov-west-1.amazonaws.com"),
        "https://ofac.treasury.gov/sanctions-list-service",
    ),
    "eu_fsf": Source(
        "eu_fsf", "EU consolidated list of persons, groups and entities subject to financial sanctions",
        "European Commission reuse policy (Decision 2011/833/EU)",
        "Commission documents may be reused with acknowledgement of the source.",
        "European Commission, Financial Sanctions Files (FSF)",
        ("webgate.ec.europa.eu",),
        "https://data.europa.eu/data/datasets/consolidated-list-of-persons-groups-and-entities-subject-to-eu-financial-sanctions",
    ),
    "un": Source(
        "un", "UN Security Council Consolidated List", "United Nations public information",
        "Published by the UN Security Council for implementation by states and the public.",
        "United Nations Security Council Consolidated List",
        ("scsanctions.un.org", "unsolprodfiles.blob.core.windows.net"),
        "https://main.un.org/securitycouncil/en/content/un-sc-consolidated-list",
    ),
    "opentimestamps": Source(
        "opentimestamps", "OpenTimestamps public calendars", "Free public service",
        "Calendars aggregate digests into Bitcoin transactions; a proof is verified against "
        "the Bitcoin block header, not against the calendar.",
        "OpenTimestamps (opentimestamps.org)",
        # The aggregators a digest is submitted to, and the calendars their pending
        # attestations name (and are upgraded from) — different hosts, both needed.
        ("a.pool.opentimestamps.org", "b.pool.opentimestamps.org",
         "a.pool.eternitywall.com", "ots.btc.catallaxy.com",
         "alice.btc.calendar.opentimestamps.org", "bob.btc.calendar.opentimestamps.org",
         "finney.calendar.eternitywall.com", "btc.calendar.catallaxy.com"),
        "https://opentimestamps.org/",
    ),
    "bitcoin_headers": Source(
        "bitcoin_headers", "Bitcoin block headers (two independent explorers)", "Public chain data",
        "Block headers are public consensus data; two explorers must agree before a proof "
        "is called confirmed.",
        "Bitcoin block headers via mempool.space and blockstream.info",
        ("mempool.space", "blockstream.info"),
    ),
}

ALLOWED_HOSTS: frozenset[str] = frozenset(h for s in SOURCES.values() for h in s.hosts)


def source(source_id: str) -> Source:
    try:
        return SOURCES[source_id]
    except KeyError:
        raise ValueError(f"source not approved: {source_id}") from None


__all__ = ["ALLOWED_HOSTS", "SOURCES", "Source", "source"]
