"""The programme's rhythm: cross-course mixing on special days, and whether their ties last.
EXPLORATORY.

Research question: the exploratory item "The programme's rhythm" of ``research/analysis-plan.md``
(cross-course mixing on special days, excursion and rotation, and whether those ties persist).
Construct: a programme day that breaks the course routine as a chance for resonance across the
academy's bubbles `[inferred]`. Nothing here is a test: no error control, two-sided, effect sizes
with 95 % bootstrap intervals, no p-values.

Unit of analysis: the person-period for mixing (each person against themselves, special days
against ordinary days), the new tie (a pair's first tie) for persistence.

Definitions are the confirmatory outcomes' (``outcomes.py``, ``social_energy.outcomes``): a close
5-minute bin at -65 dBm or stronger, a tie at 60 close minutes in a camp day (07:30-07:30), a day
counts for a person seen for at least an hour, participants with ``beacons`` consent only, course
from the spine. A pair bin counts when *either* partner logged it (the main rule), which recovers
the bins a tag lost from its partner's side.

Days (``study.yaml`` explorer notes, the spine's events): the excursion (18 Aug) and the rotation
day (22 Aug) are special. Ordinary days are 14-28 Aug without them; 13 Aug (arrival, observed from
18:00 only) is left out of every contrast. 24-27 Aug carry fewer tag-hours with the tag's own
records (an instrument loss, not fewer encounters: private note spine-inference-2026-10-18, Q8),
which halves close pair-bins and so ties; the coverage figure shows it and every result is also
reported without those days.

1. **Mixing.** Per day, the share of ties across courses against the share random mixing among the
   people present would give (``social_energy.rhythm.daily_mixing``). Per person, the excess of
   their cross-course share of tie minutes over their own random-mixing share, on the special day
   against ordinary days (``period_mixing``); the within-person difference is summarised over
   people with a percentile bootstrap that resamples people.
2. **Persistence.** A tie is new on the pair's first tied day from 15 Aug (13-14 Aug set the
   baseline, as for C3). For each new tie and each later camp day on which both partners were
   present: tied again or not (``retie_opportunities``). Reported (a) as the share tied again
   within three days, (b) on any later day, and (c) from a logistic model of "tied again" on the
   kind of day the tie formed on, with a term per follow-up day (which absorbs days the instrument
   saw less) and per lag (capped at 6 days). Intervals resample people (a tie's weight is the
   product of its partners' draws: ``node_bootstrap_weights``).

Variants: the main tie definition and the plan's neighbours -70 dBm and 30 minutes; lost windows
dropped on both sides (sensitivity 5) to show what the partner-side recovery is worth; ordinary
days without 24-27 Aug; persistence with the 24-27 Aug follow-up days left out.

Reporting: aggregates only. Day-level rows always hold far more than five people; person-level
contrasts are reported as distributions (mean, quartiles) over at least ``MIN_GROUP`` people; no
course-level result.

Run first: ``copresence_by_phase.py build``, ``beacon_diagnostics.py``. Then:

    uv run --extra analysis python studies/dsa-2026/analyses/exploratory_rhythm.py

Writes to ``$SOCIAL_ENERGY_DATA/dsa-2026/derived/analyses/exploratory/``: ``rhythm_*.csv``,
``rhythm_summary.json``, ``fig_rhythm_*.png``, and ``own_record_bins.parquet`` (the bins in which
each tag's own records exist, also read by ``exploratory_acoustics.py``).
"""

from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

import numpy as np
import polars as pl

sys.path.insert(0, str(Path(__file__).parent))
import copresence_by_phase as cp
import outcomes as oc

from social_energy import paths
from social_energy.outcomes import daily_close_ties, drop_pair_bins, present_days
from social_energy.rhythm import (
    daily_mixing,
    node_bootstrap_weights,
    period_mixing,
    retie_opportunities,
)
from social_energy.spine import Spine

