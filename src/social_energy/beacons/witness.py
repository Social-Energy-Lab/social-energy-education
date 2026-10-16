"""Witness repair of the logger ID bug (IDs 48-57 printed as "0"-"9").

The bug touched only the readout's own label. Every partner recorded the tag correctly as ``ID2``.
So for an ambiguous readout printed as ``n``, each contact "heard X at t" asks: did X, in its own
correctly labelled records, hear ``n`` or ``n + 48`` around ``t``? Each such sighting is a vote.

The ambiguous contacts are timed from the readout's own clock anchor (``t_own``), which does not
depend on which candidate is right. Stamps run late, so ``t_own`` can be minutes late; the same
holds for the witnesses, hence a symmetric tolerance.

Two steps, both pure: ``witness_votes`` counts, ``decide`` applies the threshold. Readouts that do
not pass stay ambiguous: flag, don't drop. ``ingest_with_witnesses`` runs the whole thing on a camp:
ingest, vote from the written tables, ingest again with the decisions as ``id_overrides``.
"""

from __future__ import annotations

import dataclasses
import shutil
from collections.abc import Iterable
from pathlib import Path

import polars as pl

from .ingest import BeaconConfig, ingest_logs_to

OFFSET = 48  # the bug's ID shift: "0"-"9" stand for 0-9 or 48-57


def witness_votes(
    ambiguous: pl.DataFrame, witnesses: pl.DataFrame, *, tolerance_s: int = 300, peak_s: int = 10
) -> pl.DataFrame:
    """Votes per ambiguous readout.

    ``ambiguous``: ``readout_key``, ``header`` (printed digit), ``observed``, ``t_own`` (UTC).
    ``witnesses``: correctly labelled contacts, ``beacon`` (the witness), ``observed``, ``t``.
    Returns ``readout_key``, ``header``, ``contacts``, ``votes_low`` (for ``header``) and
    ``votes_high`` (for ``header + 48``): how many of the readout's contacts have a witness sighting
    of that candidate within ``tolerance_s``. A candidate is never its own witness.

    Counts alone mislead when both candidates were around the same partners. Timing does not: the
    readout's clock is off by one constant amount, so the right candidate's sightings sit at one
    offset from its contacts, the wrong one's scatter. ``peak_low`` / ``peak_high`` are the share of
    the readout's contacts whose nearest sighting lies within ``peak_s`` of that candidate's
    median offset.
    """
    amb = ambiguous.with_columns(pl.col("header").cast(pl.Int64), pl.col("observed").cast(pl.Int64))
    usable = amb.filter(
        (pl.col("observed") != pl.col("header"))
        & (pl.col("observed") != pl.col("header") + OFFSET)
        & pl.col("t_own").is_not_null()
    )
    right = (
        witnesses.select(
            pl.col("beacon").cast(pl.Int64).alias("observed"),
            pl.col("observed").cast(pl.Int64).alias("candidate"),
            pl.col("t").alias("t_w"),
        )
        .filter(pl.col("t_w").is_not_null())
        .sort("t_w")
    )
    counts = []
    for name, shift in (("votes_low", 0), ("votes_high", OFFSET)):
        left = usable.with_columns((pl.col("header") + shift).alias("candidate")).sort("t_own")
        hit = left.join_asof(
            right,
            left_on="t_own",
            right_on="t_w",
            by=["observed", "candidate"],
            strategy="nearest",
            tolerance=f"{tolerance_s}s",
            check_sortedness=False,
        )
        offset = (pl.col("t_w") - pl.col("t_own")).dt.total_seconds()
        peak = name.replace("votes", "peak")
        counts.append(
            hit.with_columns(offset.alias("_d"))
            .with_columns(
                (pl.col("_d") - pl.col("_d").median().over("readout_key")).abs().alias("_e")
            )
            .group_by("readout_key")
            .agg(
                pl.col("t_w").is_not_null().sum().alias(name),
                ((pl.col("_e") <= peak_s).sum() / pl.len()).alias(peak),
            )
        )
    totals = amb.group_by("readout_key").agg(pl.col("header").first(), pl.len().alias("contacts"))
    out = totals
    for c in counts:
        out = out.join(c, on="readout_key", how="left")
    return out.with_columns(
        pl.col("votes_low").fill_null(0).cast(pl.Int64),
        pl.col("votes_high").fill_null(0).cast(pl.Int64),
        pl.col("peak_low").fill_null(0.0),
        pl.col("peak_high").fill_null(0.0),
        pl.col("contacts").cast(pl.Int64),
    ).select(
        "readout_key", "header", "contacts", "votes_low", "votes_high", "peak_low", "peak_high"
    )


