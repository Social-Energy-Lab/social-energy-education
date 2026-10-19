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
* **C3**, three candidates while the plan's stability rule picks one (every variant must rank
  people like the main one, Spearman at least 0.7):

  * ``c3_partners``: distinct close partners whose first tie with the person (on the person's
    present days) falls after the first two camp days, over the whole camp, per present day after
    them. The plan's current wording.
  * ``c3_partners_all``: distinct close partners over the whole camp, no burn-in, per present day.
  * ``c3_daily``: the first definition, ties a pair forms for the first time, on present days after
    the first two camp days, per present day after them. Kept for comparison.

* **C4** ``presses_per_hour``: self-report press episodes per exposure hour. Exposure is a 5-minute
  bin in which the tag was seen; bins in a lost window or an unsettled window
  (``beacon_diagnostics.py``) leave both the presses and the hours. A press counts only in an
  exposure bin. ``c4_worn`` (sensitivity 6 of the plan) takes as exposure the bins in which the
  tag was assigned to the person (spine assignments, a bin going to whoever wore the tag at its
  start), less exclusion windows and the same lost and unsettled windows; presses are counted the
  same way, only in those bins.

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
``rssi_-75``, ``min_15``, ``min_30``, ``lost_both_sides``; and for C4 only (sensitivity 7),
``accidental_7min``: a chain of presses is accidental only when it lasts at least 7 minutes, with
no count rule (C1-C3 equal main in that row).

Sensitivities 2 and 3 change the ingest itself, so they read a rebuilt one
(``sensitivity_ingests.py``, under ``derived/sensitivity/<variant>/``) with the main settings
otherwise; the ``ingest`` column names it. ``hand_split_fill`` (2): readouts our ID repair leaves
ambiguous take the beacon team's hand label instead (``BeaconConfig.id_fallback``); unsettled
windows remain only for readouts the hand split did not label either. ``no_drift`` (3): records
dated with ``clock_rate_ppm`` 0, lost windows from cycles at the same rate. Each reruns everything
downstream on its ingest: pairs, seen bins, present days, lost and unsettled windows, presses. A
variant whose ingest is not built is left out and listed in ``qa.json``. Sensitivity 1 (window
from 11:30) was dropped: the beacon team ruled 11:30-18:00 unusable.

Run first: ``social-energy ingest-beacons``, ``copresence_by_phase.py build``,
``beacon_diagnostics.py``, ``sensitivity_ingests.py``. Then:

    uv run python studies/dsa-2026/analyses/outcomes.py

