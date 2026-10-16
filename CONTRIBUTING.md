<!-- satellite-contributing -->
# Contributing to EMPORION

Pull requests are welcome in [emporion](https://github.com/alexar76/emporion). History here is
append-only (no force-push): a merged pull request is imported back into the canonical
[aicom](https://github.com/alexar76/aicom) monorepo and synced here again, so your commit stays.
Open an issue first for anything larger than a fix, with the version, a reproduction and the
expected result.

A new source is welcome when its licence allows reuse in a paid answer, it needs no account a
stranger could not get, and its answer can be checked: add it to `emporion/sources.py` (licence,
attribution, exact hosts), give it a fixture made of a **real** excerpt in `tests/fixtures/`,
and keep every test offline.

## Local checks

Python 3.11+:

```sh
git clone https://github.com/alexar76/emporion.git
cd emporion
python -m venv .venv && . .venv/bin/activate
pip install -e "vendor/oracle-core[pqc]" -e ".[dev]"
pytest
```

The image builds from `Dockerfile.standalone`, not the monorepo `Dockerfile`:

```sh
docker build -f Dockerfile.standalone -t emporion .
```

No account, key or network access is needed for the tests. Follow [SECURITY.md](SECURITY.md)
for security reports; never put credentials in an issue.
