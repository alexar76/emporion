"""National company registers: is this company real, alive, and who is it.

GLEIF knows the ~3 million entities that have an LEI; a small supplier usually has none.
A national register knows every company of its country. EMPORION asks the registers
that publish openly, without a key, under an open licence:

    NO  Brønnøysund Register Centre (Enhetsregisteret), NLOD 2.0
    FR  API Recherche d'entreprises (INSEE SIRENE + INPI RNE), Licence Ouverte 2.0
    CZ  ARES (Ministry of Finance)
    FI  PRH / YTJ open data (Finnish Patent and Registration Office), CC BY 4.0
    GB  Companies House, Open Government Licence v3.0 — its API needs a free key, so GB is
        offered only when the operator has set COMPANIES_HOUSE_API_KEY

Every answer has the same shape — name, number, status, legal form, founding date,
address, VAT number where the register gives one — plus `register`, the fields the
register itself uses, so nothing is lost in translation.

A number the register does not know is an answer (found: false). A register that does
not answer costs nothing.
"""

from __future__ import annotations

import base64
import os
import re
from typing import Any
from urllib.parse import quote

from emporion.net import Fetched, UpstreamError, fetch

BRREG = "https://data.brreg.no/enhetsregisteret/api/enheter"
FR_SEARCH = "https://recherche-entreprises.api.gouv.fr/search"
ARES = "https://ares.gov.cz/ekonomicke-subjekty-v-be/rest/ekonomicke-subjekty"
PRH = "https://avoindata.prh.fi/opendata-ytj-api/v3/companies"
CH = "https://api.company-information.service.gov.uk"
COUNTRIES = {"NO": "brreg", "FR": "recherche_entreprises", "CZ": "ares", "FI": "prh",
             "GB": "companies_house"}
_KEYED = {"GB": "COMPANIES_HOUSE_API_KEY"}


def available() -> list[str]:
    """The registers this EMPORION can ask now: the open ones, and keyed ones with a key."""
    return [cc for cc in COUNTRIES if cc not in _KEYED or os.environ.get(_KEYED[cc])]


def _q(name: str | None) -> str:
    return quote(str(name or "").strip())


def _digits(value: Any) -> str:
    return re.sub(r"[\s.\-]", "", str(value or ""))


# ── Norway ───────────────────────────────────────────────────────────────────


def _no_valid(orgnr: str) -> bool:
    if not re.fullmatch(r"\d{9}", orgnr):
        return False
    s = sum(int(d) * w for d, w in zip(orgnr[:8], (3, 2, 7, 6, 5, 4, 3, 2)))
    check = 11 - s % 11
    return (0 if check == 11 else check) == int(orgnr[8]) and check != 10


def _no_address(a: Any) -> str | None:
    if not isinstance(a, dict):
        return None
    parts = [*a.get("adresse", []), f"{a.get('postnummer', '')} {a.get('poststed', '')}".strip(),
             a.get("land")]
    return ", ".join(p for p in parts if p) or None


def _no(e: dict) -> dict[str, Any]:
    if e.get("slettedato"):
        status = "deleted"
    elif e.get("konkurs"):
        status = "bankrupt"
    elif e.get("underTvangsavviklingEllerTvangsopplosning"):
        status = "compulsory dissolution"
    elif e.get("underAvvikling"):
        status = "in liquidation"
    else:
        status = "active"
    n = e.get("organisasjonsnummer")
    form = e.get("organisasjonsform") or {}
    activity = e.get("naeringskode1") or {}
    return {
        "number": n, "name": e.get("navn"), "status": status,
        "legal_form": form.get("beskrivelse") or form.get("kode"),
        "founded": e.get("stiftelsesdato") or e.get("registreringsdatoEnhetsregisteret"),
        "address": _no_address(e.get("forretningsadresse") or e.get("postadresse")),
        "activity": f"{activity.get('kode')} {activity.get('beskrivelse')}".strip()
        if activity else None,
        "vat": f"NO{n}MVA" if e.get("registrertIMvaregisteret") else None,
        "register": {k: e.get(k) for k in (
            "organisasjonsform", "registreringsdatoEnhetsregisteret", "registrertIMvaregisteret",
            "registrertIForetaksregisteret", "konkurs", "underAvvikling", "slettedato",
            "antallAnsatte", "hjemmeside", "sisteInnsendteAarsregnskap") if k in e},
    }


