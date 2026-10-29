"""Who registered this domain and when: RDAP, from the TLD's own registry.

The cheapest scam signal there is: a shop that sells at half price from a domain created
nine days ago. RDAP (RFC 9083) is the structured successor of WHOIS; IANA's bootstrap
file says which server answers for each top-level domain, and that server is the
registry itself.

Only servers named in IANA's file are asked (net.py's DYNAMIC_HOSTS["iana_rdap"], filled
from the file, https only). Registrar referrals are not followed: the registry's record
already carries the dates, the registrar and the status, and a registrar's server is
not in IANA's file.

A registry that answers 404 says the name is not registered there — an answer. A TLD
with no RDAP service in IANA's file (some country codes still have none) cannot be
looked up, and that costs nothing.

Registries' terms of service forbid high-volume automated querying and repackaging of
their data. So SYMMARTYS asks one registry at most PER_HOST_PER_MINUTE times a minute,
keeps each answer CACHE_TTL_S (an hour for "not registered"; registration data changes
rarely; a cached answer says so
and keeps the original fetch time in its evidence), and passes the registry's own notices
— its terms of service among them — through in every answer, as `registry_terms`.
"""

from __future__ import annotations

import copy
import datetime as dt
import re
import threading
import time
from collections import OrderedDict, deque
from typing import Any
from urllib.parse import urlsplit

from symmartys import sources
from symmartys.net import UpstreamError, fetch

BOOTSTRAP_URL = "https://data.iana.org/rdap/dns.json"
BOOTSTRAP_TTL_S = 24 * 3600
CACHE_TTL_S = 24 * 3600
#: "Not registered" is kept shorter: a free name can be taken within the day.
CACHE_TTL_UNREGISTERED_S = 3600
CACHE_MAX = 20_000
PER_HOST_PER_MINUTE = 30
_LABEL = re.compile(r"^(?!-)[a-z0-9-]{1,63}(?<!-)$")
_RDAP_HEADERS = {"Accept": "application/rdap+json, application/json"}


class Bootstrap:
    def __init__(self):
        self.lock = threading.Lock()
        self.loaded_at = 0.0
        self.services: dict[str, list[str]] = {}
        self.publication: str | None = None
        self.evidence: dict[str, str] | None = None

    def get(self) -> dict[str, list[str]]:
        with self.lock:
            if self.services and time.time() - self.loaded_at < BOOTSTRAP_TTL_S:
                return self.services
            try:
                got = fetch(BOOTSTRAP_URL, source_id="iana_rdap", max_bytes=2 << 20, timeout=20)
                data = got.json()
                services: dict[str, list[str]] = {}
                for tlds, urls in data["services"]:
                    https = [u.rstrip("/") + "/" for u in urls if u.startswith("https://")]
                    for tld in tlds:
                        services[str(tld).lower()] = https
            except (UpstreamError, KeyError, TypeError, ValueError) as exc:
                if self.services:  # keep yesterday's file rather than answer nothing
                    return self.services
                raise UpstreamError(f"IANA's RDAP bootstrap could not be read ({exc})") from exc
            self.services, self.loaded_at = services, time.time()
            self.publication = data.get("publication")
            self.evidence = got.evidence("iana_rdap")
            sources.DYNAMIC_HOSTS["iana_rdap"] = frozenset(
                (urlsplit(u).hostname or "").lower() for us in services.values() for u in us)
            return services


BOOTSTRAP = Bootstrap()


def normalise(domain: str) -> str:
    d = str(domain or "").strip().lower().rstrip(".")
    d = re.sub(r"^[a-z]+://", "", d).split("/")[0].split(":")[0]
    try:
        d = d.encode("idna").decode("ascii")
    except UnicodeError as exc:
        raise ValueError(f"not a domain name: {domain!r}") from exc
    labels = d.split(".")
    if len(d) > 253 or len(labels) < 2 or not all(_LABEL.match(x) for x in labels):
        raise ValueError(f"not a registrable domain name: {domain!r}")
    return d


def _vcard_name(entity: dict) -> str | None:
    card = entity.get("vcardArray")
    if isinstance(card, list) and len(card) == 2 and isinstance(card[1], list):
        for prop in card[1]:
            if isinstance(prop, list) and len(prop) >= 4 and prop[0] == "fn":
                return str(prop[3]) or None
    return None


def _parse_time(value: Any) -> dt.datetime | None:
    try:
        return dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


class _Gate:
    """Per-registry request budget, and the answers already fetched."""

    def __init__(self):
        self.lock = threading.Lock()
        self.calls: dict[str, deque[float]] = {}
        self.cache: OrderedDict[str, tuple[float, float, dict[str, Any]]] = OrderedDict()

    def take(self, host: str) -> None:
        now = time.monotonic()
        with self.lock:
            q = self.calls.setdefault(host, deque())
            while q and now - q[0] > 60:
                q.popleft()
            if len(q) >= PER_HOST_PER_MINUTE:
                wait = int(60 - (now - q[0])) + 1
                raise UpstreamError(f"SYMMARTYS asks {host} at most {PER_HOST_PER_MINUTE} times a "
                                    f"minute, as registries' terms require; retry in {wait} s, "
                                    "nothing charged")
            q.append(now)

    def get(self, key: str) -> tuple[float, dict[str, Any]] | None:
        with self.lock:
            hit = self.cache.get(key)
            if hit is None:
                return None
            stored_at, ttl, out = hit
            if time.time() - stored_at > ttl:
                del self.cache[key]
                return None
            self.cache.move_to_end(key)
            return stored_at, copy.deepcopy(out)

    def put(self, keys: list[str], out: dict[str, Any]) -> None:
        ttl = CACHE_TTL_S if out.get("registered") else CACHE_TTL_UNREGISTERED_S
        with self.lock:
            for k in dict.fromkeys(keys):
                self.cache[k] = (time.time(), ttl, copy.deepcopy(out))
                self.cache.move_to_end(k)
            while len(self.cache) > CACHE_MAX:
                self.cache.popitem(last=False)


