"""Exploratory tier, EDA second pass, D: do two wearers' skin-conductance responses start in the
same seconds?

``docs/plans/ongoing/eda-second-pass.md``, analysis D, under the shared rules there.
**Every result here is exploratory**: no error control, two-sided, effects with 95% intervals and
no p-values, distributions rather than people, cells of fewer than ``MIN_GROUP`` people withheld.
Construct: near-simultaneous phasic responses as a trace of a moment two people share
`[inferred: our reading, not signed off by the research team]`. The first pass found weak
minute-level synchrony; this asks whether it lives at the scale of seconds.

**Data.** ``derived/eda/seconds.parquet`` (read per camp day, only the columns needed),
``derived/eda/scr.parquet`` and ``derived/eda/person_minutes.parquet`` (device to person per
minute, exclusion windows) from ``social-energy ingest-eda``; beacon bins from
``copresence_by_phase.py build``. Participants with ``eda`` and ``beacons`` consent. A **valid
second** is ``ok``, not a duplicate, worn, without an artifact, outside exclusion windows, and its
clock was measured (``clock_uncertain`` false). **Clock-certain only, by design**: measured
clocks agree to about a tenth of a second, fallback clocks can be seconds off, which would blur
exactly what this looks for. There is no "all clocks" variant.

**Events** (binary per second, the second of the onset):

* SCR onsets, clean (``ok``, worn, no artifact, clock measured) in a valid second, under the
  first pass's rules (``exploratory_eda.RULES``): **amp >= 0.2 µS** the primary here, **main**
  (every detection) the sensitivity.
* **Movement peaks**, the movement check: per valid second, the change of the accelerometer SD
  from the previous second (``eda.box.jerk`` on the per-second ``motion_sd_g``; both seconds
  valid). A peak is the first second of each run above the person-day's ``JERK_PERCENTILE``th
  percentile of that change: abrupt changes of movement, about as frequent as large SCRs.

**Pairs.** Two people wearing on the same camp day (04:00-04:00 local) with at least
``exploratory_eda.SYNC_MIN_OVERLAP`` common minutes (``exploratory_eda.pair_minutes``, which also
labels each common minute ``close`` / ``heard`` / ``apart`` / ``unknown`` from the pair's 5-minute
beacon bin, as in the first pass). Both directions of a pair are counted (A's onsets against B's
and B's against A's). Only seconds valid for both count, and a pair-day needs at least
``MIN_COMMON_S`` of them.

**Statistic.** The share of A's onsets with a B onset within ``WINDOW_S`` seconds, by the label
of the minute of A's onset, and over the whole overlap (``all``). **Null**: B's series (events and
valid seconds together) shifted circularly by ``SHIFTS`` (30-300 s either way) within the span of
the pair's common valid seconds; each shift recounts A's onsets where both are valid after the
shift. It keeps each person's rate, its bursts and the times of day, and breaks only the
alignment to the second. The **excess** is the observed share over the mean null share (pooled
over pairs: hits / onsets, against the same pooled over every shift); the null's own band is the
spread of the pooled share across shifts.

**Lag profile.** For every lag from ``-MAX_LAG`` to ``+MAX_LAG`` seconds (B's onset minus A's),
the number of B onsets at that lag per A onset, over the same per-shift null: a ratio of 1 is
chance, a peak at 0 is synchrony. Both directions of every pair are pooled, so the profile is
symmetric by construction: one person leading would show as twin peaks at +-lag, not as one.
The ``WINDOW_S`` share is coarse where events are frequent (chance alone fills many windows);
the profile at 0 is the sharper read.

**Movement check.** (1) The same statistic and profile for movement peaks. (2) Among SCR
co-onsets (A onsets with a B onset within ``WINDOW_S``), the share that fall within ``WINDOW_S``
of a **co-movement peak** (an A movement peak with a B movement peak within ``WINDOW_S``), beside
the same share among A's other onsets. (3) The SCR excess again on A's onsets more than
``COMOVE_EXCLUDE_S`` seconds from any co-movement peak (``*_nocomove``).

**Intervals and halves.** Node bootstrap over people (``rhythm.node_bootstrap_weights``: a pair
weighs the product of its two people's draws), ``N_BOOT`` draws, per half. Halves by the camp day
of the seconds (``eda_split``): discovery, replication, all. The ``verdict`` (``eda_split.verdict``)
is on the log excess of each label and on close minus apart (difference of log excesses, on the
same draws).

    uv run --extra analysis python studies/dsa-2026/analyses/eda2_onset_sync.py

Writes ``excess.csv``, ``lag_profile.csv``, ``comovement.csv``, ``verdicts.csv``, ``qa.json`` and
``fig_onset_sync_lags.png`` to
``$SOCIAL_ENERGY_DATA/dsa-2026/derived/analyses/exploratory/eda2/onset_sync/``. Nothing per
person. Memory stays low: one camp day of seconds at a time.
"""

