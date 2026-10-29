"""Exploratory tier, EDA second pass, analysis E: heart-rate variability by setting and by social
dose.

``docs/plans/ongoing/eda-second-pass.md``, section E, under the frozen analysis plan
(``research/analysis-plan.md``, "Exploratory analyses"). **Every result here is exploratory**:
no error control, two-sided, effects with 95% intervals and no p-values, cells of fewer than
``MIN_GROUP`` people withheld. Construct: short-term vagally mediated heart-rate variability
(RMSSD) as a trace of calm or recovery, lower under strain `[inferred: our reading, not signed
off by the research team]`. **PPG-derived HRV is noisy**: beats come from a wrist-worn optical
pulse at 128 Hz, not an ECG, so the coverage and the agreement check below come first.

**Beats.** ``derived/eda/hr_beats.parquet`` (``social-energy eda-heart-rate``): one row per
detected beat with its interval from the previous beat of the same stretch. A beat is valid
when ``ok`` (its 10-s window is the one source for that device-window and at a plausible time)
and ``plausible`` (40-200 bpm, within 30 % of its neighbours' median). A **successive
difference** is counted when both beats are valid, consecutive in the same stretch, and the
two intervals are within ``RMSSD_MAX_CHANGE`` (20 %) of the earlier one
(``eda.heart.successive_differences``); it belongs to the minute of the later beat. RMSSD of a
device-minute needs at least ``RMSSD_MIN_DIFFS`` (30) differences. **One source per
device-minute**: the SD card's beats where they give 30 differences, otherwise the export's
(the ``ok`` flag already keeps one source per 10-s window, SD first; a minute can still hold
windows of both, and the two are never pooled). Beats are read one device at a time.

**Minutes.** The first pass's person-minutes (``exploratory_eda.load_person_minutes`` and
``minutes_for``: participants with ``eda`` consent, exclusion windows dropped, its **HR minute**
rule and its clock variants). An **HRV minute** is an HR minute with an RMSSD that is **still**:
movement (accelerometer SD) below the median of the person-day's HR minutes. The camp day is
``eda_split.camp_day`` (04:00-04:00 local); wear time is minutes since the person-day's first
worn minute. Clock variant ``certain`` additionally needs every counted beat's clock measured.

**Measure.** log RMSSD, standardised within person-day (``z``) over its HRV minutes, in two
versions: ``lrmssd`` (not adjusted for heart rate) and ``lrmssd_hr`` (residualised on the
within-person-day z of heart rate and its square, pooled least squares: RMSSD falls as heart
rate rises, so part of any HRV contrast is a heart-rate contrast). Both are then adjusted for
movement in the models (z of log movement over the HRV minutes, and its square), as in the
first pass.

(1) **Setting** (``exploratory_eda.fe_contrasts``): plenum, meal time, other daytime against
course blocks; zone against ``courses``; programme item kind against no item. Fixed effects per
person-day, errors clustered by person, models none / movement / movement + clock hour + wear
time (the first pass's method rule: read the last). Settings are placed as in the first pass
(``exploratory_presses.placed_settings``), here on the exposure bins of every participant with
``beacons`` consent (the first pass used those with ``self_report`` consent too).

(2) **Social dose** (as in analysis A, participants with ``eda`` and ``beacons`` consent).
Exposure per person and 5-min bin, in the beacon observation window, outside lost or unsettled
beacon windows: ``n_close`` participants at close range (strongest reading in the bin at least
``CLOSE_RSSI``), level ``0`` (seen, nobody heard), ``heard only`` (others heard, none close),
``1``, ``2-3``, ``4-7``, ``8+``; and ``log(1+n_close)`` as a slope (with a heard-only
indicator). **Familiar vs new**: among minutes with company, the share of close partners already
tied (close for ``TIE_MIN_BINS`` bins on a camp day) on an earlier camp day, holding
log(1+n_close) fixed. Models with person-day fixed effects and errors clustered by person:
movement + clock hour + wear time, and the same plus setting.

**Split** (``eda_split``): every estimate on discovery days, replication days and all days;
``verdict`` from the two halves on the ``all`` clock (``verdict_certain`` on ``certain``).

Run after ``social-energy ingest-eda``, ``social-energy eda-heart-rate``,
``copresence_by_phase.py build`` and ``beacon_diagnostics.py``:

    uv run --extra analysis python studies/dsa-2026/analyses/eda2_hrv.py

Writes CSVs, ``qa.json`` and one aggregate figure to
``$SOCIAL_ENERGY_DATA/dsa-2026/derived/analyses/exploratory/eda2/hrv/``. ``person_hrv.csv``
there is per person (an input to analysis G) and stays in the private data root.
"""

