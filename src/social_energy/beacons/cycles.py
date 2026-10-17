"""Power cycles and restarts, read off the readouts' clock anchors.

Each readout logs ``Current Timer``: the tag's uptime in seconds at the moment the PC stamped the
line. Readout time minus uptime is the moment the tag booted. Within one power cycle that implied
start is constant, except that the PC stamps late (after long transfers, by minutes), so it only
ever rises above the cycle's true start. The cycle's earliest implied start is therefore the best
estimate of when it began.

If the tags' counters run fast by ``clock_rate_ppm``, one uptime second is ``1 / (1 + rate)`` real
seconds, so the boot a readout implies is readout time minus ``timer / (1 + rate)``. Without that
the implied start sinks a little with every readout, and the earliest one is no longer the boot.

A restart shows as uptime falling behind the wall time elapsed since the tag's previous anchor by
more than a margin. Every contact the tag held since that previous readout is gone (a restart also
clears contact flash), so the lost window runs from the previous readout to the restart (see
docs/context/instruments/beacons.md).
"""

from __future__ import annotations

from collections.abc import Iterable
from itertools import pairwise
from pathlib import Path

import polars as pl

ANCHOR = ",Current Timer: "
RECORD_LINE = (
    r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}),ID: (\d+),(?:ID2: |Self-report time: |Eco Session )"
)


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


def real_seconds(timer: pl.Expr, clock_rate_ppm: float) -> pl.Expr:
    """Tag uptime seconds as real time, for a counter running ``clock_rate_ppm`` fast."""
    if not clock_rate_ppm:
        return pl.duration(seconds=timer)
    return pl.duration(milliseconds=(timer * (1000 / (1 + clock_rate_ppm * 1e-6))).round())


def power_cycles(
    anchors: pl.DataFrame, *, restart_margin_s: int, clock_rate_ppm: float = 0.0
) -> pl.DataFrame:
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
            (pl.col("ts") - real_seconds(pl.col("timer"), clock_rate_ppm)).alias("implied"),
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


def read_deliveries(paths: Iterable[Path], timezone: str) -> pl.DataFrame:
    """When each tag delivered records: ``beacon``, ``ts`` (UTC), one row per distinct PC second.

    Only lines that carry a record (contact, self-report, eco session) count. A readout can arrive
    without its header, and so without a clock anchor, yet still drain the tag; a connection that
    logged only a ``Status`` line delivered nothing.
    """
    frames = [
        pl.scan_csv(
            path,
            has_header=False,
            separator="\x1f",
            quote_char=None,
            schema={"line": pl.String},
            encoding="utf8-lossy",
        )
        for path in paths
    ]
    if not frames:
        return pl.DataFrame(schema={"beacon": pl.Int64, "ts": pl.Datetime("us", "UTC")})
    return (
        pl.concat(frames)
        .filter(pl.col("line").str.contains(RECORD_LINE))
        .select(
            pl.col("line").str.extract(RECORD_LINE, 2).cast(pl.Int64).alias("beacon"),
            pl.col("line").str.extract(RECORD_LINE, 1).alias("ts"),
        )
        .unique()
        .with_columns(
            pl.col("ts")
            .str.strptime(pl.Datetime("us"), "%Y-%m-%d %H:%M:%S")
            .dt.replace_time_zone(timezone, ambiguous="earliest")
            .dt.convert_time_zone("UTC")
        )
        .unique()
        .sort("beacon", "ts")
        .collect(engine="streaming")
    )


def lost_windows(cycles: pl.DataFrame, deliveries: pl.DataFrame | None = None) -> pl.DataFrame:
    """Per restart, the span whose unread records were wiped: ``beacon``, ``start``, ``end``.

    ``start`` is the last readout before the restart: the previous clock anchor, or a later
    delivery of records (``read_deliveries``) when a readout arrived without its anchor. ``end``
    is the restart, estimated by the restart anchor's implied start. A restart implied before the
    last readout (a late stamp) loses nothing measurable and is left out.
    """
    windows = (
        cycles.sort("beacon", "ts", "timer")
        .with_columns(pl.col("ts").shift().over("beacon").alias("start"))
        .filter(pl.col("restart"))
        .select("beacon", "start", pl.col("implied").alias("end"))
    )
    if deliveries is not None:
        latest = (
            windows.with_row_index("_w")
            .join(deliveries.select("beacon", pl.col("ts").alias("_d")), on="beacon")
            .filter((pl.col("_d") > pl.col("start")) & (pl.col("_d") < pl.col("end")))
            .group_by("_w")
            .agg(pl.col("_d").max())
        )
        windows = (
            windows.with_row_index("_w")
            .join(latest, on="_w", how="left")
            .with_columns(pl.coalesce("_d", "start").alias("start"))
            .drop("_w", "_d")
        )
    return windows.filter(pl.col("end") > pl.col("start"))


