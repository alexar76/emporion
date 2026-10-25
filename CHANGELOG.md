# Changelog

## 0.4.2 — 2026-10-25

- **Fix: page capture accepted IPv6 addresses that carry a private IPv4 one.** The capture guard
  unwrapped IPv4-mapped addresses only, so a name answering with a NAT64 (`64:ff9b::a00:5`, which
  Python calls global) or 6to4 (`2002::/16`) form of a private or metadata address passed. Both are
  now judged by the IPv4 address inside, as signal-hunt 0.1.2 does after Vulnetix
  GCVE-110-PYPI-2026-021946.

## 0.4.1 — 2026-10-24

- **Fix: OFAC wallet screening missed more than half of the listed addresses.** OFAC cuts a
  remark too long for `SDN.CSV` and continues it in `SDN_COMMENTS.CSV`, mid-word and sometimes
  mid-address. EMPORION read only `SDN.CSV`: on 2026-10-24 it held 499 of the 1,050 listed
  addresses, screened the other 538 (e.g. most of Garantex's, SUEX's and Hydra's) as not listed,
  and kept 17 cut halves as if they were addresses. The comments file is now fetched with the
  SDN list, joined to each remark before addresses are read, and a list load fails without it.
  An OFAC snapshot cached by 0.4.0 (two files) is not served after the upgrade, and the CSV
  files are read with any byte-order mark removed.
  Reported by Vulnetix as GCVE-110-PYPI-2026-021807 (CWE-693); thank you.
- 164 tests.

## 0.4.0 — 2026-10-17

- UN Security Council designations now come through the UK Sanctions List (FCDO, Open Government
  Licence v3.0), which gives each UN designation the UK implements its UN reference number, and
  the EU list, which does for some. The UN's own file carries no reuse licence and is no longer
  read. `sanctions.screen` lists are OFAC-SDN, EU and UK; every hit carries `un_ref` when its list
  names one, and `lists: ["UN"]` screens the UK and EU entries that do. Measured on 2026-10-17:
  the three lists held all 1010 UN entries (991 by UN number in the UK list, 19 by name in the EU
  and OFAC lists); the newest UN decisions arrive with the UK's and the EU's delay.
- The landing's live scene shows the UK list (with the UN) in place of the UN file.
- 160 tests.

## 0.3.0 — 2026-10-17

Every source on terms that allow selling the answer.

- `emporion.timestamp.verify@v1` no longer asks block explorers. EMPORION keeps its own copy of
  the Bitcoin header chain from the genesis block (`bitcoin_headers.py`, ~75 MB in the data
  volume, `EMPORION_BTC_HEADERS`), fetched peer to peer from nodes found through the DNS seeds:
  every header's link, proof of work and difficulty (retargets included) is checked before it is
  kept, a second node on another /16 must serve the same chain before a header is used, and the
  chain is refreshed every 10 minutes. Slow nodes are left for faster ones, raced eight at a time.
  Until two nodes agree, a verification is a no-charge refusal.
- `emporion.domain.rdap@v1` follows registries' terms: at most 30 queries a minute per registry,
  answers cached 24 hours (an hour for "not registered", marked `cached`, original fetch time
  kept), and the registry's own notices, its terms of service among them, passed through as
  `registry_terms`.
- `emporion.company.lookup@v1` answers carry `personal_data`: purpose, GDPR Art. 6(1)(f) basis,
  and retention (no copy kept).
- 159 tests; the Bitcoin ones run on real mainnet headers, the first difficulty change included.

## 0.2.1 — 2026-10-17

- `emporion.company.lookup@v1` adds Finland (PRH / YTJ open data, CC BY 4.0; Business ID check
  digit verified locally; name search ranked by whole-word match, since PRH returns its page in
  business-ID order) and the United Kingdom (Companies House, OGL v3.0) — GB only where the
  operator sets `COMPANIES_HOUSE_API_KEY`, a free key; without it GB is not in the manifest.
- `emporion.sources@v1` counts calendar countries once (251, not 501: the library lists each under
  its alpha-2 and alpha-3 code).
- 144 tests.

## 0.2.0 — 2026-10-17

Nine capabilities more, sixteen in all.

- `emporion.web.capture@v1` ($0.003): a web page as evidence — final URL, every redirect, the IP,
  status, key headers, the TLS certificate, the SHA-256 of the body (and the body up to 512 KB),
  and the record's SHA-256 anchored in Bitcoin through OpenTimestamps. Public addresses only:
  http(s) on ports 80/443, every address of the name checked, the connection pinned to the checked
  address (no DNS rebinding), every redirect checked again, 5 MB and 25 s caps, 20 captures of one
  host per minute.
- `emporion.domain.rdap@v1` ($0.001): domain registration from the TLD's registry, found through
  IANA's RDAP bootstrap; only servers named there are asked (`DYNAMIC_HOSTS`, https only).
- `emporion.company.lookup@v1` ($0.001): national company registers by number or name — Norway
  (Brønnøysund), France (SIRENE/RNE through the State's open API), Czech Republic (ARES).
- `emporion.eori.check@v1` ($0.002): EU EORI validity from the European Commission's EOS service,
  up to 10 numbers per call.
- `emporion.calendar.check@v1` ($0.001): business days in ~250 countries and their regions and on
  markets (TARGET2, NYSE, LSE…), from python-holidays compiled in — no network.
- `emporion.timer.set@v1` ($0.002) with the free `checkin`, `cancel` and `status`: a signed POST to
  the caller's https callback at a time, or a dead man's switch; events signed with EMPORION's key
  (Ed25519, ML-DSA-65 with `ORACLE_PQC=1`), retried after 1, 5 and 30 minutes, kept in SQLite in
  the data volume (`EMPORION_TIMERS_DB`), at most 90 days.
- Roughtime (signed time) was considered and left out: of the public servers, two with published
  keys answered, and the protocol drafts still change.
- 139 tests.

## 0.1.0 — 2026-10-16

First release.

- Seven capabilities on the AIMarket v2 protocol: `emporion.vat.check@v1` (EU VIES, with the
  consultation number when the caller names its own VAT number), `emporion.lei.lookup@v1`
  (GLEIF, by LEI or by name, with parents), `emporion.fx.rate@v1` (ECB reference rates since
  1999, cross rates in Decimal), `emporion.sanctions.screen@v1` (OFAC SDN with digital-currency
  addresses, EU, UN), `emporion.timestamp.stamp@v1` and `emporion.timestamp.verify@v1`
  (OpenTimestamps, confirmed against two independent Bitcoin explorers), and the free
  `emporion.sources@v1`.
- Every answer carries its source, the fetch time and the SHA-256 of what the source returned,
  and is signed and bound to the request (Ed25519, hybrid ML-DSA-65 with `ORACLE_PQC=1`).
- Outbound HTTP only to listed hosts, with checked redirects and size caps; sanctions lists
  refreshed every 6 hours (every 5 minutes while one is missing or failed), kept on disk so a
  restart during a source's outage keeps the last good copy, and refused when older than
  48 hours.
- Live at https://emporion.modelmarket.dev/ (the landing with a 3D scene of the live service, and the
  API) and at https://modelmarket.dev/providers/emporion/, the address the hub federates with; in the
  modelmarket.dev hub catalogue.
- Documentation in English, Russian, Spanish, French and Chinese.
