"""What each tag-hour holds: the tag's own records, or why it has none.

No own records is not no contact. A partner may still have heard the tag (``heard``), and the state
says why the tag's side is missing:

* ``recorded`` / ``recorded_eco``: own records, the latter in an hour touching an eco session;
* ``not_logged``: inside an uptime period, between records that did arrive. The readout that held
  this hour vanished in a logger pause or outage, or the tag heard nobody (then ``heard`` is false);
* ``erased_by_reboot``: after the period's last delivered record, with a later period to follow;
* ``not_read_out``: after the last delivered record of the tag's last period;
* ``before_first_boot``: before the tag's first boot.
"""

from __future__ import annotations

from bisect import bisect_left
from collections.abc import Iterable
from datetime import datetime, timedelta

import polars as pl

HOUR = timedelta(hours=1)


def coverage_by_hour(
    contacts: pl.DataFrame | pl.LazyFrame,
    periods: pl.DataFrame,
    eco_sessions: pl.DataFrame,
    *,
    window: tuple[datetime, datetime],
    beacons: Iterable[int],
) -> pl.DataFrame:
    """One row per tag and hour of ``window``: ``beacon``, ``hour``, ``state``, ``heard``.

    ``contacts`` and ``eco_sessions`` count only where ``ok``. ``periods`` has ``beacon``,
    ``period`` and ``boot``, one or more rows per period. Own records are placed in a period by
    their hour: the last boot before that hour ends.
    """
    start, end = window
    first_hour = start.replace(minute=0, second=0, microsecond=0)
    hours = []
    while first_hour < end:
        hours.append(first_hour)
        first_hour += HOUR
    ok = (
        contacts.lazy()
        .filter(pl.col("ok"))
        .select("beacon", "observed", pl.col("t").dt.truncate("1h").alias("hour"))
    )
    own = ok.select("beacon", "hour").unique().collect()
    heard = ok.select(pl.col("observed").alias("beacon"), "hour").unique().collect()
    own_hours = {
        k[0]: set(g["hour"].to_list()) for k, g in own.group_by(["beacon"]) if k[0] is not None
    }
    heard_hours = {k[0]: set(g["hour"].to_list()) for k, g in heard.group_by(["beacon"])}
    boots = {
        k[0]: sorted(g["boot"].to_list())
        for k, g in periods.group_by("beacon", "period")
        .agg(pl.col("boot").first())
        .group_by(["beacon"])
    }
    eco_hours: dict[int, set[datetime]] = {}
    for row in eco_sessions.filter(pl.col("ok")).iter_rows(named=True):
        if row["t_enter"] is None or row["t_leave"] is None:
            continue
        h = row["t_enter"].replace(minute=0, second=0, microsecond=0)
        while h <= row["t_leave"]:
            eco_hours.setdefault(row["beacon"], set()).add(h)
            h += HOUR
    rows = []
    for beacon in beacons:
        tag_own = own_hours.get(beacon, set())
        tag_boots = boots.get(beacon, [])
        last_own: dict[int, datetime] = {}
        for h in tag_own:
            i = bisect_left(tag_boots, h + HOUR) - 1
            if i >= 0 and (i not in last_own or h > last_own[i]):
                last_own[i] = h
        for h in hours:
            i = bisect_left(tag_boots, h + HOUR) - 1
            if h in tag_own:
                state = "recorded_eco" if h in eco_hours.get(beacon, ()) else "recorded"
            elif i < 0:
                state = "before_first_boot"
            elif i in last_own and h <= last_own[i]:
                state = "not_logged"
            elif i + 1 < len(tag_boots):
                state = "erased_by_reboot"
            else:
                state = "not_read_out"
            rows.append((beacon, h, state, h in heard_hours.get(beacon, ())))
    return pl.DataFrame(
        rows,
        schema={
            "beacon": pl.Int64,
            "hour": pl.Datetime("us", "UTC"),
            "state": pl.String,
            "heard": pl.Boolean,
        },
        orient="row",
    )
