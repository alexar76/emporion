# Security policy — SYMMARTYS

## Report privately

Do not open a public issue for a vulnerability. Email **alexar76@rambler.ru** with the affected
revision, a reproduction and the impact. We acknowledge within 48 hours and coordinate
disclosure; researchers are credited in the release notes when they wish.

Never include in a report: a signing key from `/data`, a hub admin token, or someone else's VAT
number, name or wallet address that you looked up.

## Supported versions

| Version | Supported |
|---|---|
| latest `main` | yes |
| older tags | best effort |

## What SYMMARTYS guarantees, and where to look

| Guarantee | Where it is enforced |
|---|---|
| It talks only to the sources it relays: exact host names, HTTPS only, per source | `symmartys/sources.py` (`SOURCES`, `ALLOWED_HOSTS`), `symmartys/net.py` |
| A redirect is followed only to a host of the same source, at most 3 hops | `symmartys/net.py` (`follow_redirects=False`, checked by hand) |
| No upstream answer can exhaust memory | `symmartys/net.py` streams every body under a cap set per call, from 256 bytes (a block hash) to 128 MB (the EU list) |
| Sanctions XML from outside cannot run entity tricks | `symmartys/sanctions.py` parses with `defusedxml` |
| A screen against a list older than 48 hours is refused, not answered as complete | `symmartys/sanctions.py` (`MAX_AGE_H`) |
| A Bitcoin timestamp is confirmed only when two independent Bitcoin nodes agree on the proof-of-work-checked header chain and the header Merkle root equals the proof's result | `symmartys/timestamp.py` |
| Every answer is signed and bound to the request it answers (capability, product, SHA-256 of the input) | `symmartys/middleware.py`, oracle-core receipts; checked against the hub's own canonical in `tests/test_app.py` |
| A refusal costs the buyer nothing | answers `ok:false`; the hub debits nothing for `ok:false` |
| Invokes are rate-limited per client | `SYMMARTYS_RATE_LIMIT` (120/min by default) |
| The container runs as uid 10001, the signing key stays in `/data` | `Dockerfile.standalone` |

## In scope

- Making SYMMARTYS fetch a host that is not a listed source, or follow a redirect off it.
- Getting a signed answer that does not match the request it claims to answer, or a forged one.
- Getting a sanctions screen answered "not listed" while a list failed to load or is stale.
- A timestamp reported as confirmed that Bitcoin does not confirm.
- A crash or memory blow-up from a crafted upstream answer or input.

## Out of scope

- What a public source itself says. SYMMARTYS relays it with its date and SHA-256; a wrong
  entry belongs with the European Commission, GLEIF, the ECB, OFAC, the EU or the UN.
- A sanctions lookup is not a legal determination; see "Honest limits" in the README.
- Denial of service by sheer volume, social engineering, and issues needing access to the host.
