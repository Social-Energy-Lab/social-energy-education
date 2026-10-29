"""EDA second pass, A: social dose. Is a person's arousal different when more people are close,
when the people close are familiar, or when they come from another course?

``docs/plans/ongoing/eda-second-pass.md``, analysis A. **Every result here is exploratory**
under the frozen analysis plan: no error control, two-sided, effects with 95 % intervals and no
p-values, cells of fewer than ``MIN_GROUP`` people withheld. Every estimate is made three times,
on the **discovery** days, the **replication** days and all days (``eda_split``), and carries the
plan's ``verdict`` from the two halves. Only "replicates" is read as a lead.

**Data.** The first pass's minutes (``exploratory_eda.load_person_minutes``, ``minutes_for``):
participants with ``eda`` consent, minutes outside exclusion windows, usable minutes and HR
minutes, measures standardised within person-day, both clock variants (``all`` primary,
``certain`` sensitivity). Of these, participants who also have ``beacons`` consent, in minutes
whose 5-minute beacon bin is an **exposure bin** of theirs: their tag was seen in the bin
(``copresence_by_phase`` ``seen``) and the bin is not in a lost or unsettled window
(``outcomes.removed_bins``). A minute without beacon information is left out, not counted as
alone. Partners are participants with ``beacons`` consent (``copresence_by_phase`` ``pairs``).

**Definitions.**

* **Close** partner in a bin: the pair's strongest reading in the bin is at least
  ``CLOSE_RSSI`` (``copresence_by_phase.CLOSE_RSSI``); **heard**: any weaker reading.
* **Dose level** of a minute, from its bin: ``0`` (nobody heard), ``heard only`` (partners heard,
  none close), ``1``, ``2-3``, ``4-7``, ``8+`` close partners. Reference: ``0``.
* **Dose slope**: log(1 + close partners), with a ``heard only`` indicator alongside so that the
  slope starts from nobody heard.
* **Familiar share**, in minutes with at least one close partner: the share of close partners
  already **tied** with the person on an earlier camp day (close for at least
  ``copresence_by_phase.TIE_MIN_BINS`` bins that day; beacon camp days, the first pass's
  ``day``). The dose slope term is in the model, so the share is compared at a given dose.
* **Other-course share**, in the same minutes: the share of close partners whose course (spine)
  differs from the person's, among partners with a known course; also with the dose term.
  Familiar partners are often from the same course, so a check beyond the plan (``both
  shares``) puts the two shares in one model, on the minutes of the other-course share.
* **Setting**: as in the first pass (``exploratory_presses.placed_settings`` on the exposure
  bins: plenum, course block, meal time, other daytime, evening); reference ``course block``.

**Models.** Fixed effects per person-day, standard errors clustered by person
(``stats.within_ols``), minute level. Outcomes: SCR rate (main and amp >= 0.2 µS), tonic level
and heart rate, each standardised within person-day (``z_pd_*``) on its own minutes (usable
minutes for EDA, HR minutes for heart rate). ``MODELS``: movement (the measure's own movement
z-score and its square, as the first pass's "movement" adjustment) plus clock hour and wear-time
bands (``exploratory_eda.time_terms``); the same plus setting. Effects are in within-person-day
SD units. An estimate is withheld when fewer than ``MIN_GROUP`` people have a person-day in which
its term varies (the people who identify it).

**Halves.** A minute's half comes from its EDA camp day (04:00-04:00 local,
``eda_split.camp_day``); the fixed effects use the first pass's person-day. Both day
definitions agree for daytime wear (``qa.json`` counts any minute where they differ). The
verdict compares discovery and replication within the same clock variant: the ``all`` verdict
is the one the plan reads, the ``certain`` one is a sensitivity.

**Per person-day dose slopes** (``person_day_dose.csv``, private, for analysis G): per person-day
on the ``all`` clock, the least-squares slope of the movement-adjusted SCR rate (``r_pd_*``,
amp >= 0.2 µS, and the main rule) on log(1 + close partners), with its minutes, the spread of
the exposure and the slope's standard error. Nothing in the other outputs is per person.

Run after ``social-energy ingest-eda``, ``social-energy eda-heart-rate``,
``copresence_by_phase.py build`` and ``beacon_diagnostics.py``:

    uv run --extra analysis python studies/dsa-2026/analyses/eda2_social_dose.py

Writes ``estimates.csv``, ``verdicts.csv``, ``levels.csv``, ``person_day_dose.csv``,
``qa.json`` and ``fig_social_dose.png`` to
``$SOCIAL_ENERGY_DATA/dsa-2026/derived/analyses/exploratory/eda2/social_dose/``.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import polars as pl

sys.path.insert(0, str(Path(__file__).parent))
import copresence_by_phase as cp
import eda_split as split
import exploratory_eda as ee
import exploratory_presses as xp
import outcomes as oc

from social_energy import paths
from social_energy.spine import Spine
from social_energy.stats import within_ols

SLUG = "exploratory/eda2/social_dose"
MIN_GROUP = 5
CLOSE_RSSI = cp.CLOSE_RSSI
TIE_MIN_BINS = cp.TIE_MIN_BINS
OUTCOMES = ("scr_main", "scr_amp02", "tonic", "hr")
LEVELS = ("0", "heard only", "1", "2-3", "4-7", "8+")
MODELS = ("movement + time", "movement + time + setting")
SETTING_REF = "course block"
#: Exposures: the terms reported, and which minutes each is estimated on.
EXPOSURES = ("dose level", "dose slope", "familiar share", "other-course share", "both shares")
PERSON_DAY_RULES = ("amp02", "main")


def out_dir() -> Path:
    d = paths.study(cp.STUDY).derived / "analyses" / SLUG
    d.mkdir(parents=True, exist_ok=True)
    return d


# --- beacon side ---------------------------------------------------------------------------------


def first_ties(pairs: pl.DataFrame) -> pl.DataFrame:
    """``a``, ``b``, ``first_tie``: the first camp day each pair was tied (close in at least
    ``TIE_MIN_BINS`` bins of that day). ``pairs`` has ``a``, ``b``, ``bin``, ``day``,
    ``max_rssi``."""
    return (
        pairs.filter(pl.col("max_rssi") >= CLOSE_RSSI)
        .group_by("a", "b", "day")
        .agg(pl.col("bin").n_unique().alias("bins"))
        .filter(pl.col("bins") >= TIE_MIN_BINS)
        .group_by("a", "b")
        .agg(pl.col("day").min().alias("first_tie"))
    )


def dose_level(n_close: pl.Expr, n_heard: pl.Expr) -> pl.Expr:
    """``LEVELS`` from the close and heard partner counts of a bin."""
    return (
        pl.when(n_close >= 8).then(pl.lit("8+"))
        .when(n_close >= 4).then(pl.lit("4-7"))
        .when(n_close >= 2).then(pl.lit("2-3"))
        .when(n_close == 1).then(pl.lit("1"))
        .when(n_heard > 0).then(pl.lit("heard only"))
        .otherwise(pl.lit("0"))
    )  # fmt: skip


def exposure_bins(
    seen: pl.DataFrame,
    pairs: pl.DataFrame,
    removed: pl.DataFrame,
    *,
    people: set[str],
    partners: set[str],
    course: dict[str, str],
) -> pl.DataFrame:
    """One row per exposure bin of each of ``people``: ``entity``, ``bin``, ``day``, ``phase``,
    ``n_heard``, ``n_close``, ``n_familiar`` (close partners tied on an earlier day),
    ``n_course_known`` and ``n_other_course`` (close partners with a known course, and those
    from another course than the person's; both null when the person's course is unknown),
    ``dose_level``, ``log_dose``, ``heard_only``, ``familiar_share``, ``other_course_share``.

    ``seen`` has ``entity``, ``bin``, ``day``, ``phase``; ``pairs`` has ``a``, ``b``, ``bin``,
    ``day``, ``max_rssi``; ``removed`` has ``entity``, ``bin`` (bins a tag could not report).
    Only ``partners`` count as partners and ties."""
    partners_l = list(partners)
    p = pairs.filter(pl.col("a").is_in(partners_l) & pl.col("b").is_in(partners_l))
    ties = first_ties(p)
    ends = pl.concat([
        p.select(pl.col("a").alias("entity"), pl.col("b").alias("other"), "bin", "day",
                 "max_rssi"),
        p.select(pl.col("b").alias("entity"), pl.col("a").alias("other"), "bin", "day",
                 "max_rssi"),
    ]).filter(pl.col("entity").is_in(list(people)))  # fmt: skip
    t2 = pl.concat([ties, ties.select(pl.col("b").alias("a"), pl.col("a").alias("b"),
                                      "first_tie")])  # fmt: skip
    course_df = pl.DataFrame(
        {"e": list(course), "c": list(course.values())}, schema={"e": pl.String, "c": pl.String}
    )
    ends = (
        ends.join(t2.rename({"a": "entity", "b": "other"}), on=["entity", "other"], how="left")
        .join(course_df.rename({"e": "entity", "c": "own"}), on="entity", how="left")
        .join(course_df.rename({"e": "other", "c": "theirs"}), on="other", how="left")
    )
    close = pl.col("max_rssi") >= CLOSE_RSSI
    known = pl.col("own").is_not_null() & pl.col("theirs").is_not_null()
    agg = ends.group_by("entity", "bin").agg(
        pl.len().alias("n_heard"),
        close.sum().alias("n_close"),
        (close & (pl.col("first_tie") < pl.col("day")).fill_null(False)).sum().alias("n_familiar"),
        (close & known).sum().alias("n_course_known"),
        (close & known & (pl.col("own") != pl.col("theirs"))).sum().alias("n_other_course"),
    )
    base = (
        seen.filter(pl.col("entity").is_in(list(people)))
        .select("entity", "bin", "day", "phase")
        .unique(["entity", "bin"])
        .join(removed.select("entity", "bin"), on=["entity", "bin"], how="anti")
    )
    has_course = pl.col("entity").is_in(list(course))
    out = base.join(agg, on=["entity", "bin"], how="left").with_columns(
        pl.col("n_heard", "n_close", "n_familiar").fill_null(0).cast(pl.Int64),
        *[
            pl.when(has_course).then(pl.col(c).fill_null(0).cast(pl.Int64)).alias(c)
            for c in ("n_course_known", "n_other_course")
        ],
    )
    return out.with_columns(
        dose_level(pl.col("n_close"), pl.col("n_heard")).alias("dose_level"),
        pl.col("n_close").cast(pl.Float64).log1p().alias("log_dose"),
        ((pl.col("n_close") == 0) & (pl.col("n_heard") > 0)).cast(pl.Float64).alias("heard_only"),
        pl.when(pl.col("n_close") > 0)
        .then(pl.col("n_familiar") / pl.col("n_close"))
        .alias("familiar_share"),
        pl.when(pl.col("n_course_known") > 0)
        .then(pl.col("n_other_course") / pl.col("n_course_known"))
        .alias("other_course_share"),
    ).sort("entity", "bin")


# --- models --------------------------------------------------------------------------------------


def _design(d: pl.DataFrame, exposure: str) -> tuple[list[np.ndarray], list[str], list[str]]:
    """Exposure columns, their names, and the names that are reported."""
    if exposure == "dose level":
        levels = list(LEVELS[1:])
        v = d["dose_level"].to_numpy()
        cols = [np.column_stack([(v == lv).astype(float) for lv in levels])]
        return cols, levels, levels
    if exposure == "dose slope":
        x = d.select("log_dose", "heard_only").to_numpy()
        return [x], ["log_dose", "heard_only"], ["log_dose"]
    if exposure == "both shares":
        cols = ["familiar_share", "other_course_share"]
        return [d.select(*cols, "log_dose").to_numpy()], [*cols, "log_dose"], cols
    share = {"familiar share": "familiar_share", "other-course share": "other_course_share"}
    s = share[exposure]
    return [d.select(s, "log_dose").to_numpy()], [s, "log_dose"], [s]


def _sample(d: pl.DataFrame, exposure: str) -> pl.DataFrame:
    if exposure == "familiar share":
        return d.filter(pl.col("n_close") > 0)
    if exposure in ("other-course share", "both shares"):
        return d.filter(pl.col("other_course_share").is_not_null())
    return d


def _term_column(d: pl.DataFrame, exposure: str, term: str) -> pl.Expr:
    if exposure == "dose level":
        return (pl.col("dose_level") == term).cast(pl.Float64)
    return pl.col(term)


def informative_people(d: pl.DataFrame, x: pl.Expr) -> int:
    """People with at least one person-day in which ``x`` varies."""
    v = (
        d.select("entity", "day", x.alias("_x"))
        .group_by("entity", "day")
        .agg((pl.col("_x").max() - pl.col("_x").min()).alias("spread"))
    )
    return v.filter(pl.col("spread") > 1e-12)["entity"].n_unique()


def dose_models(d_all: pl.DataFrame, *, measures=OUTCOMES) -> list[dict]:
    """Every exposure under every model for every measure on one half's minutes (``d_all``:
    minutes joined to their exposure bin, with ``setting``)."""
    rows = []
    for x in measures:
        valid = "hr_ok" if x == "hr" else "usable"
        y_col = f"z_pd_{x}"
        d_x = d_all.filter(pl.col(valid) & pl.col(y_col).is_not_null() & pl.col(y_col).is_finite())
        mv = f"z_pd_{ee.motion_of(x)}"
        for exposure in EXPOSURES:
            d = _sample(d_x, exposure)
            if d.height == 0:
                continue
            ecols, enames, report = _design(d, exposure)
            motion = d.select(mv, f"{mv}2").fill_null(np.nan).to_numpy()
            timex = ee.time_terms(d)
            setting_levels = sorted(set(d["setting"].to_list()) - {SETTING_REF})
            sv = d["setting"].to_numpy()
            setx = (np.column_stack([(sv == lv).astype(float) for lv in setting_levels])
                    if setting_levels else np.zeros((d.height, 0)))  # fmt: skip
            absorb = (d["entity"] + "|" + d["day"].cast(pl.String)).to_numpy()
            y = d[y_col].to_numpy()
            for model in MODELS:
                cols = [*ecols, motion, timex]
                names = [*enames, "motion", "motion2",
                         *[f"time_{i}" for i in range(timex.shape[1])]]  # fmt: skip
                if model.endswith("setting"):
                    cols.append(setx)
                    names += [f"setting_{lv}" for lv in setting_levels]
                coefs = {c.name: c for c in within_ols(y, np.column_stack(cols), names,
                                                       absorb=absorb,
                                                       cluster=d["entity"].to_numpy())}  # fmt: skip
                for term in report:
                    c = coefs[term]
                    people = informative_people(d, _term_column(d, exposure, term))
                    small = people < MIN_GROUP
                    if exposure == "dose level":
                        minutes = int((d["dose_level"] == term).sum())
                    else:
                        minutes = d.height
                    rows.append({
                        "outcome": x, "exposure": exposure, "term": term, "model": model,
                        "reference": "0" if exposure == "dose level" else None,
                        "people": None if small else people,
                        "minutes": None if small else minutes,
                        "estimate_sd": None if small else c.estimate,
                        "lo": None if small else c.lo, "hi": None if small else c.hi,
                        "clusters": c.clusters, "suppressed": small,
                    })  # fmt: skip
    return rows


KEY = ["clock", "outcome", "exposure", "term", "model"]


def with_verdicts(est: pl.DataFrame) -> tuple[pl.DataFrame, pl.DataFrame]:
    """``est`` (one row per half and ``KEY``) with ``verdict`` from its discovery and
    replication rows, and the wide table: one row per ``KEY`` with each half's estimate and
    interval and the verdict."""
    wide = None
    for half in split.HALVES:
        h = est.filter(pl.col("half") == half).select(
            *KEY,
            *[pl.col(c).alias(f"{c}_{half}") for c in ("estimate_sd", "lo", "hi", "people")],
        )
        wide = h if wide is None else wide.join(h, on=KEY, how="full", coalesce=True)
    verdicts = [
        split.verdict(r["estimate_sd_discovery"], r["lo_discovery"], r["hi_discovery"],
                      r["estimate_sd_replication"], r["lo_replication"], r["hi_replication"])
        for r in wide.iter_rows(named=True)
    ]  # fmt: skip
    wide = wide.with_columns(pl.Series("verdict", verdicts, dtype=pl.String)).sort(KEY)
    return est.join(wide.select(*KEY, "verdict"), on=KEY, how="left"), wide


# --- per person-day slopes -----------------------------------------------------------------------


def person_day_slopes(d: pl.DataFrame, y: str, x: str = "log_dose") -> pl.DataFrame:
    """Per ``entity`` and ``day``: least-squares slope of ``y`` on ``x`` with its standard error
    (null when ``x`` does not vary or fewer than three minutes), ``minutes`` and ``x_sd``."""
    v = d.filter(pl.col(y).is_not_null() & pl.col(y).is_finite() & pl.col(x).is_not_null())
    g = v.group_by("entity", "day").agg(
        pl.len().alias("minutes"),
        pl.col(x).mean().alias("_mx"),
        pl.col(y).mean().alias("_my"),
        ((pl.col(x) - pl.col(x).mean()) ** 2).sum().alias("_sxx"),
        ((pl.col(x) - pl.col(x).mean()) * (pl.col(y) - pl.col(y).mean())).sum().alias("_sxy"),
        ((pl.col(y) - pl.col(y).mean()) ** 2).sum().alias("_syy"),
    )
    ok = (pl.col("_sxx") > 1e-12) & (pl.col("minutes") >= 3)
    slope = pl.col("_sxy") / pl.col("_sxx")
    rss = (pl.col("_syy") - pl.col("_sxy") ** 2 / pl.col("_sxx")).clip(lower_bound=0)
    se = (rss / (pl.col("minutes") - 2) / pl.col("_sxx")).sqrt()
    return (
        g.with_columns(
            pl.when(ok).then(slope).alias("slope"),
            pl.when(ok).then(se).alias("se"),
            (pl.col("_sxx") / (pl.col("minutes") - 1)).sqrt().alias("x_sd"),
        )
        .select("entity", "day", "minutes", "x_sd", "slope", "se")
        .sort("entity", "day")
    )


def person_day_table(j: pl.DataFrame) -> pl.DataFrame:
    """Per person-day slopes of the movement-adjusted SCR rate on log(1 + close partners), both
    rules, on usable exposure minutes, with the day's half."""
    use = j.filter(pl.col("usable"))
    out = None
    for rule in PERSON_DAY_RULES:
        s = person_day_slopes(use, f"r_pd_scr_{rule}").rename(
            {"minutes": f"minutes_{rule}", "x_sd": f"x_sd_{rule}", "slope": f"slope_scr_{rule}",
             "se": f"se_scr_{rule}"}
        )  # fmt: skip
        out = s if out is None else out.join(s, on=["entity", "day"], how="full", coalesce=True)
    close_share = use.group_by("entity", "day").agg(
        (pl.col("n_close") > 0).mean().alias("share_minutes_close"),
        pl.col("log_dose").mean().alias("mean_log_dose"),
    )
    return (
        out.join(close_share, on=["entity", "day"], how="left")
        .with_columns(split.half_of(pl.col("day")).alias("half"))
        .select("entity", "day", "half", pl.exclude("entity", "day", "half"))
        .sort("entity", "day")
    )