SLUG = "exploratory"
BIN_MINUTES = oc.BIN_MINUTES
DAYS = oc.DAYS  # 13-28 Aug
ARRIVAL = date(2026, 8, 13)
#: The days the programme broke the course routine (spine events, study.yaml explorer notes).
SPECIAL = {date(2026, 8, 18): "excursion", date(2026, 8, 22): "rotation"}
#: Fewer tag-hours with the tag's own records (instrument, not behaviour).
DIP = [date(2026, 8, d) for d in (24, 25, 26, 27)]
#: New ties are counted from this day; earlier first ties set the baseline (as C3's burn-in).
FIRST_NEW = DAYS[oc.BURN_IN_DAYS]
WITHIN_DAYS = 3
LAG_CAP = 6
MIN_GROUP = cp.MIN_GROUP
N_BOOT = 2000
N_BOOT_MODEL = 400
SEED = 20261020
VARIANTS = {
    "main": {"close_rssi": -65, "min_minutes": 60, "lost_both_sides": False},
    "rssi_-70": {"close_rssi": -70, "min_minutes": 60, "lost_both_sides": False},
    "min_30": {"close_rssi": -65, "min_minutes": 30, "lost_both_sides": False},
    "lost_both_sides": {"close_rssi": -65, "min_minutes": 60, "lost_both_sides": True},
}
INK, INK2, GRID, SURFACE = "#0b0b0b", "#52514e", "#e4e3df", "#fcfcfb"
BLUE, ORANGE, GREEN, GRAY = "#2a78d6", "#eb6834", "#2e9e6a", "#8a8984"
KIND_COLOR = {"ordinary": GRAY, "excursion": BLUE, "rotation": ORANGE}


def out_dir() -> Path:
    d = paths.study(cp.STUDY).derived / "analyses" / SLUG
    d.mkdir(parents=True, exist_ok=True)
    return d


def kind_of(d: date) -> str:
    return SPECIAL.get(d, "ordinary")


def ordinary_days(*, without_dip: bool = False) -> list[date]:
    return [d for d in DAYS if d != ARRIVAL and d not in SPECIAL and not (without_dip and d in DIP)]


# ---- own-record coverage ----------------------------------------------------------------------


def own_record_bins(layout: paths.StudyLayout, spine: Spine, people: set[str]) -> pl.DataFrame:
    """``entity``, ``bin``: 5-minute bins in which the person's own tag logged anything (``ok``).

    Cached in the output folder; the acoustics analysis reads it as an exposure variant.
    """
    f = out_dir() / "own_record_bins.parquet"
    if f.exists():
        return pl.read_parquet(f).filter(pl.col("entity").is_in(people))
    lo, hi = cp.window_bounds()
    parts = []
    for part in sorted((layout.derived / "beacons" / "contacts").glob("20*.parquet")):
        b = (
            pl.scan_parquet(part)
            .filter(pl.col("ok"))
            .select("beacon", pl.col("t").dt.truncate(cp.BIN).alias("bin"))
            .unique()
            .collect()
        )
        parts.append(b)
    own = pl.concat(parts).unique().filter((pl.col("bin") >= lo) & (pl.col("bin") < hi))
    own = spine.resolve(own, device_col="beacon", time_col="bin", kind="beacon", out="entity")
    own = spine.flag_excluded(own, device_col="beacon", time_col="bin", kind="beacon", out="_x")
    own = own.filter(pl.col("entity").str.starts_with("person:") & ~pl.col("_x"))
    own = own.select("entity", "bin").unique()
    own.write_parquet(f)
    return own.filter(pl.col("entity").is_in(people))


def coverage_by_day(
    seen: pl.DataFrame, own: pl.DataFrame, pairs: pl.DataFrame, ties: pl.DataFrame
) -> pl.DataFrame:
    """Per day: share of seen person-bins with own records, two-sided pair-bins, ties."""
    s = seen.select("entity", "bin", "day").unique()
    cov = (
        s.join(own.with_columns(pl.lit(True).alias("_own")), on=["entity", "bin"], how="left")
        .group_by("day")
        .agg(
            pl.len().alias("seen_person_bins"),
            pl.col("_own").fill_null(False).mean().alias("own_record_share"),
        )
    )
    two = pairs.group_by("day").agg(
        pl.len().alias("pair_bins"),
        (pl.col("directions") == 2).mean().alias("two_sided_share"),
        (pl.col("max_rssi") >= -65).sum().alias("close_pair_bins"),
    )
    t = ties.group_by("day").agg(pl.len().alias("ties"))
    return cov.join(two, on="day", how="left").join(t, on="day", how="left").sort("day")


# ---- statistics -------------------------------------------------------------------------------


