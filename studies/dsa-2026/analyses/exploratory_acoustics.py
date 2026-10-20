"""Room sound against press density, the clock held fixed. EXPLORATORY.

Research question: the exploratory acoustics item of ``research/analysis-plan.md``: room loudness
and spectral activity (dining hall, main hall) against press density at the same times. The first
look (``acoustics_presses.py``) held the clock fixed only by recording slot, which spans one to
three hours. Here the clock is held fixed by **hour of the day**, the obvious confound (meals and
plenums happen at fixed times, and both sound and presses follow the day's rhythm), and presses
are modelled **per exposure**. Construct: group sound as an outward trace of collective arousal
`[inferred]`; a press marks a moment the wearer felt moved `[inferred]`. No error control,
two-sided, effect sizes with 95 % intervals, no p-values.

Unit of analysis: one recorder (``audiomoth:mensa``, ``audiomoth:plenum``) per 5-minute bin inside
its scheduled slots. Bins, presses, exposure and room placement are built exactly as in
``acoustics_presses.py`` (its functions are reused): from the self-report instruction to the
handover, without the 14 Aug settings incident, bins with at least 80 % of their seconds, presses
as episodes with accidental chains dropped, lost and unsettled bins removed from presses and
exposure, room placement by the strongest room tag.

Features (each standardised within recorder, so effects are per standard deviation): ``leq_dbfs``
(the primary one), ``l10_dbfs`` (loud moments), ``l90_dbfs`` (background), ``spread_db``
(L10 - L90, how much the level moves within the bin), ``spectral_centroid_hz`` and
``spectral_flatness`` (spectral activity: crowd babble is darker and less noise-like).

Measures: presses (a) **in the room**, among participants placed in the recorder's zone, exposure
their person-time in the room; (b) **camp-wide**, among everyone seen anywhere, exposure their
person-time.

1. **Within-hour correlation.** Spearman of feature and press rate after removing each hour of
   the day's mean rank (``social_energy.rhythm.within_strata_correlation``); intervals resample
   whole recording sessions (a slot on a day).
2. **Rate ratio per SD.** Poisson model of the bin's press count with ``log(person-hours)`` as
   offset, the feature, and one term per hour of the day; standard errors clustered by day.
   Robustness, Leq only: also a term per camp day; only bins with at least five people in the
   room; exposure as the bins in which the tag's own records exist (presses only reach us through
   the tag's own records, so time heard only by others cannot hold a press, which matters most on
   24-27 Aug); without 24-27 Aug; a negative binomial instead of Poisson.

Reporting: aggregates only. Model coefficients pool many bins; figure cells (hour of the day,
quintiles) are shown only when they hold at least ``MIN_GROUP`` distinct people. dBFS is
uncalibrated, so levels compare within a recorder, never between the halls.

Run first: what ``acoustics_presses.py`` needs, and ``exploratory_rhythm.py`` (for the own-record
bins). Then:

    uv run --extra analysis python studies/dsa-2026/analyses/exploratory_acoustics.py

Writes ``acoustics_*.csv``, ``acoustics_summary.json`` and ``fig_acoustics_*.png`` to
``$SOCIAL_ENERGY_DATA/dsa-2026/derived/analyses/exploratory/``.
"""

from __future__ import annotations

import json
import sys
import warnings
from pathlib import Path

import numpy as np
import polars as pl

sys.path.insert(0, str(Path(__file__).parent))
import acoustics_presses as ap
import copresence_by_phase as cp
import exploratory_rhythm as er
import self_report_context as srx

from social_energy import paths
from social_energy.rhythm import within_strata_correlation
from social_energy.spine import Spine
from social_energy.study import StudyConfig

MIN_GROUP = cp.MIN_GROUP
N_BOOT = 2000
SEED = 20261020
FEATURES = {
    "leq_dbfs": "level (Leq)",
    "l10_dbfs": "loud moments (L10)",
    "l90_dbfs": "background (L90)",
    "spread_db": "level spread (L10-L90)",
    "spectral_centroid_hz": "spectral centroid",
    "spectral_flatness": "spectral flatness",
}
PRIMARY = "leq_dbfs"
MEASURES = {"room": "presses in the room", "camp": "presses camp-wide"}
NAME = ap.NAME
COLOR = ap.COLOR


