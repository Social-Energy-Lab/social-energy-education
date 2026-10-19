"""Readout labels from a hand-relabelled copy of the logs (logger ID bug, IDs 48-57 as "0"-"9").

A team that split the bug by hand rewrote each affected line's ``ID`` as ``n`` or ``n + 48`` and
left the rest of the line alone. So every line of an ambiguous readout in the original log has a
twin in the copy, with the same PC stamp and the same text after the ID, and the twin's ID is the
hand label. Lines are matched by that content, not by position, so a line the copy dropped or added
shifts nothing.

The labels are for ``BeaconConfig.id_fallback``: an outside judgement, used only where our own
repair (clock anchors, then witnesses) leaves a readout ambiguous. Never ingest the copy together
with the original: every line would count twice.
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

import polars as pl

from .ingest import BeaconConfig, _classify, _parse, _read_lines
from .purge import check_purged
from .witness import OFFSET

SCHEMA = {
    "readout_key": pl.String,
    "header": pl.Int64,
    "lines": pl.Int64,
    "matched": pl.Int64,
    "beacon": pl.Int64,
    "share": pl.Float64,
}


def _labels_one(original: Path, copy: Path, config: BeaconConfig) -> pl.DataFrame:
    _, parsed = _parse([original], config)
    ours = parsed.filter(pl.col("header_id").str.contains(r"^[0-9]$")).select(
        "readout_key",
        pl.col("header_id").cast(pl.Int64).alias("header"),
        "pc_time",
        "rest",
    )
    theirs = (
        _classify(_read_lines([copy]), config.timezone)
        .filter(pl.col("kind") != "unparsed")
        .with_columns(pl.col("header_id").cast(pl.Int64, strict=False).alias("label"))
        .filter(pl.col("label").is_between(0, 9) | pl.col("label").is_between(OFFSET, OFFSET + 9))
        .select(
            "pc_time",
            "rest",
            "label",
            (pl.col("label") % OFFSET).alias("header"),
        )
    )
    lines = ours.group_by("readout_key").agg(pl.col("header").first(), pl.len().alias("lines"))
    votes = (
        ours.join(theirs, on=["pc_time", "rest", "header"], how="inner")
        .group_by("readout_key", "label")
        .len()
    )
    top = (
        votes.with_columns(pl.col("len").sum().over("readout_key").alias("matched"))
        .sort(["readout_key", "len", "label"], descending=[False, True, False])
        .group_by("readout_key", maintain_order=True)
        .agg(pl.col("label").first(), pl.col("len").first().alias("top"), pl.col("matched").first())
    )
    return lines.join(top, on="readout_key", how="left").with_columns(
        pl.col("matched").fill_null(0),
        (pl.col("top") / pl.col("matched")).alias("share"),
    )


def reference_labels(
    pairs: Iterable[tuple[Path, Path]], config: BeaconConfig, *, min_share: float = 0.9
) -> pl.DataFrame:
    """Hand labels for every readout printed as "0"-"9" in the originals.

    ``pairs``: (original log, its relabelled copy). Returns one row per such readout:
    ``readout_key`` (as the ingest names it), ``header`` (printed digit), ``lines`` (its parsed
    lines), ``matched`` (lines with a twin in the copy labelled ``header`` or ``header + 48``),
    ``share`` (of matched lines carrying the commonest label) and ``beacon``: that label when its
    share is at least ``min_share``, else null. Raises ``PurgedDeviceError`` if any file names one
    of ``config.purged_devices``.
    """
    pairs = [(Path(a), Path(b)) for a, b in pairs]
    check_purged([p for pair in pairs for p in pair], config.purged_devices)
    frames = [_labels_one(original, copy, config) for original, copy in pairs]
    if not frames:
        return pl.DataFrame(schema=SCHEMA)
    return (
        pl.concat(frames)
        .with_columns(
            pl.when(pl.col("share") >= min_share).then(pl.col("label")).alias("beacon"),
        )
        .select(*[pl.col(c).cast(t) for c, t in SCHEMA.items()])
        .sort("readout_key")
    )
