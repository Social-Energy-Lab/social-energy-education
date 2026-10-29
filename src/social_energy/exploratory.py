"""Exploratory comparisons of events (self-report presses) against their own context.

No error control and no p-values: each function returns an effect size with an interval, or an
observed statistic beside its null distribution. Every input is passed in; nothing here knows a
study's dates, rooms or thresholds.

* **Within-person contrast** (:func:`within_person_contrast`): for each person, the mean of a
  value at their event bins minus its mean at their other bins, optionally only within matched
  strata (same day and phase of day), so each person is their own control.
* **Bootstrap over people** (:func:`bootstrap_mean`, :func:`person_rates`): percentile intervals
  from resampling whole people, since bins of one person are not independent.
* **Co-located co-events** (:func:`co_events`): pairs of events by different people close in time
  whose people were together; :func:`shuffle_events` relocates each event to a random exposure
  bin of the same person and stratum, which keeps every person's rate per stratum, and
  :func:`null_compare` sets the observed count against the shuffled ones.
"""

from __future__ import annotations

import math
from collections.abc import Hashable, Iterable, Sequence
from dataclasses import dataclass

import numpy as np
import polars as pl

NAN = float("nan")


# --- within-person contrast -----------------------------------------------------------------------


def within_person_contrast(
    bins: pl.DataFrame,
    *,
    value: str,
    event: str,
    id_col: str = "entity",
    strata: Sequence[str] = (),
) -> pl.DataFrame:
    """Per person: mean ``value`` at event bins minus mean at the same person's other bins.

    ``bins`` has one row per person and bin, ``event`` a boolean column. With ``strata`` (e.g.
    day and phase), each event bin is compared only with the person's non-event bins in the same
    stratum; strata without both kinds of bin are dropped, and the person's difference is the
    mean over their strata weighted by event bins. Columns: ``id_col``, ``events`` (event bins
    used), ``at_event``, ``baseline``, ``diff``. People with no usable stratum are left out.
    """
    keys = [id_col, *strata]
    per = bins.group_by(keys).agg(
        pl.col(event).sum().alias("events"),
        pl.col(value).filter(pl.col(event)).mean().alias("at_event"),
        pl.col(value).filter(~pl.col(event)).mean().alias("baseline"),
    )
    per = per.filter((pl.col("events") > 0) & pl.col("baseline").is_not_null())
    w = pl.col("events")
    return (
        per.group_by(id_col)
        .agg(
            w.sum().alias("events"),
            ((pl.col("at_event") * w).sum() / w.sum()).alias("at_event"),
            ((pl.col("baseline") * w).sum() / w.sum()).alias("baseline"),
        )
        .with_columns((pl.col("at_event") - pl.col("baseline")).alias("diff"))
        .sort(id_col)
    )


@dataclass(frozen=True)
class Interval:
    estimate: float
    lo: float
    hi: float
    n: int


def bootstrap_mean(
    values: Sequence[float], *, n_boot: int = 4000, seed: int = 0, level: float = 0.95
) -> Interval:
    """Mean of ``values`` (one per person) with a percentile bootstrap interval over people."""
    x = np.array([v for v in values if v is not None and not math.isnan(v)], dtype=float)
    n = len(x)
    if n < 2:
        return Interval(float(x.mean()) if n else NAN, NAN, NAN, n)
    rng = np.random.default_rng(seed)
    draws = x[rng.integers(0, n, (n_boot, n))].mean(axis=1)
    lo, hi = np.quantile(draws, [0.5 - level / 2, 0.5 + level / 2])
    return Interval(float(x.mean()), float(lo), float(hi), n)


# --- rates by category, bootstrapped over people --------------------------------------------------


