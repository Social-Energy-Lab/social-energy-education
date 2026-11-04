"""Checks on the DSA 2026 beacon dating, and what each tag-hour holds.

Not a research analysis. It writes how far each period sits from its partners, under the fitted
boots and under an earlier ingest for comparison, and the coverage of each tag-hour. Unit: tag and
period, tag and hour. No people: the spine is read only to tell location tags from worn ones, and
all figures are per tag-type aggregate.

Inputs: ``derived/beacons/`` and, if present, the ingest of 2026-11-04 from before the fit
(``derived/beacons-pre-sync-2026-11-04/``). Outputs: ``derived/analyses/beacon_time_sync/``.

    uv run --extra analysis python studies/dsa-2026/analyses/beacon_time_sync.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import polars as pl

sys.path.insert(0, str(Path(__file__).parent))
import copresence_by_phase as cp

from social_energy import paths
from social_energy.beacons.coverage import coverage_by_hour
from social_energy.beacons.sync import period_day_lags
from social_energy.spine import Spine
from social_energy.study import StudyConfig

SLUG = "beacon_time_sync"
RECORDED = ("recorded", "recorded_eco")


PRE_SYNC = "beacons-pre-sync-2026-11-04"


def old_periods(readouts: pl.DataFrame) -> pl.DataFrame:
    """The main ingest's power cycles in the shape ``period_day_lags`` reads."""
    return readouts.filter(
        pl.col("current_timer").is_not_null()
        & pl.col("beacon").is_not_null()
        & pl.col("cycle").is_not_null()
    ).select(
        "readout_key",
        "beacon",
        pl.col("cycle").alias("period"),
        pl.col("cycle_start").alias("boot"),
    )


def lag_shares(lags: pl.DataFrame) -> dict[str, float]:
    """Share of settled contact bins by how far their period-day sits from its partners."""
    settled = lags.filter("settled")
    total = settled["bins"].sum()
    a = pl.col("lag_s").abs()
    bands = {
        "within_1_min": a <= 60,
        "1_to_5_min": (a > 60) & (a <= 300),
        "5_to_30_min": (a > 300) & (a <= 1800),
        "over_30_min": a > 1800,
    }
    return {
        "settled_share_of_bins": round(total / lags["bins"].sum(), 4),
        **{k: round(settled.filter(c)["bins"].sum() / total, 4) for k, c in bands.items()},
    }


def state_shares(cov: pl.DataFrame, by: str) -> pl.DataFrame:
    """Share of hours per state and ``by``, for tags that recorded or that a partner placed."""
    seen = cov.filter(pl.col("heard") | pl.col("state").is_in(RECORDED))
    return (
        seen.group_by(by, "state")
        .len()
        .with_columns((pl.col("len") / pl.col("len").sum().over(by)).round(4).alias("share"))
        .sort(by, "state")
    )


def neither_side(cov: pl.DataFrame) -> pl.DataFrame:
    """Per day: of the pairs of tags both present in an hour, how many have no record from either.

    A pair of tags here need not have met, so this is the share of possible pair-hours that cannot
    be seen at all, not a count of lost encounters. ``expected`` is that share if gaps fell
    independently of each other: the day's share of tags without records, squared.
    """
    seen = cov.filter(pl.col("heard") | pl.col("state").is_in(RECORDED)).with_columns(
        (~pl.col("state").is_in(RECORDED)).alias("missing"), pl.col("hour").dt.date().alias("day")
    )
    hourly = seen.group_by("day", "hour").agg(
        pl.len().alias("n"), pl.col("missing").sum().alias("m")
    )
    return (
        hourly.with_columns(
            (pl.col("n") * (pl.col("n") - 1) / 2).alias("pairs"),
            (pl.col("m") * (pl.col("m") - 1) / 2).alias("neither"),
        )
        .group_by("day")
        .agg(
            (pl.col("neither").sum() / pl.col("pairs").sum()).round(4).alias("neither"),
            ((pl.col("m").sum() / pl.col("n").sum()) ** 2).round(4).alias("expected"),
        )
        .sort("day")
    )


def check() -> None:
    study = StudyConfig.load(cp.STUDY_YAML)
    config = study.beacon_config()
    span = study.beacon_window()
    new_dir = cp.derived_root() / "beacons"
    old_dir = cp.derived_root() / PRE_SYNC
    out = cp.derived_root() / "analyses" / SLUG
    out.mkdir(parents=True, exist_ok=True)

    new_readouts = pl.read_parquet(new_dir / "readouts.parquet")
    periods = pl.read_parquet(new_dir / "uptime_periods.parquet")
    lags = {
        "new": period_day_lags(
            new_readouts,
            pl.scan_parquet(new_dir / "contacts" / "*.parquet"),
            periods,
            window=span,
            clock_rate_ppm=config.clock_rate_ppm,
        )
    }
    if old_dir.exists():
        old_readouts = pl.read_parquet(old_dir / "readouts.parquet")
        lags["old"] = period_day_lags(
            old_readouts,
            pl.scan_parquet(old_dir / "contacts" / "*.parquet"),
            old_periods(old_readouts),
            window=span,
            clock_rate_ppm=config.clock_rate_ppm,
        )
    for name, table in lags.items():
        table.write_parquet(out / f"lags_{name}.parquet")
    summary = {name: lag_shares(table) for name, table in lags.items()}
    heads = periods.filter(pl.col("evidence").is_not_null() & (pl.col("boot").is_between(*span)))
    summary["boundaries_in_window"] = dict(heads.group_by("evidence").len().iter_rows())

    locations = {
        int(a.device.split(":")[1])
        for a in Spine.load(paths.study(cp.STUDY).spine).assignments
        if a.device.startswith("beacon:") and a.entity.startswith("location:")
    }
    tags = sorted(periods["beacon"].unique().to_list())
    cov = coverage_by_hour(
        pl.scan_parquet(new_dir / "contacts" / "*.parquet"),
        periods,
        pl.read_parquet(new_dir / "eco_sessions.parquet"),
        window=span,
        beacons=tags,
    ).with_columns(
        pl.when(pl.col("beacon").is_in(sorted(locations)))
        .then(pl.lit("location"))
        .otherwise(pl.lit("person"))
        .alias("kind"),
        pl.col("hour").dt.date().alias("day"),
    )
    cov.write_parquet(out / "coverage.parquet")
    state_shares(cov, "kind").write_csv(out / "states_by_kind.csv")
    person = cov.filter(pl.col("kind") == "person")
    state_shares(person, "day").write_csv(out / "person_states_by_day.csv")
    neither_side(person).write_csv(out / "person_neither_by_day.csv")
    (out / "summary.json").write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")
    print(json.dumps(summary, indent=2, default=str), flush=True)


if __name__ == "__main__":
    check()
