"""Exploratory tier, EDA: arousal around presses, by programme setting, and between co-present
wearers.

``research/analysis-plan.md`` (frozen 2026-10-19), section "Exploratory analyses", item "EDA".
**Every result here is exploratory**: no error control, two-sided, effects with 95% intervals and
no p-values, distributions rather than people, cells of fewer than ``MIN_GROUP`` people withheld.
Construct: phasic skin conductance as bodily arousal, one candidate trace of being moved or of
shared intensity `[inferred: our reading, not signed off by the research team]`.

**Data.** ``derived/eda/person_minutes.parquet`` from ``social-energy ingest-eda`` (participants
with ``eda`` consent, resolved through the spine; minutes in an exclusion window are dropped
here), ``derived/eda/scr.parquet`` for the sensitivity rule, and ``derived/eda/hr_minutes.parquet``
from ``social-energy eda-heart-rate`` (heart rate from the raw PPG, joined by device and minute
with ``eda.heart.with_heart_rate``). A minute is **usable** when it holds at least ``MIN_CLEAN_S``
worn seconds without an artifact. Measures per usable minute:

* SCR rate: clean SCRs (onset in the minute, not touching an artifact) per clean minute
  (count x 60 / clean seconds), under two rules decided on 2026-10-21: **main**, every
  detection (trough to peak at least 0.05 µS, rise 0.5-5 s), and **amp >= 0.2**, the same
  detections with amplitude at least 0.2 µS. Every result is reported under both.
* SCR amplitude: log of the mean amplitude of the minute's SCRs (under each rule; missing in a
  minute without one).
* Tonic level: log of the mean conductance of the clean seconds (the same under both rules).
* Movement: log of the mean per-second accelerometer SD, the covariate.

**Heart rate, a secondary outcome.** An **HR minute** is a worn minute outside exclusions with
good-quality PPG heart rate (``hr_quality`` at least ``HR_MIN_QUALITY``: at least one good 10-s
window, ``hr_ppg_bpm`` their median) and some movement; it need not be EDA-usable (the PPG and
the electrodes fail for different reasons). HR (bpm) gets the same treatment as the EDA
measures: standardised within person-day (within person for the day contrast), adjusted for
movement over the HR minutes, in (a), (b) and (c).

**Clocks.** Every analysis runs twice (``CLOCKS``): on all minutes (**all**, the primary), and
restricted to minutes whose device clock was measured (**certain**: ``clock_uncertain`` false,
and for heart rate ``hr_clock_uncertain`` false too), a sensitivity. At minute resolution the
fallback clocks (``clock_source`` ``rate``) are mostly within seconds to tens of seconds after
the clock correction, so they stay in the primary. Each output row carries ``clock``. Nothing
here is finer than a minute.

**Each person against themselves.** Tonic level differs between people by an order of magnitude,
and electrodes are put on afresh each day, so every measure is standardised within person-day
(``z_pd``) for (a), (b) and (c); for the day contrast in (b) the SCR measures and HR are
standardised within person (``z_p``) and tonic level is left out. **Motion adjustment**: SCRs
and HR rise with movement, so each standardised measure is also residualised on movement
(within-unit z of log movement and its square, pooled least squares): ``r_pd`` / ``r_p``. Both
the adjusted and the unadjusted versions are reported.

(a) **Around presses.** Press episodes of participants with ``self_report`` consent
(``self_report_context.press_episodes``, all valid presses as in the context analyses). A press
counts when its minute is a worn minute and at least ``MIN_WINDOW_VALID`` of the minutes from
-10 to +10 are usable. Profile: the mean measure at each offset; windows ``WINDOWS`` (before,
at, after) and the changes at - before and after - before. **Null**: each press moved to a random
eligible minute of the same person-day (``person-day``), or of the same person-day and phase of
day (``person-day-phase``, matched time), ``N_SHUFFLE`` times. Reported: observed beside the null
mean and band, and the mean over people of (own presses minus own shuffled presses) with a
bootstrap over people. **Collective moments**: presses that are part of a co-located pair (two
participants' presses within 5 min at close range, ``exploratory_cascades``) against the other
presses, same null; withheld when fewer than ``MIN_GROUP`` people.

(b) **Programme setting.** Usable minutes in a beacon exposure bin of the person, classified as
in ``exploratory_presses`` (setting `[inferred]`: plenum, course block, meal time, other daytime,
evening; zone of the room tag heard most; programme item kinds from the spine's events). Fixed
effects per person-day (each person against themselves on the same day), standard errors
clustered by person (``stats.within_ols``), three models (``ADJUSTMENTS``): none; movement;
movement plus clock hour and wear time (``WEAR_BANDS``, minutes since the day's first worn
minute: tonic level settles after the electrodes go on, and the morning plenum falls in the
first wear hour). Effects in within-person-day SD units against ``course block`` (setting),
``courses`` (zone) and minutes in no programme item (kind). Day kind: the rotation day (22 Aug)
against ordinary EDA days (person fixed effects; the excursion day has no EDA), and the mean
motion-adjusted level per camp day.

(c) **Synchrony.** Pairs of participants with ``eda`` and ``beacons`` consent wearing at the same
minute, with at least ``SYNC_MIN_OVERLAP`` common usable minutes in the camp day. Each signal is
detrended (minus a centred ``DETREND_WINDOW``-minute moving mean), residualised on movement
(not for movement itself), and standardised within person-day: SCR rate under both rules,
the minute-to-minute change of tonic level, and movement as a reference; the EDA signals also
without the movement adjustment (``*_unadj``), to show what movement carries. A pair-minute is
``close`` when the pair's strongest reading in its 5-minute bin is at least ``CLOSE_RSSI``,
``heard`` when weaker, ``apart`` when both tags were seen in the bin but not by each other, and
``unknown`` otherwise. Heart rate: the same on HR minutes (pairs with at least
``SYNC_MIN_OVERLAP`` common HR minutes), detrended HR adjusted for movement, unadjusted, and
movement on the same minutes as its reference. Synchrony is the mean product of the two
standardised signals (a pooled correlation). Nulls: the partner's series shifted by
``NULL_LAGS`` minutes on the same pair-minutes (keeps each signal's own rhythm and the labels),
and ``apart`` pairs at the same times (keeps the camp's shared rhythm). Intervals resample
people (a pair-minute weighs the product of its partners' draws:
``rhythm.node_bootstrap_weights``).

Run after ``social-energy ingest-eda``, ``copresence_by_phase.py build`` and
``beacon_diagnostics.py``:

    uv run --extra analysis python studies/dsa-2026/analyses/exploratory_eda.py

Writes CSVs, ``qa_eda.json`` and figures to
``$SOCIAL_ENERGY_DATA/dsa-2026/derived/analyses/exploratory/eda/``. Nothing per person.
"""

from __future__ import annotations

import json
import sys
import warnings
from pathlib import Path

import numpy as np
import polars as pl

sys.path.insert(0, str(Path(__file__).parent))
import copresence_by_phase as cp
import exploratory_presses as xp
import self_report_context as srx

from social_energy import paths
from social_energy.eda.arousal import (
    centred_detrend,
    dense_series,
    draw_positions,
    eligible,
    lagged_products,
    node_bootstrap_mean,
    percentile_interval,
    pools,
    profile,
    residualise,
    window_means,
    zscore_within,
)
from social_energy.eda.heart import with_heart_rate
from social_energy.exploratory import CloseIndex, bootstrap_mean, co_event_pairs
from social_energy.rhythm import node_bootstrap_weights
from social_energy.spine import Spine
from social_energy.stats import within_ols