from __future__ import annotations

import json
import resource
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import polars as pl

sys.path.insert(0, str(Path(__file__).parent))
import copresence_by_phase as cp
import eda_split as es
import exploratory_eda as ee

from social_energy import paths
from social_energy.eda.box import jerk
from social_energy.rhythm import node_bootstrap_weights
from social_energy.spine import Spine

SLUG = "exploratory/eda2/onset_sync"
MIN_GROUP = ee.MIN_GROUP
#: A co-onset: B's onset within this many seconds of A's.
WINDOW_S = 3
#: Lag profile from -MAX_LAG to +MAX_LAG seconds.
MAX_LAG = 20
LAGS = np.arange(-MAX_LAG, MAX_LAG + 1)
#: Circular shifts of B for the null, in seconds, both ways.
SHIFTS = tuple(s * d for d in (-1, 1) for s in range(30, 301, 2))
#: A movement peak: first second of a run above this percentile of the person-day's change.
JERK_PERCENTILE = 98.0
#: A pair-day needs this many seconds valid for both (twice the largest shift).
MIN_COMMON_S = 600
#: SCR onsets this close to a co-movement peak leave the ``*_nocomove`` variant.
COMOVE_EXCLUDE_S = 5
N_BOOT = 2000
#: Shifts counted together (bounds memory: the lag pairs grow with shifts x onsets).
SHIFT_CHUNK = 32
SEED = 20261029
LABELS = ("close", "heard", "apart", "unknown")
CELLS = (*LABELS, "all")
CODE = {k: i for i, k in enumerate(LABELS)}
SCR_RULES = {"scr_amp02": ee.RULES["amp02"], "scr_main": ee.RULES["main"]}
SIGNALS = ("scr_amp02", "scr_main", "jerk", "scr_amp02_nocomove", "scr_main_nocomove")
SIGNAL_LABEL = {
    "scr_amp02": "SCR onsets, amp >= 0.2 µS",
    "scr_main": "SCR onsets, main",
    "jerk": "movement peaks",
    "scr_amp02_nocomove": "SCR onsets >= 0.2 µS, away from co-movement",
    "scr_main_nocomove": "SCR onsets main, away from co-movement",
}
DAY_S = 86400


def out_dir() -> Path:
    d = paths.study(cp.STUDY).derived / "analyses" / SLUG
    d.mkdir(parents=True, exist_ok=True)
    return d


# --- events --------------------------------------------------------------------------------------


def movement_peaks(sd: np.ndarray, percentile: float = JERK_PERCENTILE) -> np.ndarray:
    """Seconds (indices) of movement peaks in a per-second accelerometer-SD series (NaN where the
    second is not valid): the first second of each run where the change from the previous second
    exceeds the series' ``percentile``-th percentile of that change."""
    j = jerk(np.asarray(sd, float)[:, None])
    j[0] = np.nan
    if not np.isfinite(j).any():
        return np.empty(0, dtype=np.int64)
    thr = np.nanpercentile(j, percentile)
    above = np.nan_to_num(j, nan=-np.inf) > thr
    start = above & ~np.concatenate([[False], above[:-1]])
    return np.flatnonzero(start).astype(np.int64)


def near(t: np.ndarray, ref: np.ndarray, radius: int) -> np.ndarray:
    """For each time in ``t``: is any time of ``ref`` within ``radius`` seconds?"""
    r = np.sort(np.asarray(ref, np.int64))
    t = np.asarray(t, np.int64)
    if r.size == 0:
        return np.zeros(t.size, dtype=bool)
    return np.searchsorted(r, t + radius, side="right") > np.searchsorted(r, t - radius)


# --- counting under shifts -----------------------------------------------------------------------


