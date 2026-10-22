"""Exploratory EDA at minute resolution: each person against themselves.

Tools for three kinds of question, none of which knows a study's dates, people or thresholds:

* **Scaling and adjustment.** :func:`zscore_within` standardises a measure within a group (a
  person, or a person-day: electrodes are put on afresh each day, so tonic level is only
  comparable within one wear). :func:`residualise` removes a pooled least-squares fit on
  covariates (movement), and :func:`centred_detrend` a centred moving mean along a dense series.
* **Event-locked profiles.** :class:`DenseSeries` lays each group's minutes on one padded array,
  so a profile around many events is one fancy index (:func:`profile`), and a shuffled null
  that moves each event to an eligible minute of the same group and stratum (:func:`eligible`,
  :func:`pools`, :func:`draw_positions`) costs little per shuffle.
* **Pair synchrony.** :func:`lagged_products` multiplies two people's standardised series at the
  same minute, or with the partner shifted by a lag, for labelled pair-minutes;
  :func:`node_bootstrap_mean` gives a pooled mean with an interval that resamples people (a
  pair-minute weighs the product of its partners' draws).

Nothing here knows which measure it is given: the same tools serve heart rate from the PPG
(``eda.heart``) beside the EDA measures, and a clock filter (``clock_uncertain``) is the
caller's choice of rows, made before the minutes are laid out.
"""

from __future__ import annotations

from collections.abc import Hashable, Mapping, Sequence
from dataclasses import dataclass

import numpy as np
import polars as pl

NAN = float("nan")


# --- scaling and adjustment -----------------------------------------------------------------------


def zscore_within(df: pl.DataFrame, value: str, by: Sequence[str], out: str) -> pl.DataFrame:
    """``out`` = (``value`` - group mean) / group SD (ddof 1) within ``by``; null where the group
    has fewer than two values or no spread, and where ``value`` is null or NaN."""
    v = pl.when(pl.col(value).is_nan()).then(None).otherwise(pl.col(value))
    df = df.with_columns(v.alias("__v"))
    m = pl.col("__v").mean().over(by)
    s = pl.col("__v").std().over(by)
    z = pl.when(s > 0).then((pl.col("__v") - m) / s).otherwise(None)
    return df.with_columns(z.alias(out)).drop("__v")


def residualise(
    df: pl.DataFrame, value: str, covariates: Sequence[str], out: str
) -> tuple[pl.DataFrame, np.ndarray]:
    """``out`` = ``value`` minus its pooled least-squares fit on an intercept and ``covariates``.

    Rows with a null or NaN in ``value`` or any covariate get a null ``out``. Returns the frame
    and the coefficients (intercept first).
    """
    cols = [value, *covariates]
    a = df.select(pl.col(c).cast(pl.Float64).fill_null(NAN) for c in cols).to_numpy()
    ok = np.isfinite(a).all(axis=1)
    x = np.column_stack([np.ones(ok.sum()), a[ok, 1:]])
    coef, *_ = np.linalg.lstsq(x, a[ok, 0], rcond=None)
    res = np.full(len(a), NAN)
    res[ok] = a[ok, 0] - x @ coef
    s = pl.Series(out, res).fill_nan(None)
    return df.with_columns(s), coef


def centred_detrend(values: np.ndarray, *, window: int, min_valid: int) -> np.ndarray:
    """``values`` minus the mean of the finite values in a centred window of ``window`` (odd)
    positions; NaN where the window holds fewer than ``min_valid`` finite values. NaN in, NaN
    out. Apply it to one group's dense series (or a padded concatenation whose padding is at
    least ``window // 2`` long, so windows do not reach the next group)."""
    if window % 2 != 1:
        raise ValueError("window must be odd")
    x = np.asarray(values, dtype=float)
    ok = np.isfinite(x)
    k = np.ones(window)
    s = np.convolve(np.where(ok, x, 0.0), k, mode="same")
    n = np.convolve(ok.astype(float), k, mode="same")
    with np.errstate(invalid="ignore", divide="ignore"):
        trend = np.where(n >= min_valid, s / n, NAN)
    return np.where(ok, x - trend, NAN)


# --- dense series and event-locked profiles -------------------------------------------------------