# --- main ----------------------------------------------------------------------------------------


def join_exposure(m: pl.DataFrame, expo: pl.DataFrame) -> pl.DataFrame:
    """Usable or HR minutes of ``m`` in an exposure bin, with the exposure, setting and the
    minute's EDA camp day (``split_day``) and half."""
    return (
        m.filter(pl.col("usable") | pl.col("hr_ok"))
        .join(expo.drop("day", "phase"), on=["entity", "bin"], how="inner")
        .with_columns(split.camp_day(pl.col("minute")).alias("split_day"))
        .with_columns(split.half_of(pl.col("split_day")).alias("half"))
    )


def main() -> None:
    import resource
    import time

    t0 = time.time()
    layout = paths.study(cp.STUDY)
    spine = Spine.load(layout.spine)
    out = out_dir()
    participants = {p.ref for p in spine.people if p.role == "participant"}
    beacon_ok = {f"person:{p}" for p in spine.consented("beacons")}
    eda_ok = {f"person:{p}" for p in spine.consented("eda")}
    people = participants & beacon_ok & eda_ok
    partners = participants & beacon_ok

    pm, counts = ee.load_person_minutes(layout, spine)
    pm = pm.filter(pl.col("entity").is_in(list(people)))
    seen = cp.load_all("seen").filter(pl.col("entity").is_in(list(people)))
    pairs = cp.load_all("pairs").select("a", "b", "bin", "day", "max_rssi")
    removed = oc.removed_bins(spine)
    expo = exposure_bins(seen, pairs, removed, people=people, partners=partners,
                         course=cp.course_of(spine))  # fmt: skip
    del pairs
    placed = xp.placed_settings(expo.select("entity", "bin", "day", "phase"), spine)
    expo = expo.join(placed.select("entity", "bin", "setting"), on=["entity", "bin"], how="left")

    qa: dict = {
        "people_eda_and_beacons": len(people),
        "partners_beacons": len(partners),
        "exposure_bins": expo.height,
        "exposure_people": expo["entity"].n_unique(),
        "exposure_bins_by_level": dict(expo["dose_level"].value_counts().iter_rows()),
    }
    est_rows, level_frames = [], []
    pdd = None
    for clock in ee.CLOCKS:
        m, mqa = ee.minutes_for(pm, counts, clock)
        j = join_exposure(m, expo)
        del m
        cq = {
            "minutes": mqa,
            "joined_usable": int(j["usable"].sum()),
            "joined_usable_people": j.filter("usable")["entity"].n_unique(),
            "joined_hr": int(j["hr_ok"].sum()),
            "joined_hr_people": j.filter("hr_ok")["entity"].n_unique(),
            "minutes_outside_halves": int(j["half"].is_null().sum()),
            "minutes_split_day_ne_person_day": int((j["split_day"] != j["day"]).sum()),
            "by_half": {},
        }
        for half in split.HALVES:
            h = split.subset(j, half, day_col="split_day")
            cq["by_half"][half] = {
                "usable_minutes": int(h["usable"].sum()),
                "usable_people": h.filter("usable")["entity"].n_unique(),
                "hr_minutes": int(h["hr_ok"].sum()),
                "hr_people": h.filter("hr_ok")["entity"].n_unique(),
                "usable_with_company": int((h["usable"] & (h["n_close"] > 0)).sum()),
            }
            est_rows += [r | {"clock": clock, "half": half} for r in dose_models(h)]
            lv = ee.level_means(h, "dose_level")
            level_frames.append(lv.with_columns(pl.lit(clock).alias("clock"),
                                                pl.lit(half).alias("half")))  # fmt: skip
            print(clock, half, round(time.time() - t0), "s", flush=True)
        if clock == "all":
            pdd = person_day_table(j)
        qa[clock] = cq
        del j

    est = pl.DataFrame(est_rows, infer_schema_length=None)
    est, wide = with_verdicts(est)
    est.sort([*KEY, "half"]).write_csv(out / "estimates.csv")
    wide.write_csv(out / "verdicts.csv")
    pl.concat(level_frames, how="diagonal_relaxed").write_csv(out / "levels.csv")
    pdd.write_csv(out / "person_day_dose.csv")
    qa["person_day_dose"] = {
        "person_days": pdd.height,
        "with_slope_amp02": int(pdd["slope_scr_amp02"].is_not_null().sum()),
    }
    qa["verdicts_all_clock"] = dict(
        wide.filter(pl.col("clock") == "all")["verdict"].value_counts().iter_rows()
    )
    qa["settings_used"] = {"close_rssi": CLOSE_RSSI, "tie_min_bins": TIE_MIN_BINS,
                           "levels": LEVELS, "models": MODELS, "min_group": MIN_GROUP,
                           "min_clean_s": ee.MIN_CLEAN_S, "rules": ee.RULES,
                           "hr_min_quality": ee.HR_MIN_QUALITY, "clocks": ee.CLOCKS,
                           "discovery": split.DISCOVERY,
                           "replication": split.REPLICATION}  # fmt: skip
    qa["runtime_s"] = round(time.time() - t0, 1)
    qa["peak_rss_mb"] = round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 1)
    (out / "qa.json").write_text(json.dumps(qa, indent=2, default=str), encoding="utf-8")
    figure(est.filter((pl.col("clock") == "all") & (pl.col("model") == MODELS[0])), out)
    print(json.dumps(qa, indent=2, default=str))


