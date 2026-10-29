"""EDA second pass, C: which pairs synchronise, and does it last. EXPLORATORY.

``docs/plans/ongoing/eda-second-pass.md``, analysis C. **Every result here is exploratory**: no
error control, two-sided, effects with 95 % intervals and no p-values, cells of fewer than
``MIN_GROUP`` people withheld; an estimate counts as a lead only when it replicates on the days it
was not found on (``eda_split``). Construct: minute-level co-movement of two people's arousal while
close together as one candidate trace of a shared state, and the tie that may follow as its
social consequence `[inferred: our reading, not signed off by the research team]`.

**Signals** are the first pass's (``exploratory_eda.py``, section c), imported, not redefined:
participants with ``eda`` and ``beacons`` consent; usable minutes and HR minutes as there; each
signal detrended (centred ``DETREND_WINDOW``-minute mean), residualised on movement and
standardised within person-day (``sync_signals``): **tonic change** (minute-to-minute change of
log tonic level), **SCR >= 0.2 µS** rate, and **heart rate** (on HR minutes). Pair-minutes and their
``close`` / ``heard`` / ``apart`` labels come from ``pair_minutes`` (close: the pair's strongest
reading in the 5-minute beacon bin at least ``CLOSE_RSSI``). Both clock variants (``all``
primary, ``certain`` sensitivity).

**Pair-day.** A pair (both people with the signal at the same minute) on a camp day of the split
(04:00-04:00 local, ``eda_split.camp_day``; the signals stay standardised within the first pass's
person-day). A pair-day enters when, for that signal, it has at least ``MIN_CLOSE`` close common
minutes and at least ``MIN_COMMON`` common minutes (EDA signals on usable minutes, heart rate on
HR minutes, so the two samples differ). **Synchrony** of the pair-day: the mean product of the two
standardised signals at lag 0 over its close minutes (``close``, primary), and over all its common
minutes (``common``). Each pair-day is one observation.

**Ties** are the confirmatory outcomes' (``outcomes.daily_close_ties``): tied on a beacon camp day
(07:30-07:30) with at least ``TIE_MIN`` close minutes. **Prior tie**: tied on any camp day before
the pair-day's date. **Tied later**: tied on any of the next ``FOLLOW_DAYS`` camp days. The two day
boundaries differ by 3.5 night hours (04:00 vs 07:30); minutes between them belong to the
previous beacon day.

(1) **Determinants.** Linear models of pair-day synchrony, each pair-day one row: ``mean`` (the
mean pair-day synchrony alone); ``course + prior tie`` (same course, prior tie); ``survey`` (the
same plus the absolute difference of the trust and of the lust composites, in SDs of that
difference over all pairs of the survey unit, on pairs whose two people are both in the unit of
``exploratory_gradients.membranes``: ``beacons`` and ``survey`` consent and a linked submission).

(2) **Consequence.** Logit of tied later on the pair-day's synchrony (standardised over the
pair-days in the fit), holding fixed log close minutes that camp day (beacon bins x 5, on the
split's camp day), prior tie and same course. Pair-days whose follow-up days pass the last camp
day (``LAST_DAY``) are left out. Most qualifying pair-days are of pairs already tied and in one
course, so a binary control whose minority level rests on fewer than ``MIN_GROUP`` people is held
fixed by restriction to the majority level (``hold_fixed``; such a level cannot be adjusted for,
and in a logit it separates), recorded in ``held_by_restriction``. Beside it, the same logit with
synchrony alone (``sync only``). Reported: log-odds per SD of synchrony and the odds ratio; a fit
that separates or does not converge is ``NaN`` (``draws`` counts the bootstrap fits that did).

**Intervals** resample people (node bootstrap, ``rhythm.node_bootstrap_weights``: a pair-day
weighs the product of its partners' draws), ``N_BOOT`` draws for (1), ``N_BOOT_LOGIT`` for (2).
Every estimate is reported on discovery, replication and all days; ``verdict`` applies the split
rule (``eda_split.verdict``) to the ``all``-clock rows, ``verdict_certain`` to the clock-certain
ones. A binary term is withheld when either of its levels rests on fewer than ``MIN_GROUP``
people; a model when its pair-days involve fewer than ``MIN_GROUP`` people (and, for the logit,
when either outcome level does).

**Caveats.** Close minutes are rare among common usable minutes, so few pair-days qualify; pairs
share people and pair-days repeat pairs; synchrony over 20 minutes is noisy, which attenuates any
slope; ties are co-presence, not friendship; and the camp day of the EDA and of the beacons differ
at night.

    uv run --extra analysis python studies/dsa-2026/analyses/eda2_pair_sync.py

Run after ``social-energy ingest-eda``, ``copresence_by_phase.py build`` and ``confirmatory.py``.
Writes CSVs, ``qa.json`` and ``fig_pair_sync.png`` to
``$SOCIAL_ENERGY_DATA/dsa-2026/derived/analyses/exploratory/eda2/pair_sync/``; ``pair_days.csv``
and ``person_sync.csv`` (per pair-day, per person, for analysis G) stay in that private folder.
"""

