"""ECB euro reference rates: any pair, any date since 1999, with the rate's own date.

The ECB publishes euro reference rates for about thirty currencies on TARGET business
days around 16:00 CET. A rate "on" a date is the latest published on or before it, and
the answer says which day that was — a weekend date silently priced at Friday's rate is
fine, but the buyer must be able to see it. Cross rates go through the euro, in
Decimal. Reference rates are for information, not dealing; the answer says so.

The whole history (one 640 KB zip) is cached and re-fetched every few hours; it is kept
as one date array plus one value array per currency, about 3 MB.
"""

from __future__ import annotations

import csv
import io
import threading
import time
import zipfile
from array import array
from bisect import bisect_right
from datetime import date
from decimal import ROUND_HALF_EVEN, Decimal, InvalidOperation
from typing import Any

from symmartys.net import Fetched, UpstreamError, fetch

HIST_URL = "https://www.ecb.europa.eu/stats/eurofxref/eurofxref-hist.zip"
REFRESH_S = 3 * 3600

#: ISO 4217 minor units for the ECB's currencies (two unless listed).
_MINOR = {"JPY": 0, "ISK": 0, "KRW": 0, "CLP": 0, "VND": 0, "HUF": 2, "IDR": 2}


class RateTable:
    def __init__(self, dates: array, columns: dict[str, array], fetched: Fetched):
        self.dates = dates                    # ordinals, ascending
        self.columns = columns                # currency → rate per date (nan = not quoted)
        self.fetched = fetched

    @classmethod
    def parse(cls, fetched: Fetched) -> "RateTable":
        try:
            with zipfile.ZipFile(io.BytesIO(fetched.body)) as zf:
                text = zf.read(zf.namelist()[0]).decode("utf-8")
        except (zipfile.BadZipFile, IndexError, KeyError) as exc:
            raise UpstreamError("ECB history is not a readable zip") from exc
        rows = list(csv.reader(io.StringIO(text)))
        if not rows or rows[0][0].strip() != "Date":
            raise UpstreamError("ECB history has an unexpected header")
        header = [h.strip() for h in rows[0][1:]]
        parsed: list[tuple[int, list[float]]] = []
        for row in rows[1:]:
            if not row or not row[0].strip():
                continue
            try:
                d = date.fromisoformat(row[0].strip()).toordinal()
            except ValueError:
                continue
            vals = []
            for cell in row[1:len(header) + 1]:
                cell = cell.strip()
                try:
                    vals.append(float(cell) if cell and cell != "N/A" else float("nan"))
                except ValueError:
                    vals.append(float("nan"))
            vals += [float("nan")] * (len(header) - len(vals))
            parsed.append((d, vals))
        parsed.sort(key=lambda r: r[0])
        dates = array("i", (d for d, _ in parsed))
        columns = {cur: array("d", (v[i] for _, v in parsed))
                   for i, cur in enumerate(header) if cur}
        if not dates:
            raise UpstreamError("ECB history is empty")
        return cls(dates, columns, fetched)

    @property
    def latest(self) -> date:
        return date.fromordinal(self.dates[-1])

    def currencies(self) -> list[str]:
        return sorted(["EUR", *self.columns])

    def rate_eur(self, currency: str, on: date) -> tuple[Decimal, date]:
        """EUR→currency on the latest ECB day <= on at which the currency was quoted."""
        if currency == "EUR":
            i = bisect_right(self.dates, on.toordinal()) - 1
            if i < 0:
                raise ValueError("ECB reference rates start on 1999-01-04")
            return Decimal(1), date.fromordinal(self.dates[i])
        col = self.columns.get(currency)
        if col is None:
            raise ValueError(f"the ECB does not publish {currency}; it does: "
                             f"{', '.join(self.currencies())}")
        # Walk back over days the currency was not quoted (nan), but never more than two
        # weeks: a currency the ECB stopped quoting (RUB since 2022-03) must not be
        # answered with a years-old rate.
        floor = on.toordinal() - 14
        i = bisect_right(self.dates, on.toordinal()) - 1
        while i >= 0 and self.dates[i] >= floor and col[i] != col[i]:
            i -= 1
        if i < 0 or self.dates[i] < floor or col[i] != col[i]:
            raise ValueError(f"no ECB {currency} rate within two weeks before {on.isoformat()} "
                             "(the ECB stopped or had not started quoting it)")
        return Decimal(repr(col[i])), date.fromordinal(self.dates[i])


class FxService:
    def __init__(self):
        self._table: RateTable | None = None
        self._loaded_at = 0.0
        self._lock = threading.Lock()

    def table(self) -> RateTable:
        with self._lock:
            if self._table is None or time.time() - self._loaded_at > REFRESH_S:
                try:
                    self._table = RateTable.parse(fetch(HIST_URL, source_id="ecb",
                                                        max_bytes=8 << 20))
                    self._loaded_at = time.time()
                except UpstreamError:
                    if self._table is None:
                        raise
            return self._table

    def rate(self, base: str, quote: str, on: str | None = None,
             amount: str | float | None = None) -> dict[str, Any]:
        base, quote = str(base or "").strip().upper(), str(quote or "").strip().upper()
        if not (len(base) == 3 and len(quote) == 3 and base.isalpha() and quote.isalpha()):
            raise ValueError("base and quote are ISO 4217 codes, e.g. USD and EUR")
        table = self.table()
        if on:
            try:
                day = date.fromisoformat(str(on)[:10])
            except ValueError as exc:
                raise ValueError("date must be YYYY-MM-DD") from exc
        else:
            day = table.latest
        if day < date(1999, 1, 4):
            raise ValueError("ECB reference rates start on 1999-01-04")
        r_base, d_base = table.rate_eur(base, day)
        r_quote, d_quote = table.rate_eur(quote, day)
        rate = (r_quote / r_base).quantize(Decimal("1e-8"), rounding=ROUND_HALF_EVEN)
        out: dict[str, Any] = {
            "base": base, "quote": quote, "requested_date": on or None,
            "ecb_date": max(d_base, d_quote).isoformat(),
            "rate": str(rate.normalize()),
            "inverse": str((r_base / r_quote).quantize(Decimal("1e-8")).normalize()),
            "via": "EUR" if "EUR" not in (base, quote) else None,
            "eur_rates": {c: str(r) for c, r in ((base, r_base), (quote, r_quote)) if c != "EUR"},
            "latest_ecb_date": table.latest.isoformat(),
            "note": "ECB euro reference rate (information only, not a dealing rate); "
                    "a cross rate is computed through the euro",
            "evidence": table.fetched.evidence("ecb"),
        }
        if d_base != d_quote:
            out["note"] += f"; {base} quoted {d_base}, {quote} quoted {d_quote}"
        if amount is not None:
            try:
                amt = Decimal(str(amount))
            except InvalidOperation as exc:
                raise ValueError("amount must be a number") from exc
            if not amt.is_finite() or abs(amt) > Decimal("1e15"):
                raise ValueError("amount must be a finite number below 1e15")
            minor = Decimal(1).scaleb(-_MINOR.get(quote, 2))
            out["amount"] = str(amt)
            out["converted"] = str((amt * r_quote / r_base).quantize(minor, rounding=ROUND_HALF_EVEN))
        return out


__all__ = ["FxService", "RateTable", "HIST_URL"]
