"""The programme's rhythm: mixing on special days, whether new ties last, and the clock as confound.

Inputs are the canonical tables of :mod:`social_energy.outcomes`:

* **ties**: ``day``, ``a``, ``b``, ``minutes`` (:func:`social_energy.outcomes.daily_close_ties`);
* **present**: ``entity``, ``day`` (:func:`social_energy.outcomes.present_days`);
* **groups**: entity -> group (e.g. course), ``None`` when unknown.

The measures:

* :func:`daily_mixing`: per day, the share of ties (and of tie minutes) that join two groups,
  next to the share of pairs of present people that would, ``1 - sum n_g (n_g - 1) / (N (N - 1))``,
  which is what random mixing among the people present would give.
* :func:`period_mixing`: per person and period (a label per day, e.g. ``special`` /
  ``ordinary``), the person's cross-group share of tie minutes, the random-mixing share expected
  for them, ``(N_d - n_g,d) / (N_d - 1)`` per day weighted by their tie minutes that day, and the
  difference. A within-person contrast between periods then compares people with themselves.
* :func:`retie_opportunities`: every *new* tie (a pair's first tie, on a day from ``first_from``)
  against every later day on which both partners were present, with whether they were tied again.
  Persistence then compares ties by the kind of day they formed on; a model with a term per
  follow-up day absorbs days on which the instrument saw less (fewer ties for everyone).
* :func:`node_bootstrap_weights`: resampling people, not pairs, for statistics over ties: a pair's
  weight in a draw is the product of how often each partner was drawn.
* :func:`within_strata_correlation`: a correlation after removing each stratum's mean (e.g. hour
  of day), recomputed inside every cluster-bootstrap draw.

Nothing here knows a study's days, groups or thresholds; they are passed in.
"""

from __future__ import annotations

import math
from collections.abc import Hashable, Iterable, Mapping, Sequence
from datetime import date

import numpy as np
import polars as pl

from social_energy.stats import NAN, Correlation


def _group_frame(groups: Mapping[str, str | None]) -> pl.DataFrame:
    return pl.DataFrame(
        {"entity": list(groups), "group": list(groups.values())},
        schema={"entity": pl.String, "group": pl.String},
    )


def _with_groups(ties: pl.DataFrame, groups: Mapping[str, str | None]) -> pl.DataFrame:
    g = _group_frame(groups)
    return (
        ties.join(g.rename({"entity": "a", "group": "ga"}), on="a", how="left")
        .join(g.rename({"entity": "b", "group": "gb"}), on="b", how="left")
        .filter(pl.col("ga").is_not_null() & pl.col("gb").is_not_null())
        .with_columns((pl.col("ga") != pl.col("gb")).alias("cross"))
    )


def _present_known(present: pl.DataFrame, groups: Mapping[str, str | None]) -> pl.DataFrame:
    return (
        present.select("entity", "day")
        .unique()
        .join(_group_frame(groups), on="entity")
        .filter(pl.col("group").is_not_null())
    )


def daily_mixing(
    ties: pl.DataFrame, present: pl.DataFrame, groups: Mapping[str, str | None]
) -> pl.DataFrame:
    """One row per day with present people of a known group.

    Only ties between two people present that day with a known group count. Columns: ``day``,
    ``people`` (present, known group), ``ties``, ``cross_ties``, ``minutes``, ``cross_minutes``,
    ``cross_share`` (of ties), ``cross_share_minutes``, ``expected`` (random pairs), ``excess``
    (``cross_share - expected``). Shares without a denominator are null.
    """
    known = _present_known(present, groups)
    t = (
        _with_groups(ties, groups)
        .join(known.select("entity", "day"), left_on=["a", "day"], right_on=["entity", "day"],
              how="semi")
        .join(known.select("entity", "day"), left_on=["b", "day"], right_on=["entity", "day"],
              how="semi")
    )  # fmt: skip
    sizes = known.group_by("day", "group").agg(pl.len().alias("n_g"))
    expected = sizes.group_by("day").agg(
        pl.col("n_g").sum().alias("people"),
        (pl.col("n_g") * (pl.col("n_g") - 1)).sum().alias("_same"),
    )
    expected = expected.with_columns(
        pl.when(pl.col("people") > 1)
        .then(1 - pl.col("_same") / (pl.col("people") * (pl.col("people") - 1)))
        .alias("expected")
    ).drop("_same")
    counts = t.group_by("day").agg(
        pl.len().alias("ties"),
        pl.col("cross").sum().alias("cross_ties"),
        pl.col("minutes").sum().alias("minutes"),
        pl.col("minutes").filter(pl.col("cross")).sum().alias("cross_minutes"),
    )
    return (
        expected.join(counts, on="day", how="left")
        .with_columns(pl.col("ties", "cross_ties", "minutes", "cross_minutes").fill_null(0))
        .with_columns(
            pl.when(pl.col("ties") > 0)
            .then(pl.col("cross_ties") / pl.col("ties"))
            .alias("cross_share"),
            pl.when(pl.col("minutes") > 0)
            .then(pl.col("cross_minutes") / pl.col("minutes"))
            .alias("cross_share_minutes"),
        )
        .with_columns((pl.col("cross_share") - pl.col("expected")).alias("excess"))
        .select(
            "day", "people", "ties", "cross_ties", "minutes", "cross_minutes", "cross_share",
            "cross_share_minutes", "expected", "excess",
        )
        .sort("day")
    )  # fmt: skip