from __future__ import annotations

import json
import sys
import time
import warnings
from datetime import timedelta
from pathlib import Path

import numpy as np
import polars as pl

sys.path.insert(0, str(Path(__file__).parent))
import copresence_by_phase as cp
import eda_split as split
import exploratory_eda as ee
import exploratory_gradients as eg
import outcomes as oc

from social_energy import paths
from social_energy.dyads import attribute_distance, pair_index
from social_energy.outcomes import daily_close_ties
from social_energy.rhythm import node_bootstrap_weights
from social_energy.spine import Spine

SLUG = "exploratory/eda2/pair_sync"
MIN_GROUP = 5
MIN_CLOSE = 20
MIN_COMMON = ee.SYNC_MIN_OVERLAP
CLOSE_RSSI = ee.CLOSE_RSSI
TIE_MIN = cp.TIE_MIN_BINS * oc.BIN_MINUTES
FOLLOW_DAYS = 3
LAST_DAY = oc.DAYS[-1]
CLOCKS = ee.CLOCKS
N_BOOT = 2000
N_BOOT_LOGIT = 1000
SEED = 20261029
#: Signal -> (the column in ``sync_signals``, the column defining common minutes, label).
SIGNALS = {
    "dtonic": ("s_dtonic", "s_scr_main", "tonic change"),
    "scr_amp02": ("s_scr_amp02", "s_scr_main", "SCR >= 0.2 µS"),
    "hr": ("s_hr", "s_hr", "heart rate"),
}
MINUTE_SETS = ("close", "common")
MODELS = {
    "mean": [],
    "course + prior tie": ["same_course", "prior_tie"],
    "survey": ["same_course", "prior_tie", "d_trust", "d_lust"],
}
BINARY = {"same_course", "prior_tie"}
CONSEQUENCE_TERMS = ["sync_z", "log_close_minutes", "prior_tie", "same_course"]
KEY = ["analysis", "signal", "minutes", "model", "term"]
INK, INK2, GRID, SURFACE = ee.INK, ee.INK2, ee.GRID, ee.SURFACE
HALF_COLOR = {"discovery": ee.BLUE, "replication": ee.ORANGE, "all": ee.GRAY}


def out_dir() -> Path:
    d = paths.study(cp.STUDY).derived / "analyses" / SLUG
    d.mkdir(parents=True, exist_ok=True)
    return d


# --- pair-days -----------------------------------------------------------------------------------


def pair_day_sums(
    sig: pl.DataFrame, pairs: pl.DataFrame, seen: pl.DataFrame, *, key: str, values: list[str]
) -> pl.DataFrame:
    """Per pair-day (``a``, ``b``, ``day``): for each column in ``values``, the sum and number of
    lag-0 products over close minutes (``sum_close_<v>``, ``n_close_<v>``) and over all common
    minutes (``sum_common_<v>``, ``n_common_<v>``).

    ``sig`` holds ``entity``, ``day`` (the pair-day's day), ``minute``, ``bin`` and the signals;
    common minutes are those where both people have ``key`` (``exploratory_eda.pair_minutes``,
    which also drops pair-days under its overlap). One day at a time, to keep memory small.
    """
    parts = []
    for day in sorted(sig["day"].drop_nulls().unique().to_list()):
        s = sig.filter(pl.col("day") == day)
        bins = s["bin"].unique().implode()
        pm = ee.pair_minutes(s, pairs.filter(pl.col("bin").is_in(bins)),
                             seen.filter(pl.col("bin").is_in(bins)), signal=key)  # fmt: skip
        if pm.height == 0:
            continue
        v = s.select("entity", "minute", *values)
        j = (
            pm.join(v.rename({"entity": "a", **{c: f"{c}__a" for c in values}}), on=["a", "minute"])
            .join(v.rename({"entity": "b", **{c: f"{c}__b" for c in values}}), on=["b", "minute"])
            .with_columns(
                (pl.col("label") == "close").alias("close"),
                *[(pl.col(f"{c}__a") * pl.col(f"{c}__b")).alias(f"p_{c}") for c in values],
            )
        )
        aggs = []
        for c in values:
            p, ok = pl.col(f"p_{c}"), pl.col(f"p_{c}").is_not_null()
            aggs += [
                p.filter(pl.col("close")).sum().alias(f"sum_close_{c}"),
                (ok & pl.col("close")).sum().alias(f"n_close_{c}"),
                p.sum().alias(f"sum_common_{c}"),
                ok.sum().alias(f"n_common_{c}"),
            ]
        parts.append(j.group_by("a", "b", "day").agg(aggs))
    if not parts:
        return pl.DataFrame()
    return pl.concat(parts).sort("day", "a", "b")


