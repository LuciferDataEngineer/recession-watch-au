"""Period helpers and Australian release-lag rules.

Lags are the gap between the end of a reference period and the usual ABS
publication time. They are used so a backtest can only see a number after it
would have been published. Exact release timestamps are stored when a page
or table states them.
"""

from __future__ import annotations

import calendar
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

MELBOURNE = ZoneInfo("Australia/Melbourne")
SYDNEY = ZoneInfo("Australia/Sydney")


def month_end(year: int, month: int) -> date:
    return date(year, month, calendar.monthrange(year, month)[1])


def parse_period(token: str) -> tuple[date, date, str]:
    """Return (start, end, normalised token) for YYYY-MM or YYYY-Qn."""
    token = token.strip()
    if "-Q" in token:
        year_s, q_s = token.split("-Q")
        year, quarter = int(year_s), int(q_s)
        start_month = 3 * (quarter - 1) + 1
        start = date(year, start_month, 1)
        end = month_end(year, start_month + 2)
        return start, end, f"{year}-Q{quarter}"
    if len(token) == 7 and token[4] == "-":
        year, month = int(token[:4]), int(token[5:7])
        start = date(year, month, 1)
        end = month_end(year, month)
        return start, end, f"{year:04d}-{month:02d}"
    raise ValueError(f"unrecognised period {token!r}")


def quarter_token(end: date) -> str:
    quarter = (end.month - 1) // 3 + 1
    return f"{end.year}-Q{quarter}"


def add_months(day: date, months: int) -> date:
    month_index = day.month - 1 + months
    year = day.year + month_index // 12
    month = month_index % 12 + 1
    last = calendar.monthrange(year, month)[1]
    return date(year, month, min(day.day, last))


def last_weekday(year: int, month: int, weekday: int) -> date:
    """weekday: Monday=0 ... Sunday=6. Wednesday=2."""
    last = month_end(year, month)
    delta = (last.weekday() - weekday) % 7
    return last - timedelta(days=delta)


def at_1130_sydney(day: date) -> datetime:
    local = datetime(day.year, day.month, day.day, 11, 30, tzinfo=SYDNEY)
    return local.astimezone(ZoneInfo("UTC"))


def publish_monthly(period_end: date, kind: str) -> datetime:
    """Approximate the ABS release instant for a monthly reference period."""
    if kind == "lf":
        # October 2026 reference was published 19 Nov 2026. Month-end + 19 days.
        return at_1130_sydney(period_end + timedelta(days=19))
    if kind == "cpi":
        nxt = add_months(date(period_end.year, period_end.month, 1), 1)
        return at_1130_sydney(last_weekday(nxt.year, nxt.month, 2))
    if kind == "hsi":
        # September 2026 spending was published 4 Nov 2026 (month-end + 35 days).
        return at_1130_sydney(period_end + timedelta(days=35))
    if kind == "ba":
        # September 2026 approvals page is dated 9 Nov 2026 (month-end + 40 days).
        return at_1130_sydney(period_end + timedelta(days=40))
    raise KeyError(kind)


def publish_quarterly(period_end: date, kind: str) -> datetime:
    if kind in {"gdp", "sfd"}:
        # June quarter 2026 was published 2 Sep 2026 (quarter-end + 64 days).
        return at_1130_sydney(period_end + timedelta(days=64))
    if kind == "qbis":
        # Business indicators land a few days before the national accounts.
        return at_1130_sydney(period_end + timedelta(days=58))
    raise KeyError(kind)


def melbourne_label(moment: datetime) -> str:
    local = moment.astimezone(MELBOURNE)
    hour = local.strftime("%I").lstrip("0") or "12"
    clock = f"{hour}:{local.strftime('%M')} {local.strftime('%p').lower()}"
    tz = local.tzname() or "AET"
    return f"{local.strftime('%d').lstrip('0')} {local.strftime('%b %Y')}, {clock} {tz}"
