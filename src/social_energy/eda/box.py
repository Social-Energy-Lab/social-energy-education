"""Box co-motion as a clock anchor (docs/context/instruments/eda.md, "Clock").

After hand-in, and on some mornings before hand-out, the units lie together in one box and
keep recording. Every bump of the box reaches all their accelerometers at one true moment,
so the lag between two units' motion is the difference of their clock errors, to a few
hundredths of a second. Against units whose clocks the sync records measured, that gives an
error measurement (an *anchor*) for a unit whose clock only had the fallback rate.

1. **Stretches** (``find_stretches``): per run, the off-skin stretch before its first wear
   (the morning box) and after its last (the evening box), as motion jerk on a ``hz`` grid of
   device time. A run never on skin gives its first and last ``max_stretch_s``.
2. **Pairs** (``box_edges``): every two stretches of different units that overlap on their
   corrected clocks are cross-correlated over ``window_s`` sub-windows (``clock.window_lags``).
   A pair counts when at least ``min_windows`` confident windows lie on one robust line
   (within ``agree_s``; the lag may drift slowly while a fallback clock is still wrong). Its
   lag is the residual of one unit's corrected clock minus the other's, at one moment.
3. **Joint solve** (``solve_offsets``, ``solve``): the units' residuals by least squares
   over the pairs of each connected group, dropping the worst pair while any misses the
   solution by more than ``closure_s``. The zero is the median of the units whose clock is
   measured there (sync records, not extrapolated), the reference units among them where
   there are any (they define time); a measured unit more than
   ``tolerance_s`` off it is a disagreement. An unmeasured unit gets an anchor only if it
   sits in a closed triangle of kept pairs and the group has a measured unit.
4. ``ClockModel(..., anchors=...)`` uses the anchors; ``leave_one_out`` validates them on
   runs the records measured, by pretending they had none.

Residuals are relative to whatever model placed the stretches; anchors carry the absolute
error (model error + residual), so they hold for any model, and a pair's lag can be carried
over to another model exactly (``solve`` does this, which makes leave-one-out cheap).
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations
from typing import Any

import numpy as np
import polars as pl

from .clock import ClockConfig, ClockModel, robust_line, window_lags


@dataclass(frozen=True)
class BoxConfig:
    enabled: bool = True
    hz: float = 64.0
    contact_us: float = 0.05  # skin contact, as for wear
    min_contact_s: float = 60.0  # contact at least this long is wear, not handling
    min_stretch_s: float = 900.0
    max_stretch_s: float = 7200.0
    window_s: float = 300.0
    max_lag_s: float = 120.0  # largest residual searched (a fallback clock's error)
    min_peak: float = 0.2
    min_ratio: float = 1.5
    min_windows: int = 3
    agree_s: float = 0.25
    max_drift: float = 0.002  # residual drift (s per s) a pair's windows may show
    closure_s: float = 0.25
    tolerance_s: float = 1.0
    #: The first search widens each bump by this (a fallback clock's lag drifts within a
    #: window); the second, on the clocks the first anchored, searches only ``refine_lag_s``.
    smooth_s: float = 0.5
    refine_lag_s: float = 5.0


@dataclass
class BoxStretch:
    """A run's motion jerk while off skin, on a grid of its own device clock."""

    device: str
    run: str
    position: str  # "head" (before the first wear) | "tail" (after the last) | "whole"
    t0: float  # device time of the first grid sample
    hz: float
    jerk: np.ndarray  # float32; NaN where no record

    @property
    def t1(self) -> float:
        return self.t0 + len(self.jerk) / self.hz


def jerk(acc: np.ndarray) -> np.ndarray:
    """Magnitude of the change in acceleration between consecutive records."""
    a = np.asarray(acc, float)
    d = np.diff(a, axis=0, prepend=a[:1])
    return np.sqrt((d**2).sum(axis=1))