def pair_days(sums: pl.DataFrame, value: str) -> pl.DataFrame:
    """Pair-days with at least ``MIN_CLOSE`` close and ``MIN_COMMON`` common products of
    ``value``, with ``sync_close`` and ``sync_common`` (mean products) and their minutes."""
    nc, nm = pl.col(f"n_close_{value}"), pl.col(f"n_common_{value}")
    return sums.filter((nc >= MIN_CLOSE) & (nm >= MIN_COMMON)).select(
        "a", "b", "day",
        (pl.col(f"sum_close_{value}") / nc).alias("sync_close"),
        (pl.col(f"sum_common_{value}") / nm).alias("sync_common"),
        nc.cast(pl.Int64).alias("close_common_minutes"),
        nm.cast(pl.Int64).alias("common_minutes"),
    )  # fmt: skip


def tie_history(keys: pl.DataFrame, ties: pl.DataFrame) -> pl.DataFrame:
    """``keys`` (``a``, ``b``, ``day``) with ``prior_tie`` (tied on a day before), ``tied_later``
    (tied on any of the next ``FOLLOW_DAYS`` days) and ``has_follow`` (those days all on or
    before ``LAST_DAY``). ``ties`` has ``a``, ``b``, ``day``, one row per tied pair-day."""
    t = ties.select("a", "b", pl.col("day").alias("tday")).unique()
    j = keys.select("a", "b", "day").unique().join(t, on=["a", "b"], how="left")
    lag = (pl.col("tday") - pl.col("day")).dt.total_days()
    flags = j.group_by("a", "b", "day").agg(
        (lag < 0).fill_null(False).any().alias("prior_tie"),
        ((lag >= 1) & (lag <= FOLLOW_DAYS)).fill_null(False).any().alias("tied_later"),
    )
    return keys.join(flags, on=["a", "b", "day"], how="left").with_columns(
        (pl.col("day") + timedelta(days=FOLLOW_DAYS) <= LAST_DAY).alias("has_follow")
    )


def survey_distances(mem: pl.DataFrame) -> tuple[pl.DataFrame, dict[str, float]]:
    """Per unordered pair of unit people (``a`` < ``b``): ``d_trust``, ``d_lust``, the absolute
    composite differences in SDs of that difference over all unit pairs; and those SDs."""
    m = mem.sort("entity")
    ents = m["entity"].to_list()
    i, j = pair_index(len(ents))
    out = {"a": [ents[k] for k in i], "b": [ents[k] for k in j]}
    sds = {}
    for c in ("trust", "lust"):
        d = attribute_distance(m[c].to_numpy().astype(float), i, j)
        sds[c] = float(np.std(d, ddof=1))
        out[f"d_{c}"] = d / sds[c]
    return pl.DataFrame(out), sds


# --- models --------------------------------------------------------------------------------------


def wls(y: np.ndarray, X: np.ndarray, w: np.ndarray | None = None) -> np.ndarray:
    """Weighted least squares coefficients; NaN when the weighted design is rank-deficient."""
    w = np.ones(len(y)) if w is None else np.asarray(w, dtype=float)
    keep = w > 0
    sw = np.sqrt(w[keep])
    Xw, yw = X[keep] * sw[:, None], y[keep] * sw
    if Xw.shape[0] < X.shape[1] or np.linalg.matrix_rank(Xw) < X.shape[1]:
        return np.full(X.shape[1], np.nan)
    return np.linalg.lstsq(Xw, yw, rcond=None)[0]