@dataclass(frozen=True)
class DenseSeries:
    """Every group's minutes on one array, groups separated by ``pad`` empty positions.

    ``index`` has one row per group: its key columns, ``first`` (its earliest minute), ``n``
    (minutes spanned) and ``start`` (array position of ``first``). ``values`` maps each value
    column to a float array (NaN where the group had no row). ``group_of`` gives each position's
    group row (-1 in padding).
    """

    keys: list[str]
    time: str
    index: pl.DataFrame
    values: dict[str, np.ndarray]
    group_of: np.ndarray
    pad: int

    @property
    def size(self) -> int:
        return len(self.group_of)

    def positions(self, events: pl.DataFrame) -> np.ndarray:
        """Array position of each event (``keys`` + ``time``, truncated to the minute); -1 when
        the event's group is not in the series or the minute is outside the group's span."""
        e = events.select(*self.keys, pl.col(self.time).dt.truncate("1m").alias("__t"))
        j = e.with_row_index("__row").join(self.index, on=self.keys, how="left")
        idx = ((pl.col("__t") - pl.col("first")).dt.total_minutes()).alias("__i")
        j = j.with_columns(idx).sort("__row")
        inside = (pl.col("__i") >= 0) & (pl.col("__i") < pl.col("n"))
        pos = j.select(pl.when(inside).then(pl.col("start") + pl.col("__i")).otherwise(-1))
        return pos.to_series().fill_null(-1).to_numpy().astype(np.int64)


def dense_series(
    df: pl.DataFrame, *, keys: Sequence[str], time: str, values: Sequence[str], pad: int
) -> DenseSeries:
    """Lay ``df`` (one row per group and minute) on a :class:`DenseSeries`."""
    keys = list(keys)
    d = df.with_columns(pl.col(time).dt.truncate("1m"))
    index = (
        d.group_by(keys)
        .agg(pl.col(time).min().alias("first"), pl.col(time).max().alias("last"))
        .sort(keys)
        .with_columns(((pl.col("last") - pl.col("first")).dt.total_minutes() + 1).alias("n"))
        .drop("last")
    )
    starts = pad + np.concatenate([[0], np.cumsum(index["n"].to_numpy() + pad)[:-1]])
    index = index.with_columns(pl.Series("start", starts.astype(np.int64)))
    size = int(starts[-1] + index["n"][-1] + pad) if index.height else pad
    j = d.join(index, on=keys).with_columns(
        (pl.col("start") + (pl.col(time) - pl.col("first")).dt.total_minutes()).alias("__p")
    )
    pos = j["__p"].to_numpy()
    out = {}
    for v in values:
        a = np.full(size, NAN)
        a[pos] = j[v].cast(pl.Float64).fill_null(NAN).to_numpy()
        out[v] = a
    group_of = np.full(size, -1, dtype=np.int64)
    for g, (s, n) in enumerate(zip(starts, index["n"].to_numpy(), strict=True)):
        group_of[s : s + n] = g
    return DenseSeries(keys, time, index, out, group_of, pad)


def profile(values: np.ndarray, positions: np.ndarray, offsets: np.ndarray) -> np.ndarray:
    """Events x offsets: ``values`` at each event position plus each offset (NaN where missing).
    The series' padding must be at least ``max(abs(offsets))``."""
    return values[np.asarray(positions)[:, None] + np.asarray(offsets)[None, :]]


def eligible(valid: np.ndarray, offsets: np.ndarray, min_valid: int) -> np.ndarray:
    """Positions whose window (position + ``offsets``) holds at least ``min_valid`` valid
    positions. ``valid`` is boolean over the series; padding counts as invalid."""
    v = np.asarray(valid, dtype=bool)
    offsets = np.asarray(offsets)
    n = np.zeros(len(v), dtype=np.int64)
    for k in offsets:
        if k >= 0:
            n[: len(v) - k] += v[k:]
        else:
            n[-k:] += v[:k]
    return n >= min_valid


def pools(
    ok: np.ndarray, group_of: np.ndarray, stratum: np.ndarray | None = None
) -> dict[tuple[int, Hashable], np.ndarray]:
    """``{(group row, stratum): eligible positions}``, from a boolean ``ok`` over positions.
    Without ``stratum``, the stratum is ``None`` throughout."""
    pos = np.flatnonzero(np.asarray(ok) & (group_of >= 0))
    s = [None] * len(pos) if stratum is None else np.asarray(stratum, dtype=object)[pos]
    out: dict[tuple[int, Hashable], list[int]] = {}
    for p, g, st in zip(pos.tolist(), group_of[pos].tolist(), s, strict=True):
        out.setdefault((g, st), []).append(p)
    return {k: np.asarray(v, dtype=np.int64) for k, v in out.items()}


