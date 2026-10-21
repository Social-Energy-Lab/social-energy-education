"""Correct Shimmer device clocks: device time -> sync master time -> reference time -> UTC.

Shimmer clocks can run slow while they record, by a rate that is roughly fixed per unit
(docs/context/instruments/eda.md, "Clock"). Devices in a sync group write, about once an
hour, the offset between their own clock and the sync master's into the SD card (decoded by
``eda.sd``). This module turns those records into a correction per device run:

1. **Reference curves.** Per local day, the records of the *reference devices* (units known
   to keep time; all slaves when none are configured) give ``R(t) = reference - master`` as
   a function of reference time. A day with several masters can hold several curves; each is
   found by a robust line fit (``curve_tolerance_s``) on what the previous ones left, and is
   then followed piecewise-linearly through its records merged within ``merge_s``.
2. **Device error.** A slave's record says ``offset = device - master``, so its error
   against the reference is ``e = offset - R(reference time)``, with ``reference time =
   device time - e`` (solved by iteration). Per run, a robust line through the candidate
   errors (one per curve) keeps the records that agree (``fit_tolerance_s``); the error is
   followed piecewise-linearly through them and extrapolated with their fitted rate.
3. **Master.** The master's own error is ``-R``. With several curves on its day, the curve
   whose corrected end of run lands closest to the other runs' corrected ends is taken, and
   the run is flagged uncertain when the curves disagree by more than ``ambiguity_s``.
4. **Fallback.** A run with no usable record (sync off, a unit that never synced, a day
   without reference records) gets its unit's typical rate, counted from the start of the run
   (devices are re-set when started), and is flagged ``clock_uncertain``. So are times more
   than ``max_extrapolation_s`` outside the records of a fitted run.

Corrected time = device time - e + ``reference_to_utc_s``: the reference group's own error
against UTC is a study fact (measured against external events), not something the sync
records can show.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

import numpy as np
import polars as pl

RECORDS_SCHEMA = {"device": pl.String, "run": pl.String, "t": pl.Float64, "offset_s": pl.Float64}
RUNS_SCHEMA = {
    "device": pl.String,
    "run": pl.String,
    "start": pl.Float64,
    "end": pl.Float64,
    "master": pl.Boolean,
}


@dataclass(frozen=True)
class ClockConfig:
    #: Units whose clocks keep time; their sync records define the reference. Empty: all
    #: slaves (only safe when no slave runs slow).
    reference_devices: tuple[str, ...] = ()
    timezone: str = "UTC"
    #: The reference group's error against UTC, added to every corrected time.
    reference_to_utc_s: float = 0.0
    curve_tolerance_s: float = 10.0
    fit_tolerance_s: float = 8.0
    merge_s: float = 600.0
    min_span_s: float = 1800.0  # a rate is fitted only over at least this much time
    max_offset_s: float = 4000.0  # a larger offset is not a sync record
    max_rate: float = 0.05  # |clock rate| beyond 5 % is not a clock
    max_extrapolation_s: float = 3 * 3600.0
    ambiguity_s: float = 2.0
    #: Rate (seconds per hour, negative = slow) for units with no fitted run at all.
    fallback_rates_s_per_h: dict[str, float] = field(default_factory=dict)


@dataclass(frozen=True)
class Piecewise:
    """Linear through ``knots`` (sorted times, values), extrapolated with ``slope``."""

    t: np.ndarray
    v: np.ndarray
    slope: float

    def __call__(self, x: np.ndarray | float) -> np.ndarray:
        x = np.asarray(x, float)
        y = np.interp(x, self.t, self.v)
        y = np.where(x < self.t[0], self.v[0] + self.slope * (x - self.t[0]), y)
        return np.where(x > self.t[-1], self.v[-1] + self.slope * (x - self.t[-1]), y)


def _merge(t: np.ndarray, v: np.ndarray, merge_s: float) -> tuple[np.ndarray, np.ndarray]:
    order = np.argsort(t)
    t, v = t[order], v[order]
    groups = np.zeros(len(t), np.int64)
    start = t[0] if len(t) else 0.0
    g = 0
    for i in range(len(t)):
        if t[i] - start > merge_s:
            g += 1
            start = t[i]
        groups[i] = g
    n = g + 1
    cnt = np.bincount(groups, minlength=n)
    return np.bincount(groups, t, n) / cnt, np.bincount(groups, v, n) / cnt


def robust_line(
    t: np.ndarray,
    v: np.ndarray,
    tol: float,
    max_rate: float,
    group: np.ndarray | None = None,
    min_dt: float = 600.0,
) -> tuple[np.ndarray, float, float]:
    """The line through the most points (or, with ``group``, the most distinct groups: one
    candidate per group counts) within ``tol``. Returns (inlier mask, slope, intercept); the
    mask keeps at most one candidate per group, the closest. Ties go to the smaller spread.
    A lone point is a flat line."""
    t, v = np.asarray(t, float), np.asarray(v, float)
    group = np.arange(len(t)) if group is None else np.asarray(group)
    best = (-1, np.inf, 0.0, float(v[0]) if len(v) else 0.0)
    lines = [(0.0, float(x)) for x in v]
    for i in range(len(t)):
        for j in range(i + 1, len(t)):
            dt = t[j] - t[i]
            if abs(dt) < min_dt or group[i] == group[j]:
                continue
            s = (v[j] - v[i]) / dt
            if abs(s) <= max_rate:
                lines.append((s, v[i] - s * t[i]))
    for s, c in lines:
        r = np.abs(v - (s * t + c))
        ok = r <= tol
        n = len(np.unique(group[ok]))
        spread = float(r[ok].sum())
        if n > best[0] or (n == best[0] and spread < best[1]):
            best = (n, spread, s, c)
    _, _, s, c = best
    r = np.abs(v - (s * t + c))
    mask = np.zeros(len(t), bool)
    for g in np.unique(group):
        mine = np.flatnonzero((group == g) & (r <= tol))
        if len(mine):
            mask[mine[np.argmin(r[mine])]] = True
    return mask, float(s), float(c)


def _fit(t: np.ndarray, v: np.ndarray, config: ClockConfig) -> float | None:
    """Least-squares slope over inliers spanning ``min_span_s``, else None."""
    if len(t) < 2 or np.ptp(t) < config.min_span_s:
        return None
    return float(np.polyfit(t, v, 1)[0])


@dataclass
class RunClock:
    device: str
    run: str
    day: str
    kind: str  # "sync" | "master" | "rate"
    start: float
    end: float
    error: Any  # callable: device time -> error (s)
    span: tuple[float, float] | None = None  # device times covered by records
    uncertain: bool = False
    slope: float = 0.0  # error rate, s per s
    records: int = 0
    inliers: int = 0
    curve: int | None = None
    rate_fitted: bool = True  # False: the rate is the unit's, not this run's


def _solve(r: Piecewise, t_dev: np.ndarray, sign: float, base: np.ndarray) -> np.ndarray:
    """e = base + sign * R(t_dev - e), by fixed-point iteration (|dR/dt| << 1)."""
    e = base + sign * r(t_dev)
    for _ in range(4):
        e = base + sign * r(t_dev - e)
    return e


class ClockModel:
    """Per-run clock corrections built from every device's sync records."""

    def __init__(self, records: pl.DataFrame, runs: pl.DataFrame, config: ClockConfig):
        self.config = config
        self.tz = ZoneInfo(config.timezone)
        records = records.filter(pl.col("offset_s").abs() < config.max_offset_s)
        self.curves: dict[str, list[Piecewise]] = {}
        self.runs: dict[tuple[str, str], RunClock] = {}
        self.qa: dict[str, Any] = {}
        self._build(records, runs)

    def _day(self, t: float) -> str:
        return datetime.fromtimestamp(t, UTC).astimezone(self.tz).date().isoformat()

    def _build(self, records: pl.DataFrame, runs: pl.DataFrame) -> None:
        cfg = self.config
        rec = records.with_columns(
            pl.col("t").map_elements(self._day, return_dtype=pl.String).alias("day")
        )
        runs = runs.with_columns(
            pl.col("start").map_elements(self._day, return_dtype=pl.String).alias("day")
        )
        masters = {(r["device"], r["run"]) for r in runs.filter("master").iter_rows(named=True)}
        is_slave = ~pl.struct("device", "run").map_elements(
            lambda x: (x["device"], x["run"]) in masters, return_dtype=pl.Boolean
        )
        ref = rec.filter(is_slave) if rec.height else rec
        if cfg.reference_devices:
            ref = ref.filter(pl.col("device").is_in(list(cfg.reference_devices)))

        # 1. Reference curves per day.
        pending: list[tuple[str, np.ndarray, np.ndarray, float | None]] = []
        for (day,), part in ref.group_by("day", maintain_order=True):
            n_masters = max(1, runs.filter(pl.col("master") & (pl.col("day") == day)).height)
            t, v = part["t"].to_numpy(), part["offset_s"].to_numpy()
            left = np.ones(len(t), bool)
            for k in range(n_masters):
                idx = np.flatnonzero(left)
                if len(idx) < (1 if k == 0 else 3):
                    break
                ok, _, _ = robust_line(t[idx], v[idx], cfg.curve_tolerance_s, cfg.max_rate)
                inl = idx[ok]
                if k and (len(inl) < 3 or np.ptp(t[inl]) < cfg.min_span_s):
                    break
                left[inl] = False
                pending.append((day, t[inl], v[inl], _fit(t[inl], v[inl], cfg)))
        slopes = [s for *_, s in pending if s is not None]
        prior = float(np.median(slopes)) if slopes else 0.0
        for day, t, v, s in pending:
            kt, kv = _merge(t, v, cfg.merge_s)
            self.curves.setdefault(day, []).append(Piecewise(kt, kv, prior if s is None else s))

        # 2. Slave runs with records.
        by_run = {k: g for k, g in rec.group_by("device", "run", maintain_order=True)}
        later: list[dict] = []
        for row in runs.iter_rows(named=True):
            key = (row["device"], row["run"])
            if key in masters:
                continue
            part = by_run.get(key)
            fitted = self._fit_slave(row, part) if part is not None else None
            if fitted is None:
                later.append(row)
            else:
                self.runs[key] = fitted

        # 3. Masters.
        for row in runs.filter("master").iter_rows(named=True):
            fitted = self._fit_master(row)
            if fitted is None:
                later.append(row)
            else:
                self.runs[(row["device"], row["run"])] = fitted

        # 4. Fallback: the unit's typical rate from its fitted runs, or the configured one.
        unit: dict[str, list[float]] = {}
        for rc in self.runs.values():
            if rc.rate_fitted or rc.kind == "master":
                unit.setdefault(rc.device, []).append(rc.slope)
        self.unit_rates = {d: float(np.median(s)) for d, s in unit.items()}
        for rc in self.runs.values():
            if rc.kind == "sync" and not rc.rate_fitted:
                rc.slope = self.unit_rate(rc.device)
                rc.error = Piecewise(rc.error.t, rc.error.v, rc.slope)
        for row in later:
            self.runs[(row["device"], row["run"])] = self.rate_clock(
                row["device"], row["run"], row["start"], row["end"]
            )
        kinds: dict[str, int] = {}
        for rc in self.runs.values():
            kinds[rc.kind] = kinds.get(rc.kind, 0) + 1
        self.qa = {
            "records": records.height,
            "reference_days": len(self.curves),
            "curves": sum(len(c) for c in self.curves.values()),
            "runs_by_kind": kinds,
            "runs_uncertain": sum(rc.uncertain for rc in self.runs.values()),
            "unit_rates_s_per_h": {d: round(r * 3600, 2) for d, r in self.unit_rates.items()},
        }

    def unit_rate(self, device: str) -> float:
        if device in self.unit_rates:
            return self.unit_rates[device]
        return self.config.fallback_rates_s_per_h.get(device, 0.0) / 3600

    def rate_clock(self, device: str, run: str, start: float, end: float) -> RunClock:
        """The fallback: the unit's rate counted from the start of the run (flagged)."""
        rate = self.unit_rate(device)
        return RunClock(
            device=device,
            run=run,
            day=self._day(start),
            kind="rate",
            start=start,
            end=end,
            error=lambda x, r=rate, s=start: r * (np.asarray(x, float) - s),
            uncertain=True,
            slope=rate,
        )

    def _fit_slave(self, row: dict, part: pl.DataFrame) -> RunClock | None:
        cfg = self.config
        t, off = part["t"].to_numpy(), part["offset_s"].to_numpy()
        days = [self._day(x) for x in t]
        ct, ce, cg, ck = [], [], [], []
        for i in range(len(t)):
            for k, curve in enumerate(self.curves.get(days[i], [])):
                e = float(_solve(curve, np.array([t[i]]), -1.0, np.array([off[i]]))[0])
                ct.append(t[i])
                ce.append(e)
                cg.append(i)
                ck.append(k)
        if not ct:
            return None
        ct, ce, cg = np.array(ct), np.array(ce), np.array(cg)
        ok, _, _ = robust_line(ct, ce, cfg.fit_tolerance_s, cfg.max_rate, cg)
        ti, ei = ct[ok], ce[ok]
        if row["device"] in cfg.reference_devices:
            # A reference unit keeps time by definition: a record far off it is not usable.
            near = np.abs(ei) <= cfg.fit_tolerance_s
            ti, ei = ti[near], ei[near]
            if not len(ti):
                return None
        slope = _fit(ti, ei, cfg)
        fitted = slope is not None
        if slope is None:  # replaced by the unit's rate once every run is fitted
            slope = 0.0
        kt, kv = _merge(ti, ei, cfg.merge_s)
        return RunClock(
            device=row["device"],
            run=row["run"],
            day=self._day(row["start"]),
            kind="sync",
            start=row["start"],
            end=row["end"],
            error=Piecewise(kt, kv, slope),
            span=(float(ti.min()), float(ti.max())),
            slope=slope,
            records=len(t),
            inliers=len(ti),
            rate_fitted=fitted,
        )

    def _fit_master(self, row: dict) -> RunClock | None:
        day = self._day(row["start"])
        # Only curves with records while this master ran: a master started again after the
        # last record (and re-set then) is not described by the earlier curve.
        lo, hi = row["start"] - 600.0, row["end"] + 900.0
        curves = [c for c in self.curves.get(day, []) if ((c.t >= lo) & (c.t <= hi)).any()]
        if not curves:
            return None
        grid = np.linspace(row["start"], row["end"], 50)
        errors = [_solve(c, grid, -1.0, np.zeros(len(grid))) for c in curves]
        k = 0
        uncertain = False
        if len(curves) > 1:
            ends = [
                rc.end - float(rc.error(np.array([rc.end]))[0])
                for rc in self.runs.values()
                if rc.day == day and rc.kind == "sync" and abs(rc.end - row["end"]) < 4 * 3600
            ]
            if ends:
                target = float(np.median(ends))
                k = int(np.argmin([abs(row["end"] - e[-1] - target) for e in errors]))
            spread = np.ptp(np.array(errors), axis=0).max()
            uncertain = bool(spread > self.config.ambiguity_s)
        e = errors[k]
        slope = float(np.polyfit(grid, e, 1)[0]) if np.ptp(grid) > 0 else 0.0
        r = curves[k]
        return RunClock(
            device=row["device"],
            run=row["run"],
            day=day,
            kind="master",
            start=row["start"],
            end=row["end"],
            error=lambda x, c=r: _solve(c, np.asarray(x, float), -1.0, np.zeros(np.size(x))),
            span=(float(r.t[0]), float(r.t[-1])),
            uncertain=uncertain,
            slope=slope,
            curve=k,
        )

    def correct(
        self, device: str, run: str, t: np.ndarray, rc: RunClock | None = None
    ) -> tuple[np.ndarray, np.ndarray]:
        """Corrected UTC seconds and the ``clock_uncertain`` flag for device times ``t`` of a
        run (NaN stays NaN). An unknown run gets the fallback from its first time."""
        t = np.asarray(t, float)
        fin = np.isfinite(t)
        if rc is None:
            rc = self.runs.get((device, run))
        if rc is None:
            lo = float(np.nanmin(t)) if fin.any() else 0.0
            hi = float(np.nanmax(t)) if fin.any() else 0.0
            rc = self.rate_clock(device, run, lo, hi)
        out = np.full(len(t), np.nan)
        unc = np.full(len(t), rc.uncertain)
        if fin.any():
            x = t[fin]
            lo, hi = x.min(), x.max()
            # The error changes slowly: evaluate it on a 10-s grid and interpolate.
            grid = np.arange(lo, hi + 10.0, 10.0)
            e = np.interp(x, grid, np.asarray(rc.error(grid), float))
            out[fin] = x - e + self.config.reference_to_utc_s
            if rc.span is not None and rc.kind == "sync" and abs(rc.slope) * 3600 > 1.0:
                # Far from its records, a drifting unit's rate is a guess.
                m = self.config.max_extrapolation_s
                far = (x < rc.span[0] - m) | (x > rc.span[1] + m)
                unc[np.flatnonzero(fin)[far]] = True
        return out, unc

    def summary(self) -> pl.DataFrame:
        rows = []
        for rc in sorted(self.runs.values(), key=lambda r: (r.device, r.start)):
            e0, e1 = (float(x) for x in np.asarray(rc.error(np.array([rc.start, rc.end]))))
            rows.append(
                {
                    "device": rc.device,
                    "run": rc.run,
                    "day": rc.day,
                    "kind": rc.kind,
                    "records": rc.records,
                    "inliers": rc.inliers,
                    "curve": rc.curve,
                    "rate_s_per_h": rc.slope * 3600,
                    "error_start_s": e0,
                    "error_end_s": e1,
                    "uncertain": rc.uncertain,
                }
            )
        return pl.DataFrame(
            rows,
            schema={
                "device": pl.String,
                "run": pl.String,
                "day": pl.String,
                "kind": pl.String,
                "records": pl.Int64,
                "inliers": pl.Int64,
                "curve": pl.Int64,
                "rate_s_per_h": pl.Float64,
                "error_start_s": pl.Float64,
                "error_end_s": pl.Float64,
                "uncertain": pl.Boolean,
            },
        )