def build_bins(layout, spine, study, own: pl.DataFrame) -> tuple[pl.DataFrame, pl.DataFrame, dict]:
    """One row per recorder bin, with presses and person-bins for each measure and exposure.

    Also returns the room placements (``recorder``, ``bin``, ``entity``) for distinct-people counts.
    """
    participants = {p.ref for p in spine.people if p.role == "participant"}
    reporters = {f"person:{p}" for p in spine.consented("self_report")} & participants
    placed_ok = reporters & {f"person:{p}" for p in spine.consented("beacons")}
    zone_of = {loc.ref: loc.zone for loc in spine.locations}
    qa: dict = {}
    presses, qa["presses"] = srx.press_episodes(layout, spine, participants, reporters)
    lost = srx.lost_bins(layout, spine)
    seen = cp.load_all("seen").filter(pl.col("entity").is_in(reporters)).select("entity", "bin")
    if lost is not None:
        seen = seen.join(lost, on=["entity", "bin"], how="anti")
        presses = presses.join(lost, on=["entity", "bin"], how="anti")
    presses = presses.select("entity", "bin")
    own_seen = seen.join(own.select("entity", "bin"), on=["entity", "bin"], how="semi")
    qa["presses_outside_own_bins"] = presses.join(own_seen, on=["entity", "bin"], how="anti").height
    qa["press_episodes"] = presses.height

    def camp_counts(exposure: pl.DataFrame, suffix: str) -> pl.DataFrame:
        return (
            exposure.group_by("bin")
            .agg(pl.len().alias(f"people_camp{suffix}"))
            .join(
                presses.join(exposure, on=["entity", "bin"], how="semi")
                .group_by("bin")
                .agg(pl.len().alias(f"presses_camp{suffix}")),
                on="bin",
                how="left",
            )
            .with_columns(pl.col(f"presses_camp{suffix}").fill_null(0))
        )

    camp = camp_counts(seen, "").join(camp_counts(own_seen, "_own"), on="bin", how="left")
    rooms = (
        cp.load_all("rooms")
        .filter(pl.col("entity").is_in(placed_ok))
        .with_columns(pl.col("location").replace_strict(zone_of, default=None).alias("zone"))
        .select("entity", "bin", "zone")
        .join(seen, on=["entity", "bin"], how="semi")
    )
    out, placed = [], []
    for rec in ap.recorders(study):
        q = qa.setdefault(rec["recorder"], {})
        ac = ap.acoustic_bins(layout, rec, q)
        here = rooms.filter(pl.col("zone") == rec["zone"]).select("entity", "bin")
        here_own = here.join(own_seen, on=["entity", "bin"], how="semi")
        room = None
        for h, suffix in ((here, ""), (here_own, "_own")):
            r = (
                h.group_by("bin")
                .agg(pl.len().alias(f"people_room{suffix}"))
                .join(
                    presses.join(h, on=["entity", "bin"])
                    .group_by("bin")
                    .agg(pl.len().alias(f"presses_room{suffix}")),
                    on="bin",
                    how="left",
                )
            )
            room = r if room is None else room.join(r, on="bin", how="full", coalesce=True)
        b = (
            ac.join(camp, on="bin", how="left")
            .join(room, on="bin", how="left")
            .with_columns(
                pl.col(
                    "people_room", "presses_room", "people_room_own", "presses_room_own",
                    "people_camp", "presses_camp", "people_camp_own", "presses_camp_own",
                ).fill_null(0),
                (pl.col("l10_dbfs") - pl.col("l90_dbfs")).alias("spread_db"),
                pl.col("bin").dt.convert_time_zone(cp.TZ).dt.hour().alias("hour"),
                cp.camp_day_expr(pl.col("bin")).alias("camp_day"),
            )
            .with_columns(
                pl.concat_str(
                    pl.col("recorder"), pl.col("day").cast(pl.String), pl.col("slot"),
                    separator="|",
                ).alias("session")
            )
        )  # fmt: skip
        out.append(b)
        placed.append(
            here.join(ac.select("bin"), on="bin").with_columns(pl.lit(rec["recorder"]).alias("rec"))
        )
    return pl.concat(out, how="diagonal"), pl.concat(placed), qa


def with_z(b: pl.DataFrame) -> pl.DataFrame:
    return b.with_columns(
        [((pl.col(f) - pl.col(f).mean()) / pl.col(f).std()).alias(f"z_{f}") for f in FEATURES]
    )


