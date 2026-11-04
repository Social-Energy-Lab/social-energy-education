"""A person's company around their events, lag by lag.

The time series idea follows Wu et al. 2025 (*Nature Communications* 16, 3539, Fig. 2h-k): a value
per person and time bin, read at fixed offsets from each event, and cluster inference over the
offsets (Maris & Oostenveld 2007). What counts as chance is the caller's: it passes the same
readings for shuffled events and subtracts them, so a null can keep the timetable.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


def lag_sums(
    values: np.ndarray, person: np.ndarray, at: np.ndarray, lags: np.ndarray, n_people: int
) -> tuple[np.ndarray, np.ndarray]:
    """Per person and lag, the sum and number of readings ``values[person, at + lag]``.

    ``values`` is people x bins with NaN where there is no reading; ``person`` and ``at`` give one
    event per entry, ``lags`` are in bins. Readings off the grid or NaN are not counted.
    """
    idx = np.asarray(at)[:, None] + np.asarray(lags)[None, :]
    on_grid = (idx >= 0) & (idx < values.shape[1])
    who = np.repeat(np.asarray(person)[:, None], len(lags), axis=1)
    read = np.full(idx.shape, np.nan)
    read[on_grid] = values[who[on_grid], idx[on_grid]]
    ok = ~np.isnan(read)
    sums = np.zeros((n_people, len(lags)))
    counts = np.zeros((n_people, len(lags)), dtype=np.int64)
    col = np.broadcast_to(np.arange(len(lags)), idx.shape)
    np.add.at(sums, (who[ok], col[ok]), read[ok])
    np.add.at(counts, (who[ok], col[ok]), 1)
    return sums, counts


def person_lag_means(
    sums: np.ndarray, counts: np.ndarray, events: np.ndarray, *, min_events: int
) -> np.ndarray:
    """People x lags: mean reading, NaN without a reading or for people under ``min_events``."""
    with np.errstate(invalid="ignore", divide="ignore"):
        m = sums / counts
    m[counts == 0] = np.nan
    m[np.asarray(events) < min_events] = np.nan
    return m


def window_mean(d: np.ndarray, lags: np.ndarray, lo: int, hi: int) -> np.ndarray:
    """Per person, the mean over the lags from ``lo`` to ``hi`` inclusive, skipping missing."""
    keep = (np.asarray(lags) >= lo) & (np.asarray(lags) <= hi)
    part = d[:, keep]
    n = (~np.isnan(part)).sum(axis=1)
    with np.errstate(invalid="ignore", divide="ignore"):
        out = np.nansum(part, axis=1) / n
    out[n == 0] = np.nan
    return out


def plant_after(
    values: np.ndarray, person: np.ndarray, at: np.ndarray, lo: int, hi: int, delta: float
) -> np.ndarray:
    """A copy of ``values`` raised by ``delta`` at lags ``lo`` to ``hi`` after each event.

    For checking what an analysis can see. Overlapping events add up; bins off the grid are
    skipped and missing readings stay missing.
    """
    out = values.copy()
    for p, b in zip(np.asarray(person).tolist(), np.asarray(at).tolist(), strict=True):
        out[p, max(b + lo, 0) : max(b + hi + 1, 0)] += delta
    return out


def component_sizes(n: int, a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Size of each of ``n`` nodes' connected component, given the edges ``a[k]``-``b[k]``."""
    parent = list(range(n))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for x, y in zip(np.asarray(a).tolist(), np.asarray(b).tolist(), strict=True):
        parent[find(x)] = find(y)
    roots = np.array([find(x) for x in range(n)], dtype=np.int64)
    return np.bincount(roots, minlength=n)[roots]


def eigenvector_centrality(W: np.ndarray) -> np.ndarray:
    """Leading eigenvector of the symmetric weights ``W``, scaled so the largest entry is 1.

    Without edges, all zeros. In a disconnected graph only the component with the largest
    eigenvalue is non-zero, so the measure reads "in the densest group", not "in some group".
    """
    if not W.any():
        return np.zeros(len(W))
    _, vectors = np.linalg.eigh(W)
    v = np.abs(vectors[:, -1])
    v[v < 1e-9] = 0.0
    return v / v.max()


def t_cut(n: int, alpha: float = 0.05) -> float:
    """The two-sided ``alpha`` point of Student's t for a one-sample test on ``n`` values."""
    from scipy.stats import t

    return float(t.ppf(1 - alpha / 2, n - 1))


@dataclass(frozen=True)
class Cluster:
    """Neighbouring lags (positions ``start`` to ``stop``, inclusive) past the cut, of one sign."""

    start: int
    stop: int
    sign: int
    mass: float
    p: float


def _clusters(t: np.ndarray, cut: float) -> list[tuple[int, int, float]]:
    out: list[tuple[int, int, float]] = []
    k = 0
    while k < len(t):
        if not np.isfinite(t[k]) or abs(t[k]) <= cut:
            k += 1
            continue
        stop = k
        while (
            stop + 1 < len(t)
            and np.isfinite(t[stop + 1])
            and abs(t[stop + 1]) > cut
            and np.sign(t[stop + 1]) == np.sign(t[k])
        ):
            stop += 1
        out.append((k, stop, float(t[k : stop + 1].sum())))
        k = stop + 1
    return out


def cluster_mass(
    d: np.ndarray, *, n_perm: int = 10_000, seed: int = 0, alpha: float = 0.05
) -> list[Cluster]:
    """Clusters of lags in ``d`` (people x lags, NaN allowed), with permutation p-values.

    A one-sample t per lag; lags past the two-sided ``alpha`` cut form clusters of one sign, whose
    mass is their summed t. Under the null a person's curve is as likely flipped as not, so each
    permutation flips whole people; ``p`` is the share of permutations whose largest absolute mass
    reaches the cluster's, which holds the error rate over the whole curve.
    """
    d = d[~np.isnan(d).all(axis=1)]
    x = np.nan_to_num(d)
    n = (~np.isnan(d)).sum(axis=0)
    usable = n >= 3
    ss = (x**2).sum(axis=0)
    cut = t_cut(int(np.median(n[usable])), alpha) if usable.any() else np.inf

    def t_of(summed: np.ndarray) -> np.ndarray:
        with np.errstate(invalid="ignore", divide="ignore"):
            m = summed / n
            s2 = (ss - n * m**2) / (n - 1)
            t = m / np.sqrt(s2 / n)
        return np.where(usable, t, np.nan)

    observed = _clusters(t_of(x.sum(axis=0)), cut)
    if not observed:
        return []
    rng = np.random.default_rng(seed)
    flips = rng.choice([-1.0, 1.0], size=(n_perm, len(x)))
    t_null = t_of(flips @ x)
    largest = np.array(
        [max((abs(c[2]) for c in _clusters(row, cut)), default=0.0) for row in t_null]
    )
    return [
        Cluster(
            a, b, int(np.sign(mass)), mass, (1 + int((largest >= abs(mass)).sum())) / (1 + n_perm)
        )
        for a, b, mass in observed
    ]
