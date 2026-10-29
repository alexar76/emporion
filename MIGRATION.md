# SYMMARTYS 0.5.0: local namespace migration

SYMMARTYS (συμμάρτυς, a joint or corroborating witness) succeeds this ecosystem's
EMPORION package through 0.4.2. This change is prepared locally. It does not create,
rename or publish a GitHub repository, PyPI release, container or public deployment.

## API and installation

| Surface | Through 0.4.2 | From 0.5.0 |
|---|---|---|
| Python distribution | `aimarket-emporion` | `aimarket-symmartys` |
| Python import | `emporion` | `symmartys` |
| Product ID | `emporion` | `symmartys` |
| Capability IDs | `emporion.*@v1` | `symmartys.*@v1` |
| Process | `python -m emporion.main` | `python -m symmartys.main` |
| Environment prefix | `EMPORION_` | `SYMMARTYS_` |
| Timer callback header | `X-Emporion-Timer` | `X-Symmartys-Timer` |
| Timer event issuer | `emporion` | `symmartys` |

Update provider registrations, capability allowlists, request signatures and callback
handlers together. Old capability IDs and the old Python module are not aliases in
the new package. Previously issued signed receipts remain unchanged and must still
be verified against their original IDs and public key.

From the existing local `aicom` checkout:

```sh
python -m pip install -e './oracles/core[pqc]' -e './symmartys[dev]'
cd symmartys
python -m pytest tests -q
SYMMARTYS_PUBLIC_URL=http://127.0.0.1:9351 python -m symmartys.main
```

The [legacy public source](https://github.com/alexar76/emporion) describes releases
through 0.4.2. No `alexar76/symmartys` repository is claimed by this local release.
The dated older sections of [CHANGELOG.md](CHANGELOG.md) retain their original IDs.

## Preserve identity and state

Use the existing data volume and signing key. Do not create a fresh volume merely
because the product directory or container name changed.

`SYMMARTYS_SIGNING_KEY_PATH` explicitly selects the key. If absent, the legacy
`EMPORION_SIGNING_KEY_PATH` is accepted with a warning. Without either, the resolver
uses `SYMMARTYS_STATE_DIR` (default `data`; Docker sets `/data`):

- If only `emporion_signing_key` exists there, it is reused with a warning.
- If only `symmartys_signing_key` exists, it is reused.
- If both exist, startup refuses until the operator explicitly selects the intended key.
- If neither exists, a fresh installation creates `symmartys_signing_key` normally.

Keep the selected key's ML-DSA companion files together with it. The sanctions cache,
`timers.sqlite` and `bitcoin-headers.bin` remain beside that key unless explicitly
configured. Existing timer IDs and tokens remain in the same database; callback
consumers must accept the new issuer/header above when delivery resumes.

Every application setting reads `SYMMARTYS_<suffix>` first, then the corresponding
`EMPORION_<suffix>` with a warning. This includes `PUBLIC_URL`, `HOST`, `PORT`,
`LOG_LEVEL`, `SIGNING_KEY_PATH`, `STATE_DIR`, `CACHE_DIR`, `TIMERS_DB`, `BTC_HEADERS`,
`CORS_ORIGINS` and `RATE_LIMIT`. Only configuration compatibility is provided;
legacy capability IDs are not served. Remove obsolete variables after updating the
deployment environment. `ORACLE_*` and `COMPANIES_HOUSE_API_KEY` are unchanged.

Compose requires a deliberate volume selection:

```sh
# Upgrade: substitute the actual existing volume name; do not guess it.
SYMMARTYS_VOLUME_NAME=<existing-volume> docker compose -f symmartys/docker-compose.yml up -d --build

# Deliberate fresh installation only:
docker volume create symmartys-data
SYMMARTYS_VOLUME_NAME=symmartys-data docker compose -f symmartys/docker-compose.yml up -d --build
```

Set `SYMMARTYS_PUBLIC_URL` to the address actually routed to this local deployment.
The volume is external: Compose refuses a missing or misspelled volume instead of
silently creating empty state and a new signing identity.
The new branded domains and provider paths in examples are deployment targets,
not evidence that deployment has already happened.