def boot_mean(x: np.ndarray, *, n_boot: int = N_BOOT, seed: int = SEED) -> tuple[float, ...]:
    rng = np.random.default_rng(seed)
    draws = rng.choice(x, (n_boot, len(x)), replace=True).mean(axis=1)
    lo, hi = np.quantile(draws, [0.025, 0.975])
    return float(x.mean()), float(lo), float(hi)


def mixing_contrast(pm: pl.DataFrame, special: str, ordinary: str = "ordinary") -> dict:
    """Within-person difference of cross-course share and excess, special minus ordinary."""
    w = (
        pm.filter(pl.col("period") == special)
        .select("entity", pl.col("cross_share").alias("s_share"), pl.col("excess").alias("s_ex"),
                pl.col("expected").alias("s_exp"))
        .join(
            pm.filter(pl.col("period") == ordinary).select(
                "entity", pl.col("cross_share").alias("o_share"), pl.col("excess").alias("o_ex"),
                pl.col("expected").alias("o_exp"),
            ),
            on="entity",
        )
        .drop_nulls()
    )  # fmt: skip
    n = w.height
    row: dict = {"special": special, "ordinary": ordinary, "n_people": n}
    if n < MIN_GROUP:
        return row
    d_ex = (w["s_ex"] - w["o_ex"]).to_numpy()
    d_share = (w["s_share"] - w["o_share"]).to_numpy()
    m, lo, hi = boot_mean(d_ex)
    ms, los, his = boot_mean(d_share)
    return row | {
        "special_share_mean": w["s_share"].mean(),
        "ordinary_share_mean": w["o_share"].mean(),
        "special_expected_mean": w["s_exp"].mean(),
        "ordinary_expected_mean": w["o_exp"].mean(),
        "diff_share_mean": ms,
        "diff_share_lo": los,
        "diff_share_hi": his,
        "diff_excess_mean": m,
        "diff_excess_lo": lo,
        "diff_excess_hi": hi,
        "diff_excess_q25": float(np.quantile(d_ex, 0.25)),
        "diff_excess_median": float(np.median(d_ex)),
        "diff_excess_q75": float(np.quantile(d_ex, 0.75)),
        "share_people_higher_on_special": float((d_ex > 0).mean()),
        "dz": float(d_ex.mean() / d_ex.std(ddof=1)) if d_ex.std(ddof=1) > 0 else None,
    }


def persistence_table(opps: pl.DataFrame, groups: dict[str, str | None]) -> pl.DataFrame:
    """One row per new tie: kind of formation day, cross-course, tied again within 3 / any."""
    g = pl.DataFrame(
        {"e": list(groups), "g": list(groups.values())}, schema={"e": pl.String, "g": pl.String}
    )
    per = opps.group_by("a", "b", "formed").agg(
        pl.col("tied").filter(pl.col("lag") <= WITHIN_DAYS).any().alias("again_3"),
        (pl.col("lag") <= WITHIN_DAYS).any().alias("has_3"),
        pl.col("tied").any().alias("again_any"),
    )
    return (
        per.join(g.rename({"e": "a", "g": "ga"}), on="a", how="left")
        .join(g.rename({"e": "b", "g": "gb"}), on="b", how="left")
        .with_columns(
            (pl.col("ga") != pl.col("gb")).alias("cross"),
            pl.col("formed").map_elements(kind_of, return_dtype=pl.String).alias("kind"),
        )
        .drop("ga", "gb")
    )


def _ends(per: pl.DataFrame, index: dict[str, int]) -> tuple[np.ndarray, np.ndarray]:
    """Positions of each row's two partners in ``index``, for the node-bootstrap weights."""
    return (
        per["a"].replace_strict(index).to_numpy(),
        per["b"].replace_strict(index).to_numpy(),
    )


