"""EORI number validity from the European Commission's EOS service.

Every business that imports into or exports from the EU customs territory needs an
EORI number, and a customs declaration naming an invalid one stops at the border. An
agent arranging cross-border delivery checks the other side's number first. The
Commission's EOS service answers from the member states' registrations; the name and
address come back only for an operator that agreed to their publication.

"Not valid" is an answer. A service that does not answer costs nothing.
"""

from __future__ import annotations

import re
from typing import Any
from xml.sax.saxutils import escape

from defusedxml import ElementTree as ET

from symmartys.net import UpstreamError, fetch

URL = "https://ec.europa.eu/taxation_customs/dds2/eos/validation/services/validation"
MAX_NUMBERS = 10
_EORI = re.compile(r"^[A-Z]{2}[0-9A-Z]{1,15}$")
_ENVELOPE = ('<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">'
             '<soap:Body><ev:validateEORI xmlns:ev="http://eori.ws.eos.dds.s/">{numbers}'
             '</ev:validateEORI></soap:Body></soap:Envelope>')
#: Fields EOS returns beside the verdict, when the operator consented to publication.
_DETAIL = ("name", "street", "postalCode", "city", "country")


def normalise(number: str) -> str:
    n = re.sub(r"[\s.\-/]", "", str(number or "")).upper()
    if not _EORI.match(n):
        raise ValueError(f"not an EORI number: {number!r} (a 2-letter country code and up "
                         "to 15 letters or digits)")
    return n


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def check(numbers: list[str]) -> dict[str, Any]:
    if not numbers:
        raise ValueError("give at least one EORI number")
    if len(numbers) > MAX_NUMBERS:
        raise ValueError(f"at most {MAX_NUMBERS} EORI numbers per call")
    clean = list(dict.fromkeys(normalise(n) for n in numbers))
    body = _ENVELOPE.format(numbers="".join(f"<ev:eori>{escape(n)}</ev:eori>" for n in clean))
    got = fetch(URL, source_id="eos", method="POST", content=body.encode(),
                headers={"Content-Type": "text/xml; charset=utf-8", "SOAPAction": ""},
                max_bytes=256 << 10, timeout=30)
    try:
        root = ET.fromstring(got.body)
    except ET.ParseError as exc:
        raise UpstreamError("EOS answered with unreadable XML") from exc
    fault = next((el for el in root.iter() if _local(el.tag) == "Fault"), None)
    if fault is not None:  # (an HTTP 500 fault is retried, then refused, by net.fetch)
        text = " ".join((el.text or "").strip() for el in fault.iter() if el.text)
        raise UpstreamError(f"EOS did not answer ({text[:120] or 'SOAP fault'}); "
                            "nothing charged")
    request_date, results = None, []
    for el in root.iter():
        tag = _local(el.tag)
        if tag == "requestDate":
            request_date = (el.text or "").strip() or None
        elif tag == "result":
            fields = {_local(c.tag): (c.text or "").strip() for c in el}
            status = fields.get("status")
            if status not in ("0", "1"):
                raise UpstreamError(f"EOS answered an unknown status {status!r}")
            details = {k: fields[k] for k in _DETAIL if fields.get(k)}
            results.append({"eori": fields.get("eori"), "valid": status == "0",
                            "status": fields.get("statusDescr"), **details})
    if len(results) != len(clean):
        raise UpstreamError("EOS answered for a different set of numbers")
    return {
        "results": results,
        "checked_on": request_date,
        "note": "name and address appear only for operators that consented to publication",
        "evidence": got.evidence("eos"),
    }


__all__ = ["MAX_NUMBERS", "check", "normalise"]
