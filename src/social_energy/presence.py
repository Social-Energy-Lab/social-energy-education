"""Who was with whom, where, and when: presence measures from resolved contacts.

Input is a contacts table already resolved through the spine, with columns
``observer_entity``, ``observed_entity`` (``person:…`` / ``location:…``), ``t`` (UTC)
and ``rssi``. Filter on ``ok``, exclusions and consent *before* calling these;
that choice belongs to the analysis.
"""

from __future__ import annotations

from datetime import timedelta

import polars as pl

PERSON = "person:"
LOCATION = "location:"


def _person_pairs(contacts: pl.DataFrame) -> pl.DataFrame:
    both_people = contacts.filter(
        pl.col("observer_entity").str.starts_with(PERSON)
        & pl.col("observed_entity").str.starts_with(PERSON)
        & (pl.col("observer_entity") != pl.col("observed_entity"))
    )
    return both_people.with_columns(
        pl.min_horizontal("observer_entity", "observed_entity").alias("a"),
        pl.max_horizontal("observer_entity", "observed_entity").alias("b"),
    )


def copresence(contacts: pl.DataFrame, every: str = "5m") -> pl.DataFrame:
    """One row per unordered person pair per time bin in which either heard the other.

    Columns: ``a``, ``b`` (a < b), ``bin``, ``observations`` (records in either
    direction), ``directions`` (1 = only one side heard the other, 2 = both did), and
    ``max_rssi``.
    """
    return (
        _person_pairs(contacts)
        .with_columns(pl.col("t").dt.truncate(every).alias("bin"))
        .group_by("a", "b", "bin")
        .agg(
            pl.len().alias("observations"),
            pl.col("observer_entity").n_unique().alias("directions"),
            pl.col("rssi").max().alias("max_rssi"),
        )
        .sort("bin", "a", "b")
    )


def room_per_bin(contacts: pl.DataFrame, every: str = "5m", min_hits: int = 2) -> pl.DataFrame:
    """Each person's most likely location per bin.

    The location is the one whose tag the person heard most often in the bin (ties go
    to the stronger median RSSI). Bins with fewer than ``min_hits`` hits are left out
    rather than guessed. Columns: ``entity``, ``bin``, ``location``, ``hits``,
    ``median_rssi``, ``share`` (hits of the winning location / all location hits).
    """
    heard = (
        contacts.filter(
            pl.col("observer_entity").str.starts_with(PERSON)
            & pl.col("observed_entity").str.starts_with(LOCATION)
        )
        .with_columns(pl.col("t").dt.truncate(every).alias("bin"))
        .group_by(pl.col("observer_entity").alias("entity"), "bin",
                  pl.col("observed_entity").alias("location"))
        .agg(pl.len().alias("hits"), pl.col("rssi").median().alias("median_rssi"))
    )  # fmt: skip
    return (
        heard.with_columns(pl.col("hits").sum().over("entity", "bin").alias("_all"))
        .sort(["hits", "median_rssi"], descending=True)
        .group_by("entity", "bin", maintain_order=True)
        .first()
        .filter(pl.col("hits") >= min_hits)
        .with_columns((pl.col("hits") / pl.col("_all")).alias("share"))
        .drop("_all")
        .sort("entity", "bin")
    )


def event_context(
    events: pl.DataFrame, contacts: pl.DataFrame, window: timedelta = timedelta(minutes=5)
) -> pl.DataFrame:
    """For each event (e.g. a self-report), who was around and where, within ±window.

    ``events`` needs ``entity`` and ``t``. Adds ``copresent`` (sorted list of people
    heard by or hearing the entity), ``n_copresent``, and ``location`` (the location
    tag heard most often by the entity in the window).
    """
    ev = events.select("entity", "t").with_row_index("_event")
    lo, hi = pl.col("t") - window, pl.col("t") + window
    c = contacts.select("observer_entity", "observed_entity", pl.col("t").alias("tc"))

    # Join on the entity first (either side of a contact), then filter by time. This
    # keeps the work proportional to each person's own contacts, not all contacts.
    as_observer = ev.join(c, left_on="entity", right_on="observer_entity").with_columns(
        pl.col("observed_entity").alias("other")
    )
    as_observed = ev.join(c, left_on="entity", right_on="observed_entity").with_columns(
        pl.col("observer_entity").alias("other")
    )
    in_window = (pl.col("tc") >= lo) & (pl.col("tc") <= hi)
    people = (
        pl.concat(
            [
                as_observer.select("_event", "entity", "t", "tc", "other"),
                as_observed.select("_event", "entity", "t", "tc", "other"),
            ]
        )
        .filter(
            in_window
            & pl.col("other").str.starts_with(PERSON)
            & (pl.col("other") != pl.col("entity"))
        )
        .group_by("_event")
        .agg(pl.col("other").unique().sort().alias("copresent"))
    )
    places = (
        as_observer.filter(in_window & pl.col("other").str.starts_with(LOCATION))
        .group_by("_event", "other")
        .agg(pl.len().alias("_hits"))
        .sort("_hits", descending=True)
        .group_by("_event", maintain_order=True)
        .first()
        .select("_event", pl.col("other").alias("location"))
    )
    return (
        ev.join(people, on="_event", how="left")
        .join(places, on="_event", how="left")
        .with_columns(pl.col("copresent").fill_null(pl.lit([], dtype=pl.List(pl.String))))
        .with_columns(pl.col("copresent").list.len().alias("n_copresent"))
        .sort("_event")
        .drop("_event")
    )
