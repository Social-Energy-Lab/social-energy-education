"""Pair-level (dyadic) comparisons of person attributes, against node-permutation nulls.

Pairs of people are not independent observations: every person appears in many pairs, so a
naive pair-level interval is far too narrow. The functions here follow the QAP logic instead:
fit a statistic on the observed pairs, then recompute it after permuting the *people's*
attributes (optionally only among people of the same group), which keeps the network and every
pair-level control fixed and breaks only the link between attributes and pairs.

* :func:`pair_index`, :func:`attribute_distance`: all unordered pairs and the distance between
  the two people's attribute vectors (absolute difference for one attribute, Euclidean for more).
* :class:`Residualiser`, :func:`node_dummies`, :func:`partial_fit`: a pair-level linear model by
  Frisch-Waugh-Lovell. The controls (pair covariates and one dummy per person, so each person's
  overall sociability and exposure are absorbed) are projected out once; the slope of the
  attribute distance is then cheap to recompute for every permutation.
* :func:`node_permutation_null`, :func:`null_position`: the permuted statistics and where the
  observed one falls among them.
* :func:`event_times`, :func:`partner_coevents`: for each event of a person, every partner who was
  close in the event's bin, and whether the partner had an event of their own within a window.

Nothing here knows a study's people, groups or thresholds; they are passed in.
"""

from __future__ import annotations

from collections.abc import Callable, Hashable, Mapping, Sequence
from dataclasses import dataclass

import numpy as np

from social_energy.confirmatory import permute_within

NAN = float("nan")


# --- pairs and distances --------------------------------------------------------------------------


def pair_index(n: int) -> tuple[np.ndarray, np.ndarray]:
    """Positions ``(i, j)`` of every unordered pair of ``n`` people, ``i < j``, row by row."""
    i, j = np.triu_indices(n, k=1)
    return i.astype(np.int64), j.astype(np.int64)


def attribute_distance(X: np.ndarray, i: np.ndarray, j: np.ndarray) -> np.ndarray:
    """Distance between people ``i[k]`` and ``j[k]`` on the attribute rows of ``X``.

    ``X`` is people x attributes (or one attribute as a 1-D array). With one attribute this is the
    absolute difference, with several the Euclidean distance. A pair with a missing value on
    either side is NaN.
    """
    X = np.asarray(X, dtype=float)
    if X.ndim == 1:
        X = X[:, None]
    d = X[np.asarray(i)] - X[np.asarray(j)]
    return np.sqrt((d**2).sum(axis=1))


# --- a pair-level linear model by Frisch-Waugh-Lovell ---------------------------------------------


def node_dummies(i: np.ndarray, j: np.ndarray, n: int) -> np.ndarray:
    """Pairs x ``n`` matrix with a 1 in the columns of both people of each pair.

    As controls these absorb each person's own level of the outcome (sociability, time worn), so
    only what is specific to the pair is left for the pair-level predictor.
    """
    D = np.zeros((len(i), n))
    rows = np.arange(len(i))
    D[rows, np.asarray(i)] = 1.0
    D[rows, np.asarray(j)] = 1.0
    return D


class Residualiser:
    """Projects vectors onto the orthogonal complement of the columns of ``Z`` (the controls).

    Rank-deficient ``Z`` is fine: the projection uses an orthonormal basis of its column space.
    """

    def __init__(self, Z: np.ndarray, *, tol: float = 1e-9):
        Z = np.asarray(Z, dtype=float)
        if Z.ndim == 1:
            Z = Z[:, None]
        if Z.shape[1] == 0:
            self.Q = np.zeros((Z.shape[0], 0))
        else:
            U, s, _ = np.linalg.svd(Z, full_matrices=False)
            self.Q = U[:, s > tol * max(s.max(), 1.0)]

    @property
    def rank(self) -> int:
        return self.Q.shape[1]

    def __call__(self, v: np.ndarray) -> np.ndarray:
        v = np.asarray(v, dtype=float)
        return v - self.Q @ (self.Q.T @ v)


@dataclass(frozen=True)
class PartialFit:
    """Slope of ``y`` on ``x`` given the controls, and the partial correlation."""

    slope: float
    partial_r: float
    n: int