def poisson_rr(
    d: pl.DataFrame,
    feature: str,
    measure: str,
    *,
    own: bool = False,
    day_terms: bool = False,
    negbin: bool = False,
) -> dict:
    """Rate ratio per SD of ``feature``, hour-of-day terms, day-clustered standard errors."""
    import statsmodels.api as sm
    from statsmodels.discrete.discrete_model import NegativeBinomial

    suffix = "_own" if own else ""
    count, people = f"presses_{measure}{suffix}", f"people_{measure}{suffix}"
    d = d.filter((pl.col(people) > 0) & pl.col(f"z_{feature}").is_not_null())
    y = d[count].to_numpy().astype(float)
    off = np.log(d[people].to_numpy() * ap.BIN_H)
    cols, names = [np.ones(d.height), d[f"z_{feature}"].to_numpy()], ["const", feature]
    for col in ["hour", *(["camp_day"] if day_terms else [])]:
        levels = sorted(set(d[col].to_list()))[1:]
        v = d[col].to_numpy()
        for lv in levels:
            cols.append((v == lv).astype(float))
            names.append(f"{col}_{lv}")
    x = np.column_stack(cols)
    groups = d["camp_day"].cast(pl.String).to_numpy()
    _, g = np.unique(groups, return_inverse=True)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        if negbin:
            start = np.append(
                sm.GLM(y, x, family=sm.families.Poisson(), offset=off).fit().params, 0.5
            )
            res = NegativeBinomial(y, x, loglike_method="nb2", offset=off).fit(
                start_params=start, method="bfgs", maxiter=5000, disp=0,
                cov_type="cluster", cov_kwds={"groups": g},
            )  # fmt: skip
        else:
            res = sm.GLM(y, x, family=sm.families.Poisson(), offset=off).fit(
                cov_type="cluster", cov_kwds={"groups": g}
            )
    b, se = float(res.params[1]), float(res.bse[1])
    return {
        "rate_ratio_per_sd": float(np.exp(b)),
        "lo": float(np.exp(b - 1.96 * se)),
        "hi": float(np.exp(b + 1.96 * se)),
        "bins": d.height,
        "presses": int(y.sum()),
        "person_hours": float(np.exp(off).sum()),
        "days": len(set(groups)),
    }


def analyse(bins: pl.DataFrame) -> tuple[pl.DataFrame, pl.DataFrame]:
    corr_rows, model_rows = [], []
    for rec in sorted(set(bins["recorder"])):
        d = with_z(bins.filter(pl.col("recorder") == rec))
        for m in MEASURES:
            rate = (
                pl.when(pl.col(f"people_{m}") > 0)
                .then(pl.col(f"presses_{m}") / (pl.col(f"people_{m}") * ap.BIN_H))
            )  # fmt: skip
            dm = d.with_columns(rate.alias("_rate"))
            if m == "room":  # a rate over fewer than five people is not used, as in the first look
                dm = dm.filter(pl.col("people_room") >= MIN_GROUP)
            for f in FEATURES:
                sub = dm.filter(pl.col(f).is_not_null() & pl.col("_rate").is_not_null())
                for label, strata in (
                    ("raw", ["all"] * sub.height),
                    ("within hour", sub["hour"].to_list()),
                ):
                    c = within_strata_correlation(
                        sub[f].to_list(), sub["_rate"].to_list(), strata, sub["session"].to_list(),
                        n_boot=N_BOOT, seed=SEED,
                    )  # fmt: skip
                    corr_rows.append(
                        {"recorder": rec, "measure": m, "feature": f, "comparison": label,
                         "rho": c.r, "lo": c.lo, "hi": c.hi, "bins": c.n, "sessions": c.clusters}
                    )  # fmt: skip
                model_rows.append(
                    {"recorder": rec, "measure": m, "feature": f, "spec": "hour terms"}
                    | poisson_rr(d, f, m)
                )
            specs = {
                "hour + day terms": dict(day_terms=True),
                "exposure: own-record bins": dict(own=True),
                "negative binomial": dict(negbin=True),
            }
            for spec, kw in specs.items():
                model_rows.append(
                    {"recorder": rec, "measure": m, "feature": PRIMARY, "spec": spec}
                    | poisson_rr(d, PRIMARY, m, **kw)
                )
            nodip = d.filter(~pl.col("camp_day").is_in(er.DIP))
            model_rows.append(
                {"recorder": rec, "measure": m, "feature": PRIMARY, "spec": "without 24-27 Aug"}
                | poisson_rr(nodip, PRIMARY, m)
            )
            if m == "room":
                five = d.filter(pl.col("people_room") >= MIN_GROUP)
                model_rows.append(
                    {"recorder": rec, "measure": m, "feature": PRIMARY,
                     "spec": "bins with >= 5 in room"}
                    | poisson_rr(five, PRIMARY, m)
                )  # fmt: skip
    return pl.DataFrame(corr_rows), pl.DataFrame(model_rows)