def logit(
    y: np.ndarray, X: np.ndarray, w: np.ndarray | None = None, *, max_iter: int = 50,
    tol: float = 1e-9, bound: float = 25.0,
) -> np.ndarray:  # fmt: skip
    """Weighted logistic regression coefficients by Newton-Raphson; NaN when the design is
    singular, the fit diverges (separation: a coefficient past ``bound``) or does not converge."""
    w = np.ones(len(y)) if w is None else np.asarray(w, dtype=float)
    beta = np.zeros(X.shape[1])
    for _ in range(max_iter):
        p = 1 / (1 + np.exp(-np.clip(X @ beta, -50, 50)))
        grad = X.T @ (w * (y - p))
        hess = (X * (w * p * (1 - p))[:, None]).T @ X
        try:
            step = np.linalg.solve(hess, grad)
        except np.linalg.LinAlgError:
            return np.full(X.shape[1], np.nan)
        beta = beta + step
        if not np.all(np.isfinite(beta)) or np.max(np.abs(beta)) > bound:
            return np.full(X.shape[1], np.nan)
        if np.max(np.abs(step)) < tol:
            return beta
    return np.full(X.shape[1], np.nan)


def _people(df: pl.DataFrame) -> int:
    return len(set(df["a"].to_list()) | set(df["b"].to_list()))


def _codes(df: pl.DataFrame) -> tuple[np.ndarray, np.ndarray, int]:
    people = sorted(set(df["a"].to_list()) | set(df["b"].to_list()))
    code = {p: k for k, p in enumerate(people)}
    a = np.array([code[x] for x in df["a"].to_list()], dtype=np.int64)
    b = np.array([code[x] for x in df["b"].to_list()], dtype=np.int64)
    return a, b, len(people)


def _withheld_terms(df: pl.DataFrame, terms: list[str]) -> set[str]:
    """Binary terms one of whose levels rests on fewer than ``MIN_GROUP`` people."""
    out = set()
    for t in terms:
        if t in BINARY:
            for level in (True, False):
                if _people(df.filter(pl.col(t) == level)) < MIN_GROUP:
                    out.add(t)
    return out


def _design(df: pl.DataFrame, terms: list[str]) -> tuple[np.ndarray, list[str]]:
    """Intercept and the terms that vary in ``df`` (a constant term cannot be estimated)."""
    cols, names = [np.ones(df.height)], ["const"]
    for t in terms:
        x = df[t].cast(pl.Float64).to_numpy()
        if np.nanstd(x) > 0:
            cols.append(x)
            names.append(t)
    return np.column_stack(cols), names


def _boot(fit, y, X, a, b, n_people: int, n_boot: int) -> np.ndarray:
    draws = []
    for w in node_bootstrap_weights(n_people, n_boot=n_boot, seed=SEED):
        draws.append(fit(y, X, (w[a] * w[b]).astype(float)))
    return np.array(draws)


def _interval(draws: np.ndarray) -> tuple[float, float, int]:
    f = draws[np.isfinite(draws)]
    if f.size < 10:
        return np.nan, np.nan, int(f.size)
    lo, hi = np.quantile(f, [0.025, 0.975])
    return float(lo), float(hi), int(f.size)


