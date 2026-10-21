"""Correlations with intervals, for exploratory reporting.

No p-values: an exploratory analysis reports an effect size and how uncertain it is. Two kinds of
interval:

- ``correlation``: Fisher's z interval, which assumes independent observations (Pearson's
  ``se = 1/sqrt(n-3)``; Spearman uses the Bonett-Wright ``se = sqrt((1 + r^2/2)/(n-3))``).
- ``cluster_bootstrap``: a percentile bootstrap that resamples whole clusters, for observations
  that come in correlated runs (time bins within one recording session). Treating such bins as
  independent would make the interval far too narrow.
"""

from __future__ import annotations

import math
from collections.abc import Hashable, Sequence
from dataclasses import dataclass
from statistics import NormalDist

import numpy as np

NAN = float("nan")


@dataclass(frozen=True)
class Correlation:
    r: float
    lo: float
    hi: float
    n: int
    method: str
    clusters: int | None = None


def _clean(x: Sequence, y: Sequence, extra: Sequence | None = None):
    rows = [
        (a, b, c)
        for a, b, c in zip(x, y, extra if extra is not None else [None] * len(x), strict=True)
        if a is not None and b is not None and not math.isnan(a) and not math.isnan(b)
    ]
    xs = np.array([float(a) for a, _, _ in rows])
    ys = np.array([float(b) for _, b, _ in rows])
    return xs, ys, [c for _, _, c in rows]


def _ranks(v: np.ndarray) -> np.ndarray:
    """Ranks from 1, ties sharing their average rank."""
    order = np.argsort(v, kind="mergesort")
    ranks = np.empty(len(v))
    sorted_v = v[order]
    i = 0
    while i < len(v):
        j = i
        while j + 1 < len(v) and sorted_v[j + 1] == sorted_v[i]:
            j += 1
        ranks[order[i : j + 1]] = (i + j) / 2 + 1
        i = j + 1
    return ranks


def _r(x: np.ndarray, y: np.ndarray, method: str) -> float:
    if method == "spearman":
        x, y = _ranks(x), _ranks(y)
    elif method != "pearson":
        raise ValueError(f"unknown method {method!r}")
    if len(x) < 2:
        return NAN
    dx, dy = x - x.mean(), y - y.mean()
    denom = math.sqrt(float((dx**2).sum() * (dy**2).sum()))
    return NAN if denom == 0 else float((dx * dy).sum() / denom)


def correlation(
    x: Sequence, y: Sequence, *, method: str = "pearson", level: float = 0.95
) -> Correlation:
    """Correlation of the complete pairs, with a Fisher z interval (NaN when ``n <= 3``)."""
    xs, ys, _ = _clean(x, y)
    n = len(xs)
    r = _r(xs, ys, method)
    if n <= 3 or math.isnan(r):
        return Correlation(r, NAN, NAN, n, method)
    if abs(r) >= 1:
        return Correlation(r, r, r, n, method)
    var = (1 + r**2 / 2) if method == "spearman" else 1.0
    se = math.sqrt(var / (n - 3))
    zq = NormalDist().inv_cdf(0.5 + level / 2)
    z = math.atanh(r)
    return Correlation(r, math.tanh(z - zq * se), math.tanh(z + zq * se), n, method)


def _cluster_draws(
    x: Sequence,
    y: Sequence,
    clusters: Sequence[Hashable],
    *,
    method: str,
    n_boot: int,
    seed: int,
) -> list[float]:
    xs, ys, cs = _clean(x, y, clusters)
    groups: dict[Hashable, list[int]] = {}
    for i, c in enumerate(cs):
        groups.setdefault(c, []).append(i)
    members = list(groups.values())
    rng = np.random.default_rng(seed)
    draws = []
    for _ in range(n_boot):
        pick = rng.integers(0, len(members), len(members))
        idx = np.concatenate([members[k] for k in pick])
        r = _r(xs[idx], ys[idx], method)
        if not math.isnan(r):
            draws.append(r)
    return draws


