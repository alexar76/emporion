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
        "bitcoin_headers", "Bitcoin block headers from the Bitcoin P2P network", "Public chain data",
        "Block headers are public consensus data that every Bitcoin node serves; EMPORION keeps "
        "its own copy from the genesis block, checks each header's proof of work and "
        "difficulty, and uses a header only once a second node on another network agrees.",
        "Bitcoin network (headers fetched peer to peer)",
        (),
    ),
    "eos": Source(
        "eos", "EU EORI validation (European Commission, EOS)",
        "European Commission reuse policy (Decision 2011/833/EU)",
        "A public verification service of the European Commission for Economic Operators "
        "Registration and Identification numbers; name and address appear only where the "
        "operator consented to their publication. EMPORION stores nothing.",
        "European Commission, EORI validation (EOS)",
        ("ec.europa.eu",),
        "https://ec.europa.eu/taxation_customs/dds2/eos/eori_validation.jsp",
    ),
    "brreg": Source(
        "brreg", "Brønnøysund Register Centre — Central Coordinating Register for Legal Entities (Norway)",
        "Norwegian Licence for Open Government Data (NLOD) 2.0",
        "Open data of the Norwegian state; free reuse with attribution.",
        "Brønnøysundregistrene, Enhetsregisteret (NLOD 2.0)",
        ("data.brreg.no",),
        "https://data.norge.no/nlod/en/2.0",
    ),
    "recherche_entreprises": Source(
        "recherche_entreprises", "API Recherche d'entreprises (France: SIRENE and the RNE)",
        "Licence Ouverte / Open Licence 2.0 (Etalab)",
        "French public-sector open data from INSEE's SIRENE register and the national "
        "register of companies, served by the State's digital directorate (DINUM).",
        "DINUM, API Recherche d'entreprises (INSEE SIRENE, INPI RNE), Licence Ouverte 2.0",
        ("recherche-entreprises.api.gouv.fr",),
        "https://www.etalab.gouv.fr/licence-ouverte-open-licence/",
    ),
    "ares": Source(
        "ares", "ARES — Administrative Register of Economic Subjects (Czech Republic)",
        "Czech public administration open data",
        "Published by the Czech Ministry of Finance for free public use.",
        "Ministerstvo financí ČR, ARES",
        ("ares.gov.cz",),
        "https://ares.gov.cz/stranky/vyvojar-info",
    ),
    "prh": Source(
        "prh", "PRH / YTJ open data — Finnish Trade Register and Business Information System",
        "Creative Commons Attribution 4.0 (CC BY 4.0)",
        "Open data of the Finnish Patent and Registration Office and the Tax Administration.",
        "Finnish Patent and Registration Office (PRH), YTJ open data, CC BY 4.0",
        ("avoindata.prh.fi",),
        "https://www.prh.fi/en/presentation_and_duties/opendata.html",
    ),
    "companies_house": Source(
        "companies_house", "Companies House — UK register of companies",
        "Open Government Licence v3.0",
        "Public register data of the UK Registrar of Companies; the API needs a free key, held "
        "by the operator.",
        "Contains public sector information from Companies House, licensed under the Open "
        "Government Licence v3.0",
        ("api.company-information.service.gov.uk",),
        "https://www.nationalarchives.gov.uk/doc/open-government-licence/version/3/",
    ),
    "iana_rdap": Source(
        "iana_rdap", "RDAP — domain registration data (IANA bootstrap, then the TLD registry)",
        "Public registration data (RFC 9083)",
        "IANA's bootstrap file names each TLD's RDAP service; the answer is what that "
        "registry publishes. Only registries named in IANA's file are asked.",
        "IANA RDAP bootstrap and the TLD registry's RDAP service",
        ("data.iana.org",),
        "https://www.iana.org/help/rdap-faq",
    ),
    "web": Source(
        "web", "A web page the caller names (web capture)",
        "The page's own terms; EMPORION returns it to the caller as evidence only",
        "EMPORION fetches one page once, as a browser would, and records what it answered. "
        "The content belongs to its publisher.",
        "The publisher of the captured page",
        (),
    ),
    "holidays": Source(
        "holidays", "python-holidays — public holidays and market calendars", "MIT",
        "An open-source library compiled into EMPORION: no network at answer time.",
        "python-holidays (vacanza/holidays), MIT",
        (),
        "https://github.com/vacanza/holidays/blob/dev/LICENSE",
    ),
}

ALLOWED_HOSTS: frozenset[str] = frozenset(h for s in SOURCES.values() for h in s.hosts)
#: Hosts approved at run time by a source's own root of trust — RDAP servers named in
#: IANA's bootstrap file. Filled only by the module that loaded that file.
DYNAMIC_HOSTS: dict[str, frozenset[str]] = {}


def source(source_id: str) -> Source:
    try:
        return SOURCES[source_id]
    except KeyError:
        raise ValueError(f"source not approved: {source_id}") from None


__all__ = ["ALLOWED_HOSTS", "DYNAMIC_HOSTS", "SOURCES", "Source", "source"]