def hour_profile(bins: pl.DataFrame, placed: pl.DataFrame) -> pl.DataFrame:
    """Per recorder and hour: mean Leq (energy), pooled press rates; small cells blanked."""
    distinct = (
        placed.join(bins.select("bin", "recorder", "hour"), left_on=["bin", "rec"],
                    right_on=["bin", "recorder"])
        .group_by("rec", "hour")
        .agg(pl.col("entity").n_unique().alias("distinct_room"))
        .rename({"rec": "recorder"})
    )  # fmt: skip
    return (
        bins.group_by("recorder", "hour")
        .agg(
            pl.len().alias("bins"),
            ap.energy_mean("leq_dbfs").alias("leq_dbfs"),
            (pl.col("presses_camp").sum() / (pl.col("people_camp").sum() * ap.BIN_H) * 10).alias(
                "rate_camp_10ph"
            ),
            (pl.col("presses_room").sum() / (pl.col("people_room").sum() * ap.BIN_H) * 10).alias(
                "rate_room_10ph"
            ),
            (pl.col("people_room").sum() * ap.BIN_H).alias("person_hours_room"),
        )
        .join(distinct, on=["recorder", "hour"], how="left")
        .with_columns(
            pl.when(pl.col("distinct_room") >= MIN_GROUP).then(pl.col(c)).alias(c)
            for c in ("rate_room_10ph", "person_hours_room", "distinct_room")
        )
        .sort("recorder", "hour")
    )


def quintiles(bins: pl.DataFrame, placed: pl.DataFrame) -> pl.DataFrame:
    """Leq relative to its hour (minus the recorder-hour mean) in quintiles; pooled press rates."""
    d = bins.with_columns(
        (pl.col("leq_dbfs") - pl.col("leq_dbfs").mean().over("recorder", "hour")).alias("leq_rel")
    ).with_columns(
        (pl.col("leq_rel").rank("ordinal").over("recorder") * 5
         / pl.len().over("recorder")).ceil().cast(pl.Int32).alias("quintile")
    )  # fmt: skip
    distinct = (
        placed.join(d.select("bin", "recorder", "quintile"), left_on=["bin", "rec"],
                    right_on=["bin", "recorder"])
        .group_by("rec", "quintile")
        .agg(pl.col("entity").n_unique().alias("distinct_room"))
        .rename({"rec": "recorder"})
    )  # fmt: skip
    return (
        d.group_by("recorder", "quintile")
        .agg(
            pl.len().alias("bins"),
            pl.col("leq_rel").mean().alias("leq_rel_db"),
            (pl.col("presses_camp").sum() / (pl.col("people_camp").sum() * ap.BIN_H) * 10).alias(
                "rate_camp_10ph"
            ),
            (pl.col("presses_room").sum() / (pl.col("people_room").sum() * ap.BIN_H) * 10).alias(
                "rate_room_10ph"
            ),
        )
        .join(distinct, on=["recorder", "quintile"], how="left")
        .with_columns(
            pl.when(pl.col("distinct_room") >= MIN_GROUP)
            .then(pl.col("rate_room_10ph"))
            .alias("rate_room_10ph")
        )
        .sort("recorder", "quintile")
    )


def main() -> None:
    study = StudyConfig.load(cp.STUDY_YAML)
    layout = paths.study(cp.STUDY)
    spine = Spine.load(layout.spine)
    out = er.out_dir()
    own_file = out / "own_record_bins.parquet"
    if not own_file.exists():
        raise SystemExit("run exploratory_rhythm.py first (own_record_bins.parquet)")
    own = pl.read_parquet(own_file)
    bins, placed, qa = build_bins(layout, spine, study, own)
    corr, models = analyse(bins)
    hours = hour_profile(bins, placed)
    quint = quintiles(bins, placed)
    corr.write_csv(out / "acoustics_within_hour_correlations.csv")
    models.write_csv(out / "acoustics_rate_ratios.csv")
    hours.write_csv(out / "acoustics_hour_profile.csv")
    quint.write_csv(out / "acoustics_leq_quintiles.csv")
    qa |= {
        "exploratory": True,
        "bins": bins.group_by("recorder").len().to_dicts(),
        "sessions": bins.group_by("recorder").agg(pl.col("session").n_unique()).to_dicts(),
        "bins_with_5_in_room": bins.filter(pl.col("people_room") >= MIN_GROUP)
        .group_by("recorder")
        .len()
        .to_dicts(),
    }
    (out / "acoustics_summary.json").write_text(json.dumps(qa, indent=2, default=str))
    figures(corr, models, hours, quint, out)
    with pl.Config(tbl_rows=300, tbl_cols=20, tbl_width_chars=250):
        print(json.dumps(qa, indent=2, default=str))
        print(corr.filter(pl.col("feature") == PRIMARY))
        print(models)
        print(hours)
        print(quint)
        print(corr.filter(pl.col("comparison") == "within hour"))