def cluster_bootstrap(
    x: Sequence,
    y: Sequence,
    clusters: Sequence[Hashable],
    *,
    method: str = "pearson",
    n_boot: int = 2000,
    level: float = 0.95,
    seed: int = 0,
) -> Correlation:
    """Correlation of the complete pairs, with a percentile interval from resampling clusters.

    Resamples that leave one side constant have no correlation and are skipped. Fewer than three
    clusters give no interval.
    """
    xs, ys, cs = _clean(x, y, clusters)
    r = _r(xs, ys, method)
    k = len(set(cs))
    if k < 3 or math.isnan(r):
        return Correlation(r, NAN, NAN, len(xs), method, k)
    draws = _cluster_draws(x, y, clusters, method=method, n_boot=n_boot, seed=seed)
    if not draws:
        return Correlation(r, NAN, NAN, len(xs), method, k)
    lo, hi = np.quantile(draws, [0.5 - level / 2, 0.5 + level / 2])
    return Correlation(r, float(lo), float(hi), len(xs), method, k)


@dataclass(frozen=True)
class Coefficient:
    name: str
    estimate: float
    se: float
    lo: float
    hi: float
    n: int
    clusters: int


def within_ols(
    y: Sequence[float],
    x: np.ndarray,
    names: Sequence[str],
    *,
    absorb: Sequence[Hashable],
    cluster: Sequence[Hashable],
    level: float = 0.95,
) -> list[Coefficient]:
    """OLS of ``y`` on the columns of ``x`` with one fixed effect per ``absorb`` group (absorbed
    by demeaning within the group), and cluster-robust (CR1) standard errors by ``cluster``.

    Rows with a non-finite value are dropped. The small-sample factor is
    ``G/(G-1) * (N-1)/(N-K)`` with ``K`` the columns of ``x`` (the absorbed effects are not
    counted, as is usual when the groups nest within clusters). Intervals are normal. A column
    without variation within any group gets NaN.
    """
    yv = np.asarray(y, dtype=float)
    xv = np.asarray(x, dtype=float).reshape(len(yv), -1)
    ok = np.isfinite(yv) & np.isfinite(xv).all(axis=1)
    yv, xv = yv[ok], xv[ok]
    _, g = np.unique(np.asarray(absorb, dtype=object)[ok].astype(str), return_inverse=True)
    _, c = np.unique(np.asarray(cluster, dtype=object)[ok].astype(str), return_inverse=True)
    counts = np.bincount(g)

    def demean(v: np.ndarray) -> np.ndarray:
        return v - (np.bincount(g, weights=v) / counts)[g]

    yd = demean(yv)
    xd = np.column_stack([demean(xv[:, j]) for j in range(xv.shape[1])])
    n, k = xd.shape
    keep = np.abs(xd).sum(axis=0) > 1e-12
    out = []
    est = np.full(k, NAN)
    se = np.full(k, NAN)
    if keep.any() and n > keep.sum():
        xk = xd[:, keep]
        bread = np.linalg.pinv(xk.T @ xk)
        beta = bread @ xk.T @ yd
        u = yd - xk @ beta
        n_c = int(c.max()) + 1
        scores = np.zeros((n_c, xk.shape[1]))
        np.add.at(scores, c, xk * u[:, None])
        meat = scores.T @ scores
        kk = xk.shape[1]
        factor = (n_c / (n_c - 1)) * ((n - 1) / (n - kk)) if n_c > 1 else NAN
        cov = factor * bread @ meat @ bread
        est[keep] = beta
        se[keep] = np.sqrt(np.diag(cov))
    zq = NormalDist().inv_cdf(0.5 + level / 2)
    n_clusters = len(set(c.tolist()))
    for j, name in enumerate(names):
        out.append(
            Coefficient(name, float(est[j]), float(se[j]), float(est[j] - zq * se[j]),
                        float(est[j] + zq * se[j]), n, n_clusters)
        )  # fmt: skip
    return out