Writes ``outcomes.parquet`` (one row per participant x variant), ``summary.csv`` (distributions
only, groups under ``MIN_GROUP`` suppressed), ``rank_stability.csv`` (Spearman of each variant with
main, per outcome) and ``qa.json`` (with C4's correlations with exposure) to
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
import sensitivity_ingests

from social_energy import paths
from social_energy.outcomes import (
    close_contact_outcomes,
    daily_close_ties,
    drop_pair_bins,
    event_rate,
    present_days,
    windows_to_bins,
    worn_bins,
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
#: Accidental press runs (C4): the main rule, and the beacon team's own example of a bag-pressed
#: tag, minutes of repeated pressing, as a duration-only rule (sensitivity 7).
PRESS_RULES = {
    "main": {"accidental_s": srx.ACCIDENTAL_S, "accidental_n": srx.ACCIDENTAL_N},
    "7min": {"accidental_s": 7 * 60, "accidental_n": None},
}
#: ``ingest``: None is the main ingest (``derived/beacons/``); a name is a sensitivity ingest built
#: by ``sensitivity_ingests.py`` under ``derived/sensitivity/<name>/``.
_M = {**MAIN, "lost_both_sides": False, "press": "main", "ingest": None}
VARIANTS: dict[str, dict] = {
    "main": _M,
    "rssi_-70": {**_M, "close_rssi": -70},
    "rssi_-75": {**_M, "close_rssi": -75},
    "min_15": {**_M, "min_minutes": 15},
    "min_30": {**_M, "min_minutes": 30},
    "lost_both_sides": {**_M, "lost_both_sides": True},
    "accidental_7min": {**_M, "press": "7min"},
    **{name: {**_M, "ingest": name} for name in sensitivity_ingests.VARIANTS},
}
OUTCOMES = [
    "strength_min_per_day",
    "cross_share",
    "cross_share_expected",
    "cross_share_excess",
    "c3_partners",
    "c3_partners_all",
    "c3_daily",
    "presses_per_hour",
    "c4_worn",
]
#: Measure columns from close_contact_outcomes, renamed for the study's C3 candidates.
C3_NAMES = {
    "new_ties_per_day": "c3_daily",
    "new_partners_per_day": "c3_partners",
    "partners_per_day": "c3_partners_all",
}


def removed_bins(spine: Spine, ingest: str | None = None) -> pl.DataFrame:
    """Person and bin each tag could not report: lost windows and unsettled windows.

    Each bin is resolved to its wearer at the bin's own time, so a window across a tag swap is
    credited to whoever wore the tag then. ``ingest`` names a sensitivity ingest (its own windows).
    """
    d = cp.derived_root(ingest) / "analyses" / "beacon-diagnostics"
    files = [d / "lost_windows.parquet", d / "unsettled_windows.parquet"]
    missing = [f.name for f in files if not f.exists()]
    if missing:
        run = "beacon_diagnostics.py" if ingest is None else f"sensitivity_ingests.py {ingest}"
        raise SystemExit(f"run {run} first: missing {missing} in {d}")
    windows = pl.concat([pl.read_parquet(f).select("beacon", "start", "end") for f in files])
    bins = windows_to_bins(windows, bin_minutes=BIN_MINUTES, key="beacon")
    return (
        spine.resolve(bins, device_col="beacon", time_col="bin", kind="beacon", out="entity")
        .filter(pl.col("entity").is_not_null())
        .select("entity", "bin")
        .unique()
    )


def built(table: pl.DataFrame) -> list[str]:
    """The variants in ``table``, in ``VARIANTS`` order (a sensitivity ingest may not be built)."""
    have = set(table["variant"])
    return [v for v in VARIANTS if v in have]


def summarise(table: pl.DataFrame) -> pl.DataFrame:
    """Distribution of each outcome per variant; a cell with fewer than MIN_GROUP people is null."""
    rows = []
    for variant in built(table):
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


def rank_stability(table: pl.DataFrame) -> pl.DataFrame:
    """Spearman of each variant with main per outcome, people with both values as units."""
    main = table.filter(pl.col("variant") == "main")
    rows = []
    for variant in built(table):
        if variant == "main":
            continue
        v = table.filter(pl.col("variant") == variant)
        for name in OUTCOMES:
            both = main.select("entity", pl.col(name).alias("_m")).join(
                v.select("entity", pl.col(name).alias("_v")), on="entity"
            )
            both = both.drop_nulls()
            rho = (
                both.select(pl.corr("_m", "_v", method="spearman")).item() if both.height else None
            )
            rows.append({"variant": variant, "outcome": name, "n": both.height, "spearman": rho})
    return pl.DataFrame(rows, infer_schema_length=None)


def c4_correlations(rate: pl.DataFrame) -> dict:
    """C4 against its exposure, heard and worn, and the two C4s against each other."""
    pairs = {
        "heard_rate_vs_heard_hours": ("presses_per_hour", "exposure_hours"),
        "worn_rate_vs_worn_hours": ("c4_worn", "exposure_hours_worn"),
        "worn_rate_vs_heard_hours": ("c4_worn", "exposure_hours"),
        "worn_rate_vs_heard_rate": ("c4_worn", "presses_per_hour"),
        "worn_hours_vs_heard_hours": ("exposure_hours_worn", "exposure_hours"),
    }
    out = {}
    for key, (x, y) in pairs.items():
        d = rate.select(x, y).drop_nulls()
        out[key] = {
            "n": d.height,
            "pearson": d.select(pl.corr(x, y)).item(),
            "spearman": d.select(pl.corr(x, y, method="spearman")).item(),
        }
    return out


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


def ingest_built(ingest: str) -> bool:
    root = cp.derived_root(ingest)
    return (root / "beacons" / "qa.json").exists() and any(
        (root / "analyses" / cp.SLUG).glob("pairs_*.parquet")
    )


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
    raters = sorted(press_ok & set(people))
    qa: dict = {
        "participants": frame.height,
        "with_beacon_consent": len(people),
        "with_beacon_consent_and_course": sum(groups.get(p) is not None for p in people),
        "with_self_report_and_beacon_consent": len(raters),
        "days": [str(d) for d in DAYS],
        "burn_in_days": BURN_IN_DAYS,
    }
    missing = [n for n in sensitivity_ingests.VARIANTS if not ingest_built(n)]
    if missing:
        print(f"not built, left out: {missing} (run sensitivity_ingests.py)", flush=True)
    qa["sensitivity_ingests_missing"] = missing
    variants = {n: v for n, v in VARIANTS.items() if v["ingest"] not in missing}

    in_days = pl.col("day").is_in(DAYS)
    lo, hi = srx.local(srx.INSTRUCTION), srx.local(cp.HANDOVER)
    worn = worn_bins(
        spine,
        kind="beacon",
        start=pl.select(lo).item(),
        end=pl.select(hi).item(),
        bin_minutes=BIN_MINUTES,
    )
    inputs: dict[str | None, dict] = {}
    rates: dict[tuple[str | None, str], pl.DataFrame] = {}
    for ingest in dict.fromkeys(v["ingest"] for v in variants.values()):
        # The main ingest's counts stay at the top level of qa.json, as before the sensitivities.
        q = qa if ingest is None else qa.setdefault(f"ingest_{ingest}", {})
        pairs = cp.load_all("pairs", ingest).filter(
            pl.col("a").is_in(people) & pl.col("b").is_in(people) & in_days
        )
        seen = cp.load_all("seen", ingest).filter(pl.col("entity").is_in(people))
        present = present_days(seen.filter(in_days), min_bins=cp.PRESENT_MIN_BINS)
        removed = removed_bins(spine, ingest)
        inputs[ingest] = {"pairs": pairs, "present": present, "removed": removed}
        q |= {
            "pair_bins": pairs.height,
            "seen_bins": seen.height,
            "person_days_present": present.height,
            "removed_bins": removed.height,
        }

        # C4: presses and exposure from the instruction to the handover. Exposure heard (main) and
        # worn (c4_worn), for each accidental-run rule a variant on this ingest uses.
        exposure = seen.filter((pl.col("bin") >= lo) & (pl.col("bin") < hi))
        rules = dict.fromkeys(v["press"] for v in variants.values() if v["ingest"] == ingest)
        for rule in rules:
            episodes, press_qa = srx.press_episodes(
                layout, spine, set(frame["entity"]), press_ok, **PRESS_RULES[rule], variant=ingest
            )
            events = episodes.select("entity", "t")
            heard = event_rate(
                events, exposure, people=raters, bin_minutes=BIN_MINUTES, removed=removed
            )
            on = event_rate(events, worn, people=raters, bin_minutes=BIN_MINUTES, removed=removed)
            r = heard.select(
                "entity",
                "exposure_hours",
                pl.col("events").alias("press_episodes"),
                pl.col("events_per_hour").alias("presses_per_hour"),
            ).join(
                on.select(
                    "entity",
                    pl.col("exposure_hours").alias("exposure_hours_worn"),
                    pl.col("events").alias("press_episodes_worn"),
                    pl.col("events_per_hour").alias("c4_worn"),
                ),
                on="entity",
            )
            rates[(ingest, rule)] = r
            counted = int(r["press_episodes"].sum())
            counted_worn = int(r["press_episodes_worn"].sum())
            q[f"presses_{rule}"] = press_qa | {
                "episodes_counted": counted,
                "episodes_outside_exposure": episodes.height - counted,
                "episodes_counted_worn": counted_worn,
                "episodes_outside_worn": episodes.height - counted_worn,
            }
            q[f"c4_correlations_{rule}"] = c4_correlations(r)
    m = variants["main"]["ingest"]
    both = rates[(m, "main")].join(rates[(m, "7min")], on="entity", suffix="_7")
    rated = both.drop_nulls(["presses_per_hour", "presses_per_hour_7"])
    qa["c4_accidental_7min_vs_main"] = {
        "people_with_changed_count": int(
            (both["press_episodes"] != both["press_episodes_7"]).sum()
        ),
        "spearman": rated.select(
            pl.corr("presses_per_hour", "presses_per_hour_7", method="spearman")
        ).item(),
        "spearman_worn": rated.select(pl.corr("c4_worn", "c4_worn_7", method="spearman")).item(),
    }

    tables = []
    for name, v in variants.items():
        src = inputs[v["ingest"]]
        p = drop_pair_bins(src["pairs"], src["removed"]) if v["lost_both_sides"] else src["pairs"]
        ties = daily_close_ties(
            p, close_rssi=v["close_rssi"], min_minutes=v["min_minutes"], bin_minutes=BIN_MINUTES
        )
        if name == "main":
            qa["check_daily_network"] = check_against_daily_network(ties, src["present"])
        o = close_contact_outcomes(
            ties, src["present"], people=people, days=DAYS, groups=groups,
            burn_in_days=BURN_IN_DAYS,
        ).rename(C3_NAMES)  # fmt: skip
        tables.append(
            o.join(rates[(v["ingest"], v["press"])], on="entity", how="left").with_columns(
                (pl.col("cross_share") - pl.col("cross_share_expected")).alias(
                    "cross_share_excess"
                ),
                pl.lit(name).alias("variant"),
                pl.lit(v["ingest"] or "main", dtype=pl.String).alias("ingest"),
                pl.lit(v["close_rssi"]).alias("close_rssi"),
                pl.lit(v["min_minutes"]).alias("min_minutes"),
                pl.lit(v["lost_both_sides"]).alias("lost_both_sides"),
                pl.lit(v["press"]).alias("accidental_rule"),
            )
        )
        qa[f"variant_{name}"] = {
            "pair_bins": p.height,
            "ties": ties.height,
            **{f"n_{k}": o[k].drop_nulls().len() for k in o.columns if k != "entity"},
        }

    first = [
        "variant", "ingest", "close_rssi", "min_minutes", "lost_both_sides", "accidental_rule",
        "entity",
    ]  # fmt: skip
    table = pl.concat(tables, how="vertical_relaxed")
    rest = [c for c in table.columns if c not in first and c != "cross_share_excess"]
    at = rest.index("cross_share_expected") + 1
    table = table.select(*first, *rest[:at], "cross_share_excess", *rest[at:])
    table.write_parquet(out / "outcomes.parquet")
    summary = summarise(table)
    summary.write_csv(out / "summary.csv")
    stability = rank_stability(table)
    stability.write_csv(out / "rank_stability.csv")
    (out / "qa.json").write_text(json.dumps(qa, indent=2, default=str), encoding="utf-8")
    with pl.Config(tbl_rows=100, tbl_cols=20):
        print(json.dumps(qa, indent=2, default=str))
        print(summary)
        print(stability.pivot("variant", index="outcome", values="spearman"))


if __name__ == "__main__":
    main()