def match_lag(
    ta: np.ndarray,
    xa: np.ndarray,
    tb: np.ndarray,
    xb: np.ndarray,
    max_lag_s: float,
    hz: float,
) -> tuple[float, float]:
    """Lag (s) such that ``b`` at ``t + lag`` matches ``a`` at ``t`` (b's clock reads later),
    and the peak correlation, for two signals on regular ``hz`` grids starting at ``ta[0]``
    and ``tb[0]``. NaN counts as no signal. Uses first differences, so levels do not matter."""
    lo = max(ta[0], tb[0] - max_lag_s)
    hi = min(ta[-1], tb[-1] + max_lag_s)
    if hi - lo < 4 * max_lag_s:
        return float("nan"), 0.0
    n = int((hi - lo) * hz)
    L = int(max_lag_s * hz)

    def take(t0: float, x: np.ndarray, start: float, m: int) -> np.ndarray:
        i = round((start - t0) * hz)
        out = np.zeros(m)
        a, b = max(i, 0), min(i + m, len(x))
        if b > a:
            out[a - i : b - i] = x[a:b]
        d = np.r_[0, np.diff(out)]
        d[~np.isfinite(d)] = 0
        return d

    x = take(ta[0], np.nan_to_num(np.asarray(xa, float), nan=0.0), lo, n)
    y = take(tb[0], np.nan_to_num(np.asarray(xb, float), nan=0.0), lo - max_lag_s, n + 2 * L)
    size = 1 << int(np.ceil(np.log2(len(y) + n)))
    c = np.fft.irfft(np.conj(np.fft.rfft(x, size)) * np.fft.rfft(y, size), size)[: 2 * L + 1]
    norm = np.sqrt((x * x).sum() * (y[L : L + n] ** 2).sum()) + 1e-12
    k = int(np.argmax(c))
    return (k - L) / hz, float(c[k] / norm)