SLUG = "exploratory/eda"
MIN_GROUP = 5
#: A usable minute holds at least this many worn seconds without an artifact.
MIN_CLEAN_S = 30
#: SCR rules (decided 2026-10-21): every clean detection, and those of at least 0.2 µS.
RULES = {"main": 0.0, "amp02": 0.2}
RULE_LABEL = {"main": "main (all detections)", "amp02": "amp >= 0.2 µS"}
MEASURES = ["scr_main", "scr_amp02", "amp_main", "amp_amp02", "tonic"]
#: An HR minute has at least this share of good 10-s PPG windows (1/6: at least one).
HR_MIN_QUALITY = 1 / 6
#: The primary run on all minutes, and the sensitivity on minutes with a measured clock.
CLOCKS = ("all", "certain")
LABEL = {
    "scr_main": "SCR rate, main",
    "scr_amp02": "SCR rate, amp >= 0.2",
    "amp_main": "SCR amplitude (log), main",
    "amp_amp02": "SCR amplitude (log), amp >= 0.2",
    "tonic": "tonic level (log)",
    "motion": "movement (log)",
    "raw_scr_main": "SCR per minute, main (raw)",
    "raw_scr_amp02": "SCR per minute, amp >= 0.2 (raw)",
    "dtonic": "tonic change",
    "hr": "heart rate",
    "hr_motion": "movement (HR minutes)",
    "raw_hr": "heart rate, bpm (raw)",
}
OFFSETS = np.arange(-10, 11)
WINDOWS = {"before": (-10, -2), "at": (-1, 1), "after": (2, 10)}
MIN_WINDOW_VALID = 11
PAD = 40
PRESS_NULLS = ("person-day", "person-day-phase")
CASCADE_WINDOW = 300
MIN_SUBSET_PRESSES = 10
N_SHUFFLE = 1000
N_BOOT = 2000
SEED = 20261021
CLOSE_RSSI = cp.CLOSE_RSSI
DETREND_WINDOW = 31
SYNC_MIN_OVERLAP = 30
NULL_LAGS = [-60, -45, -30, -20, -15, -10, 10, 15, 20, 30, 45, 60]
LAG_PROFILE = list(range(-10, 11))
#: Signals for synchrony; ``*_unadj`` are detrended but not adjusted for movement.
SYNC_SIGNALS = ["scr_main", "scr_amp02", "dtonic", "motion", "scr_main_unadj",
                "scr_amp02_unadj", "dtonic_unadj"]  # fmt: skip
#: Heart-rate synchrony on HR minutes; ``hr_motion`` is movement on the same minutes.
HR_SYNC_SIGNALS = ["hr", "hr_unadj", "hr_motion"]
ROTATION = "2026-08-22"
PHASES = cp.PHASE_ORDER
INK, INK2, GRID, SURFACE = "#0b0b0b", "#52514e", "#e4e3df", "#fcfcfb"
BLUE, ORANGE, GREEN, GRAY = "#2a78d6", "#eb6834", "#2e9e6a", "#8a8984"


def out_dir() -> Path:
    d = paths.study(cp.STUDY).derived / "analyses" / SLUG
    d.mkdir(parents=True, exist_ok=True)
    return d


# --- minutes -------------------------------------------------------------------------------------


def scr_counts(scr: pl.LazyFrame, min_amplitude_us: float) -> pl.DataFrame:
    """``device``, ``minute``, ``n``, ``amp``: clean SCRs (ok, worn, no artifact) with onset in
    the minute and amplitude at least ``min_amplitude_us``, and their summed amplitude."""
    return (
        scr.filter(
            pl.col("ok")
            & pl.col("worn")
            & ~pl.col("artifact")
            & (pl.col("amplitude_us") >= min_amplitude_us)
        )
        .group_by("device", pl.col("onset").dt.truncate("1m").alias("minute"))
        .agg(pl.len().cast(pl.Int64).alias("n"), pl.col("amplitude_us").sum().alias("amp"))
        .collect()
    )


def _with_defaults(pm: pl.DataFrame) -> pl.DataFrame:
    """Clock and heart-rate columns a person-minute table may lack (no clock flag, no PPG)."""
    defaults = {"clock_uncertain": pl.lit(False), "hr_ppg_bpm": pl.lit(None, pl.Float32),
                "hr_quality": pl.lit(None, pl.Float32), "hr_clock_uncertain": pl.lit(None,
                pl.Boolean)}  # fmt: skip
    return pm.with_columns(e.alias(c) for c, e in defaults.items() if c not in pm.columns)


def build_minutes(
    pm: pl.DataFrame, counts: dict[str, pl.DataFrame], *, clock: str = "all"
) -> pl.DataFrame:
    """One row per person-minute outside exclusion windows, with ``usable``, ``hr_ok`` and the
    measures.

    ``counts[rule]`` holds ``device``, ``minute``, ``n``, ``amp`` under each SCR rule. EDA
    measures are null in minutes that are not usable, ``hr`` and ``hr_motion`` in minutes that
    are not HR minutes. With ``clock="certain"`` neither holds where ``clock_uncertain`` (or,
    for heart rate, ``hr_clock_uncertain``) is true or unknown.
    """
    if clock not in CLOCKS:
        raise ValueError(f"clock must be one of {CLOCKS}")
    m = (
        _with_defaults(pm)
        .filter(~pl.col("excluded"))
        .with_columns(
            (pl.col("worn_s").cast(pl.Int64) - pl.col("artifact_s").cast(pl.Int64)).alias("clean_s")
        )
    )
    certain = ~pl.col("clock_uncertain").fill_null(True)
    hr_certain = certain & ~pl.col("hr_clock_uncertain").fill_null(True)
    usable = ((pl.col("clean_s") >= MIN_CLEAN_S) & pl.col("conductance_us").is_not_null()
              & (pl.col("conductance_us") > 0))  # fmt: skip
    hr_ok = (pl.col("hr_ppg_bpm").is_not_null() & (pl.col("hr_quality") >= HR_MIN_QUALITY - 1e-6)
             & (pl.col("motion_sd_g") > 0)).fill_null(False)  # fmt: skip
    if clock == "certain":
        usable, hr_ok = usable & certain, hr_ok & hr_certain
    m = m.with_columns(usable.alias("usable"), hr_ok.alias("hr_ok"))
    use = pl.col("usable")
    for rule, c in counts.items():
        m = m.join(
            c.rename({"n": f"n_{rule}", "amp": f"a_{rule}"}), on=["device", "minute"], how="left"
        ).with_columns(pl.col(f"n_{rule}").fill_null(0), pl.col(f"a_{rule}").fill_null(0.0))
        rate = pl.col(f"n_{rule}") * 60.0 / pl.col("clean_s")
        amp = (pl.col(f"a_{rule}") / pl.col(f"n_{rule}")).log()
        m = m.with_columns(
            pl.when(use).then(rate).alias(f"scr_{rule}"),
            pl.when(use & (pl.col(f"n_{rule}") > 0)).then(amp).alias(f"amp_{rule}"),
        )
    return (
        m.with_columns(
            pl.when(use).then(pl.col("conductance_us").cast(pl.Float64).log()).alias("tonic"),
            pl.when(use & (pl.col("motion_sd_g") > 0))
            .then(pl.col("motion_sd_g").cast(pl.Float64).log())
            .alias("motion"),
            pl.when(pl.col("hr_ok")).then(pl.col("hr_ppg_bpm").cast(pl.Float64)).alias("hr"),
            pl.when(pl.col("hr_ok"))
            .then(pl.col("motion_sd_g").cast(pl.Float64).log())
            .alias("hr_motion"),
            cp.camp_day_expr(pl.col("minute")).alias("day"),
            cp.phase_expr(pl.col("minute")).alias("phase"),
            pl.col("minute").dt.truncate(cp.BIN).alias("bin"),
        )
        .with_columns(
            (pl.col("minute") - pl.col("minute").min().over("entity", "day"))
            .dt.total_minutes()
            .alias("wear_min")
        )
        .sort("entity", "minute")
    )