def figure(est: pl.DataFrame, out: Path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    ee._style(plt)
    colours = {"discovery": ee.BLUE, "replication": ee.ORANGE, "all": ee.INK2}
    fig, axes = plt.subplots(1, len(OUTCOMES), figsize=(16, 3.8), sharey=True)
    terms = list(LEVELS[1:])
    for ax, x in zip(axes, OUTCOMES, strict=True):
        q = est.filter((pl.col("outcome") == x) & (pl.col("exposure") == "dose level")
                       & ~pl.col("suppressed"))  # fmt: skip
        for k, half in enumerate(split.HALVES):
            h = q.filter(pl.col("half") == half)
            for i, t in enumerate(terms):
                r = h.filter(pl.col("term") == t)
                if r.height == 0:
                    continue
                xx = i + (k - 1) * 0.22
                ax.plot([xx, xx], [r["lo"][0], r["hi"][0]], color=colours[half], lw=1.6)
                ax.plot(xx, r["estimate_sd"][0], "o", ms=4, color=colours[half],
                        label=half if i == 0 else None)  # fmt: skip
        ax.axhline(0, color=ee.INK2, lw=0.8)
        ax.set_xticks(range(len(terms)), terms)
        ax.set_title(ee.LABEL.get(x, x), loc="left", fontsize=10)
        ax.set_xlabel("close partners in the 5-min bin (vs nobody heard)")
    axes[0].set_ylabel("within person-day SD")
    axes[0].legend(fontsize=8)
    fig.text(0.01, 0.01, "EXPLORATORY · DSA 2026 · aggregates only · movement + clock hour + "
             "wear time · 95% CI clustered by person", fontsize=8, color=ee.INK2)  # fmt: skip
    fig.tight_layout(rect=(0, 0.04, 1, 1))
    fig.savefig(out / "fig_social_dose.png", dpi=170)
    plt.close(fig)


if __name__ == "__main__":
    main()