@dataclass(frozen=True)
class Rates:
    """Pooled rates per category, with the bootstrap draws kept for contrasts."""

    categories: list[str]
    events: np.ndarray  # per category
    hours: np.ndarray
    people_exposed: np.ndarray
    people_with_events: np.ndarray
    rate: np.ndarray
    event_draws: np.ndarray  # n_boot x categories: events of the resampled people
    hour_draws: np.ndarray  # n_boot x categories: their hours
    level: float

    @property
    def draws(self) -> np.ndarray:
        with np.errstate(invalid="ignore", divide="ignore"):
            return self.event_draws / self.hour_draws

    def table(self, *, min_people: int, per: float = 1.0) -> pl.DataFrame:
        """One row per category; ``suppressed`` when fewer than ``min_people`` were exposed or
        when between one and ``min_people - 1`` people had events (rate and counts withheld)."""
        lo, hi = np.nanquantile(self.draws, [0.5 - self.level / 2, 0.5 + self.level / 2], axis=0)
        rows = []
        for i, c in enumerate(self.categories):
            small = self.people_exposed[i] < min_people or (
                0 < self.people_with_events[i] < min_people
            )
            rows.append(
                {
                    "category": c,
                    "people_exposed": None if small else int(self.people_exposed[i]),
                    "people_with_events": None if small else int(self.people_with_events[i]),
                    "events": None if small else int(self.events[i]),
                    "hours": None if small else float(self.hours[i]),
                    "rate": None if small else float(self.rate[i] * per),
                    "lo": None if small else float(lo[i] * per),
                    "hi": None if small else float(hi[i] * per),
                    "suppressed": bool(small),
                }
            )
        return pl.DataFrame(rows)

    def ratio(self, num: Sequence[str], den: Sequence[str]) -> Interval:
        """Pooled rate of the ``num`` categories over that of the ``den`` categories."""
        a = [self.categories.index(c) for c in num]
        b = [self.categories.index(c) for c in den]

        def r(events, hours):
            return (events[a].sum() / hours[a].sum()) / (events[b].sum() / hours[b].sum())

        est = float(r(self.events, self.hours))
        e, h = self.event_draws, self.hour_draws
        with np.errstate(invalid="ignore", divide="ignore"):
            d = (e[:, a].sum(1) / h[:, a].sum(1)) / (e[:, b].sum(1) / h[:, b].sum(1))
        d = d[np.isfinite(d)]
        lo, hi = np.quantile(d, [0.5 - self.level / 2, 0.5 + self.level / 2])
        return Interval(est, float(lo), float(hi), int(self.people_exposed.max()))


def person_rates(
    events: pl.DataFrame,
    exposure: pl.DataFrame,
    *,
    category: str,
    id_col: str = "entity",
    bin_hours: float,
    n_boot: int = 2000,
    seed: int = 0,
    level: float = 0.95,
) -> Rates:
    """Events per exposure hour in each category, pooled over people.

    ``events`` and ``exposure`` both carry ``id_col`` and ``category``: one row per event, one
    row per exposure bin of ``bin_hours``. The interval resamples people with replacement.
    Events in a category where the person had no exposure are counted as given (the caller
    should only pass events in exposure bins).
    """
    cats = sorted(set(exposure[category].drop_nulls()) | set(events[category].drop_nulls()))
    ids = sorted(set(exposure[id_col]) | set(events[id_col]))
    pos_i = {p: i for i, p in enumerate(ids)}
    pos_c = {c: j for j, c in enumerate(cats)}
    E = np.zeros((len(ids), len(cats)))
    H = np.zeros((len(ids), len(cats)))
    for p, c, n in events.group_by(id_col, category).len().iter_rows():
        if c is not None:
            E[pos_i[p], pos_c[c]] += n
    for p, c, n in exposure.group_by(id_col, category).len().iter_rows():
        if c is not None:
            H[pos_i[p], pos_c[c]] += n * bin_hours
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(ids), (n_boot, len(ids)))
    with np.errstate(invalid="ignore", divide="ignore"):
        rate = E.sum(0) / H.sum(0)
    return Rates(
        cats, E.sum(0), H.sum(0), (H > 0).sum(0), (E > 0).sum(0), rate,
        E[idx].sum(axis=1), H[idx].sum(axis=1), level,
    )  # fmt: skip


# --- co-located co-events -------------------------------------------------------------------------