def motion_of(measure: str) -> str:
    """The movement column a measure is adjusted for: over its own minutes."""
    return "hr_motion" if measure == "hr" else "motion"


def standardise(m: pl.DataFrame) -> pl.DataFrame:
    """Add ``z_pd_*`` / ``z_p_*`` (within person-day / person) and their motion residuals
    ``r_pd_*`` / ``r_p_*`` for every EDA measure and heart rate, plus the movement z-scores
    (``z_pd_motion`` over usable minutes, ``z_pd_hr_motion`` over HR minutes) and squares."""
    for unit, by in (("pd", ["entity", "day"]), ("p", ["entity"])):
        for mv in ("motion", "hr_motion"):
            m = zscore_within(m, mv, by, f"z_{unit}_{mv}")
            m = m.with_columns((pl.col(f"z_{unit}_{mv}") ** 2).alias(f"z_{unit}_{mv}2"))
        for x in [*MEASURES, "hr"]:
            mv = motion_of(x)
            m = zscore_within(m, x, by, f"z_{unit}_{x}")
            m, _ = residualise(
                m, f"z_{unit}_{x}", [f"z_{unit}_{mv}", f"z_{unit}_{mv}2"], f"r_{unit}_{x}"
            )
    return m


# --- (a) around presses --------------------------------------------------------------------------

PRESS_COLUMNS = (
    [f"z_pd_{x}" for x in MEASURES]
    + [f"r_pd_{x}" for x in MEASURES]
    + ["z_pd_motion", "raw_scr_main", "raw_scr_amp02"]
)
#: Heart rate around presses, on HR minutes (eligibility counts HR minutes).
HR_PRESS_COLUMNS = ["z_pd_hr", "r_pd_hr", "z_pd_hr_motion", "raw_hr"]


def press_series(m: pl.DataFrame, columns=PRESS_COLUMNS, valid: str = "usable"):
    frame = m.with_columns(
        pl.col(valid).cast(pl.Float64).alias("valid_f"),
        pl.col("phase").replace_strict({p: i for i, p in enumerate(PHASES)}).alias("phase_code"),
        pl.col("scr_main").alias("raw_scr_main"),
        pl.col("scr_amp02").alias("raw_scr_amp02"),
        pl.col("hr").alias("raw_hr"),
    )
    s = dense_series(frame, keys=["entity", "day"], time="minute",
                     values=[*columns, "valid_f", "phase_code"], pad=PAD)  # fmt: skip
    ok = eligible(s.values["valid_f"] == 1, OFFSETS, MIN_WINDOW_VALID)
    ok &= np.isfinite(s.values["phase_code"])
    return s, ok


def _stats(prof: np.ndarray) -> dict[str, np.ndarray]:
    """Per event: each window's mean and the two changes."""
    w = {k: window_means(prof, OFFSETS, lo, hi) for k, (lo, hi) in WINDOWS.items()}
    w["at_minus_before"] = w["at"] - w["before"]
    w["after_minus_before"] = w["after"] - w["before"]
    return w


def press_analysis(
    m: pl.DataFrame, presses: pl.DataFrame, columns=PRESS_COLUMNS, valid: str = "usable"
) -> dict:
    """Observed and shuffled profiles around presses for every column and subset.

    ``presses`` has ``entity``, ``day``, ``minute`` and a boolean ``cascade``. A press is
    eligible when its window holds enough minutes where ``valid`` is true (``usable`` for the
    EDA columns, ``hr_ok`` for ``HR_PRESS_COLUMNS``). Means of empty slices (a column with no
    value in a window) are NaN, silently.
    """
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        return _press_analysis(m, presses, list(columns), valid)


def _press_analysis(m: pl.DataFrame, presses: pl.DataFrame, columns, valid) -> dict:
    s, ok = press_series(m, columns, valid)
    pos = s.positions(presses)
    inside = pos >= 0
    use = inside.copy()
    use[inside] = ok[pos[inside]]
    p = presses.with_columns(pl.Series("pos", pos)).filter(pl.Series(use))
    pos = p["pos"].to_numpy()
    groups = s.group_of[pos]
    phase = s.values["phase_code"][pos].astype(int)
    ent = p["entity"].to_list()
    subsets = {"all": np.ones(len(pos), bool), "cascade": p["cascade"].to_numpy(),
               "solo": ~p["cascade"].to_numpy()}  # fmt: skip
    qa = {
        "presses_considered": presses.height,
        "presses_in_series": int(inside.sum()),
        "presses_eligible": len(pos),
        "pressers_eligible": len(set(ent)),
        "cascade_presses_eligible": int(subsets["cascade"].sum()),
        "cascade_people_eligible": len(set(np.asarray(ent)[subsets["cascade"]].tolist())),
    }
    obs_prof = {c: profile(s.values[c], pos, OFFSETS) for c in columns}
    obs_stats = {c: _stats(obs_prof[c]) for c in columns}
    out = {"qa": qa, "rows": [], "curves": []}
    for null in PRESS_NULLS:
        strat = None if null == "person-day" else s.values["phase_code"].astype(object)
        if strat is not None:
            strat = np.where(
                np.isfinite(s.values["phase_code"]),
                np.nan_to_num(s.values["phase_code"]).astype(int),
                -1,
            ).astype(object)
        pool = pools(ok, s.group_of, strat)
        keys = [(int(g), None if strat is None else int(ph))
                for g, ph in zip(groups, phase, strict=True)]  # fmt: skip
        rng = np.random.default_rng(SEED)
        null_curve = {(c, k): [] for c in columns for k in subsets}
        null_stat = {(c, k, w): [] for c in columns for k in subsets
                     for w in obs_stats[c]}  # fmt: skip
        ev_sum = {(c, w): np.zeros(len(pos)) for c in columns for w in obs_stats[c]}
        ev_n = {(c, w): np.zeros(len(pos)) for c in columns for w in obs_stats[c]}
        for _ in range(N_SHUFFLE):
            d = draw_positions(keys, pool, rng)
            for c in columns:
                pr = profile(s.values[c], d, OFFSETS)
                st = _stats(pr)
                for k, mask in subsets.items():
                    if mask.sum() == 0:
                        continue
                    with np.errstate(all="ignore"):
                        null_curve[(c, k)].append(np.nanmean(pr[mask], axis=0))
                    for w, v in st.items():
                        null_stat[(c, k, w)].append(np.nanmean(v[mask]))
                for w, v in st.items():
                    f = np.isfinite(v)
                    ev_sum[(c, w)][f] += v[f]
                    ev_n[(c, w)][f] += 1
        for c in columns:
            for k, mask in subsets.items():
                people = len(set(np.asarray(ent)[mask].tolist()))
                small = bool(people < MIN_GROUP or mask.sum() < MIN_SUBSET_PRESSES)
                base = {"column": c, "measure": _measure(c), "adjusted": c.startswith("r_"),
                        "null": null, "presses": "all" if k == "all" else k,
                        "n_presses": int(mask.sum()), "people": people,
                        "suppressed": small}  # fmt: skip
                if small:
                    out["rows"].append(base)
                    continue
                curve = np.asarray(null_curve[(c, k)])
                with np.errstate(all="ignore"):
                    oc = np.nanmean(obs_prof[c][mask], axis=0)
                for i, off in enumerate(OFFSETS):
                    out["curves"].append(
                        {
                            **base,
                            "offset": int(off),
                            "observed": float(oc[i]),
                            "null_mean": float(np.nanmean(curve[:, i])),
                            "null_lo": float(np.nanquantile(curve[:, i], 0.025)),
                            "null_hi": float(np.nanquantile(curve[:, i], 0.975)),
                        }
                    )
                for w, v in obs_stats[c].items():
                    o = float(np.nanmean(v[mask]))
                    z = np.asarray(null_stat[(c, k, w)])
                    z = z[np.isfinite(z)]
                    if z.size == 0 or not np.isfinite(o):
                        out["rows"].append({**base, "window": w})
                        continue
                    with np.errstate(all="ignore"):
                        ev_null = ev_sum[(c, w)] / ev_n[(c, w)]
                    diff = (v - ev_null)[mask]
                    per = (
                        pl.DataFrame({"e": np.asarray(ent)[mask], "d": diff})
                        .filter(pl.col("d").is_finite())
                        .group_by("e", maintain_order=True)
                        .agg(pl.col("d").mean())
                    )
                    bm = bootstrap_mean(per["d"].to_list(), n_boot=N_BOOT, seed=SEED)
                    out["rows"].append({
                        **base, "window": w, "observed": o, "null_mean": float(z.mean()),
                        "null_lo": float(np.quantile(z, 0.025)),
                        "null_hi": float(np.quantile(z, 0.975)),
                        "excess": o - float(z.mean()),
                        "share_null_at_least": float((z >= o).mean()),
                        "share_null_at_most": float((z <= o).mean()),
                        "person_mean_excess": bm.estimate, "person_lo": bm.lo,
                        "person_hi": bm.hi, "person_n": bm.n,
                        "share_people_positive": float((per["d"] > 0).mean()),
                    })  # fmt: skip
    return out


