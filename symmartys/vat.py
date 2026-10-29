"""EU VAT number validity from VIES, with the consultation number that proves the check.

An agent buying from or selling to an EU business needs to know whether the other side's
VAT number is valid today — reverse charge, invoices and OSS returns depend on it. VIES
answers from the member state's own registry. When the caller gives its OWN VAT number
as requester, VIES issues a consultation number: the official proof, in the caller's
name, that the check was made at that moment. SYMMARTYS passes it through untouched and
keeps nothing.

"Invalid" is an answer (the buyer learned something, and pays for it). A member state
registry that is down, busy or timing out is not an answer: UpstreamError, ok:false, no
charge — VIES reports those as MS_UNAVAILABLE, MS_MAX_CONCURRENT_REQ, TIMEOUT and so on.
"""

from __future__ import annotations

import re
from typing import Any

from symmartys.net import UpstreamError, fetch

CHECK_URL = "https://ec.europa.eu/taxation_customs/vies/rest-api/check-vat-number"

#: VIES member-state prefixes. Greece is EL (not GR); XI is Northern Ireland (EU VAT
#: rules for goods after Brexit).
MEMBER_STATES = frozenset({
    "AT", "BE", "BG", "CY", "CZ", "DE", "DK", "EE", "EL", "ES", "FI", "FR", "HR", "HU",
    "IE", "IT", "LT", "LU", "LV", "MT", "NL", "PL", "PT", "RO", "SE", "SI", "SK", "XI",
})
_ALIASES = {"GR": "EL"}
_NUMBER = re.compile(r"^[0-9A-Z+*]{2,14}$")

#: VIES userError values that mean "no answer from the registry", not "invalid number".
_UNAVAILABLE = frozenset({
    "MS_UNAVAILABLE", "MS_MAX_CONCURRENT_REQ", "MS_MAX_CONCURRENT_REQ_TIME", "TIMEOUT",
    "SERVICE_UNAVAILABLE", "GLOBAL_MAX_CONCURRENT_REQ", "GLOBAL_MAX_CONCURRENT_REQ_TIME",
    "IP_BLOCKED", "VAT_BLOCKED",
})


def split_vat(vat: str, country: str | None = None) -> tuple[str, str]:
    """("DE", "811569869") from "DE 811.569-869", "de811569869" or ("811569869", "DE")."""
    raw = re.sub(r"[\s.\-/]", "", str(vat or "")).upper()
    cc = (country or "").strip().upper()
    if cc:
        cc = _ALIASES.get(cc, cc)
        if raw.startswith(cc) or (cc == "EL" and raw.startswith("GR")):
            raw = raw[2:]
    else:
        cc, raw = _ALIASES.get(raw[:2], raw[:2]), raw[2:]
    if cc not in MEMBER_STATES:
        raise ValueError(f"{cc or '?'} is not a VIES member state; EU VAT numbers start with "
                         "the country prefix (DE, FR, EL for Greece, XI for Northern Ireland)")
    if not _NUMBER.match(raw):
        raise ValueError("a VAT number is 2-14 letters or digits after the country prefix")
    return cc, raw


def _clean(text: Any) -> str | None:
    if not isinstance(text, str):
        return None
    t = " ".join(text.replace("\n", ", ").split()).strip(", ")
    return None if t in ("", "---") else t


def check(vat: str, *, country: str | None = None, requester_vat: str | None = None) -> dict[str, Any]:
    cc, number = split_vat(vat, country)
    body: dict[str, Any] = {"countryCode": cc, "vatNumber": number}
    if requester_vat:
        rcc, rnum = split_vat(requester_vat)
        body.update({"requesterMemberStateCode": rcc, "requesterNumber": rnum})
    got = fetch(CHECK_URL, source_id="vies", method="POST", json_body=body,
                headers={"Content-Type": "application/json"}, max_bytes=1 << 20,
                ok_statuses=(200, 400))
    data = got.json()
    if not isinstance(data, dict):
        raise UpstreamError("VIES answered without an object")
    # A 200 carries `userError`; a 400 carries {"errorWrappers": [{"error": …}]}.
    error = str(data.get("userError") or "")
    wrappers = data.get("errorWrappers")
    if not error and isinstance(wrappers, list) and wrappers and isinstance(wrappers[0], dict):
        error = str(wrappers[0].get("error") or "")
    if error in _UNAVAILABLE:
        raise UpstreamError(f"VIES: the {cc} registry did not answer ({error}); nothing charged, "
                            "retry later")
    if error == "INVALID_REQUESTER_INFO":
        raise ValueError("requester_vat is not a valid EU VAT number; VIES issues the "
                         "consultation number only to a valid requester")
    if error == "INVALID_INPUT" or got.status == 400:
        raise ValueError(f"VIES refused the input for {cc}{number} ({error or 'HTTP 400'}): "
                         "check the number's format for that country")
    if not isinstance(data.get("valid"), bool):
        raise UpstreamError("VIES answered without a validity flag")
    consultation = data.get("requestIdentifier") or None
    return {
        "vat": f"{cc}{number}",
        "country_code": cc,
        "valid": data["valid"],
        "name": _clean(data.get("name")),
        "address": _clean(data.get("address")),
        "checked_at": data.get("requestDate"),
        "consultation_number": consultation,
        "requester_vat": (f"{body['requesterMemberStateCode']}{body['requesterNumber']}"
                          if requester_vat else None),
        "note": ("the consultation number is VIES's proof, in the requester's name, that this "
                 "check was made at checked_at" if consultation else
                 "pass requester_vat (your own EU VAT number) to receive VIES's consultation "
                 "number as proof of the check"),
        "evidence": got.evidence("vies"),
    }


__all__ = ["MEMBER_STATES", "check", "split_vat"]
