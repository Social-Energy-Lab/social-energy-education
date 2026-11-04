"""Uptime periods from the implied boots, then boots checked against partners' records.

A readout's stamp minus its uptime implies when the tag booted. Stamps can only be late, by hours
when the logger paused, so a period's boot is the lower edge of its implied boots. Reading that edge
from later readouts backwards gives the periods: a late stamp rises above the edge and comes back; a
reboot or a timer step lifts the edge for good, by any amount. No margin separates the two, so
neither a very late stamp nor a small lasting step is misread.

The edge fails where every readout of a period was late. Then the tag's partners can date it: A
hearing B and B hearing A are one encounter, so A's on/off pattern with each partner, slid against
the partner's own, overlaps best at the error in A's boot. Matching each record to its nearest
mirror cannot do this: in a long stay both sides have a record at nearly every moment, so the
nearest one is close whatever the error. A period's partners are split in two, and the estimate
counts only if the halves agree. A boot never moves later than its edge.
"""

from __future__ import annotations

import dataclasses
import shutil
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import polars as pl

from .cycles import real_seconds
from .ingest import BeaconConfig, ingest_logs_to
from .witness import ingest_with_witnesses

PERIOD_COLUMNS = ["readout_key", "beacon", "ts", "timer", "period", "boot", "boot_edge", "evidence"]


def uptime_periods(
    anchors: pl.DataFrame,
    *,
    step_s: int = 120,
    fresh_margin_s: int = 300,
    continuity_s: int = 1800,
    back_tolerance_s: int = 90,
    clock_rate_ppm: float = 0.0,
) -> pl.DataFrame:
    """Split each tag's clock anchors into uptime periods.

    ``anchors`` has ``readout_key``, ``beacon``, ``ts``, ``timer`` and ``oldest``, the uptime of the
    readout's oldest contact (null without contacts). Adds ``period`` (1, 2, … per beacon), ``boot``
    and ``boot_edge`` (both the period's lowest implied boot here) and ``evidence``, set on a
    period's first row:

    * ``first``: the tag's first anchor;
    * ``timer_back``: uptime fell, which proves a reboot. A fall under ``back_tolerance_s`` with the
      implied boot also within it is two readouts logged out of order;
    * ``fresh_records``: the edge rose and the oldest contact lies before the previous timer by more
      than ``fresh_margin_s``, so the tag's memory restarted;
    * ``continues``: the edge rose but the oldest contact carries on from the previous timer, within
      ``continuity_s``. Nothing was wiped: late stamps or a timer step (``apply_boots``);
    * ``gap``: the edge rose and the oldest contact starts further on. A readout vanished, and the
      tag may have rebooted before it did;
    * ``step``: the edge rose and the readout has no contacts to tell by.
    """
    implied = pl.col("ts") - real_seconds(pl.col("timer"), clock_rate_ppm)
    frames = []
    for g in (
        anchors.sort("beacon", "ts", "timer")
        .with_columns(implied.alias("_implied"))
        .partition_by("beacon", maintain_order=True)
    ):
        seconds = g["_implied"].dt.epoch("ms").to_numpy() / 1000
        timer = g["timer"].to_numpy()
        oldest = g["oldest"].to_list()
        edge = np.minimum.accumulate(seconds[::-1])[::-1]
        evidence: list[str | None] = ["first"]
        for k in range(1, len(g)):
            fell = timer[k] < timer[k - 1]
            if fell and (
                timer[k - 1] - timer[k] > back_tolerance_s
                or seconds[k] - seconds[k - 1] > back_tolerance_s
            ):
                evidence.append("timer_back")
            elif edge[k] > edge[k - 1] + step_s:
                if oldest[k] is None:
                    evidence.append("step")
                elif oldest[k] < timer[k - 1] - fresh_margin_s:
                    evidence.append("fresh_records")
                elif oldest[k] <= timer[k - 1] + continuity_s:
                    evidence.append("continues")
                else:
                    evidence.append("gap")
            else:
                evidence.append(None)
        frames.append(
            g.with_columns(pl.Series("evidence", evidence, dtype=pl.String)).with_columns(
                pl.col("evidence").is_not_null().cum_sum().cast(pl.Int64).alias("period")
            )
        )
    return (
        pl.concat(frames)
        .with_columns(pl.col("_implied").min().over("beacon", "period").alias("boot"))
        .with_columns(pl.col("boot").alias("boot_edge"))
        .drop("_implied")
    )