def find_stretches(
    device: str,
    run: str,
    t_dev: np.ndarray,
    us: np.ndarray,
    acc: np.ndarray,
    bad: np.ndarray,
    config: BoxConfig,
) -> list[BoxStretch]:
    """The run's off-skin stretches next to its wear (see the module docstring). ``t_dev``:
    device time per record (NaN unplaced), ``us`` conductance, ``acc`` raw accelerometer."""
    good = np.isfinite(t_dev) & ~np.asarray(bad, bool)
    if good.sum() < 2:
        return []
    t = t_dev[good]
    lo, hi = float(t.min()), float(t.max())
    sec = np.floor(t - lo).astype(np.int64)
    n = int(sec.max()) + 1
    on = np.nan_to_num(np.asarray(us, float)[good], nan=0.0) >= config.contact_us
    contact = 2 * np.bincount(sec, on, minlength=n) > np.maximum(np.bincount(sec, minlength=n), 1)
    step = np.diff(np.r_[0, contact.astype(np.int8), 0])
    starts, ends = np.flatnonzero(step == 1), np.flatnonzero(step == -1)
    wear = (ends - starts) >= config.min_contact_s
    m = config.max_stretch_s
    if wear.any():
        first, last = lo + starts[wear][0], lo + ends[wear][-1]
        spans = [("head", max(lo, first - m), first), ("tail", last, min(hi, last + m))]
    elif hi - lo <= 2 * m:
        spans = [("whole", lo, hi)]
    else:
        spans = [("head", lo, lo + m), ("tail", hi - m, hi)]
    j = jerk(np.asarray(acc)[good])
    out = []
    for pos, a, b in spans:
        if b - a < config.min_stretch_s:
            continue
        inside = (t >= a) & (t < b)
        size = int(np.ceil((b - a) * config.hz))
        grid = np.full(size, np.nan, np.float32)
        i = np.clip(((t[inside] - a) * config.hz).astype(np.int64), 0, size - 1)
        np.fmax.at(grid, i, j[inside].astype(np.float32))
        out.append(BoxStretch(device, run, pos, float(a), config.hz, grid))
    return out


EDGES_SCHEMA = {
    "a_device": pl.String,
    "a_run": pl.String,
    "a_position": pl.String,
    "b_device": pl.String,
    "b_run": pl.String,
    "b_position": pl.String,
    "t": pl.Float64,  # corrected time of the pair's moment (a's clock)
    "lag_s": pl.Float64,  # residual of b minus residual of a, under the placing model
    "windows": pl.Int64,
    "tau_a": pl.Float64,  # device times of that moment
    "tau_b": pl.Float64,
    "est_a": pl.Float64,  # the placing model's errors there
    "est_b": pl.Float64,
}


def _placement(model: ClockModel, s: BoxStretch, step: float = 10.0):
    tau = np.arange(s.t0, s.t1 + step, step)
    c, _ = model.correct(s.device, s.run, tau)
    return tau, c


def _on_grid(s: BoxStretch, tau: np.ndarray, c: np.ndarray, lo: float, hi: float) -> np.ndarray:
    size = int((hi - lo) * s.hz)
    out = np.full(size, np.nan, np.float32)
    ct = np.interp(s.t0 + np.arange(len(s.jerk)) / s.hz, tau, c)
    m = (ct >= lo) & (ct < hi) & np.isfinite(s.jerk)
    i = np.clip(((ct[m] - lo) * s.hz).astype(np.int64), 0, size - 1)
    np.fmax.at(out, i, s.jerk[m])
    return out