def _norway(number: str | None, name: str | None, limit: int) -> tuple[list, Fetched]:
    if number:
        n = _digits(number)
        if not _no_valid(n):
            raise ValueError("a Norwegian organisation number is 9 digits with a valid "
                             "check digit")
        got = fetch(f"{BRREG}/{n}", source_id="brreg", headers={"Accept": "application/json"},
                    max_bytes=1 << 20, ok_statuses=(200, 404, 410))
        if got.status == 404:
            return [], got
        return [_no(got.json())], got
    got = fetch(f"{BRREG}?navn={_q(name)}&size={limit}", source_id="brreg",
                headers={"Accept": "application/json"}, max_bytes=4 << 20)
    hits = (got.json().get("_embedded") or {}).get("enheter") or []
    return [_no(e) for e in hits[:limit]], got


# ── France ───────────────────────────────────────────────────────────────────


def _fr(r: dict) -> dict[str, Any]:
    siege = r.get("siege") or {}
    return {
        "number": r.get("siren"), "name": r.get("nom_raison_sociale") or r.get("nom_complet"),
        "status": "active" if r.get("etat_administratif") == "A" else "ceased",
        "legal_form": r.get("nature_juridique"),
        "founded": r.get("date_creation"),
        "address": siege.get("adresse"),
        "activity": r.get("activite_principale"),
        "vat": (r.get("tva") or [None])[0] if isinstance(r.get("tva"), list) else r.get("tva"),
        "register": {"siret_head_office": siege.get("siret"),
                     "date_fermeture": r.get("date_fermeture"),
                     "categorie_entreprise": r.get("categorie_entreprise"),
                     "nature_juridique_code": r.get("nature_juridique"),
                     "nombre_etablissements_ouverts": r.get("nombre_etablissements_ouverts"),
                     "date_mise_a_jour": r.get("date_mise_a_jour")},
    }


def _france(number: str | None, name: str | None, limit: int) -> tuple[list, Fetched]:
    if number:
        n = _digits(number)
        if not re.fullmatch(r"\d{9}|\d{14}", n):
            raise ValueError("a French SIREN is 9 digits (a SIRET is 14; its first 9 are "
                             "the SIREN)")
        siren = n[:9]
        got = fetch(f"{FR_SEARCH}?q={siren}&per_page=5", source_id="recherche_entreprises",
                    max_bytes=2 << 20)
        hits = [r for r in got.json().get("results") or [] if r.get("siren") == siren]
        return [_fr(r) for r in hits[:1]], got
    got = fetch(f"{FR_SEARCH}?q={_q(name)}&per_page={limit}", source_id="recherche_entreprises",
                max_bytes=4 << 20)
    return [_fr(r) for r in (got.json().get("results") or [])[:limit]], got


# ── Czech Republic ───────────────────────────────────────────────────────────


def _cz_valid(ico: str) -> bool:
    if not re.fullmatch(r"\d{8}", ico):
        return False
    s = sum(int(d) * w for d, w in zip(ico[:7], range(8, 1, -1)))
    return (11 - s % 11) % 10 == int(ico[7])


def _cz(e: dict) -> dict[str, Any]:
    sidlo = e.get("sidlo") or {}
    return {
        "number": e.get("ico"), "name": e.get("obchodniJmeno"),
        "status": "dissolved" if e.get("datumZaniku") else "active",
        "legal_form": e.get("pravniForma"),
        "founded": e.get("datumVzniku"),
        "address": sidlo.get("textovaAdresa"),
        "activity": ", ".join((e.get("czNace") or [])[:5]) or None,
        "vat": e.get("dic"),
        "register": {"datumZaniku": e.get("datumZaniku"),
                     "pravniForma_code": e.get("pravniForma"),
                     "seznamRegistraci": e.get("seznamRegistraci"),
                     "datumAktualizace": e.get("datumAktualizace")},
    }


def _czechia(number: str | None, name: str | None, limit: int) -> tuple[list, Fetched]:
    if number:
        n = _digits(number).zfill(8)
        if not _cz_valid(n):
            raise ValueError("a Czech IČO is 8 digits with a valid check digit")
        got = fetch(f"{ARES}/{n}", source_id="ares", headers={"Accept": "application/json"},
                    max_bytes=1 << 20, ok_statuses=(200, 404))
        return ([] if got.status == 404 else [_cz(got.json())]), got
    got = fetch(f"{ARES}/vyhledat", source_id="ares", method="POST",
                json_body={"obchodniJmeno": name, "pocet": limit, "start": 0},
                headers={"Accept": "application/json", "Content-Type": "application/json"},
                max_bytes=4 << 20)
    return [_cz(e) for e in (got.json().get("ekonomickeSubjekty") or [])[:limit]], got


# ── Finland ──────────────────────────────────────────────────────────────────