def determinants(pd_: pl.DataFrame, minutes: str, *, n_boot: int = N_BOOT) -> list[dict]:
    """Every model of ``MODELS`` for pair-day synchrony over ``minutes`` (``close`` or
    ``common``): one row per term, with the node-bootstrap interval. A binary term one of whose
    levels rests on fewer than ``MIN_GROUP`` people is withheld and held fixed by restriction
    (``hold_fixed``), so the other terms are estimated on its majority level."""
    rows = []
    for model, terms in MODELS.items():
        full = pd_.drop_nulls([f"sync_{minutes}", *terms])
        small = _withheld_terms(full, terms) if full.height else set(terms) & BINARY
        d, dropped = hold_fixed(full, terms)
        base = {"analysis": "determinants", "minutes": minutes, "model": model,
                "pair_days": d.height, "people": _people(d) if d.height else 0,
                "held_by_restriction": ";".join(dropped) or None}  # fmt: skip
        for t in terms:
            if t in small:
                with_ = int(full[t].sum()) if full.height else 0
                rows.append(base | {"term": t, "withheld": True, "pair_days_with": with_})
        if base["people"] < MIN_GROUP:
            if model == "mean" or not set(terms) <= small:
                rows.append(base | {"term": "const" if model == "mean" else "model",
                                    "withheld": True})  # fmt: skip
            continue
        X, names = _design(d, [t for t in terms if t not in small])
        y = d[f"sync_{minutes}"].to_numpy()
        a, b, n = _codes(d)
        est = wls(y, X)
        boot = _boot(wls, y, X, a, b, n, n_boot)
        for k, t in enumerate(names):
            if t == "const" and model != "mean":
                continue  # the reference level's mean: not a determinant
            r = base | {"term": t, "withheld": False}
            if t in BINARY:
                r["pair_days_with"] = int(d[t].sum())
            lo, hi, ok = _interval(boot[:, k]) if np.isfinite(est[k]) else (np.nan, np.nan, 0)
            rows.append(r | {"estimate": float(est[k]), "lo": lo, "hi": hi, "draws": ok})
    return rows


def hold_fixed(d: pl.DataFrame, terms: list[str]) -> tuple[pl.DataFrame, list[str]]:
    """Restrict ``d`` to the majority level of every binary term in ``terms`` whose other level
    rests on fewer than ``MIN_GROUP`` people (held fixed by design: such a level cannot be
    adjusted for, and in a logit it separates). Returns the rows and the levels dropped."""
    dropped = []
    for t in terms:
        if t not in BINARY:
            continue
        for level in (True, False):
            sub = d.filter(pl.col(t) == level)
            if sub.height and _people(sub) < MIN_GROUP:
                d = d.filter(pl.col(t) != level)
                dropped.append(f"{t}={str(level).lower()}")
    return d, dropped


def consequence(pd_: pl.DataFrame, minutes: str, *, n_boot: int = N_BOOT_LOGIT) -> list[dict]:
    """Logits of ``tied_later`` on standardised synchrony over ``minutes`` on pair-days with
    ``has_follow``: ``logit tied later`` holds log close minutes, prior tie and same course
    fixed (a binary control whose minority level rests on fewer than ``MIN_GROUP`` people is
    held fixed by restriction, ``hold_fixed``); ``logit tied later, sync only`` has no controls.
    Rows: the synchrony term's log-odds per SD and odds ratio, and the controls."""
    d0 = pd_.filter(pl.col("has_follow")).drop_nulls(
        [f"sync_{minutes}", "log_close_minutes", "prior_tie", "same_course", "tied_later"]
    )
    rows = []
    for model, terms in (("logit tied later", CONSEQUENCE_TERMS),
                         ("logit tied later, sync only", ["sync_z"])):  # fmt: skip
        d, dropped = hold_fixed(d0, terms)
        base = {"analysis": "consequence", "minutes": minutes, "model": model,
                "pair_days": d.height,
                "held_by_restriction": ";".join(dropped) or None}  # fmt: skip
        if d.height < 2:
            rows.append(base | {"term": "sync_z", "people": _people(d) if d.height else 0,
                                "withheld": True})  # fmt: skip
            continue
        sync = d[f"sync_{minutes}"].to_numpy()
        sd = float(np.std(sync, ddof=1))
        d = d.with_columns(pl.Series("sync_z", (sync - sync.mean()) / sd if sd > 0 else sync * 0))
        base |= {"people": _people(d), "tied_later_pair_days": int(d["tied_later"].sum()),
                 "people_tied_later": _people(d.filter("tied_later")) if d["tied_later"].any()
                 else 0,
                 "people_not_tied_later": _people(d.filter(~pl.col("tied_later")))
                 if (~d["tied_later"]).any() else 0, "sync_sd": sd}  # fmt: skip
        smallest = min(base["people"], base["people_tied_later"], base["people_not_tied_later"])
        if smallest < MIN_GROUP:
            rows.append(base | {"term": "sync_z", "withheld": True})
            continue
        X, names = _design(d, terms)
        y = d["tied_later"].cast(pl.Float64).to_numpy()
        a, b, n = _codes(d)
        est = logit(y, X)
        boot = _boot(logit, y, X, a, b, n, n_boot)
        if "sync_z" not in names:
            rows.append(base | {"term": "sync_z", "withheld": True})
        for k, t in enumerate(names):
            if t == "const":
                continue
            lo, hi, ok = _interval(boot[:, k]) if np.isfinite(est[k]) else (np.nan, np.nan, 0)
            rows.append(base | {
                "term": t, "withheld": False, "estimate": float(est[k]), "lo": lo, "hi": hi,
                "draws": ok, "odds_ratio": float(np.exp(est[k])), "or_lo": float(np.exp(lo)),
                "or_hi": float(np.exp(hi)),
            })  # fmt: skip
    return rows