def persistence_rates(per: pl.DataFrame, index: dict[str, int], kinds: list[str]) -> list[dict]:
    """Share tied again (within 3 days, any later day) by kind, with node-bootstrap intervals."""
    rows = []
    draws = list(node_bootstrap_weights(len(index), n_boot=N_BOOT, seed=SEED))
    for outcome, base in (("again_3", pl.col("has_3")), ("again_any", pl.lit(True))):
        for kind in kinds:
            sub = per.filter(base & (pl.col("kind") == kind))
            if sub.height == 0:
                continue
            y = sub[outcome].cast(pl.Float64).to_numpy()
            a, b = _ends(sub, index)
            boot = []
            for w in draws:
                ww = w[a] * w[b]
                if ww.sum() > 0:
                    boot.append(float((ww * y).sum() / ww.sum()))
            lo, hi = np.quantile(boot, [0.025, 0.975])
            rows.append(
                {"outcome": outcome, "kind": kind, "new_ties": sub.height, "share": y.mean(),
                 "lo": float(lo), "hi": float(hi)}
            )  # fmt: skip
    return rows


def _design(opps: pl.DataFrame) -> tuple[np.ndarray, np.ndarray, list[str]]:
    """Intercept, origin kind (ordinary = reference), follow-up day and lag dummies."""
    kinds = [k for k in ("excursion", "rotation") if k in set(opps["kind"])]
    days = sorted(set(opps["day"]))[1:]
    lags = sorted(set(opps["lag_c"]))[1:]
    cols = [np.ones(opps.height)]
    names = ["const"]
    k = opps["kind"].to_numpy()
    for kind in kinds:
        cols.append((k == kind).astype(float))
        names.append(f"formed_{kind}")
    dd = opps["day"].to_numpy()
    for d in days:
        cols.append((dd == np.datetime64(d)).astype(float))
        names.append(f"day_{d}")
    ll = opps["lag_c"].to_numpy()
    for lag in lags:
        cols.append((ll == lag).astype(float))
        names.append(f"lag_{lag}")
    return np.column_stack(cols), opps["tied"].cast(pl.Float64).to_numpy(), names


def persistence_model(opps: pl.DataFrame, index: dict[str, int], label: str) -> list[dict]:
    """Odds ratio of being tied again, ties formed on each special day vs ordinary days."""
    import warnings

    import statsmodels.api as sm

    opps = opps.with_columns(
        pl.col("formed").map_elements(kind_of, return_dtype=pl.String).alias("kind"),
        pl.min_horizontal(pl.col("lag"), pl.lit(LAG_CAP)).alias("lag_c"),
    )
    x, y, names = _design(opps)

    def fit(w: np.ndarray | None):
        keep = slice(None) if w is None else w > 0
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            m = sm.GLM(
                y[keep], x[keep], family=sm.families.Binomial(),
                freq_weights=None if w is None else w[keep],
            ).fit()  # fmt: skip
        return m.params

    est = fit(None)
    a, b = _ends(opps, index)
    boot = []
    for w in node_bootstrap_weights(len(index), n_boot=N_BOOT_MODEL, seed=SEED):
        try:
            boot.append(fit((w[a] * w[b]).astype(float)))
        except Exception:  # a draw without a special-day tie, or a singular design
            continue
    boot = np.array(boot)
    rows = []
    for i, name in enumerate(names):
        if not name.startswith("formed_"):
            continue
        lo, hi = np.quantile(boot[:, i], [0.025, 0.975])
        rows.append(
            {"model": label, "term": name, "odds_ratio": float(np.exp(est[i])),
             "lo": float(np.exp(lo)), "hi": float(np.exp(hi)), "opportunities": opps.height,
             "new_ties": opps.select("a", "b").unique().height, "draws": len(boot)}
        )  # fmt: skip
    return rows


# ---- main -------------------------------------------------------------------------------------