_FI_STATUS = {"1": "active", "2": "removed from register", "3": "start-up not registered",
              "4": "ceased"}
_FI_SITUATION = {"KONK": "bankrupt", "SELTILA": "in liquidation", "SANE": "in re-organisation"}


def _fi_valid(business_id: str) -> bool:
    m = re.fullmatch(r"(\d{7})-(\d)", business_id)
    if not m:
        return False
    r = sum(int(d) * w for d, w in zip(m.group(1), (7, 9, 10, 5, 8, 4, 2))) % 11
    return r != 1 and (0 if r == 0 else 11 - r) == int(m.group(2))


def _fi_text(descriptions: Any, lang: str = "3") -> str | None:
    """PRH describes codes in Finnish (1), Swedish (2) and English (3); prefer English."""
    if not isinstance(descriptions, list):
        return None
    by = {d.get("languageCode"): d.get("description") for d in descriptions if isinstance(d, dict)}
    return by.get(lang) or by.get("1") or next(iter(by.values()), None)


def _fi(c: dict) -> dict[str, Any]:
    bid = (c.get("businessId") or {}).get("value")
    every = [n for n in c.get("names") or [] if isinstance(n, dict) and n.get("name")]
    # A ceased company has only ended names; then its last one is still its name.
    names = [n for n in every if not n.get("endDate")] or sorted(
        every, key=lambda n: str(n.get("endDate") or ""), reverse=True)
    name = next((n.get("name") for n in names if n.get("type") == "1"),
                names[0].get("name") if names else None)
    situations = [s.get("type") for s in c.get("companySituations") or []
                  if isinstance(s, dict) and not s.get("endDate")]
    status = next((_FI_SITUATION[t] for t in situations if t in _FI_SITUATION), None)
    if status is None:
        status = "ceased" if c.get("endDate") else _FI_STATUS.get(
            str(c.get("tradeRegisterStatus")), "active")
    forms = [f for f in c.get("companyForms") or [] if isinstance(f, dict) and not f.get("endDate")]
    addr = next((a for a in c.get("addresses") or [] if isinstance(a, dict) and a.get("type") == 1),
                None)
    address = None
    if addr:
        city = next((p.get("city") for p in addr.get("postOffices") or []
                     if p.get("languageCode") == "1"), None)
        street = " ".join(x for x in (addr.get("street"), addr.get("buildingNumber")) if x)
        address = ", ".join(x for x in (street, f"{addr.get('postCode', '')} {city or ''}".strip(),
                                         "Finland") if x)
    vat_liable = any(e.get("register") == "6" and e.get("type") in ("80", "82", "83", "84")
                     and not e.get("endDate") for e in c.get("registeredEntries") or []
                     if isinstance(e, dict))
    line = c.get("mainBusinessLine") or {}
    return {
        "number": bid, "name": name, "status": status,
        "legal_form": _fi_text(forms[0].get("descriptions")) if forms else None,
        "founded": (c.get("businessId") or {}).get("registrationDate") or c.get("registrationDate"),
        "address": address,
        "activity": f"{line.get('type')} {_fi_text(line.get('descriptions')) or ''}".strip()
        if line else None,
        "vat": f"FI{bid.replace('-', '')}" if vat_liable and bid else None,
        "register": {"tradeRegisterStatus": c.get("tradeRegisterStatus"),
                     "companySituations": situations, "endDate": c.get("endDate"),
                     "euId": (c.get("euId") or {}).get("value"),
                     "website": (c.get("website") or {}).get("url"),
                     "lastModified": c.get("lastModified")},
    }


def _finland(number: str | None, name: str | None, limit: int) -> tuple[list, Fetched]:
    if number:
        n = str(number).strip()
        if re.fullmatch(r"\d{8}", n):
            n = f"{n[:7]}-{n[7]}"
        if not _fi_valid(n):
            raise ValueError("a Finnish Business ID is 7 digits, a hyphen and a valid check "
                             "digit (e.g. 0112038-9)")
        got = fetch(f"{PRH}?businessId={n}", source_id="prh", max_bytes=1 << 20)
    else:
        got = fetch(f"{PRH}?name={_q(name)}&page=1", source_id="prh", max_bytes=8 << 20)
    found = [_fi(c) for c in got.json().get("companies") or []]
    if name:
        # PRH returns a page of matches in business-ID order, not by relevance (former and
        # auxiliary names match too): rank the exact name, then the name it starts with,
        # then the name holding it as a whole word ("Nokia Oyj" before "Nokian …"), then the
        # name starting with or containing it, active companies first within each.
        q = str(name).strip().lower()

        def rank(c: dict) -> tuple:
            n = str(c.get("name") or "").lower()
            whole_word = re.search(rf"(^|\W){re.escape(q)}(\W|$)", n) is not None
            return (n != q, not whole_word, not n.startswith(q), q not in n,
                    c.get("status") != "active")

        found.sort(key=rank)
    return found[:limit], got