def with_verdicts(res: pl.DataFrame) -> pl.DataFrame:
    """``verdict`` (from the ``all``-clock rows) and ``verdict_certain`` per estimate key."""
    out = res
    for clock, col in (("all", "verdict"), ("certain", "verdict_certain")):
        c = res.filter(pl.col("clock") == clock)
        halves = {
            h: c.filter(pl.col("half") == h).select(
                *KEY, *[pl.col(x).alias(f"{x}_{h}") for x in ("estimate", "lo", "hi")]
            )
            for h in ("discovery", "replication")
        }
        j = halves["discovery"].join(halves["replication"], on=KEY, how="full", coalesce=True)

        def v(r: dict) -> str:
            return split.verdict(*(r.get(f"{x}_{h}") for h in ("discovery", "replication")
                                   for x in ("estimate", "lo", "hi")))  # fmt: skip

        j = j.with_columns(
            pl.Series(col, [v(r) for r in j.iter_rows(named=True)], dtype=pl.String)
        ).select(*KEY, col)
        out = out.join(j, on=KEY, how="left", nulls_equal=True)
    return out


def person_sync(pd_: pl.DataFrame) -> pl.DataFrame:
    """Per person and half: mean pair-day synchrony over close minutes of tonic change and of
    SCR >= 0.2 µS over the person's pair-days, and how many pair-days each rests on.

    ``pd_`` has ``signal``, ``half``, ``a``, ``b``, ``sync_close``; ``half`` is the pair-day's
    half, and every pair-day also counts for ``all``."""
    eda = pd_.filter(pl.col("signal").is_in(["dtonic", "scr_amp02"]))
    long = pl.concat([
        eda.select("signal", "half", pl.col(e).alias("entity"), "sync_close") for e in ("a", "b")
    ])  # fmt: skip
    long = pl.concat([long, long.with_columns(pl.lit("all").alias("half"))])
    agg = long.group_by("entity", "half", "signal").agg(
        pl.col("sync_close").mean().alias("sync"), pl.len().alias("n")
    )
    wide = agg.pivot(on="signal", index=["entity", "half"], values=["sync", "n"])
    for s in ("dtonic", "scr_amp02"):
        for c in ("sync", "n"):
            if f"{c}_{s}" not in wide.columns:
                wide = wide.with_columns(pl.lit(None, pl.Float64).alias(f"{c}_{s}"))
    return wide.select(
        "entity", "half",
        pl.col("sync_dtonic").alias("sync_dtonic_close"),
        pl.col("n_dtonic").fill_null(0).cast(pl.Int64).alias("n_pair_days_dtonic"),
        pl.col("sync_scr_amp02").alias("sync_scr_amp02_close"),
        pl.col("n_scr_amp02").fill_null(0).cast(pl.Int64).alias("n_pair_days_scr_amp02"),
    ).sort("entity", "half")  # fmt: skip


# --- main ----------------------------------------------------------------------------------------