def draw_positions(
    keys: Sequence[tuple[int, Hashable]],
    pool: Mapping[tuple[int, Hashable], np.ndarray],
    rng: np.random.Generator,
) -> np.ndarray:
    """One uniformly drawn position from each event's pool (``keys[k]`` names event k's pool).
    Every event keeps its group and stratum; the draws are independent, with replacement."""
    out = np.empty(len(keys), dtype=np.int64)
    by: dict[tuple, list[int]] = {}
    for k, key in enumerate(keys):
        by.setdefault(key, []).append(k)
    for key, idx in by.items():
        p = pool[key]
        out[idx] = p[rng.integers(0, len(p), len(idx))]
    return out


def window_means(prof: np.ndarray, offsets: np.ndarray, lo: int, hi: int) -> np.ndarray:
    """Per event, the mean of its finite profile values at offsets ``lo``..``hi`` (inclusive);
    NaN for an event with none."""
    sel = (np.asarray(offsets) >= lo) & (np.asarray(offsets) <= hi)
    x = prof[:, sel]
    n = np.isfinite(x).sum(axis=1)
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.where(n > 0, np.nansum(x, axis=1) / n, NAN)


# --- pair synchrony -------------------------------------------------------------------------------


def lagged_products(
    signal: pl.DataFrame,
    pair_minutes: pl.DataFrame,
    *,
    value: str,
    lags: Sequence[int],
    id_col: str = "entity",
    time: str = "minute",
) -> pl.DataFrame:
    """For each labelled pair-minute (``a``, ``b``, ``time``) and each lag L in minutes, the
    product of ``a``'s ``value`` at the minute and ``b``'s at the minute + L.

    ``signal`` holds one row per person and minute with ``value`` (already standardised).
    Pair-minutes where either value is missing are dropped. The result keeps every column of
    ``pair_minutes`` and adds ``lag`` and ``product``.
    """
    s = signal.select(id_col, time, value).filter(pl.col(value).is_not_null())
    a = s.rename({id_col: "a", value: "__va"})
    parts = []
    for lag in lags:
        b = s.select(
            pl.col(id_col).alias("b"),
            (pl.col(time) - pl.duration(minutes=lag)).alias(time),
            pl.col(value).alias("__vb"),
        )
        j = pair_minutes.join(a, on=["a", time]).join(b, on=["b", time])
        parts.append(
            j.with_columns(
                pl.lit(lag, dtype=pl.Int64).alias("lag"),
                (pl.col("__va") * pl.col("__vb")).alias("product"),
            ).drop("__va", "__vb")
        )
    return pl.concat(parts)


@dataclass(frozen=True)
class Interval:
    estimate: float
    lo: float
    hi: float
    n: int


def node_bootstrap_mean(
    a: np.ndarray,
    b: np.ndarray,
    values: np.ndarray,
    draws: Sequence[np.ndarray],
    *,
    counts: np.ndarray | None = None,
    level: float = 0.95,
) -> tuple[Interval, np.ndarray]:
    """Pooled mean over pair rows (people coded ``a``, ``b`` as integers), with the percentile
    interval over ``draws`` (per-person draw counts, e.g. from ``rhythm.node_bootstrap_weights``):
    in each draw a row weighs ``w[a] * w[b]``.

    Without ``counts`` each row is one value. With ``counts``, row k is an aggregate: ``values[k]``
    is the sum of ``counts[k]`` values (one row per pair keeps the bootstrap cheap). Returns the
    interval (``n`` = values pooled) and the per-draw means, for differences on the same draws.
    """
    v = np.asarray(values, dtype=float)
    n = np.ones(len(v)) if counts is None else np.asarray(counts, dtype=float)
    ok = np.isfinite(v) & (n > 0)
    a, b, v, n = np.asarray(a)[ok], np.asarray(b)[ok], v[ok], n[ok]
    est = float(v.sum() / n.sum()) if n.sum() > 0 else NAN
    means = []
    for w in draws:
        ww = (w[a] * w[b]).astype(float)
        t = (ww * n).sum()
        means.append(float((ww * v).sum() / t) if t > 0 else NAN)
    m = np.asarray(means)
    f = m[np.isfinite(m)]
    lo, hi = np.quantile(f, [0.5 - level / 2, 0.5 + level / 2]) if f.size else (NAN, NAN)
    return Interval(est, float(lo), float(hi), int(n.sum())), m


def percentile_interval(draws: np.ndarray, estimate: float, *, level: float = 0.95) -> Interval:
    """An estimate beside the central percentile interval of its (finite) bootstrap draws."""
    d = np.asarray(draws, dtype=float)
    d = d[np.isfinite(d)]
    lo, hi = np.quantile(d, [0.5 - level / 2, 0.5 + level / 2]) if d.size else (NAN, NAN)
    return Interval(float(estimate), float(lo), float(hi), len(d))