from __future__ import annotations

import json
import resource
import sys
import time
from pathlib import Path

import numpy as np
import polars as pl

sys.path.insert(0, str(Path(__file__).parent))
import copresence_by_phase as cp
import eda_split as es
import exploratory_eda as xe
import exploratory_presses as xp
import outcomes as oc
import self_report_context as srx

from social_energy import paths
from social_energy.eda.arousal import residualise, zscore_within
from social_energy.eda.heart import (
    RMSSD_MAX_CHANGE,
    RMSSD_MIN_DIFFS,
    successive_differences,
)
from social_energy.spine import Spine
from social_energy.stats import cluster_bootstrap, within_ols

SLUG = "exploratory/eda2/hrv"
MIN_GROUP = xe.MIN_GROUP
CLOCKS = xe.CLOCKS
CLOSE_RSSI = cp.CLOSE_RSSI
TIE_MIN_BINS = cp.TIE_MIN_BINS
MEASURES = ["lrmssd_hr", "lrmssd"]
LABEL = {
    "lrmssd_hr": "log RMSSD, adjusted for heart rate",
    "lrmssd": "log RMSSD, not adjusted for heart rate",
}
DOSE_LEVELS = ["0", "heard only", "1", "2-3", "4-7", "8+"]
DOSE_MODELS = ("movement + time", "movement + time + setting")
#: A person's dose slope needs at least this many HRV minutes with known exposure.
PERSON_MIN_MINUTES = 30
N_BOOT = 2000
SEED = 20261029


def out_dir() -> Path:
    d = paths.study(cp.STUDY).derived / "analyses" / SLUG
    d.mkdir(parents=True, exist_ok=True)
    return d


# --- RMSSD per device-minute ---------------------------------------------------------------------


def _per_source_minute(d: pl.DataFrame) -> pl.DataFrame:
    """Per device, source and minute: counted differences, RMSSD, and whether any counted beat's
    clock is uncertain (differences of different runs of one source are pooled: each is within
    its own stretch)."""
    return (
        d.filter(pl.col("sd_ms").is_not_null())
        .group_by("device", "source", pl.col("t").dt.truncate("1m").alias("minute"))
        .agg(
            pl.len().alias("n_diffs"),
            (pl.col("sd_ms") ** 2).mean().sqrt().alias("rmssd_ms"),
            pl.col("clock_uncertain").any().alias("clock_uncertain"),
        )
    )


def device_hrv(beats: pl.DataFrame) -> tuple[pl.DataFrame, pl.DataFrame]:
    """One device's beats -> (RMSSD per device-minute from one source, the SD-vs-export pairs).

    Primary: valid = ``ok`` & ``plausible``; the SD card's minute where it holds at least
    ``RMSSD_MIN_DIFFS`` differences, else the export's. Agreement: valid = ``plausible`` alone
    (an export window covered by the card is not ``ok``), minutes where both sources reach the
    minimum."""
    keys = ("device", "source", "run")
    prim = _per_source_minute(
        successive_differences(
            beats.with_columns((pl.col("ok") & pl.col("plausible")).alias("valid")), by=keys
        )
    ).filter(pl.col("n_diffs") >= RMSSD_MIN_DIFFS)
    sd = prim.filter(pl.col("source") == "sd")
    ex = prim.filter(pl.col("source") == "export").join(
        sd.select("device", "minute"), on=["device", "minute"], how="anti"
    )
    chosen = pl.concat([sd, ex]).rename(
        {"source": "hrv_source", "clock_uncertain": "hrv_clock_uncertain"}
    )
    both = _per_source_minute(
        successive_differences(beats.with_columns(pl.col("plausible").alias("valid")), by=keys)
    ).filter(pl.col("n_diffs") >= RMSSD_MIN_DIFFS)
    pairs = (
        both.filter(pl.col("source") == "sd")
        .drop("source")
        .join(
            both.filter(pl.col("source") == "export").drop("source"),
            on=["device", "minute"],
            suffix="_export",
        )
        .rename(
            {
                "n_diffs": "n_diffs_sd",
                "rmssd_ms": "rmssd_sd",
                "rmssd_ms_export": "rmssd_export",
                "clock_uncertain": "clock_uncertain_sd",
            }
        )
    )
    return chosen, pairs