def _measure(col: str) -> str:
    for pre in ("z_pd_", "r_pd_", "z_p_", "r_p_"):
        if col.startswith(pre):
            return col.removeprefix(pre)
    return col


def cascade_flags(layout, spine, presses: pl.DataFrame) -> tuple[pl.DataFrame, dict]:
    """``presses`` with ``cascade``: the press is part of a co-located pair (two participants'
    presses within ``CASCADE_WINDOW`` s at close range in either press's bin), as in
    ``exploratory_cascades`` (exposure presses of raters with beacon consent)."""
    data = xp.load(layout, spine)
    pr = data["presses"].with_columns(pl.col("t").dt.epoch("s").alias("ts"))
    e = data["ends"].filter(pl.col("max_rssi") >= CLOSE_RSSI)
    triples = {(a, b, o) for a, b, o in e.select("entity", pl.col("bin").dt.epoch("s"), "other")
               .iter_rows()}  # fmt: skip
    close = CloseIndex(triples, bin_size=xp.BIN_S)
    pairs = co_event_pairs(pr["entity"].to_list(), pr["ts"].to_numpy(), close,
                           window=CASCADE_WINDOW, bin_size=xp.BIN_S)  # fmt: skip
    idx = np.unique(np.concatenate([pairs.first[pairs.close], pairs.second[pairs.close]]))
    flagged = pr[idx.tolist()].select("entity", "t").with_columns(pl.lit(True).alias("cascade"))
    out = presses.join(flagged, on=["entity", "t"], how="left").with_columns(
        pl.col("cascade").fill_null(False)
    )
    qa = {"colocated_pairs": int(pairs.close.sum()), "cascade_presses": len(idx)}
    return out, qa


# --- (b) settings --------------------------------------------------------------------------------


def _dummies(col: pl.Series, levels: list[str]) -> np.ndarray:
    v = col.to_numpy()
    return np.column_stack([(v == lv).astype(float) for lv in levels])


ADJUSTMENTS = ("none", "movement", "movement + time")
#: Minutes since the person-day's first worn minute, in bands: tonic level settles after the
#: electrodes go on, and the first programme items of the day fall in the first wear hour.
WEAR_BANDS = [0, 30, 60, 120, 240]


def time_terms(d: pl.DataFrame) -> np.ndarray:
    """Hour-of-day (local) and wear-time band dummies, first level of each left out."""
    hour = d["minute"].dt.convert_time_zone(cp.TZ).dt.hour().cast(pl.String)
    band = d["wear_min"].cut(WEAR_BANDS[1:], left_closed=True).cast(pl.String)
    cols = []
    for v in (hour, band):
        levels = sorted(set(v.to_list()))[1:]
        if levels:
            cols.append(_dummies(v, levels))
    return np.column_stack(cols) if cols else np.zeros((d.height, 0))


def fe_contrasts(
    df: pl.DataFrame,
    *,
    category: str,
    reference: str,
    unit: str = "pd",
    measures=MEASURES,
    label: str,
) -> list[dict]:
    """Effect of each category against ``reference`` on every measure, each person against
    themselves (fixed effects per person-day, or per person with ``unit="p"``), under each of
    ``ADJUSTMENTS`` (movement; movement, clock hour and wear time); standard errors clustered
    by person. Effects are in SDs of the measure within the unit."""
    rows = []
    d_all = df.filter(pl.col(category).is_not_null())
    levels = sorted(set(d_all[category].to_list()) - {reference})
    for x in measures:
        # The measure's own minutes (heart rate and EDA rest on different ones).
        d = d_all.filter(
            pl.col(f"z_{unit}_{x}").is_not_null() & pl.col(f"z_{unit}_{x}").is_finite()
        )
        absorb = (
            (d["entity"] + "|" + d["day"].cast(pl.String)).to_numpy() if unit == "pd"
            else d["entity"].to_numpy()
        )  # fmt: skip
        timex = time_terms(d) if "wear_min" in d.columns else None
        mv = f"z_{unit}_{motion_of(x)}"
        motion = d.select(mv, f"{mv}2").fill_null(np.nan).to_numpy()
        y = d[f"z_{unit}_{x}"].to_numpy()
        for adjustment in ADJUSTMENTS:
            if adjustment == "movement + time" and timex is None:
                continue
            cols, names = [_dummies(d[category], levels)], list(levels)
            if adjustment != "none":
                cols.append(motion)
                names += ["motion", "motion2"]
            if adjustment == "movement + time":
                cols.append(timex)
                names += [f"time_{i}" for i in range(timex.shape[1])]
            coefs = within_ols(y, np.column_stack(cols), names, absorb=absorb,
                               cluster=d["entity"].to_numpy())  # fmt: skip
            ok = np.isfinite(y)
            for lv, c in zip(levels, coefs, strict=False):
                sel = d.filter(pl.Series(ok) & (pl.col(category) == lv))
                people = sel["entity"].n_unique()
                small = people < MIN_GROUP
                rows.append({
                    "contrast": label, "measure": x, "adjustment": adjustment, "level": lv,
                    "reference": reference, "people": None if small else people,
                    "minutes": None if small else sel.height,
                    "estimate_sd": None if small else c.estimate,
                    "lo": None if small else c.lo, "hi": None if small else c.hi,
                    "clusters": c.clusters, "suppressed": small,
                })  # fmt: skip
    return rows