class CloseIndex:
    """The ``(person, bin_start, other)`` triples of "``person`` had ``other`` at close range in
    the bin starting at ``bin_start``", indexed for vectorised look-up (shuffles query it many
    times). Bin starts are integer multiples of ``bin_size``."""

    def __init__(self, close: Iterable[tuple[Hashable, int, Hashable]], *, bin_size: int):
        triples = list(close)
        names = sorted({p for p, _, _ in triples} | {o for _, _, o in triples}, key=repr)
        self.codes = {n: i for i, n in enumerate(names)}
        self.n = max(len(names), 1)
        self.bin_size = bin_size
        if triples:
            b = np.array([b for _, b, _ in triples], dtype=np.int64) // bin_size
            self.b0, self.nb = int(b.min()), int(b.max() - b.min() + 1)
            p = self.code([t[0] for t in triples])
            o = self.code([t[2] for t in triples])
            self.keys = np.unique(self._key(p, b, o))
        else:
            self.b0, self.nb, self.keys = 0, 1, np.empty(0, dtype=np.int64)

    def code(self, entities: Sequence[Hashable]) -> np.ndarray:
        return np.array([self.codes.get(e, -1) for e in entities], dtype=np.int64)

    def _key(self, p: np.ndarray, b: np.ndarray, o: np.ndarray) -> np.ndarray:
        return (p * self.n + o) * self.nb + (b - self.b0)

    def contains_codes(self, p: np.ndarray, bins: np.ndarray, o: np.ndarray) -> np.ndarray:
        """Like :meth:`contains`, with people already coded and bins as bin starts."""
        b = np.asarray(bins, dtype=np.int64) // self.bin_size
        valid = (p >= 0) & (o >= 0) & (b >= self.b0) & (b < self.b0 + self.nb)
        out = np.zeros(len(p), dtype=bool)
        if self.keys.size and valid.any():
            k = self._key(p[valid], b[valid], o[valid])
            pos = np.clip(np.searchsorted(self.keys, k), 0, self.keys.size - 1)
            out[valid] = self.keys[pos] == k
        return out

    def contains(self, person: Sequence[Hashable], bins: Sequence[int], other) -> np.ndarray:
        """For each query: did ``person`` have ``other`` close in the bin starting at ``bins``?"""
        return self.contains_codes(self.code(person), np.asarray(bins), self.code(other))


@dataclass(frozen=True)
class EventPairs:
    """Pairs of events by different people within a window: input positions of the earlier
    (``first``) and later (``second``) event, the gap in seconds, and whether the two people were
    close in the bin of either event. Equal times keep input order."""

    first: np.ndarray
    second: np.ndarray
    gap: np.ndarray
    close: np.ndarray


def co_event_pairs(
    entity: Sequence[Hashable],
    t: Sequence[int],
    close: CloseIndex | set[tuple[Hashable, int, Hashable]],
    *,
    window: int,
    bin_size: int,
) -> EventPairs:
    """Every pair of events by different people at most ``window`` seconds apart.

    ``t`` is in integer seconds; ``close`` holds ``(person, bin_start, other)`` for every bin
    (``bin_start = t - t % bin_size``) in which ``person`` had ``other`` at close range, as a set
    or a prebuilt :class:`CloseIndex`. A pair is close when the two were close in the bin of
    either event.
    """
    if not isinstance(close, CloseIndex):
        close = CloseIndex(close, bin_size=bin_size)
    t = np.asarray(t, dtype=np.int64)
    order = np.argsort(t, kind="mergesort")
    ts = t[order]
    names = {e: i for i, e in enumerate(dict.fromkeys(entity))}
    ent = np.array([names[e] for e in entity], dtype=np.int64)[order]
    code = close.code(list(entity))[order]
    n = len(ts)
    hi = np.searchsorted(ts, ts + window, side="right")
    counts = hi - np.arange(n) - 1
    total = int(counts.sum())
    a = np.repeat(np.arange(n), counts)
    start = np.repeat(np.cumsum(counts) - counts, counts)
    b = a + 1 + (np.arange(total) - start)
    keep = ent[a] != ent[b]
    a, b = a[keep], b[keep]
    ba, bb = ts[a] - ts[a] % bin_size, ts[b] - ts[b] % bin_size
    is_close = close.contains_codes(code[a], ba, code[b]) | close.contains_codes(
        code[b], bb, code[a]
    )
    return EventPairs(order[a], order[b], ts[b] - ts[a], is_close)


def co_events(
    entity: Sequence[Hashable],
    t: Sequence[int],
    close: CloseIndex | set[tuple[Hashable, int, Hashable]],
    *,
    window: int,
    bin_size: int,
) -> tuple[int, int]:
    """Pairs of events by different people within ``window`` of each other, and how many of them
    had the two people close (:func:`co_event_pairs`). Returns ``(pairs_close, pairs_any)``."""
    p = co_event_pairs(entity, t, close, window=window, bin_size=bin_size)
    return int(p.close.sum()), len(p.gap)


def shuffle_events(
    entity: Sequence[Hashable],
    stratum: Sequence[Hashable],
    exposure: dict[tuple[Hashable, Hashable], np.ndarray],
    rng: np.random.Generator,
    *,
    bin_size: int,
) -> np.ndarray:
    """New times (integer seconds) for each event: a uniformly drawn exposure bin of the same
    person and stratum, and a uniform offset within it.

    ``exposure[(person, stratum)]`` holds that person's exposure bin starts in the stratum. Each
    person keeps their number of events per stratum, and no event lands where the person was
    not observed.
    """
    out = np.empty(len(entity), dtype=np.int64)
    for k, (p, s) in enumerate(zip(entity, stratum, strict=True)):
        starts = exposure[(p, s)]
        out[k] = starts[rng.integers(0, len(starts))] + rng.integers(0, bin_size)
    return out


