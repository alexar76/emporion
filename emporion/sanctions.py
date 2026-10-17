"""Sanctions-list lookups: a wallet address or a name against OFAC SDN, the EU and the UK lists.

An agent about to pay a wallet, or to sign with a counterparty, can ask whether the
address or the name is on a public sanctions list. This is a LIST LOOKUP with the list
versions it used — not a compliance determination: names collide and aliases are
incomplete, so a hit is a reason to look closer and a miss is not a clearance. Every
answer says so and names the lists, their publication dates and SHA-256.

* Wallets: OFAC publishes digital-currency addresses in the SDN remarks (~510 on
  2026-10-16: XBT, ETH, TRX, USDT, USDC, …). Matched exactly; EVM and bech32 addresses
  case-insensitively, Base58 and others as written.
* UN listings: the UN Security Council's own file carries no reuse licence, so it is not
  read directly. The UK Sanctions List (Open Government Licence v3.0) gives each UN-derived
  designation its UN reference number, as the EU file does for some; together with OFAC
  they covered all 1010 UN entries on 2026-10-17 (991 by UN number in the UK list, the rest
  by name in the EU and OFAC lists). A hit carries `un_ref` when its list names one, and
  lists=["UN"] screens the UK and EU entries that do.
* Names: every primary name and alias of the three lists, normalised (case, accents,
  punctuation; word order ignored, so "DOE, John" is "John Doe"), scored by token
  agreement with a small edit-distance allowance. Hits at or above the threshold
  (default 0.85) come back with the name that matched.
* Freshness: lists refresh every 6 h in the background, and every RETRY_S while one is
  missing or failed; a list that failed keeps its last good snapshot. That snapshot is
  also kept on disk (gzip JSON, with its original fetch time and SHA-256), so a restart
  during a source's outage does not lose it. A screen refuses (ok:false, nothing charged)
  when a requested list is missing or older than MAX_AGE_H — an incomplete screen sold as
  complete is worse than none.
"""

from __future__ import annotations

import csv
import gzip
import io
import json
import logging
import os
import re
import threading
import time
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable

from emporion.names import norm_name, score, tokens
from emporion.net import Fetched, UpstreamError, fetch

log = logging.getLogger("emporion.sanctions")

OFAC_SDN = "https://sanctionslistservice.ofac.treas.gov/api/PublicationPreview/exports/SDN.CSV"
OFAC_ALT = "https://sanctionslistservice.ofac.treas.gov/api/PublicationPreview/exports/ALT.CSV"
EU_FSF = ("https://webgate.ec.europa.eu/fsd/fsf/public/files/xmlFullSanctionsList_1_1/"
          "content?token=dG9rZW4tMjAxNw")
UK_XML = "https://sanctionslist.fcdo.gov.uk/docs/UK-Sanctions-List.xml"

LISTS = ("OFAC-SDN", "EU", "UK")
#: Not a list EMPORION reads: the UK and EU entries that carry a UN reference number.
UN_VIEW = "UN"
REFRESH_S = 6 * 3600
#: How soon a missing or failed list is tried again. The EU file server answered 500 for
#: hours on 2026-10-16; waiting the full REFRESH_S would refuse every full screen for 6 h.
RETRY_S = 5 * 60
MAX_AGE_H = 48.0
DEFAULT_THRESHOLD = 0.85

_ADDR = re.compile(r"Digital Currency Address - ([A-Za-z0-9]{2,8}) ([A-Za-z0-9]{20,120})")


def norm_address(addr: str) -> str:
    a = str(addr).strip()
    if a.lower().startswith(("0x", "bc1", "ltc1", "tb1")):
        return a.lower()
    return a


@dataclass
class Entry:
    list_name: str
    ref: str
    name: str
    kind: str                       # individual | entity | vessel | aircraft
    programs: list[str] = field(default_factory=list)
    aliases: list[str] = field(default_factory=list)
    addresses: list[tuple[str, str]] = field(default_factory=list)
    listed_on: str | None = None
    un_ref: str | None = None       # the UN Security Council reference, when the list gives one

    def public(self) -> dict[str, Any]:
        return {"list": self.list_name, "ref": self.ref, "name": self.name, "kind": self.kind,
                "un_ref": self.un_ref,
                "programs": self.programs, "aliases": self.aliases[:12],
                "listed_on": self.listed_on,
                "digital_currency_addresses": [{"asset": a, "address": x}
                                               for a, x in self.addresses[:20]]}


