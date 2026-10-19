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
from collections.abc import Hashable, Sequence
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


def co_events(
    entity: Sequence[Hashable],
    t: Sequence[int],
    close: set[tuple[Hashable, int, Hashable]],
    *,
    window: int,
    bin_size: int,
) -> tuple[int, int]:
    """Pairs of events by different people within ``window`` of each other, and how many of them
    had the two people close.

    ``t`` is in integer seconds; ``close`` holds ``(person, bin_start, other)`` for every bin
    (``bin_start = t - t % bin_size``) in which ``person`` had ``other`` at close range. A pair
    counts as close when the two were close in the bin of either event. Returns
    ``(pairs_close, pairs_any)``.
    """
    t = np.asarray(t, dtype=np.int64)
    order = np.argsort(t, kind="mergesort")
    ts = t[order]
    es = [entity[i] for i in order]
    pairs_any = pairs_close = 0
    for i in range(len(ts)):
        j = i + 1
        while j < len(ts) and ts[j] - ts[i] <= window:
            if es[j] != es[i]:
                pairs_any += 1
                bi, bj = ts[i] - ts[i] % bin_size, ts[j] - ts[j] % bin_size
                if (es[i], bi, es[j]) in close or (es[j], bj, es[i]) in close:
                    pairs_close += 1
            j += 1
    return pairs_close, pairs_any


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