def build_pair_days(
    m: pl.DataFrame, beacon_ok: set[str], pairs, seen, ties, close_min, course, dist
) -> tuple[pl.DataFrame, dict]:
    """All pair-days of one clock variant, every signal, with the pair covariates."""
    sig = ee.sync_signals(m.filter(pl.col("entity").is_in(list(beacon_ok))))
    sig = sig.with_columns(split.camp_day(pl.col("minute")).alias("day")).filter(
        split.half_of(pl.col("day")).is_not_null()
    )
    qa: dict = {"signal_people": sig["entity"].n_unique()}
    frames = []
    for key in ("s_scr_main", "s_hr"):
        names = [s for s, (_, k, _) in SIGNALS.items() if k == key]
        values = [SIGNALS[s][0] for s in names]
        sums = pair_day_sums(sig, pairs, seen, key=key, values=values)
        qa[f"pair_days_overlap_{key}"] = sums.height
        for s, v in zip(names, values, strict=True):
            frames.append(pair_days(sums, v).with_columns(pl.lit(s).alias("signal")))
    pd_ = pl.concat(frames)
    cmap = pl.DataFrame({"e": list(course), "c": list(course.values())})
    pd_ = (
        tie_history(pd_, ties)
        .join(close_min, on=["a", "b", "day"], how="left")
        .join(cmap.rename({"e": "a", "c": "ca"}), on="a", how="left")
        .join(cmap.rename({"e": "b", "c": "cb"}), on="b", how="left")
        .join(dist, on=["a", "b"], how="left")
        .with_columns(
            (pl.col("ca") == pl.col("cb")).alias("same_course"),
            pl.col("close_minutes").fill_null(0),
            split.half_of(pl.col("day")).alias("half"),
        )
        .with_columns(pl.col("close_minutes").cast(pl.Float64).log().alias("log_close_minutes"))
        .drop("ca", "cb")
        .sort("signal", "day", "a", "b")
    )
    for s in SIGNALS:
        q = pd_.filter(pl.col("signal") == s)
        qa[s] = {"pair_days": q.height, "pairs": q.select("a", "b").unique().height,
                 "people": _people(q) if q.height else 0,
                 "by_half": dict(q["half"].value_counts().iter_rows()),
                 "with_survey": int(q["d_trust"].is_not_null().sum()),
                 "prior_tie": int(q["prior_tie"].sum()), "has_follow": int(q["has_follow"].sum()),
                 "tied_later_with_follow": int(q.filter("has_follow")["tied_later"].sum()),
                 "same_course": int(q["same_course"].sum())}  # fmt: skip
    return pd_, qa


def analyse(pd_: pl.DataFrame) -> list[dict]:
    rows = []
    for s in SIGNALS:
        for half in split.HALVES:
            d = split.subset(pd_.filter(pl.col("signal") == s), half)
            for minutes in MINUTE_SETS:
                for r in determinants(d, minutes) + consequence(d, minutes):
                    rows.append({"signal": s, "half": half} | r)
    return rows


def main() -> None:
    t0 = time.time()
    layout = paths.study(cp.STUDY)
    spine = Spine.load(layout.spine)
    out = out_dir()
    pm, counts = ee.load_person_minutes(layout, spine)
    beacon_ok = {f"person:{p}" for p in spine.consented("beacons")}
    people = sorted(set(pm["entity"].to_list()) & beacon_ok)
    pairs = (
        cp.load_all("pairs")
        .filter(pl.col("a").is_in(people) & pl.col("b").is_in(people))
        .select("a", "b", "bin", "max_rssi", "day")
    )
    ties = daily_close_ties(pairs.filter(pl.col("day").is_in(oc.DAYS)), close_rssi=CLOSE_RSSI,
                            min_minutes=TIE_MIN, bin_minutes=oc.BIN_MINUTES)  # fmt: skip
    close_min = (
        pairs.filter(pl.col("max_rssi") >= CLOSE_RSSI)
        .group_by("a", "b", split.camp_day(pl.col("bin")).alias("day"))
        .agg((pl.col("bin").n_unique() * oc.BIN_MINUTES).alias("close_minutes"))
    )
    pairs = pairs.drop("day")
    seen = cp.load_all("seen").filter(pl.col("entity").is_in(people)).select("entity", "bin")
    mem = eg.membranes(layout, spine)
    dist, sds = survey_distances(mem)
    course = cp.course_of(spine)

    qa: dict = {"exploratory": True, "eda_and_beacon_people": len(people),
                "survey_unit": mem.height, "tied_pair_days": ties.height}  # fmt: skip
    results, all_pd = [], []
    for clock in CLOCKS:
        m, _ = ee.minutes_for(pm, counts, clock)
        pd_, pqa = build_pair_days(m, beacon_ok, pairs, seen, ties, close_min, course, dist)
        del m
        qa[clock] = pqa
        print(clock, json.dumps(pqa, indent=2, default=str), flush=True)
        results += [{"clock": clock} | r for r in analyse(pd_)]
        all_pd.append(pd_.with_columns(pl.lit(clock).alias("clock")))
    res = with_verdicts(pl.DataFrame(results, infer_schema_length=None))
    res = res.sort("analysis", "signal", "minutes", "model", "term", "clock", "half")
    res.filter(pl.col("analysis") == "determinants").write_csv(out / "determinants.csv")
    res.filter(pl.col("analysis") == "consequence").write_csv(out / "consequence.csv")
    pds = pl.concat(all_pd)
    pds.write_csv(out / "pair_days.csv")  # per pair-day: private folder only
    pl.concat(
        [
            person_sync(pds.filter(pl.col("clock") == c)).with_columns(pl.lit(c).alias("clock"))
            for c in CLOCKS
        ]
    ).write_csv(out / "person_sync.csv")  # per person, for analysis G: private folder only
    qa["settings"] = {"min_close": MIN_CLOSE, "min_common": MIN_COMMON, "close_rssi": CLOSE_RSSI,
                      "tie_min": TIE_MIN, "follow_days": FOLLOW_DAYS, "last_day": LAST_DAY,
                      "detrend_window": ee.DETREND_WINDOW, "n_boot": N_BOOT,
                      "n_boot_logit": N_BOOT_LOGIT, "seed": SEED, "min_group": MIN_GROUP,
                      "survey_difference_sd": sds, "discovery": split.DISCOVERY,
                      "replication": split.REPLICATION, "clocks": CLOCKS}  # fmt: skip
    qa["runtime_s"] = round(time.time() - t0, 1)
    (out / "qa.json").write_text(json.dumps(qa, indent=2, default=str), encoding="utf-8")
    figure(res, out)
    with pl.Config(tbl_rows=400, tbl_cols=30, tbl_width_chars=260, fmt_str_lengths=30):
        show = ["signal", "minutes", "model", "term", "half", "pair_days", "people", "estimate",
                "lo", "hi", "verdict", "verdict_certain"]  # fmt: skip
        prim = res.filter((pl.col("clock") == "all") & ~pl.col("withheld"))
        print(prim.filter(pl.col("minutes") == "close").select(show))
        print(prim.filter(pl.col("minutes") == "common").select(show))
        print(json.dumps(qa, indent=2, default=str))


