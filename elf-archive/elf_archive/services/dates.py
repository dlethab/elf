"""Historical dates with explicit uncertainty.

A date is never "invented" to fill a gap: unknown stays unknown, a year stays a year,
"c. 1952" stays approximate. Partial ISO strings (YYYY, YYYY-MM, YYYY-MM-DD) are stored.

Accepted input:  1952-03-14 | 1952-03 | 1952 | c. 1952 | circa 1952-03 | 1950s |
                 1950 to 1955 | 1950-03 to 1952 | (blank) | unknown
"""
import calendar
import re
from dataclasses import dataclass
from datetime import date
from typing import Optional

MIN_YEAR, MAX_YEAR = 1000, 2100
MONTHS = ["January", "February", "March", "April", "May", "June", "July",
          "August", "September", "October", "November", "December"]
DATE_HELP = "Examples: 1952, 1952-03, 1952-03-14, c. 1952, 1950s, 1950 to 1955. Leave blank if unknown."
_PART = r"(\d{4})(?:-(\d{2})(?:-(\d{2}))?)?"
_APPROX = re.compile(rf"^(?:c\.?|ca\.?|circa|~)\s*{_PART}$", re.I)
_DECADE = re.compile(r"^(\d{3})0s$")
_RANGE = re.compile(rf"^{_PART}\s+to\s+{_PART}$", re.I)
_SIMPLE = re.compile(rf"^{_PART}$")


class DateError(ValueError):
    pass


@dataclass(frozen=True)
class FuzzyDate:
    start: Optional[str] = None
    end: Optional[str] = None
    precision: str = "unknown"
    note: Optional[str] = None

    def as_dict(self):
        return {"start": self.start, "end": self.end, "precision": self.precision, "note": self.note}


UNKNOWN = FuzzyDate()


def _check(y, m, d):
    year = int(y)
    if not MIN_YEAR <= year <= MAX_YEAR:
        raise DateError(f"Year must be between {MIN_YEAR} and {MAX_YEAR}.")
    if m is not None:
        month = int(m)
        if not 1 <= month <= 12:
            raise DateError("Month must be between 01 and 12.")
        if d is not None:
            try:
                date(year, month, int(d))
            except ValueError:
                raise DateError("That calendar date does not exist.") from None
    return "-".join(p for p in (y, m, d) if p is not None)


def _bounds(s):
    """Earliest and latest calendar day a partial ISO string can mean."""
    p = s.split("-")
    y = int(p[0])
    if len(p) == 1:
        return date(y, 1, 1), date(y, 12, 31)
    m = int(p[1])
    if len(p) == 2:
        return date(y, m, 1), date(y, m, calendar.monthrange(y, m)[1])
    d = int(p[2])
    return date(y, m, d), date(y, m, d)


def parse(text):
    t = (text or "").strip()
    if not t or t.lower() in ("unknown", "?"):
        return UNKNOWN
    if m := _APPROX.match(t):
        return FuzzyDate(_check(*m.groups()), None, "approximate")
    if m := _DECADE.match(t):
        base = int(m.group(1)) * 10
        _check(str(base), None, None)
        return FuzzyDate(str(base), str(base + 9), "decade")
    if m := _RANGE.match(t):
        g = m.groups()
        a, b = _check(*g[:3]), _check(*g[3:])
        if _bounds(a)[0] > _bounds(b)[1]:
            raise DateError("The range ends before it starts.")
        return FuzzyDate(a, b, "range")
    if m := _SIMPLE.match(t):
        iso = _check(*m.groups())
        return FuzzyDate(iso, None, {1: "year", 2: "month", 3: "exact"}[iso.count("-") + 1])
    raise DateError("Use a form like 1952, 1952-03, 1952-03-14, c. 1952, 1950s, or 1950 to 1955.")


def _one(s, months=MONTHS):
    p = s.split("-")
    y = int(p[0])
    if len(p) == 1:
        return str(y)
    if len(p) == 2:
        return f"{months[int(p[1]) - 1]} {y}"
    return f"{int(p[2])} {months[int(p[1]) - 1]} {y}"


def format_date(start, end=None, precision="unknown", *, months=MONTHS, approx="c.", unknown="Unknown"):
    """Human display that preserves the uncertainty. Labels can be localised (see i18n.fdate)."""
    if precision == "unknown" or not start:
        return unknown
    if precision == "approximate":
        return f"{approx} {_one(start, months)}"
    if precision == "decade":
        return f"{start}s"
    if precision == "range":
        return f"{_one(start, months)}–{_one(end, months)}" if end else _one(start, months)
    return _one(start, months)


def precision_note(precision):
    """Plain-language label so uncertainty is never conveyed by format alone."""
    return {"exact": "exact date", "month": "month known", "year": "year known", "decade": "decade only",
            "approximate": "approximate", "range": "date range", "unknown": "not documented"}.get(precision, precision)


def year_span(start, end, precision):
    """(first_year, last_year) for filtering/sorting; None when unknown."""
    if precision == "unknown" or not start:
        return None
    return int(start[:4]), int((end or start)[:4])


def to_input(start, end, precision):
    """Inverse of parse(): the text a form should show so a round trip preserves the uncertainty."""
    if precision == "unknown" or not start:
        return ""
    if precision == "approximate":
        return f"c. {start}"
    if precision == "decade":
        return f"{start}s"
    if precision == "range":
        return f"{start} to {end}" if end else start
    return start


def columns(prefix, fd):
    return {f"{prefix}_start": fd.start, f"{prefix}_end": fd.end,
            f"{prefix}_precision": fd.precision, f"{prefix}_note": fd.note}


def from_row(row, prefix):
    return FuzzyDate(row[f"{prefix}_start"], row[f"{prefix}_end"], row[f"{prefix}_precision"], row[f"{prefix}_note"])