def _widen(x: np.ndarray, k: int) -> np.ndarray:
    """Running maximum over ``k`` samples (NaN only where all are)."""
    if k <= 1:
        return x
    y = np.where(np.isnan(x), -np.inf, x)
    y = np.pad(y, (k // 2, k - 1 - k // 2), constant_values=-np.inf)
    out = np.lib.stride_tricks.sliding_window_view(y, k).max(axis=1)
    out[np.isneginf(out)] = np.nan
    return out.astype(np.float32)


def box_edges(
    model: ClockModel,
    stretches: list[BoxStretch],
    config: BoxConfig,
    max_lag_s: float | None = None,
    smooth_s: float = 0.0,
) -> pl.DataFrame:
    """Every confident pair of stretches (see the module docstring), placed by ``model``,
    searched within ``max_lag_s`` (default ``config.max_lag_s``). ``smooth_s`` widens each
    bump by a running maximum first, so that a lag drifting within a window (a clock still
    off in rate) keeps one peak."""
    max_lag_s = config.max_lag_s if max_lag_s is None else max_lag_s
    k = round(smooth_s * config.hz)
    placed = [_placement(model, s) for s in stretches]
    need = config.min_windows * config.window_s + 2 * max_lag_s
    ref = model.config.reference_to_utc_s
    rows = []
    for i, j in combinations(range(len(stretches)), 2):
        a, b = stretches[i], stretches[j]
        if a.device == b.device:
            continue
        (ta, ca), (tb, cb) = placed[i], placed[j]
        lo, hi = max(ca[0], cb[0]), min(ca[-1], cb[-1])
        if hi - lo < need:
            continue
        found = window_lags(
            _widen(_on_grid(a, ta, ca, lo, hi), k),
            _widen(_on_grid(b, tb, cb, lo, hi), k),
            config.hz,
            config.window_s,
            max_lag_s,
            config.min_peak,
            config.min_ratio,
            guard_s=0.5 + smooth_s,
        )
        if len(found) < config.min_windows:
            continue
        wt = np.array([x for x, _ in found])
        lags = np.array([y for _, y in found])
        ok, slope, icpt = robust_line(
            wt, lags, config.agree_s, config.max_drift, min_dt=config.window_s
        )
        if ok.sum() < config.min_windows:
            continue
        mid = float(np.median(wt[ok]))
        lag = slope * mid + icpt
        tc = lo + mid
        tau_a = float(np.interp(tc, ca, ta))
        tau_b = float(np.interp(tc + lag, cb, tb))
        rows.append(
            (
                a.device,
                a.run,
                a.position,
                b.device,
                b.run,
                b.position,
                tc,
                float(lag),
                int(ok.sum()),
                tau_a,
                tau_b,
                tau_a + ref - tc,
                tau_b + ref - (tc + lag),
            )
        )
    return pl.DataFrame(rows, schema=EDGES_SCHEMA, orient="row")


def _components(n: int, pairs: list[tuple[int, int]]) -> np.ndarray:
    parent = list(range(n))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for a, b in pairs:
        parent[find(a)] = find(b)
    return np.array([find(x) for x in range(n)])


def solve_offsets(
    n: int,
    pairs: list[tuple[int, int, float]],
    known: list[bool],
    closure_s: float,
    tolerance_s: float,
    reference: list[bool] | None = None,
) -> dict[str, Any]:
    """Residuals of ``n`` nodes from ``pairs`` (a, b, lag = r_b - r_a); see the module
    docstring. ``reference`` marks reference units: measured ones set the zero where a group
    has them. Returns per node ``residual`` (NaN without a zero), ``status`` (``check``,
    ``disagree``, ``anchor``, ``unchecked``), ``pairs`` (kept), ``triangle``, ``group``, and
    the indices of the pairs kept."""
    kept = list(range(len(pairs)))
    x = np.zeros(n)
    while True:
        comp = _components(n, [(pairs[k][0], pairs[k][1]) for k in kept])
        worst, worst_res = None, closure_s
        for g in np.unique(comp):
            nodes = np.flatnonzero(comp == g)
            mine = [k for k in kept if comp[pairs[k][0]] == g]
            if not mine:
                continue
            col = {v: i for i, v in enumerate(nodes)}
            A = np.zeros((len(mine), len(nodes)))
            y = np.zeros(len(mine))
            for r, k in enumerate(mine):
                a, b, lag = pairs[k]
                A[r, col[a]], A[r, col[b]], y[r] = -1.0, 1.0, lag
            sol = np.linalg.lstsq(A, y, rcond=None)[0]
            x[nodes] = sol
            res = np.abs(A @ sol - y)
            r = int(np.argmax(res))
            if res[r] > worst_res:
                worst, worst_res = mine[r], res[r]
        if worst is None:
            break
        kept.remove(worst)
    lag_of = {}
    for k in kept:
        a, b, lag = pairs[k]
        lag_of[(a, b)], lag_of[(b, a)] = lag, -lag
    nbrs: dict[int, set[int]] = {v: set() for v in range(n)}
    for a, b in lag_of:
        nbrs[a].add(b)
    triangle = np.zeros(n, bool)
    for v in range(n):
        for p, q in combinations(sorted(nbrs[v]), 2):
            if q in nbrs[p] and abs(lag_of[(v, p)] + lag_of[(p, q)] - lag_of[(v, q)]) <= closure_s:
                triangle[[v, p, q]] = True
    residual = np.full(n, np.nan)
    status = np.full(n, "unchecked", dtype=object)
    for g in np.unique(comp):
        nodes = np.flatnonzero(comp == g)
        ks = [v for v in nodes if known[v] and nbrs[v]]
        # The reference units define time: where measured ones lay in the box, they set the
        # zero, and every other measured unit is checked against them.
        refs = [v for v in ks if reference is not None and reference[v]]
        ks = refs or ks
        if not ks:
            continue
        xs = x[ks]
        good = np.abs(xs - np.median(xs)) <= tolerance_s
        if not good.any():
            continue
        r = x[nodes] - float(np.mean(xs[good]))
        residual[nodes] = r
        for v, rv in zip(nodes, r, strict=True):
            if not nbrs[v]:
                continue
            if known[v]:
                status[v] = "check" if abs(rv) <= tolerance_s else "disagree"
            elif triangle[v]:
                status[v] = "anchor"
    return {
        "residual": residual,
        "status": status,
        "pairs": np.array([len(nbrs[v]) for v in range(n)]),
        "triangle": triangle,
        "group": comp,
        "kept": kept,
    }


NODES_SCHEMA = {
    "device": pl.String,
    "run": pl.String,
    "position": pl.String,
    "day": pl.String,
    "tau": pl.Float64,  # device time of the anchor (median over the node's pairs)
    "known": pl.Boolean,  # the model measured this clock there
    "model_error_s": pl.Float64,  # the model's error there
    "residual_s": pl.Float64,  # what the box says the model is off by
    "error_s": pl.Float64,  # model error + residual: the measured error
    "pairs": pl.Int64,
    "triangle": pl.Boolean,
    "group": pl.Int64,
    "status": pl.String,
}


def solve(edges: pl.DataFrame, model: ClockModel, config: BoxConfig) -> pl.DataFrame:
    """One row per stretch with pairs: its anchor or check against ``model``. Pair lags
    measured under another model are carried over to this one exactly (the lag is a
    difference of clock errors; only the models' estimates of them change)."""
    if not edges.height:
        return pl.DataFrame(schema=NODES_SCHEMA)
    ref = model.config.reference_to_utc_s

    def est(device: str, run: str, tau: np.ndarray) -> np.ndarray:
        c, _ = model.correct(device, run, tau)
        return tau + ref - c

    ends = []
    for side in ("a", "b"):
        ends.append(
            edges.select(
                pl.col(f"{side}_device").alias("device"),
                pl.col(f"{side}_run").alias("run"),
                pl.col(f"{side}_position").alias("position"),
                pl.col(f"tau_{side}").alias("tau"),
                pl.col(f"est_{side}").alias("est"),
            ).with_row_index("edge")
        )
    new = {}
    for side, part in zip(("a", "b"), ends, strict=True):
        vals = np.zeros(part.height)
        for (d, r), g in part.group_by("device", "run"):
            vals[g["edge"].to_numpy()] = est(d, r, g["tau"].to_numpy())
        new[side] = vals
    lags = (
        edges["lag_s"].to_numpy()
        + (edges["est_b"].to_numpy() - new["b"])
        - (edges["est_a"].to_numpy() - new["a"])
    )
    allends = pl.concat(ends)
    nodes = (
        allends.group_by("device", "run", "position", maintain_order=True)
        .agg(pl.col("tau").median())
        .with_row_index("node")
    )
    index = {(d, r, p): int(i) for i, d, r, p, _ in nodes.iter_rows()}
    pairs = [
        (index[(ad, ar, ap)], index[(bd, br, bp)], float(lag))
        for ad, ar, ap, bd, br, bp, lag in zip(
            edges["a_device"],
            edges["a_run"],
            edges["a_position"],
            edges["b_device"],
            edges["b_run"],
            edges["b_position"],
            lags,
            strict=True,
        )
    ]
    known, model_error = [], []
    for _, d, r, _, tau in nodes.iter_rows():
        c, unc, src = model.correct_full(d, r, np.array([tau]))
        known.append(bool(not unc[0] and src[0] == 0))
        model_error.append(float(tau + ref - c[0]))
    refs = set(model.config.reference_devices)
    sol = solve_offsets(
        nodes.height,
        pairs,
        known,
        config.closure_s,
        config.tolerance_s,
        [d in refs for d in nodes["device"].to_list()],
    )
    err = np.array(model_error)
    return pl.DataFrame(
        {
            "device": nodes["device"],
            "run": nodes["run"],
            "position": nodes["position"],
            "day": [model._day(t) for t in nodes["tau"].to_list()],
            "tau": nodes["tau"],
            "known": known,
            "model_error_s": err,
            "residual_s": sol["residual"],
            "error_s": err + sol["residual"],
            "pairs": sol["pairs"],
            "triangle": sol["triangle"],
            "group": sol["group"],
            "status": sol["status"].astype(str),
        },
        schema=NODES_SCHEMA,
    ).with_columns(pl.col("residual_s", "error_s").fill_nan(None))


def measure(
    model: ClockModel, stretches: list[BoxStretch], config: BoxConfig
) -> tuple[pl.DataFrame, pl.DataFrame]:
    """Pairs and anchors against ``model`` (built from the sync records alone), in two
    searches: wide and smoothed on ``model``'s clocks, then sharp and narrow on the clocks the
    first search anchored. Returns (pairs of the second search, anchors)."""
    if len(stretches) < 2:
        return pl.DataFrame(schema=EDGES_SCHEMA), pl.DataFrame(schema=NODES_SCHEMA)
    first = solve(box_edges(model, stretches, config, smooth_s=config.smooth_s), model, config)
    better = ClockModel(model.records, model.runs_table, model.config, anchors=first)
    pairs = box_edges(better, stretches, config, max_lag_s=config.refine_lag_s)
    return pairs, solve(pairs, model, config)


LOO_SCHEMA = {
    "device": pl.String,
    "run": pl.String,
    "day": pl.String,
    "anchors": pl.Int64,  # box anchors the run got without its records
    "kind": pl.String,  # its model without its records
    "box_median_abs_s": pl.Float64,  # |box model - sync model| over the measured part
    "box_max_abs_s": pl.Float64,
    "certain_max_abs_s": pl.Float64,  # the same, over the times the box model leaves unflagged
    "fallback_max_abs_s": pl.Float64,  # |fallback - sync model| (what it replaces)
    "uncertain_share": pl.Float64,  # share of the measured part still flagged
}


def leave_one_out(
    records: pl.DataFrame,
    runs: pl.DataFrame,
    edges: pl.DataFrame,
    clock: ClockConfig,
    config: BoxConfig,
    grid_s: float = 60.0,
) -> pl.DataFrame:
    """For every slave run the records measure (a fitted rate) that has box pairs: drop its
    records, anchor it by the box alone, and compare with the model that had them, over the
    times that model measured (not extrapolated)."""
    full = ClockModel(records, runs, clock)
    paired = set(zip(edges["a_device"], edges["a_run"], strict=True)) | set(
        zip(edges["b_device"], edges["b_run"], strict=True)
    )
    rows = []
    for (device, run), rc in sorted(full.runs.items()):
        if rc.kind != "sync" or not rc.rate_fitted or (device, run) not in paired:
            continue
        mine = (pl.col("device") == device) & (pl.col("run") == run)
        rest = records.filter(~mine)
        base = ClockModel(rest, runs, clock)
        # Only the pairs of the groups this run's stretches are in matter.
        days = {full._day(rc.start), full._day(rc.end)}
        sub = edges.filter(
            pl.col("t").map_elements(full._day, return_dtype=pl.String).is_in(list(days))
        )
        nodes = solve(sub, base, config).filter(mine)
        anchored = ClockModel(rest, runs, clock, anchors=nodes)
        grid = np.arange(rc.start, rc.end, grid_s)
        _, unc_full = full.correct(device, run, grid)
        grid = grid[~unc_full]
        if not len(grid):
            continue
        truth = np.asarray(rc.error(grid), float)
        c_box, unc_box = anchored.correct(device, run, grid)
        c_fb, _ = base.correct(device, run, grid)
        ref = clock.reference_to_utc_s
        d_box = np.abs(grid + ref - c_box - truth)
        d_fb = np.abs(grid + ref - c_fb - truth)
        arc = anchored.runs[(device, run)]
        rows.append(
            (
                device,
                run,
                rc.day,
                arc.anchors,
                arc.kind,
                float(np.median(d_box)),
                float(d_box.max()),
                float(d_box[~unc_box].max()) if (~unc_box).any() else None,
                float(d_fb.max()),
                float(unc_box.mean()),
            )
        )
    return pl.DataFrame(rows, schema=LOO_SCHEMA, orient="row")


def nodes_summary(nodes: pl.DataFrame) -> dict[str, Any]:
    if not nodes.height:
        return {"nodes": 0}
    by = dict(nodes.group_by("status").len().iter_rows())
    checks = nodes.filter(pl.col("known") & pl.col("residual_s").is_not_null())
    a = checks["residual_s"].abs()
    return {
        "nodes": nodes.height,
        "by_status": {k: int(v) for k, v in sorted(by.items())},
        "measured_checked": checks.height,
        "measured_median_abs_s": round(float(a.median()), 3) if checks.height else None,
        "measured_max_abs_s": round(float(a.max()), 3) if checks.height else None,
    }


def loo_summary(loo: pl.DataFrame, tolerance_s: float = 1.0) -> dict[str, Any]:
    if not loo.height:
        return {"runs": 0}
    got = loo.filter(pl.col("anchors") > 0)
    out: dict[str, Any] = {"runs": loo.height, "anchored": got.height}
    if got.height:
        out |= {
            "box_median_of_max_abs_s": round(float(got["box_max_abs_s"].median()), 3),
            "box_worst_max_abs_s": round(float(got["box_max_abs_s"].max()), 3),
            "box_within_tolerance": int((got["box_max_abs_s"] <= tolerance_s).sum()),
            "certain_runs": int(got["certain_max_abs_s"].is_not_null().sum()),
            "certain_worst_max_abs_s": round(float(got["certain_max_abs_s"].max() or 0.0), 3),
            "certain_within_tolerance": int((got["certain_max_abs_s"] <= tolerance_s).sum()),
            "certain_share": round(float(1 - got["uncertain_share"].mean()), 3),
            "fallback_median_of_max_abs_s": round(float(got["fallback_max_abs_s"].median()), 3),
        }
    return out