def period_mixing(
    ties: pl.DataFrame,
    present: pl.DataFrame,
    groups: Mapping[str, str | None],
    period: Mapping[date, str],
) -> pl.DataFrame:
    """One row per person and period in which the person has tie minutes with a known group.

    Only days in ``period`` count, ties on the person's present days, partners of a known group.
    Columns: ``entity``, ``period``, ``days``, ``minutes``, ``cross_minutes``, ``cross_share``,
    ``expected`` (the person's random-mixing share per day, weighted by their tie minutes that
    day), ``excess``.
    """
    days = list(period)
    lab = pl.DataFrame(
        {"day": days, "period": [period[d] for d in days]},
        schema={"day": pl.Date, "period": pl.String},
    )
    known = _present_known(present, groups).filter(pl.col("day").is_in(days))
    sizes = known.group_by("day", "group").agg(pl.len().alias("n_g"))
    totals = known.group_by("day").agg(pl.len().alias("n"))
    own_expected = (
        known.join(sizes, on=["day", "group"])
        .join(totals, on="day")
        .with_columns(
            pl.when(pl.col("n") > 1)
            .then((pl.col("n") - pl.col("n_g")) / (pl.col("n") - 1))
            .alias("expected")
        )
        .select("entity", "day", "expected")
    )
    t = _with_groups(ties.filter(pl.col("day").is_in(days)), groups)
    ends = pl.concat(
        [
            t.select(pl.col("a").alias("entity"), "day", "minutes", "cross"),
            t.select(pl.col("b").alias("entity"), "day", "minutes", "cross"),
        ]
    ).join(known.select("entity", "day"), on=["entity", "day"], how="semi")
    per_day = (
        ends.group_by("entity", "day")
        .agg(
            pl.col("minutes").sum(),
            pl.col("minutes").filter(pl.col("cross")).sum().alias("cross_minutes"),
        )
        .join(own_expected, on=["entity", "day"], how="left")
        .join(lab, on="day")
    )
    return (
        per_day.group_by("entity", "period")
        .agg(
            pl.len().alias("days"),
            pl.col("minutes").sum(),
            pl.col("cross_minutes").sum(),
            ((pl.col("expected") * pl.col("minutes")).sum() / pl.col("minutes").sum()).alias(
                "expected"
            ),
        )
        .with_columns((pl.col("cross_minutes") / pl.col("minutes")).alias("cross_share"))
        .with_columns((pl.col("cross_share") - pl.col("expected")).alias("excess"))
        .select(
            "entity", "period", "days", "minutes", "cross_minutes", "cross_share", "expected",
            "excess",
        )
        .sort("entity", "period")
    )  # fmt: skip