def _overlap(own: dict, partners: dict, keys: list, max_lag: int) -> np.ndarray:
    total = np.zeros(2 * max_lag + 1)
    lags = np.arange(-max_lag, max_lag + 1)
    for k in keys:
        x, y = own[k], partners[k]
        low = int(x.min()) - max_lag
        size = int(x.max()) + max_lag - low + 1
        y = y[(y >= low) & (y < low + size)]
        if not len(y):
            continue
        a, b = np.zeros(size), np.zeros(size)
        a[x - low] = 1
        b[y - low] = 1
        n = 2 * size
        r = np.fft.irfft(np.fft.rfft(a, n) * np.conj(np.fft.rfft(b, n)), n)
        total += r[lags % n]
    return total


def mirror_lag(own: dict, partners: dict, *, max_lag: int, seed: int = 0) -> dict:
    """How many bins ``own`` lies after ``partners``, from each partner's on/off pattern.

    Both map a partner to the sorted, distinct bins of its contact with this tag: ``own`` as this
    tag dated them, ``partners`` as that partner dated them. Returns ``lag`` over all partners,
    ``lag_a`` and ``lag_b`` over two random halves, and ``partners``, how many were shared.
    """
    keys = sorted(k for k in own if len(own[k]) and k in partners and len(partners[k]))
    if not keys:
        return {"lag": None, "lag_a": None, "lag_b": None, "partners": 0}
    shuffled = list(np.random.default_rng(seed).permutation(keys))
    half = len(shuffled) // 2
    a = _overlap(own, partners, shuffled[:half], max_lag)
    b = _overlap(own, partners, shuffled[half:], max_lag)
    peak = lambda v: int(v.argmax()) - max_lag  # noqa: E731
    return {"lag": peak(a + b), "lag_a": peak(a), "lag_b": peak(b), "partners": len(keys)}


def apply_boots(
    periods: pl.DataFrame,
    lags: pl.DataFrame,
    *,
    merge_s: int = 300,
    max_delay_s: int = 21_600,
) -> pl.DataFrame:
    """Move periods' boots by their settled lags, and settle the steps that lifted the edge.

    ``lags`` has ``beacon``, ``period``, ``lag_s`` and ``settled``. A boot may not pass its edge: a
    stamp is never early, so a lag pushing a boot later is the partner's error.

    A period whose boot now lands within ``merge_s`` of the one before it joins that one, unless
    there is proof of a reboot. A ``continues`` period also joins when partners cannot tell and its
    rise is within ``max_delay_s``, what a logger pause can do: nothing shows the tag restarted. One
    that partners settled elsewhere, or that rose further, moved its clock: ``timer_step``.
    """
    moved = periods.join(lags, on=["beacon", "period"], how="left").with_columns(
        pl.when(pl.col("settled").fill_null(False))
        .then(pl.col("boot") - pl.duration(milliseconds=(pl.col("lag_s") * 1000).round()))
        .otherwise(pl.col("boot"))
        .alias("_boot"),
        pl.col("settled").fill_null(False).alias("_settled"),
    )
    moved = moved.with_columns(pl.min_horizontal("_boot", "boot_edge").alias("boot")).drop(
        "_boot", "lag_s", "settled"
    )
    out = []
    for g in moved.sort("beacon", "ts", "timer").partition_by("beacon", maintain_order=True):
        heads = g.filter(pl.col("evidence").is_not_null())
        number: dict[int, int] = {}
        kept: dict[str, str] = {}
        current, boot = 0, None
        for row in heads.iter_rows(named=True):
            kind = row["evidence"]
            joins = False
            if boot is not None and kind in ("continues", "gap", "step", "timer_step"):
                rise = (row["boot"] - boot).total_seconds()
                joins = abs(rise) <= merge_s or (
                    kind == "continues" and not row["_settled"] and rise <= max_delay_s
                )
            if not joins:
                current += 1
                boot = row["boot"]
                kept[row["readout_key"]] = "timer_step" if kind == "continues" else kind
            number[row["period"]] = current
        out.append(
            g.with_columns(
                pl.col("period").replace_strict(number, return_dtype=pl.Int64),
                pl.col("readout_key")
                .replace_strict(kept, default=None, return_dtype=pl.String)
                .alias("evidence"),
            ).with_columns(
                pl.col("boot").min().over("period"),
                pl.col("boot_edge").min().over("period"),
            )
        )
    return pl.concat(out).drop("_settled")


