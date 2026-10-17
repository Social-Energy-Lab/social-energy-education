"""Per-person outcome measures from binned close co-presence and self-reports.

Inputs are canonical tables an analysis has already filtered (``ok`` records, exclusion windows,
consent, observation window):

* **pairs**: one row per unordered person pair per time bin, as from
  :func:`social_energy.presence.copresence` — ``a``, ``b``, ``bin``, ``max_rssi`` — plus a ``day``
  column (:func:`camp_day`).
* **seen**: ``entity``, ``day``, ``bin`` — the bins in which a person's tag heard, or was heard by,
  anything.
* **events**: ``entity``, ``t`` — e.g. self-report press episodes.

The measures:

* **Close tie** (:func:`daily_close_ties`): a pair on a day, counting the bins whose strongest
  reading is at or above ``close_rssi``; a tie when those add up to at least ``min_minutes``.
* **Strength** (C1-style): a person's minutes in ties per day present, averaged over the days
  present. A day counts when the person was seen for at least ``min_bins`` bins; ties on other days
  do not count for that person.
* **Cross-group share** (C2-style): tie minutes with partners of another group over tie minutes
  with partners of a known group, with the share expected if everyone present mixed at random:
  ``(N - n_g) / (N - 1)``, ``N`` people present with a known group, ``n_g`` of them in the
  person's own group (the person included).
* **New ties per day** (C3-style): ties a pair forms for the first time, on days after the first
  ``burn_in_days``, per present day after them.
* **Event rate** (C4-style): events per exposure hour, with removed bins (e.g. lost windows) taken
  out of both the events and the hours.

Every threshold is the study's choice and is passed in.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from datetime import date, timedelta

import polars as pl


def camp_day(t: pl.Expr, *, timezone: str, day_start: timedelta) -> pl.Expr:
    """The local date of the day a UTC timestamp falls in, days starting at ``day_start``."""
    return (t.dt.convert_time_zone(timezone) - day_start).dt.date()


def windows_to_bins(
    windows: pl.DataFrame, *, bin_minutes: int, key: str = "entity"
) -> pl.DataFrame:
    """Every bin a ``[start, end)`` window touches, as ``key``, ``bin`` (unique)."""
    every = f"{bin_minutes}m"
    return (
        windows.filter(pl.col("end") > pl.col("start"))
        .with_columns(
            pl.datetime_ranges(
                pl.col("start").dt.truncate(every), pl.col("end"), interval=every, closed="left"
            ).alias("bin")
        )
        .explode("bin", empty_as_null=False)
        .select(key, "bin")
        .unique()
    )


def drop_pair_bins(pairs: pl.DataFrame, removed: pl.DataFrame) -> pl.DataFrame:
    """Pair bins without those in which either side is in ``removed`` (``entity``, ``bin``)."""
    r = removed.select("entity", "bin").unique()
    return pairs.join(r, left_on=["a", "bin"], right_on=["entity", "bin"], how="anti").join(
        r, left_on=["b", "bin"], right_on=["entity", "bin"], how="anti"
    )


def daily_close_ties(
    pairs: pl.DataFrame, *, close_rssi: int, min_minutes: int, bin_minutes: int
) -> pl.DataFrame:
    """Ties per day: ``day``, ``a``, ``b``, ``minutes`` (close bins x ``bin_minutes``).

    A bin is close when its strongest reading is at least ``close_rssi``; the pair is tied on the
    day when its close minutes reach ``min_minutes``. Both limits are inclusive.
    """
    return (
        pairs.filter(pl.col("max_rssi") >= close_rssi)
        .group_by("day", "a", "b")
        .agg((pl.col("bin").n_unique() * bin_minutes).alias("minutes"))
        .filter(pl.col("minutes") >= min_minutes)
        .sort("day", "a", "b")
    )


def present_days(seen: pl.DataFrame, *, min_bins: int) -> pl.DataFrame:
    """``entity``, ``day`` on which the person was seen in at least ``min_bins`` bins."""
    return (
        seen.group_by("entity", "day")
        .agg(pl.col("bin").n_unique().alias("_bins"))
        .filter(pl.col("_bins") >= min_bins)
        .select("entity", "day")
        .sort("entity", "day")
    )


def _ends(ties: pl.DataFrame) -> pl.DataFrame:
    """Each tie twice, once from each side: ``entity``, ``other``, ``day``, ``minutes``."""
    return pl.concat(
        [
            ties.select(pl.col("a").alias("entity"), pl.col("b").alias("other"), "day", "minutes"),
            ties.select(pl.col("b").alias("entity"), pl.col("a").alias("other"), "day", "minutes"),
        ]
    )


def close_contact_outcomes(
    ties: pl.DataFrame,
    present: pl.DataFrame,
    *,
    people: Sequence[str],
    days: Iterable[date],
    groups: Mapping[str, str | None],
    burn_in_days: int,
) -> pl.DataFrame:
    """One row per person in ``people`` (in that order) with the close-contact outcomes.

    Only ties between two of ``people`` on one of ``days`` count, and only on the person's
    present days. Columns: ``entity``, ``days_present``, ``strength_min_per_day``,
    ``close_minutes``, ``cross_minutes``, ``cross_share``, ``cross_share_expected``,
    ``days_after_burn_in``, ``new_ties``, ``new_ties_per_day``. A measure without a denominator
    (no present day, no group, no tie minutes with a known group) is null.
    """
    days = sorted(set(days))
    after = days[burn_in_days:]
    people = list(people)
    who = pl.DataFrame({"entity": people}, schema={"entity": pl.String})
    group = pl.DataFrame(
        {"entity": list(groups), "group": list(groups.values())},
        schema={"entity": pl.String, "group": pl.String},
    )
    ties = ties.filter(
        pl.col("a").is_in(people) & pl.col("b").is_in(people) & pl.col("day").is_in(days)
    )
    present = present.filter(pl.col("entity").is_in(people) & pl.col("day").is_in(days))
    ends = _ends(ties).join(present, on=["entity", "day"], how="semi")

    # C1: tie minutes per present day.
    minutes = ends.group_by("entity", "day").agg(pl.col("minutes").sum())
    per_day = present.join(minutes, on=["entity", "day"], how="left").with_columns(
        pl.col("minutes").fill_null(0)
    )
    strength = per_day.group_by("entity").agg(
        pl.len().alias("days_present"),
        pl.col("minutes").mean().alias("strength_min_per_day"),
        pl.col("minutes").sum().alias("close_minutes"),
    )

    # C2: share of tie minutes with partners of another group, and its random-mixing baseline.
    known = (
        ends.join(group, on="entity", how="left")
        .join(group.rename({"entity": "other", "group": "other_group"}), on="other", how="left")
        .filter(pl.col("group").is_not_null() & pl.col("other_group").is_not_null())
        .group_by("entity")
        .agg(
            pl.col("minutes").sum().alias("_known"),
            pl.col("minutes").filter(pl.col("group") != pl.col("other_group")).sum()
            .alias("cross_minutes"),
        )
    )  # fmt: skip
    pool = (
        present.select("entity")
        .unique()
        .join(group, on="entity")
        .filter(pl.col("group").is_not_null())
    )
    n = pool.height
    sizes = pool.group_by("group").agg(pl.len().alias("_n_g"))
    expected = pool.join(sizes, on="group").select(
        "entity",
        (pl.when(pl.lit(n) > 1).then((pl.lit(n) - pl.col("_n_g")) / (pl.lit(n) - 1))).alias(
            "cross_share_expected"
        ),
    )

    # C3: first day each pair is tied, counted for each side on its present days after burn-in.
    first = ties.group_by("a", "b").agg(pl.col("day").min())
    new = (
        _ends(first.with_columns(pl.lit(0).alias("minutes")))
        .filter(pl.col("day").is_in(after))
        .join(present, on=["entity", "day"], how="semi")
        .group_by("entity")
        .agg(pl.len().alias("new_ties"))
    )
    after_days = (
        present.filter(pl.col("day").is_in(after))
        .group_by("entity")
        .agg(pl.len().alias("days_after_burn_in"))
    )

    has_group = pl.col("entity").is_in(pool["entity"].implode())
    return (
        who.join(strength, on="entity", how="left")
        .join(known, on="entity", how="left")
        .join(expected, on="entity", how="left")
        .join(after_days, on="entity", how="left")
        .join(new, on="entity", how="left")
        .with_columns(
            pl.col("days_present").fill_null(0),
            pl.col("days_after_burn_in").fill_null(0),
            pl.col("new_ties").fill_null(0),
            pl.when(has_group).then(pl.col("cross_minutes").fill_null(0)).alias("cross_minutes"),
        )
        .with_columns(
            pl.when(pl.col("_known") > 0)
            .then(pl.col("cross_minutes") / pl.col("_known"))
            .alias("cross_share"),
            pl.when(pl.col("days_after_burn_in") > 0)
            .then(pl.col("new_ties") / pl.col("days_after_burn_in"))
            .alias("new_ties_per_day"),
        )
        .select(
            "entity",
            "days_present",
            "strength_min_per_day",
            "close_minutes",
            "cross_minutes",
            "cross_share",
            "cross_share_expected",
            "days_after_burn_in",
            "new_ties",
            "new_ties_per_day",
        )
    )


def event_rate(
    events: pl.DataFrame,
    exposure: pl.DataFrame,
    *,
    people: Sequence[str],
    bin_minutes: int,
    removed: pl.DataFrame | None = None,
) -> pl.DataFrame:
    """Events per exposure hour, one row per person in ``people`` (in that order).

    ``exposure`` is ``entity``, ``bin``; ``removed`` (same shape) is taken out of it first. An
    event counts only when its bin is in the remaining exposure, so the numerator never holds time
    the denominator lacks. Columns: ``entity``, ``exposure_hours``, ``events``,
    ``events_per_hour`` (null without exposure).
    """
    every = f"{bin_minutes}m"
    people = list(people)
    bins = exposure.select("entity", "bin").unique().filter(pl.col("entity").is_in(people))
    if removed is not None:
        bins = bins.join(removed.select("entity", "bin").unique(), on=["entity", "bin"], how="anti")
    counted = (
        events.with_columns(pl.col("t").dt.truncate(every).alias("bin"))
        .join(bins, on=["entity", "bin"], how="semi")
        .group_by("entity")
        .agg(pl.len().alias("events"))
    )
    hours = bins.group_by("entity").agg((pl.len() * bin_minutes / 60).alias("exposure_hours"))
    return (
        pl.DataFrame({"entity": people}, schema={"entity": pl.String})
        .join(hours, on="entity", how="left")
        .join(counted, on="entity", how="left")
        .with_columns(pl.col("exposure_hours").fill_null(0.0), pl.col("events").fill_null(0))
        .with_columns(
            pl.when(pl.col("exposure_hours") > 0)
            .then(pl.col("events") / pl.col("exposure_hours"))
            .alias("events_per_hour")
        )
    )