def hrv_minutes(layout) -> tuple[pl.DataFrame, pl.DataFrame, dict]:
    """``device_hrv`` over every device, scanning ``hr_beats`` lazily one device at a time."""
    path = layout.derived / "eda" / "hr_beats.parquet"
    lf = pl.scan_parquet(path).select(
        "device", "source", "run", "t", "ibi_ms", "plausible", "ok", "clock_uncertain"
    )
    devices = sorted(lf.select(pl.col("device").unique()).collect()["device"].to_list())
    chosen, pairs = [], []
    qa = {"devices": len(devices), "beats": 0, "beats_ok_plausible": 0}
    for dev in devices:
        b = lf.filter(pl.col("device") == dev).collect()
        qa["beats"] += b.height
        qa["beats_ok_plausible"] += int((b["ok"] & b["plausible"]).sum())
        c, p = device_hrv(b)
        chosen.append(c)
        pairs.append(p)
        del b
    ch = pl.concat(chosen)
    qa["device_minutes_rmssd"] = ch.height
    qa["device_minutes_by_source"] = dict(ch["hrv_source"].value_counts().iter_rows())
    return ch, pl.concat(pairs), qa


def agreement(pairs: pl.DataFrame, pm: pl.DataFrame) -> tuple[pl.DataFrame, dict]:
    """SD-sample against export-sample RMSSD on the same device-minutes: over all such minutes
    and over participants' worn minutes; log scale, intervals resampling devices."""
    worn = pm.filter(~pl.col("excluded")).select("device", "minute").unique()
    rows = []
    for scope, d in (
        ("all device-minutes", pairs),
        ("participants' worn minutes", pairs.join(worn, on=["device", "minute"])),
    ):
        for clock in CLOCKS:
            q = (
                d
                if clock == "all"
                else d.filter(~pl.col("clock_uncertain_sd") & ~pl.col("clock_uncertain_export"))
            )
            if q.height < 3:
                rows.append({"scope": scope, "clock": clock, "minutes": q.height})
                continue
            a, b = np.log(q["rmssd_sd"].to_numpy()), np.log(q["rmssd_export"].to_numpy())
            diff = a - b
            r = cluster_bootstrap(
                a.tolist(), b.tolist(), q["device"].to_list(), n_boot=N_BOOT, seed=SEED
            )
            rows.append(
                {
                    "scope": scope,
                    "clock": clock,
                    "minutes": q.height,
                    "devices": q["device"].n_unique(),
                    "r_log": r.r,
                    "r_lo": r.lo,
                    "r_hi": r.hi,
                    "bias_log": float(diff.mean()),
                    "sd_log": float(diff.std(ddof=1)),
                    "loa_low_log": float(diff.mean() - 1.96 * diff.std(ddof=1)),
                    "loa_high_log": float(diff.mean() + 1.96 * diff.std(ddof=1)),
                    "median_abs_diff_ms": float(
                        np.median(np.abs(q["rmssd_sd"].to_numpy() - q["rmssd_export"].to_numpy()))
                    ),
                    "identical_share": float(np.mean(np.abs(diff) < 1e-6)),
                    "median_rmssd_sd_ms": float(np.median(q["rmssd_sd"].to_numpy())),
                }
            )
    return pl.DataFrame(rows, infer_schema_length=None), {"pairs_minutes": pairs.height}


# --- HRV minutes ---------------------------------------------------------------------------------


