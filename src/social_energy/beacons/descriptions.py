"""Written descriptions of self-report moments → one flagged row per card entry.

Participants could describe a moment they marked with the button on a paper card: their study
ID, when it happened, and what happened. A researcher transcribes the cards into a table with
three columns (``id``, ``when``, ``text``), each as written. ``when`` is free text: a date, a
date with a clock time or a range, a programme item, or nothing.

``parse_when`` reads a date and a start clock time out of it when it can; anything else stays
in ``when`` for a reader. Nothing is dropped: rows without an ID or text are flagged, and the QA
dict accounts for every row. The text itself is participants' free text and never leaves the
team's data (see ``docs/context/instruments/beacons.md``).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, time

import polars as pl

#: ``27.08.2026``, ``23.08.``, ``24.-25.08.``, ``25./26.08.2026``: first day, optional second day,
#: month, optional year.
_DATE = re.compile(r"(\d{1,2})\.(?:\s*[-/]\s*(\d{1,2})\.)?\s*(\d{1,2})\.(\d{4})?")
#: ``11:20 Uhr``, ``10-11 Uhr``, ``(0:50 Uhr``: the first clock time before "Uhr".
_CLOCK = re.compile(r"(\d{1,2})(?::(\d{2}))?\s*(?:-\s*\d{1,2}(?::\d{2})?\s*)?Uhr")
#: ID cells that mean "no ID on the card".
_NO_ID = re.compile(r"(no|keine)\s*id", re.IGNORECASE)


@dataclass(frozen=True)
class When:
    day: date | None
    clock: time | None
    flags: set[str] = field(default_factory=set)


def parse_when(text: str | None, *, year: int, first_day: date, last_day: date) -> When:
    """The day and start time a card's ``when`` names, with flags for what was uncertain.

    Flags: ``no_date`` (no date found), ``implausible_date`` (a date outside first..last day, or
    not a date), ``date_range`` (a span of days or "and others": the first day is kept),
    ``uncertain`` (a question mark). A clock time is read only with a date.
    """
    flags: set[str] = set()
    s = text or ""
    if "?" in s:
        flags.add("uncertain")
    if re.search(r"weitere|others", s, re.IGNORECASE):
        flags.add("date_range")
    m = _DATE.search(s)
    if not m:
        return When(None, None, flags | {"no_date"})
    d1, d2, month, y = m.groups()
    if d2:
        flags.add("date_range")
    try:
        day = date(int(y) if y else year, int(month), int(d1))
    except ValueError:
        return When(None, None, flags | {"implausible_date"})
    if not first_day <= day <= last_day:
        return When(None, None, flags | {"implausible_date"})
    clock = None
    c = _CLOCK.search(s[m.end() :])
    if c and int(c.group(1)) < 24 and int(c.group(2) or 0) < 60:
        clock = time(int(c.group(1)), int(c.group(2) or 0))
    return When(day, clock, flags)


def _study_id(value: object) -> str | None:
    if value is None:
        return None
    s = str(value).strip()
    if not s or _NO_ID.search(s):
        return None
    return s.removesuffix(".0")


def _clean(text: object) -> str | None:
    if text is None:
        return None
    s = " ".join(str(text).split())
    if len(s) >= 2 and s[0] == '"' and s.count('"') % 2 == 1:
        s = s[1:]  # an opening quote the transcriber did not close
    if len(s) >= 2 and s[0] == s[-1] == '"':
        s = s[1:-1]
    return s.strip() or None


def parse_descriptions(
    raw: pl.DataFrame, *, year: int, first_day: date, last_day: date
) -> tuple[pl.DataFrame, dict[str, int]]:
    """One row per input row: ``study_id``, ``when``, ``day``, ``clock``, ``text`` and flags.

    Flags: ``no_id``, ``empty`` (no text), the ``parse_when`` flags as booleans, and ``ok``
    (an ID and a text). ``raw`` has ``id``, ``when`` and ``text``, values as written.
    """
    rows = []
    for r in raw.iter_rows(named=True):
        w = parse_when(r["when"], year=year, first_day=first_day, last_day=last_day)
        sid = _study_id(r["id"])
        text = _clean(r["text"])
        rows.append({
            "study_id": sid,
            "when": None if r["when"] is None else " ".join(str(r["when"]).split()),
            "day": w.day,
            "clock": w.clock,
            "text": text,
            "no_id": sid is None,
            "empty": text is None,
            "no_date": "no_date" in w.flags,
            "implausible_date": "implausible_date" in w.flags,
            "date_range": "date_range" in w.flags,
            "uncertain": "uncertain" in w.flags,
            "ok": sid is not None and text is not None,
        })  # fmt: skip
    schema = {
        "study_id": pl.String, "when": pl.String, "day": pl.Date, "clock": pl.Time,
        "text": pl.String, "no_id": pl.Boolean, "empty": pl.Boolean, "no_date": pl.Boolean,
        "implausible_date": pl.Boolean, "date_range": pl.Boolean, "uncertain": pl.Boolean,
        "ok": pl.Boolean,
    }  # fmt: skip
    df = pl.DataFrame(rows, schema=schema, orient="row")
    qa = {
        "rows": df.height,
        "ok": int(df["ok"].sum()),
        "no_id": int(df["no_id"].sum()),
        "empty": int(df["empty"].sum()),
        "dated": int(df["day"].is_not_null().sum()),
        "timed": int(df["clock"].is_not_null().sum()),
    }
    return df, qa