@dataclass
class Snapshot:
    list_name: str
    entries: list[Entry]
    fetched: list[Fetched]
    published: str | None
    loaded_at: float

    def meta(self) -> dict[str, Any]:
        return {"list": self.list_name, "entries": len(self.entries),
                "published": self.published,
                "fetched_at": self.fetched[0].fetched_at if self.fetched else None,
                "sha256": [f.sha256 for f in self.fetched],
                "age_hours": round((time.time() - self.loaded_at) / 3600, 2)}


# ── Parsers ──────────────────────────────────────────────────────────────────


def parse_ofac(sdn: Fetched, alt: Fetched | None) -> Snapshot:
    entries: dict[str, Entry] = {}
    for row in csv.reader(io.StringIO(sdn.body.decode("utf-8", "replace"))):
        if len(row) < 12 or not row[0].strip().isdigit():
            continue
        clean = [c.strip() if c.strip() != "-0-" else "" for c in row]
        kind = {"individual": "individual", "vessel": "vessel",
                "aircraft": "aircraft"}.get(clean[2].lower(), "entity")
        e = Entry("OFAC-SDN", clean[0], clean[1], kind,
                  [p for p in re.split(r"[\]\[;\s]+", clean[3]) if p])
        e.addresses = [(a.upper(), x) for a, x in _ADDR.findall(clean[11])]
        entries[clean[0]] = e
    if alt is not None:
        for row in csv.reader(io.StringIO(alt.body.decode("utf-8", "replace"))):
            if len(row) >= 4 and row[0].strip() in entries and row[3].strip() not in ("", "-0-"):
                entries[row[0].strip()].aliases.append(row[3].strip())
    m = re.search(r"/(\d{4}-\d{2}-\d{2})/", sdn.url)
    return Snapshot("OFAC-SDN", list(entries.values()), [f for f in (sdn, alt) if f],
                    m.group(1) if m else None, time.time())


def _xml_iter(body: bytes):
    from defusedxml.ElementTree import iterparse

    return iterparse(io.BytesIO(body), events=("start", "end"))


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def parse_eu(got: Fetched) -> Snapshot:
    entries: list[Entry] = []
    published = None
    cur: Entry | None = None
    for event, el in _xml_iter(got.body):
        tag = _local(el.tag)
        if event == "start" and tag == "export":
            published = (el.get("generationDate") or "")[:10] or None
        elif event == "start" and tag == "sanctionEntity":
            cur = Entry("EU", el.get("euReferenceNumber") or el.get("logicalId") or "", "", "entity",
                        un_ref=(el.get("unitedNationId") or "").strip() or None)
        elif event == "end" and cur is not None:
            if tag == "nameAlias":
                whole = (el.get("wholeName") or "").strip()
                if whole and not cur.name:
                    cur.name = whole  # the first alias the EU lists is the primary name
                elif whole and whole != cur.name and whole not in cur.aliases:
                    cur.aliases.append(whole)
            elif tag == "subjectType":
                cur.kind = "individual" if el.get("code") == "person" else "entity"
            elif tag == "regulation":
                prog = el.get("programme")
                if prog and prog not in cur.programs:
                    cur.programs.append(prog)
                cur.listed_on = cur.listed_on or el.get("publicationDate")
            elif tag == "sanctionEntity":
                if cur.name:
                    entries.append(cur)
                cur = None
            el.clear()
    return Snapshot("EU", entries, [got], published, time.time())


_UK_KIND = {"Individual": "individual", "Entity": "entity", "Ship": "vessel"}


def _uk_date(text: str | None) -> str | None:
    """dd/mm/yyyy, as the UK list writes dates, to ISO."""
    m = re.fullmatch(r"(\d{2})/(\d{2})/(\d{4})", (text or "").strip())
    return f"{m.group(3)}-{m.group(2)}-{m.group(1)}" if m else None


