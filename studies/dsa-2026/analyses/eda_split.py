"""Split-half rule of the EDA second pass (``docs/plans/ongoing/eda-second-pass.md``).

The camp days with EDA wear, alternated in date order, fixed before any second-pass analysis
ran: estimates are found on the **discovery** days and checked on the **replication** days.
A camp day runs 04:00-04:00 local, as in the EDA ingest.
"""

from __future__ import annotations

from datetime import date

import polars as pl

TZ = "Europe/Berlin"
DAY_START_H = 4
DISCOVERY = tuple(date(2026, 8, d) for d in (15, 17, 20, 22, 24, 26, 28))
REPLICATION = tuple(date(2026, 8, d) for d in (16, 19, 21, 23, 25, 27))
HALVES = ("discovery", "replication", "all")


def camp_day(t: pl.Expr) -> pl.Expr:
    """The camp day (04:00-04:00 local) of a UTC timestamp."""
    return (t.dt.convert_time_zone(TZ) - pl.duration(hours=DAY_START_H)).dt.date()


def half_of(day: pl.Expr) -> pl.Expr:
    """``discovery``, ``replication`` or null (a day outside both) for a camp-day column."""
    return (
        pl.when(day.is_in(list(DISCOVERY)))
        .then(pl.lit("discovery"))
        .when(day.is_in(list(REPLICATION)))
        .then(pl.lit("replication"))
        .otherwise(None)
    )


def subset(df: pl.DataFrame, half: str, day_col: str = "day") -> pl.DataFrame:
    """Rows of one half (``all``: every row on a day of either half)."""
    if half not in HALVES:
        raise ValueError(f"half must be one of {HALVES}")
    days = {"discovery": DISCOVERY, "replication": REPLICATION}.get(half, DISCOVERY + REPLICATION)
    return df.filter(pl.col(day_col).is_in(list(days)))


def verdict(
    disc: float, disc_lo: float, disc_hi: float, rep: float, rep_lo: float, rep_hi: float
) -> str:
    """The plan's verdict for one estimate from its discovery and replication intervals."""
    vals = (disc, disc_lo, disc_hi, rep, rep_lo, rep_hi)
    if any(v is None or v != v for v in vals):
        return "not estimable"
    if disc_lo <= 0 <= disc_hi:
        return "no lead"
    if (rep > 0) != (disc > 0):
        return "does not replicate"
    if rep_lo <= 0 <= rep_hi:
        return "same direction"
    return "replicates"