def main() -> None:
    layout = paths.study(cp.STUDY)
    spine = Spine.load(layout.spine)
    out = out_dir()
    frame = spine.people_frame().filter(pl.col("role") == "participant")
    beacon_ok = {f"person:{p}" for p in spine.consented("beacons")}
    people = sorted(set(frame["entity"]) & beacon_ok)
    groups = dict(zip(frame["entity"], frame["course"], strict=True))
    groups = {p: groups[p] for p in people}
    index = {p: i for i, p in enumerate(people)}
    in_days = pl.col("day").is_in(DAYS)

    pairs = cp.load_all("pairs").filter(
        pl.col("a").is_in(people) & pl.col("b").is_in(people) & in_days
    )
    seen = cp.load_all("seen").filter(pl.col("entity").is_in(people) & in_days)
    present = present_days(seen, min_bins=cp.PRESENT_MIN_BINS)
    removed = oc.removed_bins(spine)
    qa: dict = {
        "exploratory": True,
        "participants_with_beacon_consent": len(people),
        "with_course": sum(groups[p] is not None for p in people),
        "person_days_present": present.height,
        "special_days": {str(k): v for k, v in SPECIAL.items()},
        "dip_days": [str(d) for d in DIP],
        "first_new_tie_day": str(FIRST_NEW),
    }

    period_all = {d: kind_of(d) for d in DAYS if d != ARRIVAL}
    period_no_dip = {d: k for d, k in period_all.items() if d not in DIP}

    daily_rows, contrast_rows, rate_rows, model_rows = [], [], [], []
    main_ties = None
    for name, v in VARIANTS.items():
        p = drop_pair_bins(pairs, removed) if v["lost_both_sides"] else pairs
        ties = daily_close_ties(
            p, close_rssi=v["close_rssi"], min_minutes=v["min_minutes"], bin_minutes=BIN_MINUTES
        )
        if name == "main":
            main_ties = ties
        daily_rows.append(
            daily_mixing(ties, present, groups).with_columns(
                pl.lit(name).alias("variant"),
                pl.col("day").map_elements(kind_of, return_dtype=pl.String).alias("kind"),
                pl.col("day").is_in(DIP).alias("dip"),
            )
        )
        for days_label, period in (("all", period_all), ("without_24_27", period_no_dip)):
            pm = period_mixing(ties, present, groups, period)
            for special in SPECIAL.values():
                contrast_rows.append(
                    {"variant": name, "ordinary_days": days_label} | mixing_contrast(pm, special)
                )
            if name == "main" and days_label == "all":
                pm.write_parquet(out / "rhythm_person_period.parquet")  # internal, per person

        opps = retie_opportunities(ties, present, first_from=FIRST_NEW, days=DAYS)
        per = persistence_table(opps, groups)
        qa[f"new_ties_{name}"] = per.height
        kinds = ["ordinary", "excursion", "rotation"]
        for r in persistence_rates(per, index, kinds):
            rate_rows.append({"variant": name, "follow_up": "all", "origin": "all"} | r)
        # Ordinary origins without the dip days themselves (their own ties are undercounted).
        per_nd = per.filter(~pl.col("formed").is_in(DIP))
        for r in persistence_rates(per_nd, index, ["ordinary"]):
            rate_rows.append({"variant": name, "follow_up": "all", "origin": "without_24_27"} | r)
        # Cross-course new ties only.
        for r in persistence_rates(per.filter(pl.col("cross")), index, kinds):
            rate_rows.append({"variant": name, "follow_up": "all", "origin": "cross_course"} | r)
        if name in ("main", "rssi_-70", "min_30"):
            model_rows += persistence_model(opps, index, f"{name}: day + lag terms")
        if name == "main":
            model_rows += persistence_model(
                opps.filter(~pl.col("day").is_in(DIP)), index,
                "main: follow-up without 24-27 Aug",
            )  # fmt: skip
            model_rows += persistence_model(
                opps.filter(~pl.col("formed").is_in(DIP)), index,
                "main: ordinary origins without 24-27 Aug",
            )  # fmt: skip
            model_rows += persistence_model(
                opps.filter(pl.col("lag") <= WITHIN_DAYS), index, "main: lags 1-3 only"
            )
            cross_pairs = per.filter(pl.col("cross")).select("a", "b")
            model_rows += persistence_model(
                opps.join(cross_pairs, on=["a", "b"], how="semi"), index,
                "main: cross-course new ties only",
            )  # fmt: skip
            per.write_parquet(out / "rhythm_new_ties.parquet")  # internal, per pair

    daily = pl.concat(daily_rows, how="vertical_relaxed")
    contrast = pl.DataFrame(contrast_rows, infer_schema_length=None)
    rates = pl.DataFrame(rate_rows, infer_schema_length=None)
    models = pl.DataFrame(model_rows, infer_schema_length=None)
    own = own_record_bins(layout, spine, set(people))
    coverage = coverage_by_day(seen, own, pairs, main_ties)

    daily.write_csv(out / "rhythm_daily_mixing.csv")
    contrast.write_csv(out / "rhythm_mixing_contrast.csv")
    rates.write_csv(out / "rhythm_persistence_rates.csv")
    models.write_csv(out / "rhythm_persistence_model.csv")
    coverage.write_csv(out / "rhythm_coverage.csv")
    qa["outputs"] = sorted(p.name for p in out.glob("rhythm_*"))
    (out / "rhythm_summary.json").write_text(json.dumps(qa, indent=2, default=str))
    figures(daily, contrast, rates, models, coverage, out)
    with pl.Config(tbl_rows=200, tbl_cols=30, tbl_width_chars=250):
        print(json.dumps(qa, indent=2, default=str))
        print(daily.filter(pl.col("variant") == "main"))
        print(contrast)
        print(rates)
        print(models)
        print(coverage)