def hrv_frame(m: pl.DataFrame, hrv: pl.DataFrame, clock: str) -> pl.DataFrame:
    """The first pass's minutes of one clock variant -> HR minutes with RMSSD, ``still`` and
    (on HRV minutes) the standardised measures and covariates."""
    d = (
        m.select("entity", "device", "minute", "bin", "hr_ok", "hr", "motion_sd_g")
        .with_columns(es.camp_day(pl.col("minute")).alias("day"))
        .with_columns(
            (pl.col("minute") - pl.col("minute").min().over("entity", "day"))
            .dt.total_minutes()
            .alias("wear_min"),
            es.half_of(pl.col("day")).alias("half"),
        )
        .filter(pl.col("hr_ok"))
        .join(hrv, on=["device", "minute"], how="left")
    )
    if clock == "certain":
        d = d.with_columns(
            pl.when(~pl.col("hrv_clock_uncertain").fill_null(True))
            .then(pl.col("rmssd_ms"))
            .alias("rmssd_ms")
        )
    med = pl.col("motion_sd_g").median().over("entity", "day")
    d = d.with_columns(
        (pl.col("motion_sd_g") < med).alias("still"),
        pl.col("rmssd_ms").is_not_null().alias("has_rmssd"),
    ).with_columns((pl.col("still") & pl.col("has_rmssd")).alias("hrv_ok"))
    v = d.filter("hrv_ok").with_columns(
        pl.col("rmssd_ms").log().alias("lrmssd_raw"),
        pl.col("motion_sd_g").cast(pl.Float64).log().alias("lmotion"),
    )
    by = ["entity", "day"]
    v = zscore_within(v, "lrmssd_raw", by, "z_pd_lrmssd")
    v = zscore_within(v, "hr", by, "z_pd_hr")
    v = zscore_within(v, "lmotion", by, "z_pd_motion")
    v = v.with_columns(
        (pl.col("z_pd_hr") ** 2).alias("z_pd_hr2"),
        (pl.col("z_pd_motion") ** 2).alias("z_pd_motion2"),
    )
    v, _ = residualise(v, "z_pd_lrmssd", ["z_pd_hr", "z_pd_hr2"], "z_pd_lrmssd_hr")
    v, _ = residualise(
        v, "z_pd_lrmssd", ["z_pd_motion", "z_pd_motion2", "z_pd_hr", "z_pd_hr2"], "r_pd_lrmssd_hr"
    )
    return d, v


def coverage(d: pl.DataFrame, clock: str) -> list[dict]:
    """Per half: HR minutes, those with an RMSSD, HRV minutes (still), people, shares, source."""
    rows = []
    for half in es.HALVES:
        h = es.subset(d, half)
        hv = h.filter("hrv_ok")
        per = hv.group_by("entity").len()
        n_hr = h.height
        rows.append(
            {
                "clock": clock,
                "half": half,
                "hr_minutes": n_hr,
                "hr_people": h["entity"].n_unique(),
                "rmssd_minutes": int(h["has_rmssd"].sum()),
                "rmssd_share_of_hr": float(h["has_rmssd"].mean()) if n_hr else None,
                "hrv_minutes": hv.height,
                "hrv_people": hv["entity"].n_unique(),
                "hrv_share_of_hr": hv.height / n_hr if n_hr else None,
                "hrv_person_days": hv.select("entity", "day").n_unique(),
                "hrv_minutes_per_person_median": float(per["len"].median()) if per.height else None,
                "hrv_minutes_from_export": int((hv["hrv_source"] == "export").sum()),
                "rmssd_ms_median": float(hv["rmssd_ms"].median()) if hv.height else None,
                "rmssd_ms_iqr_low": float(hv["rmssd_ms"].quantile(0.25)) if hv.height else None,
                "rmssd_ms_iqr_high": float(hv["rmssd_ms"].quantile(0.75)) if hv.height else None,
                "hr_bpm_mean": float(hv["hr"].mean()) if hv.height else None,
            }
        )
    return rows


# --- (1) settings --------------------------------------------------------------------------------


def item_kinds(v: pl.DataFrame, placed: pl.DataFrame, events: pl.DataFrame) -> pl.DataFrame:
    """HRV minutes in an exposure bin with ``zone``, ``setting`` and ``kind``, the list of
    programme item kinds that apply to the person in the bin."""
    eb = xp.event_bins(events, placed.select("entity", "bin", "location"))
    kinds = eb.group_by("entity", "bin").agg(pl.col("kind").unique())
    return (
        v.join(placed.select("entity", "bin", "zone", "setting"), on=["entity", "bin"])
        .join(kinds, on=["entity", "bin"], how="left")
        .with_columns(pl.col("kind").fill_null(pl.lit([], dtype=pl.List(pl.String))))
    )


def common_kinds(jk: pl.DataFrame) -> list[str]:
    """Programme item kinds met by at least ``MIN_GROUP`` people (fixed on all days, so every
    half has the same levels)."""
    per_kind = (
        jk.explode("kind", empty_as_null=True)
        .filter(pl.col("kind").is_not_null())
        .group_by("kind")
        .agg(pl.col("entity").n_unique().alias("people"))
    )
    return sorted(per_kind.filter(pl.col("people") >= MIN_GROUP)["kind"].to_list())