def retie_opportunities(
    ties: pl.DataFrame, present: pl.DataFrame, *, first_from: date, days: Iterable[date]
) -> pl.DataFrame:
    """Each new tie against each later day of ``days`` on which both partners were present.

    A tie is new on the pair's first tied day among ``days``, if that day is on or after
    ``first_from`` (earlier first ties set the baseline and are never new). Columns: ``a``, ``b``,
    ``formed``, ``day`` (the follow-up day), ``lag`` (days), ``tied`` (tied again that day).
    """
    days = sorted(set(days))
    ties = ties.filter(pl.col("day").is_in(days))
    first = (
        ties.group_by("a", "b")
        .agg(pl.col("day").min().alias("formed"))
        .filter(pl.col("formed") >= first_from)
    )
    p = present.select("entity", "day").unique().filter(pl.col("day").is_in(days))
    later = first.join(pl.DataFrame({"day": days}, schema={"day": pl.Date}), how="cross").filter(
        pl.col("day") > pl.col("formed")
    )
    both = later.join(p, left_on=["a", "day"], right_on=["entity", "day"], how="semi").join(
        p, left_on=["b", "day"], right_on=["entity", "day"], how="semi"
    )
    tied = ties.select("a", "b", "day").unique().with_columns(pl.lit(True).alias("tied"))
    return (
        both.join(tied, on=["a", "b", "day"], how="left")
        .with_columns(
            pl.col("tied").fill_null(False),
            (pl.col("day") - pl.col("formed")).dt.total_days().cast(pl.Int32).alias("lag"),
        )
        .select("a", "b", "formed", "day", "lag", "tied")
        .sort("formed", "a", "b", "day")
    )


def node_bootstrap_weights(n_people: int, *, n_boot: int, seed: int = 0):
    """Yield ``n_boot`` arrays of length ``n_people``: how often each person is drawn.

    Draw ``n_people`` people with replacement. For a statistic over pairs, a pair's weight is the
    product of its two partners' counts; a statistic over people uses the counts directly.
    """
    rng = np.random.default_rng(seed)
    for _ in range(n_boot):
        yield np.bincount(rng.integers(0, n_people, n_people), minlength=n_people)


def _ranks(v: np.ndarray) -> np.ndarray:
    """Ranks from 1, ties sharing their average rank (vectorised)."""
    _, inv, counts = np.unique(v, return_inverse=True, return_counts=True)
    ends = np.cumsum(counts)
    return ((ends - counts + 1 + ends) / 2)[inv]


def _demeaned_r(x: np.ndarray, y: np.ndarray, strata: np.ndarray, method: str) -> float:
    if method == "spearman":
        x, y = _ranks(x), _ranks(y)
    elif method != "pearson":
        raise ValueError(f"unknown method {method!r}")
    _, inv = np.unique(strata, return_inverse=True)
    counts = np.bincount(inv)
    dx = x - (np.bincount(inv, weights=x) / counts)[inv]
    dy = y - (np.bincount(inv, weights=y) / counts)[inv]
    denom = math.sqrt(float((dx**2).sum() * (dy**2).sum()))
    return NAN if denom == 0 else float((dx * dy).sum() / denom)


def within_strata_correlation(
    x: Sequence,
    y: Sequence,
    strata: Sequence[Hashable],
    clusters: Sequence[Hashable],
    *,
    method: str = "spearman",
    n_boot: int = 2000,
    level: float = 0.95,
    seed: int = 0,
) -> Correlation:
    """Correlation of ``x`` and ``y`` after removing each stratum's mean, with a cluster interval.

    Spearman ranks the whole sample first, then removes the stratum means of the ranks: two bins
    are compared only through how each departs from its own stratum (e.g. the same hour of the
    day). Every bootstrap draw resamples whole clusters and recomputes ranks and means. Rows with
    a missing value are dropped; fewer than three clusters give no interval.
    """
    rows = [
        (float(a), float(b), s, c)
        for a, b, s, c in zip(x, y, strata, clusters, strict=True)
        if a is not None and b is not None and not math.isnan(a) and not math.isnan(b)
    ]
    xs = np.array([r[0] for r in rows])
    ys = np.array([r[1] for r in rows])
    ss = np.array([str(r[2]) for r in rows])
    cs = [r[3] for r in rows]
    r = _demeaned_r(xs, ys, ss, method) if rows else NAN
    members: dict[Hashable, list[int]] = {}
    for i, c in enumerate(cs):
        members.setdefault(c, []).append(i)
    groups = list(members.values())
    if len(groups) < 3 or math.isnan(r):
        return Correlation(r, NAN, NAN, len(rows), method, len(groups))
    rng = np.random.default_rng(seed)
    draws = []
    for _ in range(n_boot):
        idx = np.concatenate([groups[k] for k in rng.integers(0, len(groups), len(groups))])
        d = _demeaned_r(xs[idx], ys[idx], ss[idx], method)
        if not math.isnan(d):
            draws.append(d)
    if not draws:
        return Correlation(r, NAN, NAN, len(rows), method, len(groups))
    lo, hi = np.quantile(draws, [0.5 - level / 2, 0.5 + level / 2])
    return Correlation(r, float(lo), float(hi), len(rows), method, len(groups))
