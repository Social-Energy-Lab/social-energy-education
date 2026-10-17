"""Per-person outcome measures for the confirmatory tests C1-C4 (``research/analysis-plan.md``).

**No survey data.** This script never reads, loads or joins any survey table (``derived/survey/``,
``raw/survey/``), and its output holds no survey column. The analysis plan forbids joining the
outcomes to the survey before the plan is signed and frozen; the outcomes are computed blind to it.

Outcomes (definitions in ``social_energy.outcomes``; every choice below is `[inferred]` until the
research team signs the plan):

* **C1** ``strength_min_per_day``: minutes in close ties per camp day present, averaged over the
  person's present days. Close: a 5-minute bin whose strongest reading is at least ``close_rssi``;
  tie: a pair close for at least ``min_minutes`` in one camp day (07:30-07:30).
* **C2** ``cross_share``: share of tie minutes with participants of another course (course from
  ``Spine.people_frame()`` only), with ``cross_share_expected``, the share if everyone present
  mixed at random, and ``cross_share_excess``, the difference.
* **C3** ``new_ties_per_day``: ties a pair forms for the first time, on present days after the
  first two camp days, per present day after them.
* **C4** ``presses_per_hour``: self-report press episodes per exposure hour. Exposure is a 5-minute
  bin in which the tag was seen; bins in a lost window or an unsettled window
  (``beacon_diagnostics.py``) leave both the presses and the hours. A press counts only in an
  exposure bin.

Unit: participant. Filters, in order:

1. Pairs and seen bins from ``copresence_by_phase.py build``: our ingest, ``ok`` records, the
   observation window (``study.yaml``), both sides resolved through the spine and outside their
   exclusion windows, both people with ``beacons`` consent. Only participant-participant pairs
   count here.
2. Camp days 13-28 Aug; the 29 Aug stub (07:30-09:00) is left out, as in the co-presence report.
   A day counts for a person when the tag was seen in at least 12 bins (one hour).
3. C4: presses from the instruction (14 Aug 08:45) to the handover, episodes and accidental runs as
   in ``self_report_context.py``; participants with both ``self_report`` and ``beacons`` consent
   (exposure comes from the beacon data), C4 null for the rest.

Lost windows: in the main variant a pair bin survives one tag's lost window, because its partner
logged it (co-presence is counted from either side); the ``lost_both_sides`` variant drops the bin
for both partners instead (sensitivity 5 of the plan).

Variants (sensitivity 4 and 5 of the plan): ``main`` (-65 dBm, 60 min), ``rssi_-70``,
``rssi_-75``, ``min_15``, ``min_30``, ``lost_both_sides``. Sensitivities 1 (window from 11:30),
2 (hand-split fill) and 3 (no drift correction) need a rebuild of the ingest and are not here.

Run first: ``social-energy ingest-beacons``, ``copresence_by_phase.py build``,
``beacon_diagnostics.py``. Then:

    uv run python studies/dsa-2026/analyses/outcomes.py

Writes ``outcomes.parquet`` (one row per participant x variant), ``summary.csv`` (distributions
only, groups under ``MIN_GROUP`` suppressed) and ``qa.json`` to
``$SOCIAL_ENERGY_DATA/dsa-2026/derived/analyses/outcomes/``.
"""

from __future__ import annotations

import json
import sys
from datetime import timedelta
from pathlib import Path

import polars as pl

sys.path.insert(0, str(Path(__file__).parent))
import copresence_by_phase as cp
import self_report_context as srx

from social_energy import paths
from social_energy.outcomes import (
    close_contact_outcomes,
    daily_close_ties,
    drop_pair_bins,
    event_rate,
    present_days,
    windows_to_bins,
)
from social_energy.spine import Spine