GATE = _Gate()


def _terms(data: Any) -> list[dict[str, Any]]:
    """The registry's own notices (its terms of service among them), passed through."""
    out = []
    for n in (data.get("notices") or []) if isinstance(data, dict) else []:
        if not isinstance(n, dict):
            continue
        links = [str(l.get("href")) for l in n.get("links") or []
                 if isinstance(l, dict) and str(l.get("href", "")).startswith("http")]
        text = " ".join(str(x) for x in n.get("description") or [])[:400]
        out.append({"title": n.get("title"), "description": text or None, "links": links[:3]})
    return out[:6]


def lookup(domain: str, *, bootstrap: Bootstrap = BOOTSTRAP,
           gate: _Gate | None = None) -> dict[str, Any]:
    name = normalise(domain)
    gate = gate or GATE
    hit = gate.get(name)
    if hit is not None:
        stored_at, out = hit
        out["cached"] = True
        out["cache_age_s"] = int(time.time() - stored_at)
        created = _parse_time(out.get("created"))
        if created and created.tzinfo:
            out["age_days"] = (dt.datetime.now(dt.timezone.utc) - created).days
        return out
    out = _fetch(name, bootstrap, gate)
    gate.put([name, out["domain"]], out)
    out["cached"] = False
    return out


def _fetch(name: str, bootstrap: Bootstrap, gate: _Gate) -> dict[str, Any]:
    services = bootstrap.get()
    labels = name.split(".")
    base = None
    for i in range(len(labels) - 1):
        suffix = ".".join(labels[i + 1:])
        if suffix in services:
            base = services[suffix]
            tld = suffix
            break
    if base is None:
        raise ValueError(f".{labels[-1]} publishes no RDAP service in IANA's bootstrap; "
                         "nothing charged")
    if not base:
        raise ValueError(f".{tld}'s RDAP service is plain http only; SYMMARTYS asks over "
                         "https alone. Nothing charged")
    # IANA lists TLDs, not the second levels some registries sell under (co.uk, com.au),
    # so the registrable name is found by asking: the longest candidate first, down to one
    # label under the TLD, stopping at the first the registry knows (some answer 404 for a
    # name below a registration, some 400).
    n_tld = len(tld.split("."))
    candidates = [".".join(labels[-k:])
                  for k in range(min(len(labels), n_tld + 3), n_tld, -1)]

    def ask(candidate: str):
        last: Exception | None = None
        for url in base:
            try:
                gate.take((urlsplit(url).hostname or "").lower())
                return fetch(f"{url}domain/{candidate}", source_id="iana_rdap",
                             headers=_RDAP_HEADERS, max_bytes=1 << 20, timeout=20,
                             ok_statuses=(200, 400, 404))
            except UpstreamError as exc:
                last = exc
        raise UpstreamError(f"the .{tld} registry's RDAP service did not answer ({last}); "
                            "nothing charged")

    for registrable in candidates:
        got = ask(registrable)
        if got.status == 200:
            break
    if got.status == 400:
        raise ValueError(f"the .{tld} registry refused {candidates[-1]} as a domain name; "
                         "nothing charged")
    out: dict[str, Any] = {"domain": registrable if got.status == 200 else candidates[-1],
                           "queried": name, "tld": tld}
    if got.status == 404:
        try:
            terms = _terms(got.json())
        except UpstreamError:
            terms = []
        out.update({"registered": False,
                    "note": f"the .{tld} registry has no record of {name}",
                    "registry_terms": terms})
        out["evidence"] = got.evidence("iana_rdap")
        return out
    data = got.json()
    if not isinstance(data, dict) or data.get("objectClassName") != "domain":
        raise UpstreamError("the registry answered without a domain object")
    events = {str(e.get("eventAction")): e.get("eventDate")
              for e in data.get("events", []) if isinstance(e, dict)}
    created = _parse_time(events.get("registration"))
    registrar = None
    for ent in data.get("entities", []) or []:
        if isinstance(ent, dict) and "registrar" in (ent.get("roles") or []):
            ids = {str(p.get("type")): p.get("identifier")
                   for p in ent.get("publicIds", []) or [] if isinstance(p, dict)}
            registrar = {"name": _vcard_name(ent), "iana_id": ids.get("IANA Registrar ID")}
            break
    now = dt.datetime.now(dt.timezone.utc)
    out.update({
        "registered": True,
        "created": events.get("registration"),
        "updated": events.get("last changed"),
        "expires": events.get("expiration"),
        "age_days": (now - created).days if created and created.tzinfo else None,
        "registrar": registrar,
        "status": [str(s) for s in data.get("status", []) or []],
        "nameservers": sorted({str(n.get("ldhName", "")).lower()
                               for n in data.get("nameservers", []) or []
                               if isinstance(n, dict) and n.get("ldhName")}),
        "dnssec": bool((data.get("secureDNS") or {}).get("delegationSigned")),
        "registry_terms": _terms(data),
        "evidence": got.evidence("iana_rdap"),
    })
    if out["age_days"] is not None and out["age_days"] < 90:
        out["note"] = f"registered {out['age_days']} days ago"
    return out


__all__ = ["BOOTSTRAP", "BOOTSTRAP_URL", "Bootstrap", "CACHE_TTL_S", "GATE",
           "PER_HOST_PER_MINUTE", "lookup", "normalise"]