def settings_rows(jk: pl.DataFrame, kinds_ok: list[str]) -> list[dict]:
    """Setting, zone and programme-item contrasts (``xe.fe_contrasts``) on HRV minutes
    (``item_kinds``); item kinds outside ``kinds_ok`` pool as ``other or several``."""

    rows = xe.fe_contrasts(
        jk, category="setting", reference="course block", measures=MEASURES, label="setting"
    )
    rows += xe.fe_contrasts(
        jk, category="zone", reference="courses", measures=MEASURES, label="zone"
    )
    jk = jk.with_columns(
        pl.when(pl.col("kind").list.len() == 0)
        .then(pl.lit("none"))
        .when(pl.col("kind").list.len() == 1)
        .then(pl.col("kind").list.first())
        .otherwise(pl.lit("several"))
        .alias("kind1")
    ).with_columns(
        pl.when(pl.col("kind1").is_in([*kinds_ok, "none"]))
        .then(pl.col("kind1"))
        .otherwise(pl.lit("other or several"))
        .alias("kind1")
    )
    rows += xe.fe_contrasts(
        jk, category="kind1", reference="none", measures=MEASURES, label="programme item"
    )
    return rows


# --- (2) social dose -----------------------------------------------------------------------------


def dose_level(n_close: pl.Expr, n_heard: pl.Expr) -> pl.Expr:
    """``0``, ``heard only``, ``1``, ``2-3``, ``4-7``, ``8+`` from the bin's counts."""
    return (
        pl.when(n_close >= 8)
        .then(pl.lit("8+"))
        .when(n_close >= 4)
        .then(pl.lit("4-7"))
        .when(n_close >= 2)
        .then(pl.lit("2-3"))
        .when(n_close == 1)
        .then(pl.lit("1"))
        .when(n_heard > 0)
        .then(pl.lit("heard only"))
        .otherwise(pl.lit("0"))
    )


def familiarity(
    ends: pl.DataFrame, close_rssi: int = CLOSE_RSSI, tie_min_bins: int = TIE_MIN_BINS
) -> pl.DataFrame:
    """Per ``entity`` and ``bin`` with a close partner: ``n_close`` and ``share_familiar``, the
    share of the close partners tied with the person on an earlier camp day (a tie: close in at
    least ``tie_min_bins`` bins of one camp day). ``ends`` holds both directions of every pair
    (``entity``, ``other``, ``bin``, ``max_rssi``)."""
    close = ends.filter(pl.col("max_rssi") >= close_rssi).with_columns(
        es.camp_day(pl.col("bin")).alias("day")
    )
    first_tie = (
        close.group_by("entity", "other", "day")
        .agg(pl.col("bin").n_unique().alias("bins"))
        .filter(pl.col("bins") >= tie_min_bins)
        .group_by("entity", "other")
        .agg(pl.col("day").min().alias("first_tie"))
    )
    return (
        close.join(first_tie, on=["entity", "other"], how="left")
        .with_columns((pl.col("first_tie") < pl.col("day")).fill_null(False).alias("familiar"))
        .group_by("entity", "bin")
        .agg(
            pl.col("other").n_unique().alias("n_close"),
            pl.col("familiar").mean().alias("share_familiar"),
        )
    )


def exposure(spine: Spine, people: set[str], participants: set[str]) -> pl.DataFrame:
    """Per person with ``beacons`` consent and 5-min bin in which they were seen inside the
    observation window, outside lost or unsettled beacon windows: ``n_close``, ``n_heard``,
    ``level``, ``share_familiar`` (null without company), plus ``day``/``phase`` (copresence
    conventions) for placing settings."""
    lo, hi = pl.select(srx.local(srx.INSTRUCTION)).item(), pl.select(srx.local(cp.HANDOVER)).item()
    seen = cp.load_all("seen").filter(
        pl.col("entity").is_in(list(people)) & (pl.col("bin") >= lo) & (pl.col("bin") < hi)
    )
    seen = (
        seen.join(oc.removed_bins(spine), on=["entity", "bin"], how="anti")
        .select("entity", "bin", "day", "phase")
        .unique(["entity", "bin"])
    )
    pairs = cp.load_all("pairs").filter(
        pl.col("a").is_in(list(participants))
        & pl.col("b").is_in(list(participants))
        & (pl.col("bin") >= lo)
        & (pl.col("bin") < hi)
    )
    ends = pl.concat(
        [
            pairs.select(
                pl.col("a").alias("entity"), pl.col("b").alias("other"), "bin", "max_rssi"
            ),
            pairs.select(
                pl.col("b").alias("entity"), pl.col("a").alias("other"), "bin", "max_rssi"
            ),
        ]
    )
    heard = ends.group_by("entity", "bin").agg(pl.col("other").n_unique().alias("n_heard"))
    fam = familiarity(ends)
    return (
        seen.join(heard, on=["entity", "bin"], how="left")
        .join(fam, on=["entity", "bin"], how="left")
        .with_columns(pl.col("n_heard", "n_close").fill_null(0))
        .with_columns(dose_level(pl.col("n_close"), pl.col("n_heard")).alias("level"))
    )