# --- figure --------------------------------------------------------------------------------------


def figure(res: pl.DataFrame, out: Path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    ee._style(plt)
    r = res.filter((pl.col("clock") == "all") & (pl.col("minutes") == "close")
                   & ~pl.col("withheld") & pl.col("estimate").is_not_null())  # fmt: skip
    panels = [
        ("determinants", "mean", "const", "mean pair-day synchrony"),
        ("determinants", "course + prior tie", "same_course", "same course (diff. in sync)"),
        ("determinants", "course + prior tie", "prior_tie", "tied before (diff. in sync)"),
        ("determinants", "survey", "d_trust", "trust difference, per SD"),
        ("determinants", "survey", "d_lust", "lust difference, per SD"),
        ("consequence", "logit tied later", "sync_z", "tied later: log-odds per SD sync"),
    ]
    fig, axes = plt.subplots(1, len(panels), figsize=(19, 3.6), sharey=True)
    sigs = list(SIGNALS)
    for ax, (an, model, term, title) in zip(axes, panels, strict=True):
        q = r.filter((pl.col("analysis") == an) & (pl.col("model") == model)
                     & (pl.col("term") == term))  # fmt: skip
        for k, s in enumerate(sigs):
            for j, half in enumerate(split.HALVES):
                z = q.filter((pl.col("signal") == s) & (pl.col("half") == half))
                if z.height == 0:
                    continue
                y = k + (j - 1) * 0.22
                ax.plot([z["lo"][0], z["hi"][0]], [y, y], color=HALF_COLOR[half], lw=2)
                ax.plot(z["estimate"][0], y, "o", color=HALF_COLOR[half], ms=4,
                        label=half if k == 0 else None)  # fmt: skip
        ax.axvline(0, color=INK2, lw=0.8)
        ax.set_title(title, loc="left", fontsize=9)
        ax.set_yticks(range(len(sigs)), [SIGNALS[s][2] for s in sigs])
    fig.legend(*axes[0].get_legend_handles_labels(), fontsize=8, loc="lower right", ncol=3)
    fig.text(0.01, 0.01, "EXPLORATORY · DSA 2026 · aggregates only · pair-days with >= 20 close "
             "minutes · synchrony over close minutes · 95% node bootstrap · clock: all",
             fontsize=8, color=INK2)  # fmt: skip
    fig.tight_layout(rect=(0, 0.05, 1, 1))
    fig.savefig(out / "fig_pair_sync.png", dpi=170)
    plt.close(fig)


if __name__ == "__main__":
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        main()