def shift_counts(a_on, a_lab, b_on, a_valid, b_valid, lo, hi, offsets, *, chunk=SHIFT_CHUNK,
                 **kw) -> dict[str, np.ndarray]:  # fmt: skip
    """:func:`_shift_counts` over ``offsets`` in chunks of ``chunk``, so memory stays flat."""
    off = list(offsets)
    parts = [_shift_counts(a_on, a_lab, b_on, a_valid, b_valid, lo, hi, off[i : i + chunk], **kw)
             for i in range(0, len(off), chunk)]  # fmt: skip
    return {k: np.concatenate([p[k] for p in parts]) for k in parts[0]}


def _shift_counts(
    a_on: np.ndarray,
    a_lab: np.ndarray,
    b_on: np.ndarray,
    a_valid: np.ndarray,
    b_valid: np.ndarray,
    lo: int,
    hi: int,
    offsets,
    *,
    n_lab: int = len(LABELS),
    window: int = WINDOW_S,
    max_lag: int = MAX_LAG,
) -> dict[str, np.ndarray]:
    """A's events against B's, with B shifted circularly by each of ``offsets`` within
    ``[lo, hi)``.

    ``a_on`` / ``b_on``: event seconds (unique, each in its own person's valid seconds);
    ``a_lab``: a label code per A event; ``a_valid`` / ``b_valid``: boolean per second. Under a
    shift ``s`` B's events and valid seconds move together to ``lo + (x - lo + s) mod (hi - lo)``;
    an A event counts where B is valid after the shift, a B event where A is valid. Offset 0 is
    the observed alignment. Returns ``onsets`` and ``hits`` (offsets x labels: A events counted,
    and those with a B event within ``window`` s) and ``lags`` (offsets x labels x lags: B events
    at each lag ``-max_lag..max_lag`` from an A event).
    """
    off = np.asarray(offsets, dtype=np.int64)[:, None]
    n_s, n_lag = off.shape[0], 2 * max_lag + 1
    length = hi - lo
    ma = (a_on >= lo) & (a_on < hi)
    a, lab = np.asarray(a_on, np.int64)[ma], np.asarray(a_lab, np.int64)[ma]
    b = np.asarray(b_on, np.int64)
    b = b[(b >= lo) & (b < hi)]
    out = {"onsets": np.zeros((n_s, n_lab)), "hits": np.zeros((n_s, n_lab)),
           "lags": np.zeros((n_s, n_lab, n_lag))}  # fmt: skip
    if a.size == 0 or length <= 0:
        return out
    a_keep = b_valid[lo + (a[None, :] - lo - off) % length]
    bs = lo + (b[None, :] - lo + off) % length
    b_keep = a_valid[bs]
    gap = length + 4 * max_lag + 4
    row = np.arange(n_s, dtype=np.int64)[:, None] * gap
    keys = np.sort((bs + row)[b_keep])
    q = a[None, :] + row
    rows = np.broadcast_to(np.arange(n_s)[:, None], a_keep.shape)
    labs = np.broadcast_to(lab[None, :], a_keep.shape)
    cell = (rows * n_lab + labs)[a_keep]
    qk = q[a_keep]
    hit = np.searchsorted(keys, qk + window, side="right") > np.searchsorted(keys, qk - window)
    out["onsets"] = np.bincount(cell, minlength=n_s * n_lab).reshape(n_s, n_lab).astype(float)
    out["hits"] = (
        np.bincount(cell, weights=hit.astype(float), minlength=n_s * n_lab)
        .reshape(n_s, n_lab)
        .astype(float)
    )
    left = np.searchsorted(keys, qk - max_lag)
    cnt = np.searchsorted(keys, qk + max_lag, side="right") - left
    total = int(cnt.sum())
    if total:
        which = np.repeat(np.arange(qk.size), cnt)
        start = np.repeat(np.cumsum(cnt) - cnt, cnt)
        partner = left[which] + (np.arange(total) - start)
        diff = keys[partner] - qk[which]
        idx = cell[which] * n_lag + diff + max_lag
        out["lags"] = (
            np.bincount(idx, minlength=n_s * n_lab * n_lag).reshape(n_s, n_lab, n_lag).astype(float)
        )
    return out