def _dummies(v: pl.Series, levels: list[str]) -> np.ndarray:
    a = v.to_numpy()
    return np.column_stack([(a == lv).astype(float) for lv in levels])


def dose_rows(v: pl.DataFrame) -> list[dict]:
    """Level contrasts, the log(1+n) slope and familiar vs new, within person-day."""
    rows = []
    for x in MEASURES:
        d0 = v.filter(
            pl.col(f"z_pd_{x}").is_not_null()
            & pl.col(f"z_pd_{x}").is_finite()
            & pl.col("z_pd_motion").is_not_null()
        )
        for model in DOSE_MODELS:
            for kind in ("level", "slope", "familiar"):
                d = d0.filter(pl.col("n_close") >= 1) if kind == "familiar" else d0
                if d.height < 3:
                    continue
                cols = [d.select("z_pd_motion", "z_pd_motion2").to_numpy(), xe.time_terms(d)]
                names = ["motion", "motion2", *[f"time_{i}" for i in range(cols[1].shape[1])]]
                if model.endswith("setting"):
                    sv = d["setting"].fill_null("unplaced")
                    lv = sorted(set(sv.to_list()) - {"course block"})
                    cols.append(_dummies(sv, lv))
                    names += [f"setting_{s}" for s in lv]
                lin = pl.col("n_close").log1p()
                if kind == "level":
                    terms = [lv for lv in DOSE_LEVELS[1:] if lv in set(d["level"].to_list())]
                    x_main = _dummies(d["level"], terms)
                elif kind == "slope":
                    terms = ["log(1+n_close)", "heard only"]
                    x_main = np.column_stack(
                        [
                            d.select(lin).to_series().to_numpy(),
                            (d["level"] == "heard only").to_numpy() * 1.0,
                        ]
                    )
                else:
                    terms = ["share familiar", "log(1+n_close)"]
                    x_main = d.select("share_familiar", lin).to_numpy()
                X = np.column_stack([x_main, *cols])
                coefs = within_ols(
                    d[f"z_pd_{x}"].to_numpy(),
                    X,
                    [*terms, *names],
                    absorb=(d["entity"] + "|" + d["day"].cast(pl.String)).to_numpy(),
                    cluster=d["entity"].to_numpy(),
                )
                for t, c in zip(terms, coefs, strict=False):
                    if kind == "level":
                        sel = d.filter(pl.col("level") == t)
                    elif t == "heard only":
                        sel = d.filter(pl.col("level") == "heard only")
                    else:
                        sel = d
                    people = sel["entity"].n_unique()
                    small = people < MIN_GROUP
                    rows.append(
                        {
                            "contrast": f"dose {kind}",
                            "measure": x,
                            "adjustment": model,
                            "level": t,
                            "reference": "0" if kind == "level" else "",
                            "people": None if small else people,
                            "minutes": None if small else sel.height,
                            "estimate_sd": None if small else c.estimate,
                            "lo": None if small else c.lo,
                            "hi": None if small else c.hi,
                            "clusters": c.clusters,
                            "suppressed": small,
                        }
                    )
    return rows