#: Raw per-category means: SCR per minute under both rules and log movement over usable
#: minutes, heart rate (bpm) over HR minutes.
LEVEL_VALUES = {"scr_main": "usable", "scr_amp02": "usable", "motion": "usable", "hr": "hr_ok"}


def level_means(df: pl.DataFrame, category: str) -> pl.DataFrame:
    """Raw levels per category (``LEVEL_VALUES``): the mean over people of each person's mean,
    with the people and minutes behind it; values resting on fewer than ``MIN_GROUP`` people
    are withheld (``suppressed`` for the EDA values, ``hr_suppressed`` for heart rate)."""
    d = df.filter(pl.col(category).is_not_null())
    parts = []
    for v, valid in LEVEL_VALUES.items():
        rows = d.filter(pl.col(valid) & pl.col(v).is_not_null())
        per = rows.group_by(category, "entity").agg(pl.col(v).mean(), pl.len().alias("n"))
        agg = per.group_by(category).agg(
            pl.col(v).mean(),
            pl.len().alias(f"{v}_people"),
            pl.col("n").sum().alias(f"{v}_minutes"),
        )
        small = pl.col(f"{v}_people") < MIN_GROUP
        parts.append(agg.with_columns(
            [pl.when(small).then(None).otherwise(pl.col(c)).alias(c)
             for c in (v, f"{v}_people", f"{v}_minutes")]
        ))  # fmt: skip
    levels = d.select(pl.col(category).unique())
    for part in parts:
        levels = levels.join(part, on=category, how="left")
    eda_n = pl.col("scr_main_people")
    return (
        levels.with_columns(
            eda_n.alias("people"), pl.col("scr_main_minutes").alias("minutes"),
            pl.col("motion").alias("log_motion"), eda_n.is_null().alias("suppressed"),
            pl.col("hr").alias("hr_bpm"), pl.col("hr_people").is_null().alias("hr_suppressed"),
        )
        .select(pl.col(category).alias("level"), "people", "minutes", "scr_main", "scr_amp02",
                "log_motion", "suppressed", "hr_people", "hr_minutes", "hr_bpm", "hr_suppressed")
        .sort("level")
    )  # fmt: skip


def setting_inputs(layout, spine) -> dict:
    """Beacon-placed settings and programme item windows: the same for every clock variant."""
    data = xp.load(layout, spine)
    placed = xp.placed_settings(data["exposure"], spine)
    return {"placed": placed, "events": xp.event_windows(spine, known_only=False)}


def settings_analysis(m: pl.DataFrame, inputs: dict) -> dict:
    """Contrasts by setting, zone, programme item and day kind (``fe_contrasts``) for the EDA
    measures on usable minutes and heart rate on HR minutes, raw levels, and the per-day table."""
    placed = inputs["placed"]
    use = m.filter(pl.col("usable") | pl.col("hr_ok"))
    j = use.join(placed.select("entity", "bin", "zone", "setting"), on=["entity", "bin"],
                 how="left")  # fmt: skip
    placed_ = j.filter(pl.col("setting").is_not_null())
    qa = {
        "usable_minutes": int(use["usable"].sum()),
        "in_exposure": int(placed_["usable"].sum()),
        "people_in_exposure": placed_.filter("usable")["entity"].n_unique(),
        "hr_minutes": int(use["hr_ok"].sum()),
        "hr_in_exposure": int(placed_["hr_ok"].sum()),
        "hr_people_in_exposure": placed_.filter("hr_ok")["entity"].n_unique(),
    }
    measures = [*MEASURES, "hr"]
    rows = fe_contrasts(j, category="setting", reference="course block", measures=measures,
                        label="setting")  # fmt: skip
    rows += fe_contrasts(j, category="zone", reference="courses", measures=measures, label="zone")
    means = [level_means(j, "setting").with_columns(pl.lit("setting").alias("contrast")),
             level_means(j, "zone").with_columns(pl.lit("zone").alias("contrast"))]  # fmt: skip
    # Programme item kinds: a minute may fall in several; the reference is no item.
    eb = xp.event_bins(inputs["events"], placed.select("entity", "bin", "location"))
    kinds = eb.group_by("entity", "bin").agg(pl.col("kind").unique())
    jk = placed_.join(kinds, on=["entity", "bin"], how="left")
    jk = jk.with_columns(pl.col("kind").fill_null(pl.lit([], dtype=pl.List(pl.String))))
    per_kind = (jk.filter("usable").explode("kind").filter(pl.col("kind").is_not_null())
                .group_by("kind").agg(pl.col("entity").n_unique().alias("people")))  # fmt: skip
    kinds_ok = sorted(per_kind.filter(pl.col("people") >= MIN_GROUP)["kind"].to_list())
    jk = jk.with_columns(
        pl.when(pl.col("kind").list.len() == 0).then(pl.lit("none"))
        .when(pl.col("kind").list.len() == 1).then(pl.col("kind").list.first())
        .otherwise(pl.lit("several")).alias("kind1")
    )  # fmt: skip
    jk = jk.with_columns(
        pl.when(pl.col("kind1").is_in([*kinds_ok, "none"])).then(pl.col("kind1"))
        .otherwise(pl.lit("other or several")).alias("kind1")
    )  # fmt: skip
    rows += fe_contrasts(jk, category="kind1", reference="none", measures=measures,
                         label="programme item")  # fmt: skip
    means.append(level_means(jk, "kind1").with_columns(pl.lit("programme item").alias("contrast")))
    # Day kind: the rotation day against ordinary EDA days, within person, same clock hours.
    rot = pl.lit(ROTATION).str.to_date()
    dk = use.with_columns(
        pl.when(pl.col("day") == rot).then(pl.lit("rotation")).otherwise(pl.lit("ordinary"))
        .alias("day_kind"),
    )  # fmt: skip
    rows += fe_contrasts(
        dk,
        category="day_kind",
        reference="ordinary",
        unit="p",
        measures=[x for x in measures if x != "tonic"],
        label="day kind",
    )
    means.append(level_means(dk, "day_kind").with_columns(pl.lit("day kind").alias("contrast")))
    days = per_day(use)
    return {"rows": rows, "means": pl.concat(means, how="diagonal_relaxed"), "days": days,
            "qa": qa}  # fmt: skip


#: Per-day levels: motion-adjusted, within-person z of each, over its own minutes.
DAY_VALUES = ("scr_main", "scr_amp02", "hr")


def per_day(use: pl.DataFrame) -> pl.DataFrame:
    """Per camp day: the mean over people of their motion-adjusted, within-person standardised
    level that day (SCR rate under both rules, heart rate), with a bootstrap over people; a
    value resting on fewer than ``MIN_GROUP`` people is withheld."""
    pd_ = (
        use.sort("day", "entity")
        .group_by("day", "entity", maintain_order=True)
        .agg(pl.col(f"r_p_{x}").mean() for x in DAY_VALUES)
    )
    rows = []
    for day in sorted(set(pd_["day"].to_list())):
        d = pd_.filter(pl.col("day") == day)
        row = {"day": day}
        for x in DAY_VALUES:
            v = d[f"r_p_{x}"].drop_nulls().drop_nans().to_list()
            row[f"{x}_people"] = len(v)
            if len(v) < MIN_GROUP:
                continue
            b = bootstrap_mean(v, n_boot=N_BOOT, seed=SEED)
            row |= {f"{x}_mean": b.estimate, f"{x}_lo": b.lo, f"{x}_hi": b.hi}
        row["suppressed"] = row["scr_main_people"] < MIN_GROUP
        rows.append(row)
    return pl.DataFrame(rows, infer_schema_length=None)