# ---- figures ----------------------------------------------------------------------------------


def _style(plt) -> None:
    plt.rcParams.update(
        {
            "font.size": 11,
            "axes.spines.top": False,
            "axes.spines.right": False,
            "axes.edgecolor": INK2,
            "axes.labelcolor": INK2,
            "xtick.color": INK2,
            "ytick.color": INK2,
            "axes.grid": True,
            "grid.color": GRID,
            "grid.linewidth": 0.6,
            "figure.facecolor": SURFACE,
            "axes.facecolor": SURFACE,
            "savefig.facecolor": SURFACE,
            "axes.titlecolor": INK,
            "axes.titlesize": 12,
            "legend.frameon": False,
        }
    )


def _shade_dip(ax, labels: list[str]) -> None:
    i0, i1 = labels.index("24"), labels.index("27")
    ax.axvspan(i0 - 0.5, i1 + 0.5, color=GRID, alpha=0.6, lw=0, zorder=0)


def figures(daily, contrast, rates, models, coverage, out: Path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    _style(plt)
    note = "EXPLORATORY · DSA 2026 · aggregates only"

    # 1. Mixing by day, against random mixing.
    d = daily.filter((pl.col("variant") == "main") & (pl.col("day") != ARRIVAL)).sort("day")
    labels = [x.strftime("%d") for x in d["day"]]
    xs = np.arange(len(labels))
    colors = [KIND_COLOR[k] for k in d["kind"]]
    fig, ax = plt.subplots(figsize=(10, 4.6))
    _shade_dip(ax, labels)
    ax.bar(xs, d["cross_share"].to_numpy() * 100, color=colors, width=0.7)
    ax.plot(xs, d["expected"].to_numpy() * 100, color=INK, lw=1.5, ls=":",
            label="if everyone present mixed at random")  # fmt: skip
    ax.set_xticks(xs, labels)
    ax.set_xlabel("August (camp day 07:30-07:30)")
    ax.set_ylabel("ties across courses (%)")
    ax.set_ylim(0, 100)
    ax.set_title("Ties across courses by day: excursion (blue) and rotation (orange) vs ordinary")
    ax.text(xs[labels.index("24")] - 0.4, 95, "fewer own records\n(instrument)", fontsize=9,
            color=INK2, va="top")  # fmt: skip
    ax.legend(loc="upper left", bbox_to_anchor=(0, 0.93))
    fig.text(0.01, 0.01, note + " · tie = ≥60 min at ≥-65 dBm in a day", fontsize=8, color=INK2)
    fig.tight_layout(rect=(0, 0.03, 1, 1))
    fig.savefig(out / "fig_rhythm_mixing_by_day.png", dpi=180)
    plt.close(fig)

    # 2. Within-person contrast, special minus ordinary (excess over random), with variants.
    c = contrast.filter(pl.col("diff_excess_mean").is_not_null())
    fig, ax = plt.subplots(figsize=(9, 4.8))
    rowsy, ylabels = [], []
    for i, r in enumerate(c.iter_rows(named=True)):
        y = -i
        col = KIND_COLOR[r["special"]]
        ax.plot([r["diff_excess_lo"] * 100, r["diff_excess_hi"] * 100], [y, y], color=col, lw=2)
        ax.plot(r["diff_excess_mean"] * 100, y, "o", color=col)
        rowsy.append(y)
        days = "" if r["ordinary_days"] == "all" else ", ord. w/o 24-27"
        ylabels.append(f"{r['special']} · {r['variant']}{days} (n={r['n_people']})")
    ax.axvline(0, color=INK2, lw=1)
    ax.set_yticks(rowsy, ylabels, fontsize=8.5)
    ax.set_xlabel("special day minus ordinary days, cross-course share above random (pp)")
    ax.set_title("Within each person: extra cross-course mixing on the special day", loc="left")
    fig.text(0.01, 0.01, note + " · mean and 95% bootstrap interval over people", fontsize=8,
             color=INK2)  # fmt: skip
    fig.tight_layout(rect=(0, 0.03, 1, 1))
    fig.savefig(out / "fig_rhythm_mixing_within_person.png", dpi=180)
    plt.close(fig)

    # 3. Persistence: share of new ties tied again within 3 days, and model odds ratios.
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(11, 4.6), gridspec_kw={"width_ratios": [1, 1.3]})
    r = rates.filter((pl.col("variant") == "main") & (pl.col("origin") == "all"))
    for j, outcome in enumerate(("again_3", "again_any")):
        sub = r.filter(pl.col("outcome") == outcome)
        for k, row in enumerate(sub.iter_rows(named=True)):
            x = j * 4 + k
            a1.bar(x, row["share"] * 100, color=KIND_COLOR[row["kind"]], width=0.8)
            a1.plot([x, x], [row["lo"] * 100, row["hi"] * 100], color=INK, lw=1.5)
    a1.set_xticks([1, 5], ["tied again\nwithin 3 days", "tied again\non any later day"])
    a1.set_ylabel("new ties (%)")
    a1.set_title("New ties seen again, by the day they formed")
    handles = [plt.Rectangle((0, 0), 1, 1, color=KIND_COLOR[k]) for k in KIND_COLOR]
    a1.legend(handles, list(KIND_COLOR), loc="upper left")
    m = models
    for i, row in enumerate(m.iter_rows(named=True)):
        kind = row["term"].removeprefix("formed_")
        a2.plot([row["lo"], row["hi"]], [-i, -i], color=KIND_COLOR[kind], lw=2)
        a2.plot(row["odds_ratio"], -i, "o", color=KIND_COLOR[kind])
    a2.axvline(1, color=INK2, lw=1)
    a2.set_xscale("log")
    a2.set_yticks([-i for i in range(m.height)],
                  [f"{t.removeprefix('formed_')} · {x}" for t, x in zip(m["term"], m["model"],
                                                                         strict=True)],
                  fontsize=8)  # fmt: skip
    a2.set_xlabel("odds ratio, tied again vs ordinary-day ties (log)")
    a2.set_title("Same, adjusted for follow-up day and lag")
    fig.text(0.01, 0.01, note + " · 95% intervals resample people", fontsize=8, color=INK2)
    fig.tight_layout(rect=(0, 0.03, 1, 1))
    fig.savefig(out / "fig_rhythm_persistence.png", dpi=180)
    plt.close(fig)

    # 4. The 24-27 Aug coverage dip, shown.
    cv = coverage.filter(pl.col("day") != ARRIVAL).sort("day")
    labels = [x.strftime("%d") for x in cv["day"]]
    xs = np.arange(len(labels))
    fig, (b1, b2) = plt.subplots(2, 1, figsize=(10, 5.6), sharex=True)
    for ax in (b1, b2):
        _shade_dip(ax, labels)
    b1.plot(xs, cv["own_record_share"].to_numpy() * 100, "o-", color=BLUE,
            label="seen person-time with the tag's own records")  # fmt: skip
    b1.plot(xs, cv["two_sided_share"].to_numpy() * 100, "s-", color=GREEN,
            label="pair-bins logged by both partners")  # fmt: skip
    b1.set_ylabel("%")
    b1.set_ylim(0, 100)
    b1.legend(loc="lower left", fontsize=9)
    b1.set_title("Instrument coverage per day: 24-27 Aug lose own records (grey band)")
    b2.bar(xs, cv["ties"].to_numpy(), color=GRAY, width=0.7)
    b2.set_ylabel("ties (pairs)")
    b2.set_xticks(xs, labels)
    b2.set_xlabel("August")
    fig.text(0.01, 0.01, note + " · bins a tag lost are recovered from its partner's side",
             fontsize=8, color=INK2)  # fmt: skip
    fig.tight_layout(rect=(0, 0.03, 1, 1))
    fig.savefig(out / "fig_rhythm_coverage.png", dpi=180)
    plt.close(fig)


if __name__ == "__main__":
    main()