# ── United Kingdom ───────────────────────────────────────────────────────────

_CH_NUMBER = re.compile(r"^(?:[A-Z]{2}\d{6}|\d{1,8})$")


def _ch_headers() -> dict[str, str]:
    key = os.environ.get("COMPANIES_HOUSE_API_KEY", "")
    if not key:
        raise ValueError("GB needs the operator's Companies House API key, and this EMPORION "
                         "has none; nothing charged")
    # HTTP Basic with the key as the user name and no password (Companies House's scheme).
    token = base64.b64encode(f"{key}:".encode()).decode()
    return {"Authorization": f"Basic {token}", "Accept": "application/json"}


def _ch_address(a: Any) -> str | None:
    if not isinstance(a, dict):
        return None
    keys = ("premises", "address_line_1", "address_line_2", "locality", "region", "postal_code",
            "country")
    return ", ".join(str(a[k]) for k in keys if a.get(k)) or None


def _gb(c: dict) -> dict[str, Any]:
    raw = str(c.get("company_status") or "")
    status = {"active": "active", "dissolved": "dissolved", "liquidation": "in liquidation",
              "receivership": "in receivership", "administration": "in administration",
              "insolvency-proceedings": "insolvency proceedings"}.get(raw, raw.replace("-", " ")
                                                                       or None)
    return {
        "number": c.get("company_number"),
        "name": c.get("company_name") or c.get("title"),
        "status": status,
        "legal_form": c.get("type") or c.get("company_type"),
        "founded": c.get("date_of_creation"),
        "address": _ch_address(c.get("registered_office_address") or c.get("address"))
        or c.get("address_snippet"),
        "activity": ", ".join(c.get("sic_codes") or []) or None,
        "vat": None,
        "register": {"company_status": raw or None, "date_of_cessation": c.get("date_of_cessation"),
                     "jurisdiction": c.get("jurisdiction"),
                     "has_insolvency_history": c.get("has_insolvency_history"),
                     "accounts_overdue": ((c.get("accounts") or {}).get("overdue")),
                     "confirmation_statement_overdue":
                         ((c.get("confirmation_statement") or {}).get("overdue"))},
    }


def _britain(number: str | None, name: str | None, limit: int) -> tuple[list, Fetched]:
    headers = _ch_headers()
    if number:
        n = re.sub(r"\s", "", str(number)).upper()
        if not _CH_NUMBER.match(n):
            raise ValueError("a UK company number is 8 characters: digits, or two letters and "
                             "six digits (SC…, NI…, OC…)")
        n = n.zfill(8)
        got = fetch(f"{CH}/company/{n}", source_id="companies_house", headers=headers,
                    max_bytes=1 << 20, ok_statuses=(200, 404))
        return ([] if got.status == 404 else [_gb(got.json())]), got
    got = fetch(f"{CH}/search/companies?q={_q(name)}&items_per_page={limit}",
                source_id="companies_house", headers=headers, max_bytes=4 << 20)
    return [_gb(c) for c in (got.json().get("items") or [])[:limit]], got


def lookup(country: str, *, number: str | None = None, name: str | None = None,
           limit: int = 5) -> dict[str, Any]:
    cc = str(country or "").strip().upper()
    if cc not in COUNTRIES:
        raise ValueError(f"no open company register for {cc or '?'} yet; known: "
                         f"{', '.join(available())} (and every LEI holder via "
                         "emporion.lei.lookup@v1)")
    if not number and not (name and len(str(name).strip()) >= 2):
        raise ValueError("give number, or a name of at least 2 characters")
    limit = max(1, min(int(limit or 5), 10))
    fn = {"NO": _norway, "FR": _france, "CZ": _czechia, "FI": _finland, "GB": _britain}[cc]
    companies, got = fn(number, None if number else name, limit)
    if any(not isinstance(c, dict) for c in companies):
        raise UpstreamError("the register answered in an unexpected shape")
    out: dict[str, Any] = {"country": cc, "query": {"number": number} if number else
                           {"name": name}, "found": bool(companies), "companies": companies,
                           "evidence": got.evidence(COUNTRIES[cc])}
    if number and not companies:
        out["note"] = f"the {cc} register has no company with that number"
    return out


__all__ = ["COUNTRIES", "available", "lookup"]