@dataclass(frozen=True)
class NullComparison:
    observed: float
    null_mean: float
    null_lo: float
    null_hi: float
    ratio: float
    share_null_at_least: float
    n_shuffles: int


def null_compare(observed: float, null: Sequence[float], *, level: float = 0.95):
    """The observed statistic beside its shuffled distribution: mean, central interval, ratio of
    observed to null mean, and the share of shuffles at least as large as observed."""
    z = np.asarray(null, dtype=float)
    lo, hi = np.quantile(z, [0.5 - level / 2, 0.5 + level / 2])
    m = float(z.mean())
    return NullComparison(
        float(observed),
        m,
        float(lo),
        float(hi),
        float(observed / m) if m > 0 else NAN,
        float((z >= observed).mean()),
        len(z),
    )


# --- group moments, who goes first, ratios clustered by day ---------------------------------------


def group_members(entity: Sequence[Hashable], first: np.ndarray, second: np.ndarray) -> list[set]:
    """The distinct people of each connected component of events joined by the pairs
    ``(first[k], second[k])`` (e.g. the close pairs of :func:`co_event_pairs`). Events in no pair
    are not a group; a chain counts as one component (single linkage)."""
    parent = list(range(len(entity)))

    def root(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for a, b in zip(np.asarray(first).tolist(), np.asarray(second).tolist(), strict=True):
        ra, rb = root(a), root(b)
        if ra != rb:
            parent[rb] = ra
    members: dict[int, set] = {}
    for k in set(np.asarray(first).tolist()) | set(np.asarray(second).tolist()):
        members.setdefault(root(k), set()).add(entity[k])
    return list(members.values())


def group_sizes(entity: Sequence[Hashable], first: np.ndarray, second: np.ndarray) -> np.ndarray:
    """Distinct people in each group of :func:`group_members`, sorted."""
    return np.array(sorted(len(m) for m in group_members(entity, first, second)), dtype=np.int64)


def first_mover_logit(diff: np.ndarray, *, max_iter: int = 50, tol: float = 1e-10) -> np.ndarray:
    """Coefficients of P(this one first) = logistic(beta . (x_first - x_second)), from ordered
    pairs (Bradley-Terry with covariates, no intercept, since the model must be symmetric).

    ``diff`` is pairs x covariates: the first event's person minus the second's. Newton-Raphson;
    NaN when it does not converge (e.g. complete separation).
    """
    d = np.atleast_2d(np.asarray(diff, dtype=float))
    beta = np.zeros(d.shape[1])
    for _ in range(max_iter):
        p = 1 / (1 + np.exp(-(d @ beta)))
        grad = d.T @ (1 - p)
        hess = (d * (p * (1 - p))[:, None]).T @ d
        try:
            step = np.linalg.solve(hess, grad)
        except np.linalg.LinAlgError:
            return np.full(d.shape[1], NAN)
        beta = beta + step
        if np.max(np.abs(step)) < tol:
            return beta
    return np.full(d.shape[1], NAN)


def cluster_ratio(
    observed: np.ndarray,
    expected: np.ndarray,
    *,
    n_boot: int = 4000,
    seed: int = 0,
    level: float = 0.95,
) -> Interval | list[Interval]:
    """Pooled ratio sum(observed) / sum(expected) with a percentile interval from resampling
    clusters (rows, e.g. camp days) with replacement.

    ``expected`` is typically the mean of a shuffled null per cluster. With 2-D input (clusters x
    categories) one interval per category is returned, all from the same resampled clusters.
    """
    obs, exp_ = np.asarray(observed, dtype=float), np.asarray(expected, dtype=float)
    one = obs.ndim == 1
    if one:
        obs, exp_ = obs[:, None], exp_[:, None]
    k = obs.shape[0]
    idx = np.random.default_rng(seed).integers(0, k, (n_boot, k))
    with np.errstate(invalid="ignore", divide="ignore"):
        est = obs.sum(0) / exp_.sum(0)
        draws = obs[idx].sum(1) / exp_[idx].sum(1)
    out = []
    for c in range(obs.shape[1]):
        d = draws[:, c][np.isfinite(draws[:, c])]
        lo, hi = np.quantile(d, [0.5 - level / 2, 0.5 + level / 2]) if d.size else (NAN, NAN)
        out.append(Interval(float(est[c]), float(lo), float(hi), k))
    return out[0] if one else out