# ---- figures ----------------------------------------------------------------------------------


def figures(corr, models, hours, quint, out: Path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    er._style(plt)
    note = "EXPLORATORY · DSA 2026 · aggregates only · dBFS uncalibrated (compare within a hall)"

    # 1. The confound: level and press rate by hour of day.
    fig, axes = plt.subplots(2, 2, figsize=(11, 6), sharex="col")
    for j, rec in enumerate(("mensa", "plenum")):
        h = hours.filter(pl.col("recorder") == rec)
        axes[0, j].plot(h["hour"], h["leq_dbfs"], "o-", color=COLOR[rec])
        axes[0, j].set_title(NAME[rec])
        axes[0, j].set_ylabel("Leq (dBFS)")
        axes[1, j].plot(h["hour"], h["rate_camp_10ph"], "o-", color=ap.INK2, label="camp-wide")
        axes[1, j].plot(h["hour"], h["rate_room_10ph"], "s-", color=COLOR[rec], label="in the hall")
        axes[1, j].set_ylabel("presses / 10 person-h")
        axes[1, j].set_xlabel("hour of day (recorded slots only)")
        axes[1, j].legend(fontsize=9)
    fig.suptitle("Both sound and presses follow the clock: the confound held fixed below")
    fig.text(0.01, 0.01, note, fontsize=8, color=ap.INK2)
    fig.tight_layout(rect=(0, 0.03, 1, 1))
    fig.savefig(out / "fig_acoustics_hour_profile.png", dpi=180)
    plt.close(fig)

    # 2. Rate ratio per SD, hour terms, every feature; and Leq robustness.
    main = models.filter(pl.col("spec") == "hour terms")
    fig, axes = plt.subplots(1, 2, figsize=(12, 5.2), sharey=True)
    feats = list(FEATURES)
    for j, m in enumerate(MEASURES):
        ax = axes[j]
        for k, rec in enumerate(("mensa", "plenum")):
            r = main.filter((pl.col("recorder") == rec) & (pl.col("measure") == m))
            for row in r.iter_rows(named=True):
                y = -feats.index(row["feature"]) + (0.15 if k == 0 else -0.15)
                ax.plot([row["lo"], row["hi"]], [y, y], color=COLOR[rec], lw=2)
                ax.plot(row["rate_ratio_per_sd"], y, "o", color=COLOR[rec],
                        label=NAME[rec] if row["feature"] == PRIMARY else None)  # fmt: skip
        ax.axvline(1, color=ap.INK2, lw=1)
        ax.set_xscale("log")
        ax.set_title(MEASURES[m])
        ax.set_xlabel("press rate ratio per SD of the feature")
        ax.set_yticks([-i for i in range(len(feats))], [FEATURES[f] for f in feats])
    handles, labels = axes[0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="upper right", fontsize=9)
    fig.suptitle("Within the same hour of day, does a louder or busier room carry more presses?")
    fig.text(0.01, 0.01, note + " · Poisson, offset person-hours, hour-of-day terms, "
             "95% CI clustered by day", fontsize=8, color=ap.INK2)  # fmt: skip
    fig.tight_layout(rect=(0, 0.03, 1, 1))
    fig.savefig(out / "fig_acoustics_rate_ratios.png", dpi=180)
    plt.close(fig)

    # 3. Leq relative to its hour, in quintiles, against pooled press rates.
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.4), sharey=True)
    for j, rec in enumerate(("mensa", "plenum")):
        q = quint.filter(pl.col("recorder") == rec)
        ax = axes[j]
        ax.plot(q["leq_rel_db"], q["rate_camp_10ph"], "o-", color=ap.INK2, label="camp-wide")
        ax.plot(q["leq_rel_db"], q["rate_room_10ph"], "s-", color=COLOR[rec], label="in the hall")
        ax.set_title(NAME[rec])
        ax.set_xlabel("Leq relative to the same hour's mean (dB), quintile means")
        ax.legend(fontsize=9)
    axes[0].set_ylabel("presses / 10 person-h")
    fig.suptitle("Louder than usual for the hour: press rates by quintile")
    fig.text(0.01, 0.01, note, fontsize=8, color=ap.INK2)
    fig.tight_layout(rect=(0, 0.03, 1, 1))
    fig.savefig(out / "fig_acoustics_leq_quintiles.png", dpi=180)
    plt.close(fig)


if __name__ == "__main__":
    main()