def comovement_counts(
    a_on: np.ndarray,
    a_lab: np.ndarray,
    b_on: np.ndarray,
    cm: np.ndarray,
    valid: np.ndarray,
    *,
    n_lab: int = len(LABELS),
    window: int = WINDOW_S,
) -> np.ndarray:
    """Observed alignment only: per label, [co-onsets near a co-movement peak, co-onsets, other
    onsets near a co-movement peak, other onsets]. ``valid``: both people valid per second."""
    keep = valid[a_on]
    a, lab = a_on[keep], a_lab[keep]
    b = b_on[valid[b_on]]
    hit = near(a, b, window)
    by = near(a, cm, window)
    out = np.zeros((n_lab, 4))
    for k, w in enumerate((hit & by, hit, ~hit & by, ~hit)):
        out[:, k] = np.bincount(lab, weights=w.astype(float), minlength=n_lab)
    return out


# --- one camp day --------------------------------------------------------------------------------


def day_bounds(day) -> tuple[datetime, datetime]:
    tz = ZoneInfo(es.TZ)
    start = datetime(day.year, day.month, day.day, es.DAY_START_H, tzinfo=tz)
    end = start + timedelta(days=1)
    return start.astimezone(ZoneInfo("UTC")), end.astimezone(ZoneInfo("UTC"))


def load_day(layout, owners: pl.DataFrame, day) -> dict:
    """Valid seconds, movement and SCR onsets per person for one camp day (one day of seconds in
    memory). ``owners``: ``device``, ``minute``, ``entity`` of eligible, non-excluded minutes."""
    d = layout.derived / "eda"
    t0, t1 = day_bounds(day)
    win = (pl.col("t") >= t0) & (pl.col("t") < t1)
    sec = (
        pl.scan_parquet(d / "seconds.parquet")
        .select(
            "device", "t", "motion_sd_g", "ok", "duplicate", "worn", "artifact", "clock_uncertain"
        )
        .filter(win)
        .filter(
            pl.col("ok")
            & ~pl.col("duplicate")
            & pl.col("worn")
            & ~pl.col("artifact")
            & ~pl.col("clock_uncertain").fill_null(True)
        )
        .select("device", "t", "motion_sd_g")
        .collect()
    )
    n_seconds = sec.height
    sec = sec.with_columns(pl.col("t").dt.truncate("1m").alias("minute")).join(
        owners, on=["device", "minute"]
    )
    sec = sec.with_columns(((pl.col("t") - t0).dt.total_seconds()).alias("s"))
    scr = (
        pl.scan_parquet(d / "scr.parquet")
        .select("device", "onset", "amplitude_us", "ok", "worn", "artifact", "clock_uncertain")
        .filter((pl.col("onset") >= t0) & (pl.col("onset") < t1))
        .filter(
            pl.col("ok")
            & pl.col("worn")
            & ~pl.col("artifact")
            & ~pl.col("clock_uncertain").fill_null(True)
        )
        .collect()
        .with_columns(pl.col("onset").dt.truncate("1m").alias("minute"))
        .join(owners, on=["device", "minute"])
        .with_columns(((pl.col("onset") - t0).dt.total_seconds()).alias("s"))
    )
    people: dict[str, dict] = {}
    for (ent,), g in sec.group_by("entity"):
        s = g["s"].to_numpy()
        valid = np.zeros(DAY_S, dtype=bool)
        valid[s] = True
        sd = np.full(DAY_S, np.nan)
        sd[s] = g["motion_sd_g"].cast(pl.Float64).fill_null(np.nan).to_numpy()
        ev = {"jerk": movement_peaks(sd)}
        sc = scr.filter(pl.col("entity") == ent)
        for sig, amp in SCR_RULES.items():
            on = np.unique(sc.filter(pl.col("amplitude_us") >= amp)["s"].to_numpy())
            ev[sig] = on[valid[on]] if on.size else on.astype(np.int64)
        people[ent] = {"valid": valid, "events": ev}
    qa = {"valid_seconds_any_owner": n_seconds, "valid_seconds": sec.height,
          "people": len(people),
          "events": {k: int(sum(p["events"][k].size for p in people.values()))
                     for k in ("jerk", *SCR_RULES)}}  # fmt: skip
    return {"people": people, "t0": t0, "qa": qa}


