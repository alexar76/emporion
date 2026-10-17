"""Business days: is this date a working day here, and what is N working days from it.

An agent that promises "payment within 5 business days" or settles in euro needs the
calendar of the place it trades in: the country's (or a region's) public holidays, its
weekend (Friday-Saturday in some countries), or a market's closing days — TARGET2 for
euro settlement, NYSE, LSE and others.

The calendars come from python-holidays (MIT), compiled into the package: no network,
nothing to go down. Its version is part of every answer, because a calendar is only as
current as the release it ships in — a holiday a government declares next week is not
in it until a release adds it.
"""

from __future__ import annotations

import datetime as dt
from functools import lru_cache
from typing import Any

import holidays

MAX_SPAN_DAYS = 3660
MAX_ADD = 1000
_WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")


@lru_cache(maxsize=1)
def _countries() -> dict[str, list[str]]:
    return holidays.list_supported_countries()


@lru_cache(maxsize=1)
def _markets() -> dict[str, list[str]]:
    return holidays.list_supported_financial()


def _date(value: Any, name: str) -> dt.date:
    if value in (None, ""):
        return dt.datetime.now(dt.timezone.utc).date()
    try:
        return dt.date.fromisoformat(str(value)[:10])
    except ValueError as exc:
        raise ValueError(f"{name} must be YYYY-MM-DD") from exc


@lru_cache(maxsize=256)
def _calendar(country: str | None, market: str | None, subdiv: str | None,
              language: str | None, year: int) -> holidays.HolidayBase:
    years = range(year - 1, year + 3)
    if market:
        return holidays.financial_holidays(market, years=years)
    kwargs: dict[str, Any] = {"years": years}
    if subdiv:
        kwargs["subdiv"] = subdiv
    if language:
        kwargs["language"] = language
    return holidays.country_holidays(country, **kwargs)


def _resolve(country: str | None, market: str | None, subdiv: str | None) -> tuple:
    if bool(country) == bool(market):
        raise ValueError("give either country (ISO 3166 alpha-2, e.g. DE) or market "
                         "(e.g. XECB for TARGET2, XNYS, XLON)")
    if market:
        m = market.strip().upper()
        if m not in _markets():
            raise ValueError(f"unknown market {m}; known: {', '.join(sorted(_markets()))}")
        return None, m, None
    c = country.strip().upper()
    if c not in _countries():
        raise ValueError(f"no calendar for country {c}")
    s = subdiv.strip().upper() if subdiv else None
    if s and s not in _countries()[c]:
        raise ValueError(f"{c} has no subdivision {s}; known: {', '.join(_countries()[c][:60])}")
    return c, None, s


class _Cal:
    """Holidays and weekend for one place, growing its year range as dates need it."""

    def __init__(self, country, market, subdiv, language):
        self.key = (country, market, subdiv, language)

    def of(self, day: dt.date) -> holidays.HolidayBase:
        try:
            return _calendar(*self.key, day.year)
        except NotImplementedError as exc:
            raise ValueError(str(exc)) from exc

    def holiday(self, day: dt.date) -> str | None:
        return self.of(day).get(day)

    def working(self, day: dt.date) -> bool:
        cal = self.of(day)
        return day.weekday() not in cal.weekend and day not in cal

    def step(self, day: dt.date, n: int) -> dt.date:
        """The n-th working day after (n > 0) or before (n < 0) day."""
        sign, left = (1 if n > 0 else -1), abs(n)
        while left:
            day += dt.timedelta(days=sign)
            if self.working(day):
                left -= 1
        return day


def check(*, country: str | None = None, market: str | None = None, subdiv: str | None = None,
          date: str | None = None, add_business_days: int | None = None,
          until: str | None = None, list_year: int | None = None,
          language: str | None = None) -> dict[str, Any]:
    c, m, s = _resolve(country, market, subdiv)
    cal = _Cal(c, m, s, language)
    day = _date(date, "date")
    out: dict[str, Any] = {
        "calendar": {"country": c, "subdivision": s, "market": m},
        "date": day.isoformat(),
        "weekday": _WEEKDAYS[day.weekday()],
        "is_business_day": cal.working(day),
        "holiday": cal.holiday(day),
        "weekend": sorted(_WEEKDAYS[d] for d in cal.of(day).weekend),
        "next_business_day": cal.step(day, 1).isoformat(),
        "previous_business_day": cal.step(day, -1).isoformat(),
    }
    if add_business_days is not None:
        n = int(add_business_days)
        if abs(n) > MAX_ADD:
            raise ValueError(f"add_business_days must be within ±{MAX_ADD}")
        out["add_business_days"] = n
        out["result_date"] = (cal.step(day, n) if n else day).isoformat()
    if until:
        end = _date(until, "until")
        lo, hi = sorted((day, end))
        if (hi - lo).days > MAX_SPAN_DAYS:
            raise ValueError("until must be within 10 years of date")
        count, d = 0, lo + dt.timedelta(days=1)
        while d <= hi:
            count += cal.working(d)
            d += dt.timedelta(days=1)
        out["until"] = end.isoformat()
        out["business_days_between"] = count if end >= day else -count
        out["between_note"] = "counts working days after date, up to and including until"
    if list_year is not None:
        y = int(list_year)
        if not 1950 <= y <= 2100:
            raise ValueError("list_year must be 1950-2100")
        yc = _calendar(c, m, s, language, y)
        out["holidays"] = [{"date": k.isoformat(), "name": v}
                           for k, v in sorted(yc.items()) if k.year == y]
    out["evidence"] = {"source": f"python-holidays {holidays.__version__}",
                       "licence": "MIT", "url": "https://github.com/vacanza/holidays",
                       "note": "compiled into EMPORION; a holiday declared after this "
                               "release is not in it"}
    return out


def supported() -> dict[str, Any]:
    # The library lists each country under its alpha-2 and its alpha-3 code; count it once.
    return {"countries": sum(1 for code in _countries() if len(code) == 2),
            "markets": sorted(_markets()),
            "version": holidays.__version__}


__all__ = ["check", "supported"]