def parse_uk(got: Fetched) -> Snapshot:
    """The UK Sanctions List (FCDO), XML: one <Designation> per person, entity or ship."""
    entries: list[Entry] = []
    published = None
    rec: dict[str, Any] | None = None
    name: dict[str, str] = {}
    for event, el in _xml_iter(got.body):
        tag = _local(el.tag)
        if event == "start":
            if tag == "Designation":
                rec = {"names": [], "programs": []}
            elif tag == "Name" and rec is not None:
                name = {}
            continue
        text = (el.text or "").strip()
        if rec is None:
            if tag == "DateGenerated":
                published = _uk_date(text)
        elif tag in ("Name1", "Name2", "Name3", "Name4", "Name5", "Name6") and text:
            name[tag] = text
        elif tag == "NameType":
            name["type"] = text
        elif tag == "Name":
            full = " ".join(name[k] for k in ("Name1", "Name2", "Name3", "Name4", "Name5", "Name6")
                            if k in name)
            if full:
                rec["names"].append((name.get("type", ""), " ".join(full.split())))
        elif tag in ("UniqueID", "UNReferenceNumber", "IndividualEntityShip", "DateDesignated"):
            rec[tag] = text
        elif tag == "RegimeName" and text:
            rec["programs"].append(text)
        elif tag == "Designation":
            names = rec["names"]
            primary = next((n for t, n in names if t == "Primary Name"), names[0][1] if names else "")
            if primary:
                aliases = list(dict.fromkeys(n for _t, n in names if n != primary))
                entries.append(Entry("UK", rec.get("UniqueID", ""), primary,
                                     _UK_KIND.get(rec.get("IndividualEntityShip", ""), "entity"),
                                     rec["programs"], aliases, [], _uk_date(rec.get("DateDesignated")),
                                     (rec.get("UNReferenceNumber") or "").strip() or None))
            rec = None
        el.clear()
    return Snapshot("UK", entries, [got], published, time.time())


# ── The index ────────────────────────────────────────────────────────────────


class _Index:
    def __init__(self, snapshots: dict[str, Snapshot]):
        self.snapshots = snapshots
        self.entries: list[Entry] = [e for s in snapshots.values() for e in s.entries]
        self.by_token: dict[str, list[int]] = defaultdict(list)
        self.names: list[tuple[int, str, frozenset[str], str]] = []  # entry, name, tokens, norm
        self.by_address: dict[str, list[int]] = defaultdict(list)
        self.by_prefix: dict[str, set[str]] = defaultdict(set)
        for i, e in enumerate(self.entries):
            for n in [e.name, *e.aliases]:
                toks = tokens(n)
                if not toks:
                    continue
                j = len(self.names)
                self.names.append((i, n, toks, norm_name(n)))
                for t in toks:
                    self.by_token[t].append(j)
                    if len(t) >= 5:
                        self.by_prefix[t[:4]].add(t)
            for _asset, addr in e.addresses:
                self.by_address[norm_address(addr)].append(i)