def _lower_hull(points: list[tuple[float, float]]) -> list[tuple[float, float]]:
    hull: list[tuple[float, float]] = []
    for p in points:
        while len(hull) >= 2:
            (x1, y1), (x2, y2) = hull[-2], hull[-1]
            if (x2 - x1) * (p[1] - y1) - (y2 - y1) * (p[0] - x1) > 0:
                break
            hull.pop()
        hull.append(p)
    return hull


def _min_delay_slope(timer: list[float], lag: list[float]) -> tuple[float, float] | None:
    """Slope and intercept of the line under every (timer, lag) that minimises the summed gap.

    Stamp delays only ever add, so the true clock relation is the lower edge of the points. The
    line under all points with the least total gap above it runs along the lower convex hull, on
    the edge that spans the mean timer (minimum-delay skew estimate; Moon et al., 1999).
    """
    hull = _lower_hull(sorted(set(zip(timer, lag, strict=True))))
    mean = sum(timer) / len(timer)
    for (x0, y0), (x1, y1) in pairwise(hull):
        if x0 <= mean <= x1 and x1 > x0:
            slope = (y1 - y0) / (x1 - x0)
            return slope, y0 - slope * x0
    return None


def estimate_clock_rate(
    readouts: pl.DataFrame,
    *,
    restart_margin_s: int,
    min_readouts: int = 6,
    min_span_s: int = 86_400,
    max_gap_s: float = 10.0,
) -> dict[str, object]:
    """Camp-wide timer drift from the readouts' clock anchors, in parts per million (fast > 0).

    ``readouts`` needs ``beacon``, ``pc_time`` and ``current_timer`` (an ingest's readout table).
    Per power cycle with at least ``min_readouts`` anchors over ``min_span_s`` of uptime, the
    implied start's lower edge (``_min_delay_slope``) sinks by ``rate`` seconds per uptime second.
    A cycle counts only if a quarter of its anchors lie within ``max_gap_s`` of that line; fewer
    clean anchors give a slope that measures stamp delays, not the clock. Returns the median rate
    over the clean cycles, how many there were, and the per-cycle table.
    """
    anchors = readouts.filter(
        pl.col("current_timer").is_not_null() & pl.col("beacon").is_not_null()
    ).select("beacon", pl.col("pc_time").alias("ts"), pl.col("current_timer").alias("timer"))
    cyc = power_cycles(anchors, restart_margin_s=restart_margin_s).with_columns(
        ((pl.col("ts") - pl.col("cycle_start")).dt.total_seconds() - pl.col("timer")).alias("lag")
    )
    rows = []
    for (beacon, cycle), g in cyc.group_by(["beacon", "cycle"]):
        timer = g["timer"].cast(pl.Float64).to_list()
        lag = g["lag"].cast(pl.Float64).to_list()
        if len(timer) < min_readouts or max(timer) - min(timer) < min_span_s:
            continue
        fit = _min_delay_slope(timer, lag)
        if fit is None:
            continue
        slope, intercept = fit
        gaps = sorted(y - (intercept + slope * x) for x, y in zip(timer, lag, strict=True))
        rows.append(
            {"beacon": beacon, "cycle": cycle, "readouts": len(timer), "ppm": -slope * 1e6,
             "gap_q25_s": gaps[len(gaps) // 4], "clean": gaps[len(gaps) // 4] <= max_gap_s}
        )  # fmt: skip
    table = pl.DataFrame(
        rows,
        schema={"beacon": pl.Int64, "cycle": pl.Int64, "readouts": pl.Int64, "ppm": pl.Float64,
                "gap_q25_s": pl.Float64, "clean": pl.Boolean},
    )  # fmt: skip
    clean = table.filter(pl.col("clean"))
    return {
        "ppm": clean["ppm"].median() if clean.height else None,
        "cycles_used": clean.height,
        "cycles": table,
    }