SLUG = "outcomes"
BIN_MINUTES = 5
#: Camp days whose outcomes count: 13-28 Aug (cp.FIRST_DAY up to, not including, cp.LAST_DAY).
DAYS = [cp.FIRST_DAY + timedelta(d) for d in range((cp.LAST_DAY - cp.FIRST_DAY).days)]
#: C3: ties first seen on these first days set the baseline and are not "new".
BURN_IN_DAYS = 2
#: Main settings (dsa-2026-first-analyses plan): close at -65 dBm, a tie is an hour in a day.
MAIN = {"close_rssi": cp.CLOSE_RSSI, "min_minutes": cp.TIE_MIN_BINS * BIN_MINUTES}
VARIANTS: dict[str, dict] = {
    "main": {**MAIN, "lost_both_sides": False},
    "rssi_-70": {**MAIN, "close_rssi": -70, "lost_both_sides": False},
    "rssi_-75": {**MAIN, "close_rssi": -75, "lost_both_sides": False},
    "min_15": {**MAIN, "min_minutes": 15, "lost_both_sides": False},
    "min_30": {**MAIN, "min_minutes": 30, "lost_both_sides": False},
    "lost_both_sides": {**MAIN, "lost_both_sides": True},
}
OUTCOMES = [
    "strength_min_per_day",
    "cross_share",
    "cross_share_expected",
    "cross_share_excess",
    "new_ties_per_day",
    "presses_per_hour",
]


def removed_bins(layout: paths.StudyLayout, spine: Spine) -> pl.DataFrame:
    """Person and bin each tag could not report: lost windows and unsettled windows.

    Each bin is resolved to its wearer at the bin's own time, so a window across a tag swap is
    credited to whoever wore the tag then.
    """
    d = layout.derived / "analyses" / "beacon-diagnostics"
    files = [d / "lost_windows.parquet", d / "unsettled_windows.parquet"]
    missing = [f.name for f in files if not f.exists()]
    if missing:
        raise SystemExit(f"run beacon_diagnostics.py first: missing {missing}")
    windows = pl.concat([pl.read_parquet(f).select("beacon", "start", "end") for f in files])
    bins = windows_to_bins(windows, bin_minutes=BIN_MINUTES, key="beacon")
    return (
        spine.resolve(bins, device_col="beacon", time_col="bin", kind="beacon", out="entity")
        .filter(pl.col("entity").is_not_null())
        .select("entity", "bin")
        .unique()
    )


def summarise(table: pl.DataFrame) -> pl.DataFrame:
    """Distribution of each outcome per variant; a cell with fewer than MIN_GROUP people is null."""
    rows = []
    for variant in VARIANTS:
        v = table.filter(pl.col("variant") == variant)
        for name in OUTCOMES:
            x = v[name].drop_nulls()
            row = {"variant": variant, "outcome": name, "n": x.len()}
            if x.len() >= cp.MIN_GROUP:
                row |= {
                    "mean": x.mean(),
                    "sd": x.std(),
                    "p10": x.quantile(0.1, "linear"),
                    "p25": x.quantile(0.25, "linear"),
                    "median": x.median(),
                    "p75": x.quantile(0.75, "linear"),
                    "p90": x.quantile(0.9, "linear"),
                    "share_zero": (x == 0).mean(),
                }
            rows.append(row)
    return pl.DataFrame(rows, infer_schema_length=None)


def check_against_daily_network(ties: pl.DataFrame, present: pl.DataFrame) -> dict | None:
    """Mean degree per day from our ties against copresence_by_phase's daily_network.csv."""
    f = cp.out_dir() / "daily_network.csv"
    if not f.exists():
        return None
    ref = pl.read_csv(f, try_parse_dates=True).select("day", "people", "ties", "mean_degree")
    ours = (
        present.group_by("day")
        .agg(pl.len().alias("people_ours"))
        .join(ties.group_by("day").agg(pl.len().alias("ties_ours")), on="day", how="left")
        .with_columns(pl.col("ties_ours").fill_null(0))
        .join(ref, on="day")
    )
    return {
        "days_compared": ours.height,
        "max_abs_diff_people": ours.select((pl.col("people") - pl.col("people_ours")).abs().max())
        .item(),
        "max_abs_diff_ties": ours.select((pl.col("ties") - pl.col("ties_ours")).abs().max()).item(),
    }  # fmt: skip