def person_hrv(v: pl.DataFrame, exp: pl.DataFrame) -> pl.DataFrame:
    """Per person and half (clock ``all``): mean log RMSSD (raw) over HRV minutes, their number,
    and the slope of movement- and heart-rate-adjusted z log RMSSD on log(1+n_close) within
    person-day (null with fewer than ``PERSON_MIN_MINUTES`` minutes of known exposure)."""
    j = v.join(exp.select("entity", "bin", "n_close"), on=["entity", "bin"], how="left")
    rows = []
    for half in es.HALVES:
        h = es.subset(j, half)
        for ent, g in h.group_by("entity"):
            ent = ent[0]
            row = {
                "entity": ent,
                "half": half,
                "mean_log_rmssd": float(g["lrmssd_raw"].mean()),
                "n_minutes": g.height,
            }
            q = g.filter(pl.col("n_close").is_not_null() & pl.col("r_pd_lrmssd_hr").is_not_null())
            row["n_dose_minutes"] = q.height
            slope = None
            if q.height >= PERSON_MIN_MINUTES:
                x = np.array(q.select(pl.col("n_close").log1p()).to_series().to_numpy(), float)
                y = np.array(q["r_pd_lrmssd_hr"].to_numpy(), float)
                day = q["day"].cast(pl.String).to_numpy()
                for k in np.unique(day):
                    s = day == k
                    x[s] -= x[s].mean()
                    y[s] -= y[s].mean()
                if (x**2).sum() > 1e-9:
                    slope = float((x * y).sum() / (x**2).sum())
            row["dose_slope"] = slope
            rows.append(row)
    return pl.DataFrame(rows, infer_schema_length=None).sort("half", "entity")


# --- verdicts ------------------------------------------------------------------------------------

KEY = ["contrast", "measure", "adjustment", "level"]


def with_verdicts(df: pl.DataFrame) -> pl.DataFrame:
    """``verdict`` (clock ``all``) and ``verdict_certain`` per estimate, on every row."""
    out = df
    for clock, col in (("all", "verdict"), ("certain", "verdict_certain")):
        q = df.filter(pl.col("clock") == clock)
        halves = {
            h: q.filter(pl.col("half") == h).select(*KEY, "estimate_sd", "lo", "hi")
            for h in ("discovery", "replication")
        }
        j = halves["discovery"].join(
            halves["replication"], on=KEY, how="full", coalesce=True, suffix="_rep"
        )
        verdicts = [
            es.verdict(
                *(
                    np.nan if v is None else v
                    for v in (
                        r["estimate_sd"],
                        r["lo"],
                        r["hi"],
                        r["estimate_sd_rep"],
                        r["lo_rep"],
                        r["hi_rep"],
                    )
                )
            )
            for r in j.iter_rows(named=True)
        ]
        j = j.select(KEY).with_columns(pl.Series(col, verdicts, dtype=pl.String))
        out = out.join(j, on=KEY, how="left", nulls_equal=True)
    return out.with_columns(pl.col("verdict", "verdict_certain").fill_null("not estimable"))


# --- main ----------------------------------------------------------------------------------------


def main() -> None:
    t0 = time.time()
    layout = paths.study(cp.STUDY)
    spine = Spine.load(layout.spine)
    out = out_dir()
    pm, counts = xe.load_person_minutes(layout, spine)
    hrv, pairs, hqa = hrv_minutes(layout)
    agree, aqa = agreement(pairs, pm)
    del pairs

    participants = {p.ref for p in spine.people if p.role == "participant"}
    beacon_ok = {f"person:{p}" for p in spine.consented("beacons")} & participants
    exp = exposure(spine, beacon_ok, participants)
    placed = xp.placed_settings(exp.select("entity", "bin", "day", "phase"), spine)
    events = xp.event_windows(spine, known_only=False)
    exp = exp.join(placed.select("entity", "bin", "setting"), on=["entity", "bin"], how="left")

    qa: dict = {
        "beats": hqa,
        "agreement": aqa,
        "exposure_bins": exp.height,
        "exposure_people": exp["entity"].n_unique(),
    }
    cov, srows, drows, persons = [], [], [], None
    for clock in CLOCKS:
        m, mqa = xe.minutes_for(pm, counts, clock)
        d, v = hrv_frame(m, hrv, clock)
        del m
        cov += coverage(d, clock)
        vb = v.filter(pl.col("entity").is_in(list(beacon_ok))).join(
            exp.select("entity", "bin", "n_close", "n_heard", "level", "share_familiar", "setting"),
            on=["entity", "bin"],
        )
        qa[clock] = {
            "hr_minutes": mqa["hr_minutes"],
            "hrv_minutes": v.height,
            "hrv_minutes_with_exposure": vb.height,
            "hrv_people_with_exposure": vb["entity"].n_unique(),
        }
        jk = item_kinds(v, placed, events)
        kinds_ok = common_kinds(jk)
        for half in es.HALVES:
            tags = {"clock": clock, "half": half}
            srows += [r | tags for r in settings_rows(es.subset(jk, half), kinds_ok)]
            drows += [r | tags for r in dose_rows(es.subset(vb, half))]
        if clock == "all":
            persons = person_hrv(v, exp.filter(pl.col("entity").is_in(list(beacon_ok))))
        print(clock, json.dumps(qa[clock]), flush=True)
    settings = with_verdicts(pl.DataFrame(srows, infer_schema_length=None))
    dose = with_verdicts(pl.DataFrame(drows, infer_schema_length=None))
    pl.DataFrame(cov).write_csv(out / "coverage.csv")
    agree.write_csv(out / "agreement.csv")
    settings.write_csv(out / "settings_contrasts.csv")
    dose.write_csv(out / "dose_contrasts.csv")
    persons.write_csv(out / "person_hrv.csv")
    qa["settings_used"] = {
        "rmssd_max_change": RMSSD_MAX_CHANGE,
        "rmssd_min_diffs": RMSSD_MIN_DIFFS,
        "still": "motion below the person-day median of HR minutes",
        "source_rule": "sd if it reaches the minimum, else export",
        "close_rssi": CLOSE_RSSI,
        "tie_min_bins": TIE_MIN_BINS,
        "min_group": MIN_GROUP,
        "person_min_minutes": PERSON_MIN_MINUTES,
        "clocks": CLOCKS,
        "halves": es.HALVES,
    }
    qa["runtime_s"] = round(time.time() - t0, 1)
    qa["peak_rss_mb"] = round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 1)
    (out / "qa.json").write_text(json.dumps(qa, indent=2, default=str), encoding="utf-8")
    figure(settings, dose, out)
    print(json.dumps(qa, indent=2, default=str))