def day_pairs(people: dict, pairs: pl.DataFrame, seen: pl.DataFrame, t0, day) -> pl.DataFrame:
    """Labelled common minutes of the day's pairs, through ``exploratory_eda.pair_minutes``."""
    rows = []
    for ent, p in people.items():
        mins = np.unique(np.flatnonzero(p["valid"]) // 60)
        rows.append(pl.DataFrame({"entity": ent, "m": mins}))
    if not rows:
        return pl.DataFrame()
    sig = (
        pl.concat(rows)
        .with_columns((pl.lit(t0) + pl.duration(minutes=pl.col("m"))).alias("minute"))
        .with_columns(
            pl.lit(day).alias("day"),
            pl.col("minute").dt.truncate(cp.BIN).alias("bin"),
            pl.lit(1.0).alias("on"),
        )
    )
    ents = list(people)
    t1 = t0 + timedelta(days=1)
    in_day = (pl.col("bin") >= t0) & (pl.col("bin") < t1)
    pairs = pairs.filter(in_day & pl.col("a").is_in(ents) & pl.col("b").is_in(ents))
    seen = seen.filter(in_day & pl.col("entity").is_in(ents))
    return ee.pair_minutes(sig, pairs, seen, signal="on").with_columns(
        ((pl.col("minute") - pl.lit(t0)).dt.total_minutes()).alias("m")
    )


def run_day(data: dict, pm_: pl.DataFrame, day) -> tuple[list[dict], dict, dict]:
    """Every ordered pair of the day under every signal: pair records, per-shift totals per label
    (for the null band) and QA."""
    people = data["people"]
    recs: list[dict] = []
    band = {s: np.zeros((len(SHIFTS), len(LABELS), 2)) for s in SIGNALS}
    offsets = (0, *SHIFTS)
    n_pairs = 0
    for (a, b), g in pm_.group_by("a", "b"):
        lab_min = np.full(DAY_S // 60, CODE["unknown"], dtype=np.int64)
        lab_min[g["m"].to_numpy()] = g["label"].replace_strict(CODE).to_numpy()
        va, vb = people[a]["valid"], people[b]["valid"]
        both = va & vb
        idx = np.flatnonzero(both)
        if idx.size < MIN_COMMON_S:
            continue
        n_pairs += 1
        lo, hi = int(idx[0]), int(idx[-1]) + 1
        for x, y, vx, vy in ((a, b, va, vb), (b, a, vb, va)):
            ex, ey = people[x]["events"], people[y]["events"]
            jx, jy = ex["jerk"], ey["jerk"]
            jx_in, jy_in = jx[both[jx]], jy[both[jy]]
            cm = jx_in[near(jx_in, jy_in, WINDOW_S)]
            for sig in SIGNALS:
                base = sig.removesuffix("_nocomove")
                on = ex[base]
                if sig.endswith("_nocomove"):
                    on = on[~near(on, cm, COMOVE_EXCLUDE_S)]
                lab = lab_min[on // 60]
                c = shift_counts(on, lab, ey[base], vx, vy, lo, hi, offsets)
                band[sig][:, :, 0] += c["onsets"][1:]
                band[sig][:, :, 1] += c["hits"][1:]
                rec = {"day": day, "a": x, "b": y, "signal": sig,
                       "obs_on": c["onsets"][0], "obs_hit": c["hits"][0],
                       "null_on": c["onsets"][1:].sum(0), "null_hit": c["hits"][1:].sum(0),
                       "lag_obs": c["lags"][0], "lag_null": c["lags"][1:].sum(0)}  # fmt: skip
                if sig in SCR_RULES:
                    rec["comove"] = comovement_counts(on, lab, ey[base], cm, both)
                recs.append(rec)
    return recs, band, {"pairs": n_pairs}


# --- aggregation ---------------------------------------------------------------------------------


def _with_all(x: np.ndarray) -> np.ndarray:
    """Append the ``all`` cell (sum over labels) on the label axis (axis 1)."""
    return np.concatenate([x, x.sum(1, keepdims=True)], axis=1)


def _ratio(num_h, num_n, den_h, den_n):
    with np.errstate(invalid="ignore", divide="ignore"):
        return (num_h / num_n) / (den_h / den_n)


def _interval(draws: np.ndarray) -> tuple[float, float]:
    d = draws[np.isfinite(draws)]
    if d.size == 0:
        return float("nan"), float("nan")
    lo, hi = np.quantile(d, [0.025, 0.975])
    return float(lo), float(hi)


def summarise(recs: list[dict], band: dict, half: str, *, n_boot: int = N_BOOT,
              seed: int = SEED) -> dict[str, list[dict]]:  # fmt: skip
    """Excess, lag profile and co-movement rows of one half; unordered person pairs, node
    bootstrap over the half's people."""
    rows: dict[str, list[dict]] = {"excess": [], "lags": [], "comove": []}
    if not recs:
        return rows
    people = sorted({r["a"] for r in recs} | {r["b"] for r in recs})
    code = {p: i for i, p in enumerate(people)}
    w = np.stack(list(node_bootstrap_weights(len(people), n_boot=n_boot, seed=seed))).astype(float)
    for sig in SIGNALS:
        rs = [r for r in recs if r["signal"] == sig]
        if not rs:
            continue
        keys = sorted({tuple(sorted((r["a"], r["b"]))) for r in rs})
        kix = {k: i for i, k in enumerate(keys)}
        n_p = len(keys)
        acc = {f: np.zeros((n_p, *np.shape(rs[0][f]))) for f in
               ("obs_on", "obs_hit", "null_on", "null_hit", "lag_obs", "lag_null")}  # fmt: skip
        if "comove" in rs[0]:
            acc["comove"] = np.zeros((n_p, *rs[0]["comove"].shape))
        for r in rs:
            i = kix[tuple(sorted((r["a"], r["b"])))]
            for f in acc:
                acc[f][i] += r[f]
        acc = {f: _with_all(v) for f, v in acc.items()}
        ia = np.array([code[k[0]] for k in keys])
        ib = np.array([code[k[1]] for k in keys])
        pw = w[:, ia] * w[:, ib]
        b_on, b_hit = pw @ acc["obs_on"], pw @ acc["obs_hit"]
        b_non, b_nhit = pw @ acc["null_on"], pw @ acc["null_hit"]
        with np.errstate(divide="ignore"):
            b_log = np.log(_ratio(b_hit, b_on, b_nhit, b_non))
        tot = {f: acc[f].sum(0) for f in acc}
        bs = band.get(sig, np.zeros((len(SHIFTS), len(LABELS), 2)))
        logs = {}
        for c, cell in enumerate(CELLS):
            on = acc["obs_on"][:, c]
            in_cell = on > 0
            ppl = len(set(ia[in_cell]) | set(ib[in_cell]))
            small = ppl < MIN_GROUP
            row = {"half": half, "signal": sig, "label": cell, "pairs": int(in_cell.sum()),
                   "people": ppl, "suppressed": small}  # fmt: skip
            if not small:
                band_c = bs.sum(1) if cell == "all" else bs[:, c]
                with np.errstate(invalid="ignore", divide="ignore"):
                    shares = band_c[:, 1] / band_c[:, 0]
                share = tot["obs_hit"][c] / tot["obs_on"][c]
                null_share = tot["null_hit"][c] / tot["null_on"][c]
                ratio = share / null_share
                lo, hi = _interval(b_log[:, c])
                logs[cell] = (np.log(ratio), b_log[:, c])
                row |= {"onsets": int(tot["obs_on"][c]), "co_onsets": int(tot["obs_hit"][c]),
                        "share": share, "null_share": null_share,
                        "null_band_lo": float(np.nanquantile(shares, 0.025)),
                        "null_band_hi": float(np.nanquantile(shares, 0.975)),
                        "shifts_at_least_observed": float(np.nanmean(shares >= share)),
                        "excess": ratio, "excess_lo": float(np.exp(lo)),
                        "excess_hi": float(np.exp(hi)), "log_excess": float(np.log(ratio)),
                        "log_lo": lo, "log_hi": hi}  # fmt: skip
                lo_d = pw @ acc["lag_obs"][:, c, :] / b_on[:, [c]]
                ln_d = pw @ acc["lag_null"][:, c, :] / b_non[:, [c]]
                with np.errstate(invalid="ignore", divide="ignore"):
                    lr_d = lo_d / ln_d
                    obs_r = tot["lag_obs"][c] / tot["obs_on"][c]
                    nul_r = tot["lag_null"][c] / tot["null_on"][c]
                for j, lag in enumerate(LAGS):
                    l_lo, l_hi = _interval(lr_d[:, j])
                    rows["lags"].append({"half": half, "signal": sig, "label": cell,
                                         "lag": int(lag), "per_onset": float(obs_r[j]),
                                         "null_per_onset": float(nul_r[j]),
                                         "ratio": float(obs_r[j] / nul_r[j]),
                                         "ratio_lo": l_lo, "ratio_hi": l_hi})  # fmt: skip
                if "comove" in acc:
                    cmv = acc["comove"][:, c, :]
                    bc = pw @ cmv
                    with np.errstate(invalid="ignore", divide="ignore"):
                        s_co, s_ot = bc[:, 0] / bc[:, 1], bc[:, 2] / bc[:, 3]
                    t = cmv.sum(0)
                    e_co, e_ot = t[0] / t[1], t[2] / t[3]
                    rows["comove"].append({
                        "half": half, "signal": sig, "label": cell, "people": ppl,
                        "co_onsets": int(t[1]), "other_onsets": int(t[3]),
                        "co_onsets_near_comove": e_co,
                        "co_lo": _interval(s_co)[0], "co_hi": _interval(s_co)[1],
                        "other_near_comove": e_ot,
                        "other_lo": _interval(s_ot)[0], "other_hi": _interval(s_ot)[1],
                        "difference": e_co - e_ot,
                        "diff_lo": _interval(s_co - s_ot)[0], "diff_hi": _interval(s_co - s_ot)[1],
                    })  # fmt: skip
            rows["excess"].append(row)
        if "close" in logs and "apart" in logs:
            est = logs["close"][0] - logs["apart"][0]
            lo, hi = _interval(logs["close"][1] - logs["apart"][1])
            rows["excess"].append({"half": half, "signal": sig, "label": "close minus apart",
                                   "suppressed": False, "log_excess": float(est), "log_lo": lo,
                                   "log_hi": hi, "excess": float(np.exp(est)),
                                   "excess_lo": float(np.exp(lo)),
                                   "excess_hi": float(np.exp(hi))})  # fmt: skip
    return rows


def verdicts(excess: pl.DataFrame) -> pl.DataFrame:
    """One verdict per signal and label from the discovery and replication log excesses."""
    out = []
    est = excess.filter(pl.col("log_excess").is_not_null())
    for (sig, lab), g in est.group_by("signal", "label", maintain_order=True):
        by = {r["half"]: r for r in g.iter_rows(named=True)}
        d, r, a = by.get("discovery"), by.get("replication"), by.get("all")
        v = "not estimable"
        if d and r:
            v = es.verdict(d["log_excess"], d["log_lo"], d["log_hi"], r["log_excess"],
                           r["log_lo"], r["log_hi"])  # fmt: skip
        row = {"signal": sig, "label": lab, "verdict": v}
        for name, x in (("disc", d), ("rep", r), ("all", a)):
            for k in ("log_excess", "log_lo", "log_hi"):
                row[f"{name}_{k}"] = x[k] if x else None
        out.append(row)
    return pl.DataFrame(out, infer_schema_length=None)


# --- main ----------------------------------------------------------------------------------------


def main() -> None:
    t_start = time.time()
    layout = paths.study(cp.STUDY)
    spine = Spine.load(layout.spine)
    out = out_dir()
    participants = {p.ref for p in spine.people if p.role == "participant"}
    eligible = (
        participants
        & {f"person:{p}" for p in spine.consented("eda")}
        & {f"person:{p}" for p in spine.consented("beacons")}
    )
    owners = (
        pl.scan_parquet(layout.derived / "eda" / "person_minutes.parquet")
        .select("entity", "device", "minute", "excluded")
        .filter(pl.col("entity").is_in(list(eligible)) & ~pl.col("excluded"))
        .select("device", "minute", "entity")
        .collect()
    )
    elig = list(eligible)
    pairs = (
        cp.load_all("pairs")
        .filter(pl.col("a").is_in(elig) & pl.col("b").is_in(elig))
        .select("a", "b", "bin", "max_rssi")
    )
    seen = cp.load_all("seen").filter(pl.col("entity").is_in(elig)).select("entity", "bin")
    days = sorted(es.DISCOVERY + es.REPLICATION)
    recs: list[dict] = []
    bands: dict = {}
    qa: dict = {"days": {}}
    for day in days:
        data = load_day(layout, owners, day)
        pm_ = day_pairs(data["people"], pairs, seen, data["t0"], day)
        r, band, dqa = ([], {}, {"pairs": 0}) if pm_.is_empty() else run_day(data, pm_, day)
        recs += r
        bands[day] = band
        qa["days"][str(day)] = data["qa"] | dqa
        print(day, qa["days"][str(day)], f"{time.time() - t_start:.0f}s", flush=True)
        del data
    tables: dict[str, list[dict]] = {"excess": [], "lags": [], "comove": []}
    for half in es.HALVES:
        keep = {"discovery": es.DISCOVERY, "replication": es.REPLICATION}.get(half, tuple(days))
        hr = [r for r in recs if r["day"] in keep]
        hb = {s: sum(bands[d][s] for d in keep if bands.get(d)) for s in SIGNALS}
        hb = {s: v for s, v in hb.items() if isinstance(v, np.ndarray)}
        for k, v in summarise(hr, hb, half).items():
            tables[k] += v
    excess = pl.DataFrame(tables["excess"], infer_schema_length=None)
    ver = verdicts(excess)
    excess = excess.join(ver.select("signal", "label", "verdict"), on=["signal", "label"],
                         how="left")  # fmt: skip
    lags = pl.DataFrame(tables["lags"], infer_schema_length=None)
    comove = pl.DataFrame(tables["comove"], infer_schema_length=None)
    excess.write_csv(out / "excess.csv")
    lags.write_csv(out / "lag_profile.csv")
    comove.write_csv(out / "comovement.csv")
    ver.write_csv(out / "verdicts.csv")
    qa["totals"] = {
        "pair_days": int(sum(d["pairs"] for d in qa["days"].values())),
        "people": len({r["a"] for r in recs}),
        "eligible_people": len(eligible),
    }
    qa["settings_used"] = {"window_s": WINDOW_S, "max_lag": MAX_LAG, "shifts": [min(SHIFTS),
                           max(SHIFTS), len(SHIFTS)], "jerk_percentile": JERK_PERCENTILE,
                           "comove_exclude_s": COMOVE_EXCLUDE_S, "n_boot": N_BOOT, "seed": SEED,
                           "min_group": MIN_GROUP, "min_overlap_min": ee.SYNC_MIN_OVERLAP,
                           "rules": SCR_RULES, "close_rssi": ee.CLOSE_RSSI,
                           "clock": "certain only"}  # fmt: skip
    qa["runtime_s"] = round(time.time() - t_start, 1)
    qa["peak_rss_mb"] = round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 1)
    (out / "qa.json").write_text(json.dumps(qa, indent=2, default=str), encoding="utf-8")
    figure(lags, out)
    with pl.Config(tbl_rows=200, tbl_cols=30, tbl_width_chars=260):
        print(ver)
    print(json.dumps(qa["totals"] | {"runtime_s": qa["runtime_s"],
                                     "peak_rss_mb": qa["peak_rss_mb"]}))  # fmt: skip


def figure(lags: pl.DataFrame, out: Path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    ee._style(plt)
    colours = {"close": ee.ORANGE, "heard": ee.BLUE, "apart": ee.GRAY, "all": ee.INK}
    sigs = ("scr_amp02", "jerk")
    fig, axes = plt.subplots(2, 3, figsize=(15, 7), sharex=True)
    for i, sig in enumerate(sigs):
        for j, half in enumerate(es.HALVES):
            ax = axes[i, j]
            for lab, col in colours.items():
                q = lags.filter((pl.col("signal") == sig) & (pl.col("half") == half)
                                & (pl.col("label") == lab)).sort("lag")  # fmt: skip
                if q.height == 0:
                    continue
                x = q["lag"].to_numpy()
                if lab in ("close", "all"):
                    ax.fill_between(x, q["ratio_lo"].to_numpy(), q["ratio_hi"].to_numpy(),
                                    color=col, alpha=0.12, lw=0)  # fmt: skip
                ax.plot(x, q["ratio"].to_numpy(), "o-", ms=2.5, lw=1.2, color=col,
                        label="all overlap" if lab == "all" else lab)  # fmt: skip
            ax.axhline(1, color=ee.INK2, lw=0.8)
            ax.axvline(0, color=ee.INK2, lw=0.6, ls=":")
            ax.set_title(f"{SIGNAL_LABEL[sig]} · {half}", loc="left", fontsize=10)
            if i == 1:
                ax.set_xlabel("partner's event minus own (s)")
        axes[i, 0].set_ylabel("events per own event, over shift null")
    axes[0, 0].legend(fontsize=8)
    fig.text(0.01, 0.01, "EXPLORATORY · DSA 2026 · aggregates only · clock-certain seconds · "
             "95% node bootstrap over people (close, all)", fontsize=8, color=ee.INK2)  # fmt: skip
    fig.tight_layout(rect=(0, 0.03, 1, 1))
    fig.savefig(out / "fig_onset_sync_lags.png", dpi=170)
    plt.close(fig)


if __name__ == "__main__":
    main()