def partial_fit(y_res: np.ndarray, x_res: np.ndarray) -> PartialFit:
    """The OLS slope and partial correlation from ``y`` and ``x`` already residualised on the same
    controls (:class:`Residualiser`). Equal to the coefficient of ``x`` in the full regression.
    NaN when ``x`` is (numerically) explained by the controls."""
    y, x = np.asarray(y_res, dtype=float), np.asarray(x_res, dtype=float)
    xx, yy, xy = float(x @ x), float(y @ y), float(x @ y)
    if xx <= 1e-12 * max(len(x), 1):
        return PartialFit(NAN, NAN, len(y))
    r = xy / np.sqrt(xx * yy) if yy > 0 else NAN
    return PartialFit(xy / xx, float(r), len(y))


# --- node-permutation nulls -----------------------------------------------------------------------


def node_permutation_null(
    statistic: Callable[[np.ndarray], float],
    groups: Sequence[Hashable],
    *,
    n_perm: int,
    seed: int,
) -> np.ndarray:
    """``statistic(perm)`` for ``n_perm`` permutations of the people.

    ``perm`` is an index array over people (``groups`` has one entry per person): person ``k``
    takes the attributes of person ``perm[k]``. People only swap with people of the same group,
    so a group's attribute mix is kept. Failed statistics (NaN) stay in the array as NaN.
    """
    rng = np.random.default_rng(seed)
    out = np.empty(n_perm)
    for b in range(n_perm):
        out[b] = statistic(permute_within(groups, rng))
    return out


@dataclass(frozen=True)
class NullPosition:
    """Where an observed statistic falls in its null distribution.

    ``percentile`` is the share of null draws below the observed value (ties count half);
    ``share_as_extreme`` the share at least as far from the null mean as the observed value, in
    either direction.
    """

    observed: float
    null_mean: float
    null_lo: float
    null_hi: float
    percentile: float
    share_as_extreme: float
    n: int


def null_position(observed: float, null: Sequence[float], *, level: float = 0.95) -> NullPosition:
    z = np.asarray(null, dtype=float)
    z = z[np.isfinite(z)]
    if not z.size or not np.isfinite(observed):
        return NullPosition(float(observed), NAN, NAN, NAN, NAN, NAN, int(z.size))
    lo, hi = np.quantile(z, [0.5 - level / 2, 0.5 + level / 2])
    m = float(z.mean())
    below = float((z < observed).mean() + 0.5 * (z == observed).mean())
    extreme = float((np.abs(z - m) >= abs(observed - m) - 1e-12).mean())
    return NullPosition(float(observed), m, float(lo), float(hi), below, extreme, int(z.size))


# --- partners at events ---------------------------------------------------------------------------


def event_times(entity: Sequence[Hashable], t: Sequence[int]) -> dict[Hashable, np.ndarray]:
    """Each person's event times (integer seconds), sorted."""
    t = np.asarray(t, dtype=np.int64)
    out: dict[Hashable, list[int]] = {}
    for e, x in zip(entity, t.tolist(), strict=True):
        out.setdefault(e, []).append(x)
    return {e: np.sort(np.asarray(v, dtype=np.int64)) for e, v in out.items()}


@dataclass(frozen=True)
class PartnerEvents:
    """One row per (event, partner close in the event's bin): the event's input position, the
    partner, and whether the partner had an event within the window of it."""

    event: np.ndarray
    partner: list
    coevent: np.ndarray


def partner_coevents(
    entity: Sequence[Hashable],
    t: Sequence[int],
    partners: Mapping[tuple[Hashable, int], Sequence[Hashable]],
    *,
    window: int,
    bin_size: int,
) -> PartnerEvents:
    """For each event ``k`` (person ``entity[k]`` at ``t[k]`` seconds), every partner in
    ``partners[(entity[k], bin_start)]`` (``bin_start = t - t % bin_size``) and whether that
    partner had an event at most ``window`` seconds before or after ``t[k]``.

    The caller decides who counts as a partner in a bin (e.g. close, and able to have an event
    there); the partner's events are taken from the same ``entity`` and ``t``.
    """
    t = np.asarray(t, dtype=np.int64)
    times = event_times(entity, t)
    ev, who, hit = [], [], []
    for k, (e, x) in enumerate(zip(entity, t.tolist(), strict=True)):
        for o in partners.get((e, x - x % bin_size), ()):
            if o == e:
                continue
            ts = times.get(o)
            found = False
            if ts is not None:
                p = int(np.searchsorted(ts, x - window, side="left"))
                found = p < len(ts) and ts[p] <= x + window
            ev.append(k)
            who.append(o)
            hit.append(found)
    return PartnerEvents(np.asarray(ev, dtype=np.int64), who, np.asarray(hit, dtype=bool))