@dataclass(frozen=True)
class SyncRound:
    """One pass over the partners: bin width and how far to search, in seconds."""

    bin_s: int
    max_lag_s: int
    agree_s: int


DEFAULT_ROUNDS = (
    SyncRound(bin_s=30, max_lag_s=21_600, agree_s=120),
    SyncRound(bin_s=30, max_lag_s=21_600, agree_s=120),
    SyncRound(bin_s=30, max_lag_s=21_600, agree_s=120),
)


def change_point(early: np.ndarray, late: np.ndarray) -> tuple[int, int]:
    """Where to switch from clock ``early`` to clock ``late``: the split with most matches.

    Both are 0/1 per record in uptime order: does a partner's record agree under that clock? Returns
    the first index on the late clock (0: all late, ``len``: all early) and that split's matches.
    """
    before = np.concatenate(([0], np.cumsum(early)))
    after = np.concatenate((np.cumsum(late[::-1])[::-1], [0]))
    totals = before + after
    best = int(totals.argmax())
    return best, int(totals[best])


def _period_of_readouts(readouts: pl.DataFrame, periods: pl.DataFrame) -> pl.DataFrame:
    """``readout_key``, ``period``, ``boot`` for every readout, also those with no anchor."""
    placed = readouts.join(periods.select("readout_key", "period", "boot"), on="readout_key")
    starts = periods.group_by("beacon", "period").agg(pl.col("boot").first()).sort("boot")
    rest = (
        readouts.join(periods.select("readout_key"), on="readout_key", how="anti")
        .filter(pl.col("beacon").is_not_null())
        .sort("pc_time")
        .join_asof(
            starts,
            left_on="pc_time",
            right_on="boot",
            by="beacon",
            strategy="backward",
            check_sortedness=False,
        )
    )
    columns = ["readout_key", "beacon", "period", "boot"]
    return pl.concat([placed.select(columns), rest.select(columns)])


