"""Legal entities by LEI (ISO 17442) from the Global LEI Index — CC0.

Who is this counterparty, is its registration current, and who owns it? An LEI answers
all three: the GLEIF record carries the legal name, jurisdiction, legal form, addresses,
entity status, registration status and renewal date, and the reported direct and
ultimate parents. Lookup by LEI (check digits verified before any request — a typo is
caught locally) or by name (GLEIF's fuzzy completion, then the records).
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import quote

from emporion.names import similarity
from emporion.net import UpstreamError, fetch

API = "https://api.gleif.org/api/v1"
_LEI = re.compile(r"^[0-9A-Z]{18}[0-9]{2}$")


def lei_checksum_ok(lei: str) -> bool:
    """ISO 17442 / ISO 7064 MOD 97-10: letters → 10..35, the number mod 97 is 1."""
    if not _LEI.match(lei):
        return False
    digits = "".join(str(int(ch, 36)) for ch in lei)
    return int(digits) % 97 == 1


def _get(path: str) -> tuple[Any, dict[str, str]] | None:
    got = fetch(f"{API}{path}", source_id="gleif", max_bytes=4 << 20, ok_statuses=(200, 404),
                headers={"Accept": "application/vnd.api+json"})
    if got.status == 404:
        return None
    return got.json(), got.evidence("gleif")


def _address(a: Any) -> dict[str, Any] | None:
    if not isinstance(a, dict):
        return None
    return {"lines": [x for x in a.get("addressLines") or [] if x], "city": a.get("city"),
            "region": a.get("region"), "postal_code": a.get("postalCode"),
            "country": a.get("country")}


def _record(data: dict[str, Any]) -> dict[str, Any]:
    attrs = data.get("attributes") or {}
    ent, reg = attrs.get("entity") or {}, attrs.get("registration") or {}
    return {
        "lei": attrs.get("lei") or data.get("id"),
        "legal_name": (ent.get("legalName") or {}).get("name"),
        "other_names": [n.get("name") for n in ent.get("otherNames") or [] if isinstance(n, dict)],
        "jurisdiction": ent.get("jurisdiction"),
        "legal_form": (ent.get("legalForm") or {}).get("id"),
        "entity_status": ent.get("status"),
        "registered_as": ent.get("registeredAs"),
        "legal_address": _address(ent.get("legalAddress")),
        "headquarters_address": _address(ent.get("headquartersAddress")),
        "registration_status": reg.get("status"),
        "initial_registration": reg.get("initialRegistrationDate"),
        "last_update": reg.get("lastUpdateDate"),
        "next_renewal": reg.get("nextRenewalDate"),
        "managing_lou": reg.get("managingLou"),
        "corroboration": reg.get("corroborationLevel"),
        "bic": attrs.get("bic") or [],
    }


def _parent(lei: str, which: str) -> dict[str, Any] | None:
    hit = _get(f"/lei-records/{lei}/{which}-parent")
    if hit is None or not isinstance(hit[0].get("data"), dict):
        return None
    rec = _record(hit[0]["data"])
    return {"lei": rec["lei"], "legal_name": rec["legal_name"],
            "jurisdiction": rec["jurisdiction"]}


def lookup(lei: str | None = None, name: str | None = None, *, limit: int = 5,
           parents: bool = True) -> dict[str, Any]:
    if lei:
        code = re.sub(r"\s", "", str(lei)).upper()
        if not lei_checksum_ok(code):
            raise ValueError(f"{code[:24]!r} is not a valid LEI: 20 characters whose ISO 17442 "
                             "check digits (mod 97) must hold — likely a typo")
        hit = _get(f"/lei-records/{code}")
        if hit is None:
            return {"found": False, "lei": code,
                    "note": "a well-formed LEI that GLEIF does not hold (never issued, or retired)"}
        record = _record(hit[0]["data"])
        if parents:
            record["direct_parent"] = _parent(code, "direct")
            record["ultimate_parent"] = _parent(code, "ultimate")
        return {"found": True, "record": record, "evidence": hit[1]}
    if not name or not str(name).strip():
        raise ValueError("pass lei (20 characters) or name")
    query = str(name).strip()[:120]
    want = max(1, min(10, limit))
    # Two GLEIF searches, ranked here: fuzzy completion finds near spellings, the names
    # filter finds the full legal names fuzzy completion drops ("Deutsche Bank" →
    # "Deutsche Bank Aktiengesellschaft"). Ranking is EMPORION's own (names.py), with
    # active, issued registrations first among equals.
    fuzzy = _get(f"/fuzzycompletions?field=entity.legalName&q={quote(query)}")
    ids: list[str] = []
    for row in (fuzzy[0].get("data") if fuzzy else None) or []:
        rel = (((row.get("relationships") or {}).get("lei-records") or {}).get("data") or {})
        if rel.get("id") and rel["id"] not in ids:
            ids.append(rel["id"])
    records: dict[str, dict[str, Any]] = {}
    evidence = None
    named = _get(f"/lei-records?filter[entity.names]={quote(query)}&page[size]=20")
    if named is not None:
        evidence = named[1]
        for d in named[0].get("data") or []:
            rec = _record(d)
            records[rec["lei"]] = rec
    missing = [i for i in ids[:10] if i not in records]
    if missing:
        more = _get(f"/lei-records?filter[lei]={','.join(missing)}&page[size]={len(missing)}")
        if more is not None:
            evidence = evidence or more[1]
            for d in more[0].get("data") or []:
                rec = _record(d)
                records[rec["lei"]] = rec
    if not records:
        if fuzzy is None and named is None:
            raise UpstreamError("GLEIF search unavailable")
        return {"found": False, "query": query, "candidates": [],
                "evidence": evidence or (fuzzy or named)[1]}

    def rank(rec: dict[str, Any]) -> tuple:
        names = [rec["legal_name"] or "", *rec["other_names"]]
        best = max(similarity(query, n) for n in names if n)
        return (-best, rec["entity_status"] != "ACTIVE", rec["registration_status"] != "ISSUED",
                rec["legal_name"] or "")

    ranked = sorted(records.values(), key=rank)[:want]
    for rec in ranked:
        rec["match_score"] = max(similarity(query, n)
                                 for n in [rec["legal_name"] or "", *rec["other_names"]] if n)
    return {"found": True, "query": query, "candidates": ranked,
            "note": "best name match first (active, issued registrations first among equals); "
                    "confirm by LEI before relying on one",
            "evidence": evidence}


__all__ = ["lei_checksum_ok", "lookup"]