def comotion(
    signals: dict[str, np.ndarray],
    t0: float,
    hz: float,
    window_s: float = 600.0,
    max_lag_s: float = 60.0,
    min_peak: float = 0.2,
    min_ratio: float = 1.5,
    min_windows: int = 3,
    agree_s: float = 0.25,
) -> pl.DataFrame:
    """Clock residuals of devices lying together: per pair, the lag of their motion (jerk)
    signals on one ``hz`` grid from ``t0``, over ``window_s`` sub-windows. A pair counts when
    at least ``min_windows`` confident sub-windows (peak >= ``min_peak``, ``min_ratio`` over
    the next peak) agree within ``agree_s`` of their median. Returns one row per device:
    the median of its confident pair lags (positive = its clock reads late), and the pairs."""
    devices = sorted(signals)
    w = int(window_s * hz)
    L = int(max_lag_s * hz)
    pair_rows = []
    for i, a in enumerate(devices):
        for b in devices[i + 1 :]:
            x, y = signals[a], signals[b]
            n = min(len(x), len(y))
            lags = []
            for s in range(L, n - w - L, w):
                xa = x[s : s + w]
                yb = y[s - L : s + w + L]
                if np.isnan(xa).mean() > 0.2 or np.isnan(yb).mean() > 0.2:
                    continue
                xa = np.nan_to_num(xa - np.nanmean(xa))
                yb = np.nan_to_num(yb - np.nanmean(yb))
                size = 1 << int(np.ceil(np.log2(len(yb) + w)))
                c = np.fft.irfft(np.conj(np.fft.rfft(xa, size)) * np.fft.rfft(yb, size), size)
                c = c[: 2 * L + 1] / (np.sqrt((xa * xa).sum() * (yb[L : L + w] ** 2).sum()) + 1e-12)
                k = int(np.argmax(c))
                pk = c[k]
                guard = int(0.5 * hz)
                rest = np.r_[c[: max(0, k - guard)], c[k + guard + 1 :]]
                ratio = pk / max(rest.max() if len(rest) else 0.0, 1e-9)
                if pk >= min_peak and ratio >= min_ratio:
                    lags.append((k - L) / hz)
            if len(lags) >= min_windows:
                med = float(np.median(lags))
                agree = [x for x in lags if abs(x - med) <= agree_s]
                if len(agree) >= min_windows:
                    pair_rows.append((a, b, float(np.median(agree)), len(agree)))
    pairs = pl.DataFrame(
        pair_rows,
        schema={"a": pl.String, "b": pl.String, "lag_s": pl.Float64, "windows": pl.Int64},
        orient="row",
    )
    rows = []
    for d in devices:
        mine = [lag for a, b, lag, _ in pair_rows if b == d] + [
            -lag for a, b, lag, _ in pair_rows if a == d
        ]
        if mine:
            rows.append((d, float(np.median(mine)), len(mine)))
    per_device = pl.DataFrame(
        rows,
        schema={"device": pl.String, "residual_s": pl.Float64, "pairs": pl.Int64},
        orient="row",
    )
    return per_device.with_columns(pl.lit(pairs.height).alias("pairs_in_window"))