def find_timer_steps(
    records: pl.DataFrame,
    periods: pl.DataFrame,
    readouts: pl.DataFrame,
    *,
    window: tuple,
    clock_rate_ppm: float = 0.0,
    bin_s: int = 30,
    step_s: int = 300,
    min_gain: int = 50,
    min_gain_share: float = 0.1,
) -> pl.DataFrame:
    """Clocks that moved between two readouts, so that one readout holds both sides of the step.

    One boot per period cannot date such records. Wherever a tag's implied boot lastingly rises by
    more than ``step_s`` between two readouts, the records of that stretch are tried against the
    boots on both sides, in uptime order, and partners' records pick the split (``change_point``).
    Late stamps look the same in the anchors, but their records match one boot throughout, so no
    split gains anything. A split must gain ``min_gain`` matches and ``min_gain_share`` of the
    stretch. Returns ``beacon``, ``period``, ``from_uptime``, ``to_uptime``, ``add_s``: add this to
    the time of that period's records in that uptime range.
    """
    schema = {
        "beacon": pl.Int64,
        "period": pl.Int64,
        "from_uptime": pl.Int64,
        "to_uptime": pl.Int64,
        "add_s": pl.Float64,
    }
    start, end = window
    placed = _period_of_readouts(readouts, periods)
    dated = (
        records.join(placed.select("readout_key", "period", "boot"), on="readout_key")
        .with_columns(
            (
                pl.col("boot") + real_seconds(pl.col("uptime_s").cast(pl.Int64), clock_rate_ppm)
            ).alias("t")
        )
        .filter(pl.col("t").is_between(start, end))
    )
    hearing = {
        key: np.unique(g["bin"].to_numpy())
        for key, g in dated.with_columns((pl.col("t").dt.epoch("s") // bin_s).alias("bin"))
        .select("beacon", "observed", "bin")
        .unique()
        .group_by(["beacon", "observed"])
    }
    rows = []
    implied = pl.col("ts") - real_seconds(pl.col("timer"), clock_rate_ppm)
    for g in (
        periods.sort("beacon", "ts", "timer")
        .with_columns(implied.alias("_implied"))
        .partition_by("beacon", maintain_order=True)
    ):
        beacon = int(g["beacon"][0])
        seconds = g["_implied"].dt.epoch("ms").to_numpy() / 1000
        edge = np.minimum.accumulate(seconds[::-1])[::-1]
        timer = g["timer"].to_numpy()
        period = g["period"].to_numpy()
        boots = g["boot"].dt.epoch("ms").to_numpy() / 1000
        own = dated.filter(pl.col("beacon") == beacon)
        for k in range(1, len(g)):
            rise = edge[k] - edge[k - 1]
            if rise <= step_s or timer[k] < timer[k - 1]:
                continue
            same = period[k] == period[k - 1]
            # The clock before the step: the previous readout's boot. After it: this edge, or this
            # period's fitted boot when the rise opened a period of its own.
            early_boot = boots[k - 1]
            late_boot = boots[k] if not same else edge[k]
            if late_boot - early_boot <= step_s:
                continue
            stretch = (
                own.filter(
                    (pl.col("period") == int(period[k]))
                    & (pl.col("uptime_s") >= int(timer[k - 1]))
                    & (pl.col("uptime_s") <= int(timer[k]))
                )
                .select("observed", "uptime_s")
                .unique()
                .sort("uptime_s")
            )
            if not stretch.height:
                continue
            uptime = stretch["uptime_s"].to_numpy().astype(float) / (1 + clock_rate_ppm * 1e-6)
            observed = stretch["observed"].to_numpy()
            matches = {}
            for name, boot in (("early", early_boot), ("late", late_boot)):
                b = ((boot + uptime) // bin_s).astype(np.int64)
                hit = np.zeros(len(b), dtype=np.int64)
                for o in np.unique(observed):
                    theirs = hearing.get((int(o), beacon))
                    if theirs is None:
                        continue
                    mask = observed == o
                    hit[mask] = np.isin(b[mask], theirs)
                matches[name] = hit
            split, best = change_point(matches["early"], matches["late"])
            current = int((matches["late"] if not same else matches["early"]).sum())
            gain = best - current
            if gain < max(min_gain, min_gain_share * len(uptime)):
                continue
            ups = stretch["uptime_s"].to_numpy()
            if same:  # dated from the early boot: the part after the split moves later
                if split >= len(ups):
                    continue
                low, high, add = int(ups[split]), int(timer[k]), late_boot - early_boot
            else:  # dated from the late boot: the part before the split moves earlier
                if split <= 0:
                    continue
                low, high, add = int(ups[0]), int(ups[split - 1]), early_boot - late_boot
            rows.append((beacon, int(period[k]), low, high, float(add)))
    return pl.DataFrame(rows, schema=schema, orient="row")


def fit_boots(
    readouts: pl.DataFrame,
    contacts: pl.LazyFrame,
    *,
    window: tuple,
    clock_rate_ppm: float = 0.0,
    rounds: tuple[SyncRound, ...] = DEFAULT_ROUNDS,
    min_partners: int = 4,
    merge_s: int = 300,
    seed: int = 0,
    log=None,
) -> tuple[pl.DataFrame, pl.DataFrame, pl.DataFrame]:
    """Periods with boots fitted to partners, every round's lag per period, and timer steps.

    ``readouts`` and ``contacts`` are an ingest's tables (ok contacts of the current boot are used);
    ``window`` is the (start, end) in UTC over which patterns are compared, so that tags lying
    together in a box before handout do not count. Only uptime is read from the contacts, so the
    first ingest's dating does not enter.
    """
    records = (
        contacts.filter(pl.col("ok") & ~pl.col("pre_reboot"))
        .select(
            pl.col("beacon").cast(pl.Int16),
            pl.col("observed").cast(pl.Int16),
            pl.col("uptime_s").cast(pl.Int32),
            "readout_key",
        )
        .collect(engine="streaming")
    )
    oldest = records.group_by("readout_key").agg(pl.col("uptime_s").min().alias("oldest"))
    anchors = (
        readouts.filter(
            pl.col("current_timer").is_not_null()
            & pl.col("beacon").is_not_null()
            & (pl.col("id_status") != "ambiguous")
        )
        .select(
            "readout_key",
            "beacon",
            pl.col("pc_time").alias("ts"),
            pl.col("current_timer").alias("timer"),
        )
        .join(oldest.with_columns(pl.col("oldest").cast(pl.Int64)), on="readout_key", how="left")
    )
    periods = uptime_periods(anchors, clock_rate_ppm=clock_rate_ppm)
    start, end = window
    history = []
    for number, r in enumerate(rounds, start=1):
        placed = _period_of_readouts(readouts, periods)
        dated = (
            records.join(placed.select("readout_key", "period", "boot"), on="readout_key")
            .with_columns(
                pl.col("boot") + real_seconds(pl.col("uptime_s").cast(pl.Int64), clock_rate_ppm)
            )
            .rename({"boot": "t"})
            .filter(pl.col("t").is_between(start, end))
            .with_columns((pl.col("t").dt.epoch("s") // r.bin_s).cast(pl.Int32).alias("bin"))
            .select("beacon", "observed", "period", "bin")
            .unique()
        )
        hearing = {
            key: np.sort(g["bin"].to_numpy())
            for key, g in dated.select("beacon", "observed", "bin")
            .unique()
            .group_by(["beacon", "observed"])
        }
        rows = []
        for (beacon, period), g in dated.group_by(["beacon", "period"]):
            own = {k[0]: h["bin"].to_numpy() for k, h in g.group_by(["observed"])}
            own = {k: np.sort(v) for k, v in own.items()}
            theirs = {k: hearing[(k, beacon)] for k in own if (k, beacon) in hearing}
            m = mirror_lag(own, theirs, max_lag=r.max_lag_s // r.bin_s, seed=seed + number)
            if m["lag"] is None:
                continue
            rows.append(
                {
                    "round": number,
                    "beacon": int(beacon),
                    "period": int(period),
                    "lag_s": float(m["lag"] * r.bin_s),
                    "partners": m["partners"],
                    "bins": g.height,
                    "settled": m["partners"] >= min_partners
                    and abs(m["lag_a"] - m["lag_b"]) * r.bin_s <= r.agree_s,
                }
            )
        lags = pl.DataFrame(
            rows,
            schema={
                "round": pl.Int64,
                "beacon": pl.Int64,
                "period": pl.Int64,
                "lag_s": pl.Float64,
                "partners": pl.Int64,
                "bins": pl.Int64,
                "settled": pl.Boolean,
            },
        )
        history.append(lags)
        periods = apply_boots(
            periods, lags.select("beacon", "period", "lag_s", "settled"), merge_s=merge_s
        )
        if log:
            log(number, lags, periods)
    steps = find_timer_steps(
        records, periods, readouts, window=window, clock_rate_ppm=clock_rate_ppm
    )
    return periods, pl.concat(history), steps


def ingest_with_sync(
    paths: Iterable[Path],
    config: BeaconConfig,
    out: Path,
    *,
    window: tuple,
    rounds: tuple[SyncRound, ...] = DEFAULT_ROUNDS,
) -> dict[str, int]:
    """``ingest_with_witnesses``, then boots fitted to partners, then the records dated from them.

    Also writes ``uptime_periods.parquet`` (one row per clock anchor), ``boot_fit.parquet`` (every
    round's lag per period) and ``timer_steps.parquet``. ``window`` is the (start, end) in UTC to
    compare patterns over.
    """
    paths, out = list(paths), Path(out)
    ingest_with_witnesses(paths, config, out)
    periods, history, steps = fit_boots(
        pl.read_parquet(out / "readouts.parquet"),
        pl.scan_parquet(out / "contacts" / "*.parquet"),
        window=window,
        clock_rate_ppm=config.clock_rate_ppm,
        rounds=rounds,
    )
    periods.select(PERIOD_COLUMNS).write_parquet(out / "uptime_periods.parquet")
    history.write_parquet(out / "boot_fit.parquet")
    steps.write_parquet(out / "timer_steps.parquet")
    overrides = config.id_overrides
    witness = out / "id_witness.parquet"
    if witness.exists():
        settled = pl.read_parquet(witness).drop_nulls("beacon")
        overrides = tuple(zip(settled["readout_key"], settled["beacon"], strict=True))
    restart = pl.col("evidence").is_not_null() & (pl.col("evidence") != "first")
    rows = periods.with_columns(restart.alias("restart")).select(
        "readout_key", "period", "boot", "restart"
    )
    shutil.rmtree(out / "contacts")
    return ingest_logs_to(
        paths,
        dataclasses.replace(
            config,
            id_overrides=overrides,
            period_overrides=tuple(rows.rows()),
            clock_steps=tuple(steps.rows()),
        ),
        out,
    )


def period_day_lags(
    readouts: pl.DataFrame,
    contacts: pl.LazyFrame,
    periods: pl.DataFrame,
    *,
    window: tuple,
    clock_rate_ppm: float = 0.0,
    bin_s: int = 30,
    max_lag_s: int = 7200,
    min_bins: int = 200,
    agree_s: int = 120,
    seed: int = 99,
) -> pl.DataFrame:
    """Each period's remaining lag per UTC day, with these ``periods``' boots applied.

    A check, not a fit: a lag that differs inside a period shows what one boot cannot express, such
    as a timer step. ``periods`` has ``readout_key``, ``beacon``, ``period`` and ``boot``. Returns
    ``beacon``, ``period``, ``day``, ``bins``, ``partners``, ``lag_s`` and ``settled``.
    """
    records = (
        contacts.filter(pl.col("ok") & ~pl.col("pre_reboot"))
        .select(
            pl.col("beacon").cast(pl.Int16),
            pl.col("observed").cast(pl.Int16),
            pl.col("uptime_s").cast(pl.Int32),
            "readout_key",
        )
        .collect(engine="streaming")
    )
    placed = _period_of_readouts(
        readouts, periods.select("readout_key", "beacon", "period", "boot")
    )
    start, end = window
    dated = (
        records.join(placed.select("readout_key", "period", "boot"), on="readout_key")
        .with_columns(
            (
                pl.col("boot") + real_seconds(pl.col("uptime_s").cast(pl.Int64), clock_rate_ppm)
            ).alias("t")
        )
        .filter(pl.col("t").is_between(start, end))
        .with_columns(
            (pl.col("t").dt.epoch("s") // bin_s).cast(pl.Int32).alias("bin"),
            pl.col("t").dt.date().alias("day"),
        )
        .select("beacon", "observed", "period", "day", "bin")
        .unique()
    )
    hearing = {
        key: np.sort(g["bin"].to_numpy())
        for key, g in dated.select("beacon", "observed", "bin")
        .unique()
        .group_by(["beacon", "observed"])
    }
    rows = []
    for (beacon, period, day), g in dated.group_by(["beacon", "period", "day"]):
        if g.height < min_bins:
            continue
        own = {k[0]: np.sort(h["bin"].to_numpy()) for k, h in g.group_by(["observed"])}
        theirs = {k: hearing[(k, beacon)] for k in own if (k, beacon) in hearing}
        m = mirror_lag(own, theirs, max_lag=max_lag_s // bin_s, seed=seed)
        if m["lag"] is None:
            continue
        rows.append(
            {
                "beacon": int(beacon),
                "period": int(period),
                "day": day,
                "bins": g.height,
                "partners": m["partners"],
                "lag_s": float(m["lag"] * bin_s),
                "settled": abs(m["lag_a"] - m["lag_b"]) * bin_s <= agree_s,
            }
        )
    return pl.DataFrame(
        rows,
        schema={
            "beacon": pl.Int64,
            "period": pl.Int64,
            "day": pl.Date,
            "bins": pl.Int64,
            "partners": pl.Int64,
            "lag_s": pl.Float64,
            "settled": pl.Boolean,
        },
    )