# --- figure --------------------------------------------------------------------------------------


def figure(settings: pl.DataFrame, dose: pl.DataFrame, out: Path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    xe._style(plt)
    colour = {"discovery": xe.BLUE, "replication": xe.ORANGE, "all": xe.INK2}
    panels = [
        (
            "setting vs course block",
            settings.filter(pl.col("contrast") == "setting").filter(
                pl.col("adjustment") == "movement + time"
            ),
        ),
        (
            "company vs nobody heard",
            dose.filter(pl.col("contrast") == "dose level").filter(
                pl.col("adjustment") == "movement + time"
            ),
        ),
        (
            "slopes",
            dose.filter(pl.col("contrast").is_in(["dose slope", "dose familiar"]))
            .filter(pl.col("adjustment") == "movement + time")
            .filter(pl.col("level").is_in(["log(1+n_close)", "share familiar"]))
            .with_columns((pl.col("contrast") + ": " + pl.col("level")).alias("level")),
        ),
    ]
    fig, axes = plt.subplots(1, 3, figsize=(16, 4.2))
    for ax, (title, q) in zip(axes, panels, strict=True):
        q = q.filter(
            (pl.col("clock") == "all") & (pl.col("measure") == "lrmssd_hr") & ~pl.col("suppressed")
        )
        levels = sorted(set(q["level"].to_list()))
        for j, half in enumerate(es.HALVES):
            for i, lv in enumerate(levels):
                r = q.filter((pl.col("level") == lv) & (pl.col("half") == half))
                if r.height == 0 or r["estimate_sd"][0] is None:
                    continue
                y = i + (j - 1) * 0.22
                ax.plot([r["lo"][0], r["hi"][0]], [y, y], color=colour[half], lw=2)
                ax.plot(
                    r["estimate_sd"][0], y, "o", color=colour[half], label=half if i == 0 else None
                )
        ax.axvline(0, color=xe.INK2, lw=1)
        ax.set_yticks(range(len(levels)), levels)
        ax.set_title(title, loc="left", fontsize=10)
        ax.set_xlabel("within person-day SD of log RMSSD")
    axes[0].legend(fontsize=8)
    fig.text(
        0.01,
        0.01,
        "EXPLORATORY · DSA 2026 · aggregates only · log RMSSD adjusted for heart "
        "rate, movement, clock hour and wear time · still minutes · 95% CI clustered by "
        "person",
        fontsize=8,
        color=xe.INK2,
    )
    fig.tight_layout(rect=(0, 0.05, 1, 1))
    fig.savefig(out / "fig_hrv.png", dpi=170)
    plt.close(fig)


if __name__ == "__main__":
    main()