def decide(
    votes: pl.DataFrame,
    *,
    min_votes: int = 5,
    min_share: float = 0.9,
    min_peak_ratio: float = 3.0,
) -> pl.DataFrame:
    """The readouts the votes settle: ``readout_key``, ``beacon``, plus the vote columns.

    Needs at least ``min_votes`` votes in all. Then either one candidate holds ``min_share`` of
    them, or the vote majority's timing peak is at least ``min_peak_ratio`` times the other's.
    A peak that strong *against* the count leaves the readout unsettled: the two signals disagree.
    Without peak columns, only the count decides.
    """
    total = pl.col("votes_low") + pl.col("votes_high")
    high_share = pl.col("votes_high") / total
    by_count = (
        pl.when(high_share >= min_share).then(pl.lit("high"))
        .when(high_share <= 1 - min_share).then(pl.lit("low"))
    )  # fmt: skip
    majority = (
        pl.when(high_share > 0.5).then(pl.lit("high")).when(high_share < 0.5).then(pl.lit("low"))
    )
    if "peak_low" in votes.columns:
        lo, hi = pl.col("peak_low"), pl.col("peak_high")
        strong = (
            pl.when(hi >= min_peak_ratio * lo).then(pl.lit("high"))
            .when(lo >= min_peak_ratio * hi).then(pl.lit("low"))
        )  # fmt: skip
        strong = pl.when((lo + hi) > 0).then(strong)
    else:
        strong = pl.lit(None, dtype=pl.String)
    pick = (
        pl.when(by_count.is_not_null() & (strong.is_null() | (strong == by_count))).then(by_count)
        .when(strong.is_not_null() & (strong == majority) & by_count.is_null()).then(strong)
    )  # fmt: skip
    return (
        votes.filter(total >= min_votes)
        .with_columns(
            pl.when(pick == "high")
            .then(pl.col("header") + OFFSET)
            .when(pick == "low")
            .then(pl.col("header"))
            .cast(pl.Int64)
            .alias("beacon")
        )
        .filter(pl.col("beacon").is_not_null())
    )


AMBIGUOUS_DIGITS = list(range(10)) + list(range(OFFSET, OFFSET + 10))


def votes_from_tables(out: Path, config: BeaconConfig) -> pl.DataFrame:
    """Witness votes for every ambiguous readout in an ``ingest_logs_to`` output directory."""
    out = Path(out)
    readouts = pl.read_parquet(out / "readouts.parquet")
    amb_readouts = readouts.filter(pl.col("id_status") == "ambiguous").select(
        "readout_key", pl.col("header_id").cast(pl.Int64).alias("header"), "anchor"
    )
    contacts = pl.scan_parquet(out / "contacts" / "*.parquet")
    ambiguous = (
        contacts.filter(pl.col("readout_key").is_in(amb_readouts["readout_key"].implode()))
        .select("readout_key", "observed", "uptime_s")
        .collect()
        .join(amb_readouts, on="readout_key")
        .with_columns((pl.col("anchor") + pl.duration(seconds=pl.col("uptime_s"))).alias("t_own"))
        .select("readout_key", "header", "observed", "t_own")
    )
    witnesses = (
        contacts.filter(
            pl.col("observed").is_in(AMBIGUOUS_DIGITS)
            & ~pl.col("id_ambiguous")
            & ~pl.col("duplicate")
            & ~pl.col("invalid_value")
            & pl.col("t").is_not_null()
        )
        .select("beacon", "observed", "t")
        .collect()
    )
    return witness_votes(
        ambiguous, witnesses, tolerance_s=config.witness_tolerance_s, peak_s=config.witness_peak_s
    )


def ingest_with_witnesses(paths: Iterable[Path], config: BeaconConfig, out: Path) -> dict[str, int]:
    """``ingest_logs_to`` plus witness repair; also writes ``id_witness.parquet``.

    That table holds every ambiguous readout of the first pass with its votes and the ``beacon`` the
    votes settled (null where they did not).
    """
    paths, out = list(paths), Path(out)
    qa = ingest_logs_to(paths, config, out)
    if not qa["ids_ambiguous"]:
        return qa
    votes = votes_from_tables(out, config)
    settled = decide(
        votes,
        min_votes=config.witness_min_votes,
        min_share=config.witness_min_share,
        min_peak_ratio=config.witness_min_peak_ratio,
    ).select("readout_key", "beacon")
    if settled.height:
        overrides = tuple(zip(settled["readout_key"], settled["beacon"], strict=True))
        shutil.rmtree(out)
        qa = ingest_logs_to(paths, dataclasses.replace(config, id_overrides=overrides), out)
    votes.join(settled, on="readout_key", how="left").write_parquet(out / "id_witness.parquet")
    return qa
