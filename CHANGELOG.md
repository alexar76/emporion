# Changelog

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