def main() -> None:
    layout = paths.study(cp.STUDY)
    spine = Spine.load(layout.spine)
    out = layout.derived / "analyses" / SLUG
    out.mkdir(parents=True, exist_ok=True)

    frame = spine.people_frame().filter(pl.col("role") == "participant")
    beacon_ok = {f"person:{p}" for p in spine.consented("beacons")}
    press_ok = {f"person:{p}" for p in spine.consented("self_report")} & beacon_ok
    people = sorted(set(frame["entity"]) & beacon_ok)
    groups = dict(zip(frame["entity"], frame["course"], strict=True))
    qa: dict = {
        "participants": frame.height,
        "with_beacon_consent": len(people),
        "with_beacon_consent_and_course": sum(groups.get(p) is not None for p in people),
        "with_self_report_and_beacon_consent": len(set(people) & press_ok),
        "days": [str(d) for d in DAYS],
        "burn_in_days": BURN_IN_DAYS,
    }

    in_days = pl.col("day").is_in(DAYS)
    pairs = cp.load_all("pairs").filter(
        pl.col("a").is_in(people) & pl.col("b").is_in(people) & in_days
    )
    seen = cp.load_all("seen").filter(pl.col("entity").is_in(people))
    present = present_days(seen.filter(in_days), min_bins=cp.PRESENT_MIN_BINS)
    removed = removed_bins(layout, spine)
    qa |= {
        "pair_bins": pairs.height,
        "seen_bins": seen.height,
        "person_days_present": present.height,
        "removed_bins": removed.height,
    }

    # C4: presses and exposure from the instruction to the handover.
    episodes, press_qa = srx.press_episodes(layout, spine, set(frame["entity"]), press_ok)
    qa["presses"] = press_qa
    lo, hi = srx.local(srx.INSTRUCTION), srx.local(cp.HANDOVER)
    exposure = seen.filter((pl.col("bin") >= lo) & (pl.col("bin") < hi))
    rate = event_rate(
        episodes.select("entity", "t"),
        exposure,
        people=sorted(press_ok & set(people)),
        bin_minutes=BIN_MINUTES,
        removed=removed,
    ).select(
        "entity",
        pl.col("exposure_hours"),
        pl.col("events").alias("press_episodes"),
        pl.col("events_per_hour").alias("presses_per_hour"),
    )
    qa["press_episodes_counted"] = int(rate["press_episodes"].sum())
    qa["press_episodes_outside_exposure"] = episodes.height - qa["press_episodes_counted"]

    tables = []
    for name, v in VARIANTS.items():
        p = drop_pair_bins(pairs, removed) if v["lost_both_sides"] else pairs
        ties = daily_close_ties(
            p, close_rssi=v["close_rssi"], min_minutes=v["min_minutes"], bin_minutes=BIN_MINUTES
        )
        if name == "main":
            qa["check_daily_network"] = check_against_daily_network(ties, present)
        o = close_contact_outcomes(
            ties, present, people=people, days=DAYS, groups=groups, burn_in_days=BURN_IN_DAYS
        )
        tables.append(
            o.join(rate, on="entity", how="left").with_columns(
                (pl.col("cross_share") - pl.col("cross_share_expected")).alias(
                    "cross_share_excess"
                ),
                pl.lit(name).alias("variant"),
                pl.lit(v["close_rssi"]).alias("close_rssi"),
                pl.lit(v["min_minutes"]).alias("min_minutes"),
                pl.lit(v["lost_both_sides"]).alias("lost_both_sides"),
            )
        )
        qa[f"variant_{name}"] = {
            "pair_bins": p.height,
            "ties": ties.height,
            **{f"n_{k}": o[k].drop_nulls().len() for k in o.columns if k != "entity"},
        }

    first = ["variant", "close_rssi", "min_minutes", "lost_both_sides", "entity"]
    table = pl.concat(tables, how="vertical_relaxed")
    rest = [c for c in table.columns if c not in first and c != "cross_share_excess"]
    at = rest.index("cross_share_expected") + 1
    table = table.select(*first, *rest[:at], "cross_share_excess", *rest[at:])
    table.write_parquet(out / "outcomes.parquet")
    summary = summarise(table)
    summary.write_csv(out / "summary.csv")
    (out / "qa.json").write_text(json.dumps(qa, indent=2, default=str), encoding="utf-8")
    with pl.Config(tbl_rows=100, tbl_cols=20):
        print(json.dumps(qa, indent=2, default=str))
        print(summary)


if __name__ == "__main__":
    main()