class SanctionsService:
    """Holds the three lists, refreshes them, answers screens."""

    def __init__(self, loaders: dict[str, Callable[[], Snapshot]] | None = None,
                 cache_dir: str | Path | None = None):
        self.loaders = loaders or {
            "OFAC-SDN": lambda: parse_ofac(
                fetch(OFAC_SDN, source_id="ofac", max_bytes=64 << 20, timeout=120),
                fetch(OFAC_ALT, source_id="ofac", max_bytes=32 << 20, timeout=120)),
            "EU": lambda: parse_eu(fetch(EU_FSF, source_id="eu_fsf", max_bytes=128 << 20,
                                         timeout=180)),
            "UK": lambda: parse_uk(fetch(UK_XML, source_id="uk_fcdo", max_bytes=64 << 20,
                                         timeout=180)),
        }
        self._snapshots: dict[str, Snapshot] = {}
        self._index: _Index | None = None
        self._lock = threading.Lock()
        self._errors: dict[str, str] = {}
        self._thread: threading.Thread | None = None
        self.cache_dir = Path(cache_dir) if cache_dir else None

    # ── The last good lists, on disk ─────────────────────────────────────────

    def _cache_path(self, name: str) -> Path:
        assert self.cache_dir is not None
        return self.cache_dir / f"sanctions-{name}.json.gz"

    def _save(self, snap: Snapshot) -> None:
        if self.cache_dir is None:
            return
        doc = {"list_name": snap.list_name, "published": snap.published,
               "loaded_at": snap.loaded_at, "entries": [asdict(e) for e in snap.entries],
               # The bytes are not kept: a screen needs the entries, and the evidence is the
               # URL, the fetch time and the SHA-256 of what the source returned.
               "fetched": [{"url": f.url, "status": f.status, "fetched_at": f.fetched_at,
                            "sha256": f.sha256} for f in snap.fetched]}
        try:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            path = self._cache_path(snap.list_name)
            tmp = path.with_suffix(".tmp")
            tmp.write_bytes(gzip.compress(json.dumps(doc, ensure_ascii=False).encode()))
            os.replace(tmp, path)
        except OSError as exc:
            log.warning("sanctions list %s not cached: %s", snap.list_name, exc)

    def load_cache(self) -> list[str]:
        """Pick up the last good lists a previous run saved — only those still within
        MAX_AGE_H of when they were fetched; an older one would be refused anyway."""
        if self.cache_dir is None:
            return []
        loaded = []
        for name in self.loaders:
            path = self._cache_path(name)
            if not path.is_file():
                continue
            try:
                doc = json.loads(gzip.decompress(path.read_bytes()))
                if (time.time() - float(doc["loaded_at"])) / 3600 > MAX_AGE_H:
                    continue
                snap = Snapshot(
                    list_name=name,
                    entries=[Entry(**{**e, "addresses": [tuple(a) for a in e["addresses"]]})
                             for e in doc["entries"]],
                    fetched=[Fetched(f["url"], int(f["status"]), b"", f["fetched_at"], f["sha256"])
                             for f in doc["fetched"]],
                    published=doc.get("published"), loaded_at=float(doc["loaded_at"]))
            except (OSError, ValueError, KeyError, TypeError) as exc:
                log.warning("cached sanctions list %s unreadable, ignored: %s", name, exc)
                continue
            if not snap.entries:
                continue
            with self._lock:
                self._snapshots.setdefault(name, snap)
            loaded.append(name)
        if loaded:
            index = _Index(dict(self._snapshots))
            with self._lock:
                self._index = index
            log.info("sanctions lists from the last run: %s", ", ".join(loaded))
        return loaded

    def refresh(self) -> dict[str, str]:
        changed = False
        for name, loader in self.loaders.items():
            try:
                snap = loader()
                if not snap.entries:
                    raise UpstreamError("parsed no entries")
                with self._lock:
                    self._snapshots[name] = snap
                self._errors.pop(name, None)
                self._save(snap)
                changed = True
            except Exception as exc:  # noqa: BLE001 — keep the last good snapshot
                self._errors[name] = f"{type(exc).__name__}: {str(exc)[:160]}"
                log.warning("sanctions list %s not refreshed: %s", name, self._errors[name])
        if changed:
            index = _Index(dict(self._snapshots))
            with self._lock:
                self._index = index
        return dict(self._errors)

    def next_wait(self, interval_s: float = REFRESH_S) -> float:
        """The full interval when every list loaded; RETRY_S while one is missing or failed."""
        with self._lock:
            index = self._index
        missing = index is None or any(n not in index.snapshots for n in self.loaders)
        return min(interval_s, RETRY_S) if (missing or self._errors) else interval_s

    def start(self, interval_s: float = REFRESH_S) -> None:
        def loop():
            self.load_cache()
            while True:
                self.refresh()
                time.sleep(self.next_wait(interval_s))

        self._thread = threading.Thread(target=loop, name="sanctions-refresh", daemon=True)
        self._thread.start()

    def status(self) -> dict[str, Any]:
        """The lists a screen uses right now — the index, not what was fetched and is still
        being indexed. Reading the fetched snapshots made /health say all three were loaded
        while every screen still refused, and during a refresh made emporion.sources@v1 show
        the new lists' dates and hashes while screens answered from the old ones."""
        with self._lock:
            index = self._index
        snaps = index.snapshots if index is not None else {}
        return {"lists": {n: (snaps[n].meta() if n in snaps else None) for n in LISTS},
                "errors": dict(self._errors)}

    def _ready(self, lists: list[str]) -> _Index:
        with self._lock:
            index = self._index
        missing = [n for n in lists if index is None or n not in index.snapshots]
        if missing:
            raise UpstreamError(f"sanctions list(s) not loaded yet: {', '.join(missing)}; "
                                "nothing charged, retry in a minute")
        stale = [n for n in lists
                 if (time.time() - index.snapshots[n].loaded_at) / 3600 > MAX_AGE_H]
        if stale:
            raise UpstreamError(f"sanctions list(s) older than {MAX_AGE_H:g} h: {', '.join(stale)}; "
                                "refusing an outdated screen, nothing charged")
        return index

    def screen(self, *, address: str | None = None, name: str | None = None,
               kind: str | None = None, lists: list[str] | None = None,
               threshold: float = DEFAULT_THRESHOLD, limit: int = 10) -> dict[str, Any]:
        asked = [str(x).upper() for x in (lists or LISTS)]
        explicit = set(asked)
        wanted = list(dict.fromkeys(
            [x for x in asked if x != UN_VIEW] + (["UK", "EU"] if UN_VIEW in explicit else [])))

        def included(e: Entry) -> bool:
            # The UN view: UK and EU entries that carry a UN reference number — unless that
            # list was asked for in full as well.
            if e.list_name not in wanted:
                return False
            return bool(e.un_ref) or e.list_name in explicit or UN_VIEW not in explicit
        bad = [x for x in wanted if x not in LISTS]
        if bad:
            raise ValueError(f"unknown list(s) {bad}; lists are {', '.join(LISTS)} and UN "
                             "(the UK and EU entries with a UN reference number)")
        if not address and not name:
            raise ValueError("pass address (a wallet) or name (a person or entity)")
        if not 0.7 <= float(threshold) <= 1.0:
            raise ValueError("threshold must be from 0.7 to 1.0")
        index = self._ready(wanted)
        hits: list[dict[str, Any]] = []
        if address:
            key = norm_address(address)
            for i in index.by_address.get(key, []):
                e = index.entries[i]
                if included(e):
                    hits.append({"score": 1.0, "matched": "digital currency address",
                                 "entry": e.public()})
        if name:
            q_toks, q_norm = tokens(name), norm_name(name)
            if not q_toks:
                raise ValueError("the name has no searchable words")
            cand: set[int] = set()
            for t in q_toks:
                cand.update(index.by_token.get(t, ()))
                if len(t) >= 5:  # a misspelt token still finds names sharing its first 4 letters
                    for near in index.by_prefix.get(t[:4], ()):
                        if near != t:
                            cand.update(index.by_token.get(near, ()))
            best: dict[int, tuple[float, str]] = {}
            for j in cand:
                i, n, toks, nnorm = index.names[j]
                e = index.entries[i]
                if not included(e) or (kind and e.kind != kind):
                    continue
                s = score(q_toks, q_norm, toks, nnorm)
                if s >= threshold and s > best.get(i, (0.0, ""))[0]:
                    best[i] = (s, n)
            for i, (s, n) in sorted(best.items(), key=lambda kv: -kv[1][0])[:max(1, min(50, limit))]:
                hits.append({"score": s, "matched": n, "entry": index.entries[i].public()})
        return {
            "query": {"address": address, "name": name, "kind": kind, "threshold": threshold,
                      "lists": asked},
            "listed": bool(hits),
            "hits": hits,
            "lists": [index.snapshots[n].meta() for n in wanted],
            "note": "a lookup in public sanctions lists, not a compliance determination: a hit "
                    "is a reason to look closer, a miss is not a clearance. Confirm against "
                    "the official list before acting.",
        }


__all__ = ["DEFAULT_THRESHOLD", "Entry", "LISTS", "RETRY_S", "SanctionsService", "Snapshot", "norm_address",
           "norm_name", "parse_eu", "parse_ofac", "parse_uk", "score", "tokens"]
