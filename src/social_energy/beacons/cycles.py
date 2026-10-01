"""Power cycles and restarts, read off the readouts' clock anchors.

Each readout logs ``Current Timer``: the tag's uptime in seconds at the moment the PC stamped the
line. Readout time minus uptime is the moment the tag booted. Within one power cycle that implied
start is constant, except that the PC stamps late (after long transfers, by minutes), so it only
ever rises above the cycle's true start. The cycle's earliest implied start is therefore the best
estimate of when it began.

A restart shows as uptime falling behind the wall time elapsed since the tag's previous anchor by
more than a margin. Everything the tag held in RAM since that previous readout is gone, so the
lost window runs from the previous readout to the restart. Part of it may survive in flash, which
makes the window an upper bound (see docs/context/instruments/beacons.md).
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

import polars as pl

ANCHOR = ",Current Timer: "


def read_clock_anchors(paths: Iterable[Path], timezone: str) -> pl.DataFrame:
    """Every ``Current Timer`` line: ``beacon``, ``ts`` (UTC), ``timer`` (s), deduplicated.

    Lines whose tag ID is not a number are skipped; the ingest's QA accounts for them.
    """
    rows = []
    for path in paths:
        with Path(path).open(encoding="utf-8", errors="replace") as f:
            for line in f:
                if ANCHOR not in line:
                    continue
                ts, tag, rest = line.strip().split(",", 2)
                try:
                    rows.append((ts, int(tag.split(":")[1]), int(rest.split(":")[1])))
                except (IndexError, ValueError):
                    continue
    return (
        pl.DataFrame(
            rows,
            schema={"ts": pl.String, "beacon": pl.Int64, "timer": pl.Int64},
            orient="row",
        )
        .with_columns(
            pl.col("ts")
            .str.strptime(pl.Datetime("us"), "%Y-%m-%d %H:%M:%S")
            .dt.replace_time_zone(timezone, ambiguous="earliest")
            .dt.convert_time_zone("UTC")
        )
        .unique()
        .select("beacon", "ts", "timer")
        .sort("beacon", "ts", "timer")
    )


def power_cycles(anchors: pl.DataFrame, *, restart_margin_s: int) -> pl.DataFrame:
    """Add each anchor's power cycle to a table of ``beacon``, ``ts``, ``timer``.

    New columns: ``implied`` (ts - timer), ``restart`` (this anchor follows a restart),
    ``cycle`` (1, 2, … per beacon), ``cycle_start`` (the cycle's earliest implied start) and
    ``delay_s`` (how late this anchor was stamped against that start).
    """
    prev = lambda c: pl.col(c).shift().over("beacon")  # noqa: E731
    elapsed = (pl.col("ts") - prev("ts")).dt.total_seconds()
    restart = pl.col("timer") < prev("timer") + elapsed - restart_margin_s
    return (
        anchors.sort("beacon", "ts", "timer")
        .with_columns(
            (pl.col("ts") - pl.duration(seconds=pl.col("timer"))).alias("implied"),
            restart.fill_null(False).alias("restart"),
            prev("ts").alias("prev_ts"),
        )
        .with_columns(
            (pl.col("restart") | pl.col("prev_ts").is_null())
            .cum_sum()
            .over("beacon")
            .cast(pl.Int64)
            .alias("cycle")
        )
        .with_columns(pl.col("implied").min().over("beacon", "cycle").alias("cycle_start"))
        .with_columns(
            (pl.col("implied") - pl.col("cycle_start"))
            .dt.total_seconds()
            .cast(pl.Int64)
            .alias("delay_s")
        )
        .drop("prev_ts")
    )


def lost_windows(cycles: pl.DataFrame) -> pl.DataFrame:
    """Per restart, the span whose unread records were wiped: ``beacon``, ``start``, ``end``.

    ``start`` is the previous readout; ``end`` is the restart, estimated by the restart anchor's
    implied start. A restart implied before the previous readout (a late stamp) loses nothing
    measurable and is left out.
    """
    return (
        cycles.sort("beacon", "ts", "timer")
        .with_columns(pl.col("ts").shift().over("beacon").alias("start"))
        .filter(pl.col("restart"))
        .select("beacon", "start", pl.col("implied").alias("end"))
        .filter(pl.col("end") > pl.col("start"))
    )