# --- (c) synchrony -------------------------------------------------------------------------------


def sync_signals(m: pl.DataFrame) -> pl.DataFrame:
    """Per person-minute: detrended, motion-residualised, standardised signals ``s_*``
    (``SYNC_SIGNALS`` on usable minutes, ``HR_SYNC_SIGNALS`` on HR minutes)."""
    frame = m
    cols = ["scr_main", "scr_amp02", "tonic", "motion", "hr", "hr_motion"]
    s = dense_series(frame, keys=["entity", "day"], time="minute", values=cols, pad=PAD)
    v = s.values
    dtonic = np.full_like(v["tonic"], np.nan)
    dtonic[1:] = v["tonic"][1:] - v["tonic"][:-1]
    raw = {"scr_main": v["scr_main"], "scr_amp02": v["scr_amp02"], "dtonic": dtonic,
           "motion": v["motion"], "hr": v["hr"], "hr_motion": v["hr_motion"]}  # fmt: skip
    det = {k: centred_detrend(x, window=DETREND_WINDOW, min_valid=DETREND_WINDOW // 3)
           for k, x in raw.items()}  # fmt: skip
    pos = s.positions(frame)
    out = frame.select("entity", "day", "minute", "bin").with_columns(
        [pl.Series(f"d_{k}", det[k][pos]).fill_nan(None) for k in det]
    )
    out = out.with_columns((pl.col("d_motion") ** 2).alias("d_motion2"),
                           (pl.col("d_hr_motion") ** 2).alias("d_hr_motion2"))  # fmt: skip
    signals = [*SYNC_SIGNALS, *HR_SYNC_SIGNALS]
    for k in signals:
        base = k.removesuffix("_unadj")
        col = f"d_{base}"
        if k in ("motion", "hr_motion") or k.endswith("_unadj"):
            out = out.with_columns(pl.col(col).alias(f"e_{k}"))
        else:
            mv = f"d_{motion_of(base)}"
            out, _ = residualise(out, col, [mv, f"{mv}2"], f"e_{k}")
        out = zscore_within(out, f"e_{k}", ["entity", "day"], f"s_{k}")
    return out.select("entity", "day", "minute", "bin", *[f"s_{k}" for k in signals])


def pair_minutes(
    sig: pl.DataFrame, pairs: pl.DataFrame, seen: pl.DataFrame, *, signal: str = "s_scr_main"
) -> pl.DataFrame:
    """Pair-minutes (``a`` < ``b``) of people both with ``signal`` in ``sig`` at the minute,
    labelled ``close`` / ``heard`` / ``apart`` / ``unknown`` from the 5-minute beacon bins;
    pair-days with fewer than ``SYNC_MIN_OVERLAP`` common minutes are dropped."""
    s = sig.filter(pl.col(signal).is_not_null()).select("entity", "day", "minute", "bin")
    j = (
        s.rename({"entity": "a"})
        .join(s.select(pl.col("entity").alias("b"), "minute"), on="minute")
        .filter(pl.col("a") < pl.col("b"))
    )
    n = j.group_by("a", "b", "day").len()
    j = j.join(n.filter(pl.col("len") >= SYNC_MIN_OVERLAP).drop("len"), on=["a", "b", "day"])
    p = pairs.select("a", "b", "bin", "max_rssi")
    seen1 = seen.select("entity", "bin").unique().with_columns(pl.lit(True).alias("_s"))
    j = (
        j.join(p, on=["a", "b", "bin"], how="left")
        .join(seen1.rename({"entity": "a", "_s": "sa"}), on=["a", "bin"], how="left")
        .join(seen1.rename({"entity": "b", "_s": "sb"}), on=["b", "bin"], how="left")
    )
    return j.with_columns(
        pl.when(pl.col("max_rssi") >= CLOSE_RSSI).then(pl.lit("close"))
        .when(pl.col("max_rssi").is_not_null()).then(pl.lit("heard"))
        .when(pl.col("sa").fill_null(False) & pl.col("sb").fill_null(False)).then(pl.lit("apart"))
        .otherwise(pl.lit("unknown")).alias("label")
    ).select("a", "b", "day", "minute", "label")  # fmt: skip


def _pair_sums(lp: pl.DataFrame) -> pl.DataFrame:
    return lp.group_by("label", "ia", "ib").agg(
        pl.col("product").sum().alias("sum"), pl.len().alias("n")
    )


def synchrony(sig: pl.DataFrame, pm_: pl.DataFrame, signals=SYNC_SIGNALS) -> dict:
    """Mean product at lag 0 per label, against the shifted-partner null and against ``apart``
    pairs at the same times; the lag profile; intervals resample people."""
    people = sorted(set(pm_["a"].to_list()) | set(pm_["b"].to_list()))
    code = {p: i for i, p in enumerate(people)}
    draws = list(node_bootstrap_weights(len(people), n_boot=N_BOOT, seed=SEED))
    pm_ = pm_.with_columns(pl.col("a").replace_strict(code).alias("ia"),
                           pl.col("b").replace_strict(code).alias("ib"))  # fmt: skip
    rows, lag_rows = [], []
    counts = pm_.group_by("label").agg(pl.len().alias("pair_minutes"),
                                       pl.struct("a", "b").n_unique().alias("pairs"),
                                       pl.concat_list("a", "b").explode().n_unique()
                                       .alias("people"))  # fmt: skip
    for k in signals:
        sk = sig.select("entity", "minute", f"s_{k}")
        per_lag = {}
        for lag in sorted(set(LAG_PROFILE) | set(NULL_LAGS)):
            lp = lagged_products(sk, pm_, value=f"s_{k}", lags=[lag])
            per_lag[lag] = _pair_sums(lp)
        null = (
            pl.concat([per_lag[g] for g in NULL_LAGS])
            .group_by("label", "ia", "ib")
            .agg(pl.col("sum").sum(), pl.col("n").sum())
        )
        stat = {}
        for label in ("close", "heard", "apart", "unknown"):
            z = per_lag[0].filter(pl.col("label") == label)
            if z.height == 0:
                continue
            obs, obs_d = node_bootstrap_mean(z["ia"].to_numpy(), z["ib"].to_numpy(),
                                             z["sum"].to_numpy(), draws,
                                             counts=z["n"].to_numpy())  # fmt: skip
            nl = null.filter(pl.col("label") == label)
            nul, nul_d = node_bootstrap_mean(nl["ia"].to_numpy(), nl["ib"].to_numpy(),
                                             nl["sum"].to_numpy(), draws,
                                             counts=nl["n"].to_numpy())  # fmt: skip
            stat[label] = (obs, obs_d, nul, nul_d)
            ppl = len(set(z["ia"].to_list()) | set(z["ib"].to_list()))
            small = ppl < MIN_GROUP
            ex = percentile_interval(obs_d - nul_d, obs.estimate - nul.estimate)
            rows.append({"signal": k, "label": label, "pair_minutes": obs.n, "pairs": z.height,
                         "people": ppl, "suppressed": small,
                         **({} if small else {
                             "sync": obs.estimate, "sync_lo": obs.lo, "sync_hi": obs.hi,
                             "shift_null": nul.estimate, "shift_lo": nul.lo, "shift_hi": nul.hi,
                             "excess_over_shift": ex.estimate, "excess_lo": ex.lo,
                             "excess_hi": ex.hi})})  # fmt: skip
            if small:
                continue
            for lag in LAG_PROFILE:
                q = per_lag[lag].filter(pl.col("label") == label)
                tot = q["n"].sum()
                lag_rows.append({"signal": k, "label": label, "lag": lag, "pair_minutes": tot,
                                 "sync": float(q["sum"].sum() / tot) if tot else None})  # fmt: skip
        if "close" in stat and "apart" in stat:
            c, a = stat["close"], stat["apart"]
            d0 = percentile_interval(c[1] - a[1], c[0].estimate - a[0].estimate)
            dd = percentile_interval((c[1] - c[3]) - (a[1] - a[3]),
                                     (c[0].estimate - c[2].estimate)
                                     - (a[0].estimate - a[2].estimate))  # fmt: skip
            rows.append({"signal": k, "label": "close minus apart", "sync": d0.estimate,
                         "sync_lo": d0.lo, "sync_hi": d0.hi, "excess_over_shift": dd.estimate,
                         "excess_lo": dd.lo, "excess_hi": dd.hi})  # fmt: skip
    return {"rows": pl.DataFrame(rows, infer_schema_length=None),
            "lags": pl.DataFrame(lag_rows, infer_schema_length=None), "counts": counts}  # fmt: skip


# --- main ----------------------------------------------------------------------------------------


def load_person_minutes(layout, spine) -> tuple[pl.DataFrame, dict[str, pl.DataFrame]]:
    """Participants' person-minutes with heart rate joined, and the SCR counts per rule."""
    d = layout.derived / "eda"
    cols = ["entity", "minute", "device", "worn_s", "artifact_s", "conductance_us",
            "motion_sd_g", "scr_n", "scr_amp_us", "excluded", "clock_uncertain",
            "clock_source"]  # fmt: skip
    participants = {p.ref for p in spine.people if p.role == "participant"}
    eda_ok = {f"person:{p}" for p in spine.consented("eda")}
    pm = pl.scan_parquet(d / "person_minutes.parquet").select(cols).collect()
    pm = pm.filter(pl.col("entity").is_in(list(participants & eda_ok)))
    pm = with_heart_rate(pm, pl.read_parquet(d / "hr_minutes.parquet"))
    scr = pl.scan_parquet(d / "scr.parquet").select(
        "device", "onset", "amplitude_us", "artifact", "ok", "worn"
    )
    counts = {rule: scr_counts(scr, amp) for rule, amp in RULES.items()}
    return pm, counts


def minutes_for(pm: pl.DataFrame, counts: dict[str, pl.DataFrame], clock: str):
    """The standardised minutes of one clock variant, and their QA."""
    m = standardise(build_minutes(pm, counts, clock=clock))
    kept = pm.filter(~pl.col("excluded"))
    qa = {
        "person_minutes": pm.height,
        "people": pm["entity"].n_unique(),
        "excluded_minutes": int(pm["excluded"].sum()),
        "clock_uncertain_minutes": int(kept["clock_uncertain"].sum()),
        "clock_source_minutes": dict(
            kept["clock_source"].cast(pl.String).value_counts().iter_rows()
        ),
        "usable_minutes": int(m["usable"].sum()),
        "usable_people": m.filter(pl.col("usable"))["entity"].n_unique(),
        "usable_share": float(m["usable"].mean()),
        "hr_minutes": int(m["hr_ok"].sum()),
        "hr_people": m.filter(pl.col("hr_ok"))["entity"].n_unique(),
        "hr_share": float(m["hr_ok"].mean()),
        "hr_and_usable_minutes": int((m["hr_ok"] & m["usable"]).sum()),
        "hr_bpm_mean": float(m["hr"].mean()),
        "scr_per_min_main": float(m["scr_main"].mean()),
        "scr_per_min_amp02": float(m["scr_amp02"].mean()),
    }
    if clock == "all":
        check = pm.join(counts["main"], on=["device", "minute"], how="left").with_columns(
            pl.col("n").fill_null(0)
        )
        qa["main_rule_count_mismatch_minutes"] = int((check["n"] != check["scr_n"]).sum())
    return m, qa


def _tag(df: pl.DataFrame, **cols) -> pl.DataFrame:
    return df.with_columns(pl.lit(v).alias(k) for k, v in cols.items())


def run_variant(m: pl.DataFrame, presses: pl.DataFrame, inputs: dict, beacon_ok: set[str],
                pairs: pl.DataFrame, seen: pl.DataFrame) -> tuple[dict, dict]:  # fmt: skip
    """(a), (b) and (c) on one clock variant's minutes: output frames and QA."""
    qa: dict = {}
    out: dict[str, list[pl.DataFrame]] = {}

    def add(name: str, df: pl.DataFrame, **tags) -> None:
        if df.height:
            out.setdefault(name, []).append(_tag(df, **tags))

    # (a) Around presses: EDA on usable minutes, heart rate on HR minutes.
    for outcome, cols, valid in (("eda", PRESS_COLUMNS, "usable"),
                                 ("hr", HR_PRESS_COLUMNS, "hr_ok")):  # fmt: skip
        pa = press_analysis(m, presses, cols, valid)
        qa[f"presses_{outcome}"] = pa["qa"]
        add("presses_windows", pl.DataFrame(pa["rows"], infer_schema_length=None),
            outcome=outcome)  # fmt: skip
        add("presses_profile", pl.DataFrame(pa["curves"], infer_schema_length=None),
            outcome=outcome)  # fmt: skip

    # (b) Settings, zones, programme items, day kind.
    sa = settings_analysis(m, inputs)
    qa["settings"] = sa["qa"]
    add("settings_contrasts", pl.DataFrame(sa["rows"], infer_schema_length=None))
    add("settings_levels", sa["means"])
    add("days", sa["days"])

    # (c) Synchrony: EDA pairs on usable minutes, heart-rate pairs on HR minutes.
    sig = sync_signals(m.filter(pl.col("entity").is_in(list(beacon_ok))))
    for outcome, signals, key in (("eda", SYNC_SIGNALS, "s_scr_main"),
                                  ("hr", HR_SYNC_SIGNALS, "s_hr")):  # fmt: skip
        pm_ = pair_minutes(sig, pairs, seen, signal=key)
        sy = synchrony(sig, pm_, signals)
        add("synchrony", sy["rows"], outcome=outcome)
        add("synchrony_lags", sy["lags"], outcome=outcome)
        qa[f"synchrony_{outcome}"] = {
            "pair_minutes": pm_.height,
            "pair_days": pm_.select("a", "b", "day").unique().height,
            "people": len(set(pm_["a"]) | set(pm_["b"])),
            "by_label": {r["label"]: {"pair_minutes": r["pair_minutes"], "pairs": r["pairs"]}
                         for r in sy["counts"].iter_rows(named=True)},
        }  # fmt: skip
    return {k: pl.concat(v, how="diagonal_relaxed") for k, v in out.items()}, qa


def main() -> None:
    layout = paths.study(cp.STUDY)
    spine = Spine.load(layout.spine)
    out = out_dir()
    pm, counts = load_person_minutes(layout, spine)

    participants = {p.ref for p in spine.people if p.role == "participant"}
    raters = {f"person:{p}" for p in spine.consented("self_report")} & participants
    presses, press_qa = srx.press_episodes(layout, spine, participants, raters)
    presses, casc_qa = cascade_flags(layout, spine, presses)
    presses = presses.with_columns(pl.col("t").alias("minute"))
    inputs = setting_inputs(layout, spine)
    beacon_ok = {f"person:{p}" for p in spine.consented("beacons")}
    pairs = cp.load_all("pairs").select("a", "b", "bin", "max_rssi")
    seen = cp.load_all("seen").select("entity", "bin")

    qa: dict = {"presses": press_qa | casc_qa}
    frames: dict[str, list[pl.DataFrame]] = {}
    for clock in CLOCKS:
        m, mqa = minutes_for(pm, counts, clock)
        print(clock, json.dumps(mqa, indent=2, default=str), flush=True)
        res, vqa = run_variant(m, presses, inputs, beacon_ok, pairs, seen)
        qa[clock] = {"minutes": mqa, **vqa}
        for name, df in res.items():
            frames.setdefault(name, []).append(_tag(df, clock=clock))
        del m
    tables = {k: pl.concat(v, how="diagonal_relaxed") for k, v in frames.items()}
    for name, df in tables.items():
        df.write_csv(out / f"{name}.csv")
    qa["settings_used"] = {"min_clean_s": MIN_CLEAN_S, "rules": RULES, "windows": WINDOWS,
                           "min_window_valid": MIN_WINDOW_VALID, "n_shuffle": N_SHUFFLE,
                           "n_boot": N_BOOT, "seed": SEED, "close_rssi": CLOSE_RSSI,
                           "detrend_window": DETREND_WINDOW, "sync_min_overlap": SYNC_MIN_OVERLAP,
                           "null_lags": NULL_LAGS, "min_group": MIN_GROUP,
                           "hr_min_quality": HR_MIN_QUALITY, "clocks": CLOCKS}  # fmt: skip
    (out / "qa_eda.json").write_text(json.dumps(qa, indent=2, default=str), encoding="utf-8")
    primary = {k: v.filter(pl.col("clock") == "all") for k, v in tables.items()}
    figures(primary["presses_profile"], primary["settings_contrasts"], primary["synchrony_lags"],
            out)  # fmt: skip
    with pl.Config(tbl_rows=600, tbl_cols=30, tbl_width_chars=260, fmt_str_lengths=40):
        print(json.dumps(qa, indent=2, default=str))


# --- figures -------------------------------------------------------------------------------------


def _style(plt) -> None:
    plt.rcParams.update({
        "font.size": 10, "axes.spines.top": False, "axes.spines.right": False,
        "axes.edgecolor": INK2, "axes.labelcolor": INK2, "xtick.color": INK2,
        "ytick.color": INK2, "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.6,
        "figure.facecolor": SURFACE, "axes.facecolor": SURFACE, "savefig.facecolor": SURFACE,
        "axes.titlecolor": INK, "legend.frameon": False,
    })  # fmt: skip


def figures(curves: pl.DataFrame, settings: pl.DataFrame, lags: pl.DataFrame, out: Path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    _style(plt)
    note = "EXPLORATORY · DSA 2026 · aggregates only"
    # 1. Around presses, motion-adjusted, null within person-day.
    panels = [
        ("r_pd_scr_main", "SCR rate, main"),
        ("r_pd_scr_amp02", "SCR rate, amp >= 0.2 µS"),
        ("r_pd_tonic", "tonic level"),
        ("z_pd_motion", "movement (not adjusted)"),
        ("r_pd_hr", "heart rate (fewer presses)"),
    ]
    fig, axes = plt.subplots(1, 5, figsize=(18, 3.8), sharex=True)
    for ax, (col, title) in zip(axes, panels, strict=True):
        c = curves.filter((pl.col("column") == col) & (pl.col("null") == "person-day")
                          & (pl.col("presses") == "all")).sort("offset")  # fmt: skip
        if c.height == 0:
            continue
        x = c["offset"].to_numpy()
        ax.fill_between(x, c["null_lo"].to_numpy(), c["null_hi"].to_numpy(), color=GRID,
                        label="presses moved within the person-day (95%)")  # fmt: skip
        ax.plot(x, c["null_mean"].to_numpy(), color=GRAY, lw=1)
        ax.plot(x, c["observed"].to_numpy(), "o-", color=ORANGE, ms=3, label="at presses")
        ax.axvline(0, color=INK2, lw=0.8)
        ax.set_title(title, loc="left", fontsize=10)
        ax.set_xlabel("minutes from press")
    axes[0].set_ylabel("within person-day SD")
    axes[0].legend(fontsize=8, loc="upper left")
    fig.text(0.01, 0.01, note + " · SCR, tonic and heart rate adjusted for movement", fontsize=8,
             color=INK2)  # fmt: skip
    fig.tight_layout(rect=(0, 0.04, 1, 1))
    fig.savefig(out / "fig_eda_presses.png", dpi=170)
    plt.close(fig)

    # 2. Settings against course blocks: movement only, then also clock hour and wear time.
    meas = [("scr_main", BLUE), ("scr_amp02", GREEN), ("tonic", ORANGE), ("hr", GRAY)]
    fig, axes = plt.subplots(1, 2, figsize=(12, 4), sharex=True, sharey=True)
    for ax, adj in zip(axes, ("movement", "movement + time"), strict=True):
        s = settings.filter((pl.col("contrast") == "setting") & ~pl.col("suppressed")
                            & (pl.col("adjustment") == adj))  # fmt: skip
        levels = sorted(set(s["level"].to_list()))
        for j, (x, col) in enumerate(meas):
            q = s.filter(pl.col("measure") == x)
            for i, lv in enumerate(levels):
                r = q.filter(pl.col("level") == lv)
                if r.height == 0:
                    continue
                y = i + (j - 1.5) * 0.18
                ax.plot([r["lo"][0], r["hi"][0]], [y, y], color=col, lw=2)
                ax.plot(r["estimate_sd"][0], y, "o", color=col,
                        label=LABEL[x] if i == 0 else None)  # fmt: skip
        ax.axvline(0, color=INK2, lw=1)
        ax.set_yticks(range(len(levels)), levels)
        ax.set_title(f"adjusted for {adj}", loc="left", fontsize=10)
        ax.set_xlabel("against course blocks, same person and day (SD)")
    axes[0].legend(fontsize=8)
    fig.text(0.01, 0.01, note + " · 95% CI clustered by person · time = clock hour + wear time",
             fontsize=8, color=INK2)  # fmt: skip
    fig.tight_layout(rect=(0, 0.04, 1, 1))
    fig.savefig(out / "fig_eda_settings.png", dpi=170)
    plt.close(fig)

    # 3. Synchrony by lag.
    fig, axes = plt.subplots(1, 5, figsize=(18, 3.6), sharex=True)
    for ax, k in zip(axes, [*SYNC_SIGNALS[:4], "hr"], strict=True):
        for label, col in (("close", ORANGE), ("heard", BLUE), ("apart", GRAY)):
            q = lags.filter((pl.col("signal") == k) & (pl.col("label") == label)).sort("lag")
            if q.height:
                ax.plot(q["lag"].to_numpy(), q["sync"].to_numpy(), "o-", ms=3, color=col,
                        label=label)  # fmt: skip
        ax.axhline(0, color=INK2, lw=0.8)
        ax.set_title(LABEL.get(k, k), loc="left", fontsize=10)
        ax.set_xlabel("partner shifted (min)")
    axes[0].set_ylabel("mean product of z (correlation)")
    axes[0].legend(fontsize=8)
    fig.text(0.01, 0.01, note + " · detrended, movement-adjusted (except movement)", fontsize=8,
             color=INK2)  # fmt: skip
    fig.tight_layout(rect=(0, 0.04, 1, 1))
    fig.savefig(out / "fig_eda_synchrony.png", dpi=170)
    plt.close(fig)


if __name__ == "__main__":
    main()
