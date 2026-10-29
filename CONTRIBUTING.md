<!-- satellite-contributing -->
# Contributing to SYMMARTYS

Work on this product in the local `aicom/symmartys` directory. The
[legacy public source](https://github.com/alexar76/emporion) contains releases through
0.4.2; this local rename does not create a new public repository. Keep proposed changes
local for review, with the version, a reproduction and the expected result.

A new source is welcome when its licence allows reuse in a paid answer, it needs no account a
stranger could not get, and its answer can be checked: add it to `symmartys/sources.py` (licence,
attribution, exact hosts), give it a fixture made of a **real** excerpt in `tests/fixtures/`,
and keep every test offline.

## Local checks

Python 3.11+:

```sh
# From the existing local aicom workspace:
cd symmartys
python -m venv .venv && . .venv/bin/activate
pip install -e "../oracles/core[pqc]" -e ".[dev]"
pytest
```

Build the local image from the monorepo root:

```sh
cd ..
docker build -f symmartys/Dockerfile -t symmartys .
```

No account, production key or network access is needed for the tests. Follow [SECURITY.md](SECURITY.md)
for security reports; never put credentials in an issue.

`Dockerfile.standalone` is retained as a packaging template and requires `vendor/oracle-core/`.
