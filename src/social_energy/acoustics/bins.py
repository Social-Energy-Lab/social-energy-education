"""Per-window acoustic features → one row per clock-aligned time bin.

Other instruments (beacons, self-reports) are counted in fixed clock bins, so joining acoustics to
them needs the same bins. Levels are averaged as energy: ``leq`` is the equivalent continuous level
of the bin, and a few loud seconds raise it more than an arithmetic mean of decibels would.
``l10``/``l50``/``l90`` are the levels exceeded 10/50/90 % of the bin's windows (the 90th, 50th
and 10th percentiles), the usual room-acoustics summary of loud moments, typical level and
background. Spectral shape (centroid, flatness, zero-crossing rate) is the median window, so a
single bang does not move it. Band levels are energy means like ``leq``.

A bin with less than ``min_coverage`` of its length recorded (the edge of a recording session, a
gap) is left out rather than summarised from a fragment.
"""

from __future__ import annotations

from datetime import timedelta

import polars as pl

LEVEL = "rms_dbfs"
SHAPE = ("spectral_centroid_hz", "spectral_flatness", "zcr")


def _energy_mean_db(col: str, factor: float) -> pl.Expr:
    """``factor`` is 10 for power quantities in dB; amplitude dB (20 log10) are power dB too."""
    return (10 * (10 ** (pl.col(col) / factor)).mean().log10()).alias(col)


def bin_features(
    features: pl.DataFrame,
    every: timedelta = timedelta(minutes=5),
    *,
    window_s: float = 1.0,
    min_coverage: float = 0.8,
) -> pl.DataFrame:
    """One row per ``every`` bin: ``bin``, ``seconds``, ``coverage``, levels, shape and bands.

    ``features`` is the output of ``extract_features`` (``t`` plus per-window columns), for one
    recorder. Columns out: ``leq_dbfs``, ``l10_dbfs``, ``l50_dbfs``, ``l90_dbfs``, the median of
    each shape column present, and the energy mean of each ``band_*`` column.
    """
    bands = [c for c in features.columns if c.startswith("band_")]
    shape = [c for c in SHAPE if c in features.columns]
    bin_s = every.total_seconds()
    q = lambda p: pl.col(LEVEL).quantile(p, interpolation="linear")  # noqa: E731
    return (
        features.with_columns(pl.col("t").dt.truncate(f"{int(bin_s)}s").alias("bin"))
        .group_by("bin")
        .agg(
            (pl.len() * window_s).alias("seconds"),
            (pl.len() * window_s / bin_s).alias("coverage"),
            _energy_mean_db(LEVEL, 10).alias("leq_dbfs"),
            q(0.9).alias("l10_dbfs"),
            q(0.5).alias("l50_dbfs"),
            q(0.1).alias("l90_dbfs"),
            *[pl.col(c).median() for c in shape],
            *[_energy_mean_db(c, 10) for c in bands],
        )
        .filter(pl.col("coverage") >= min_coverage)
        .sort("bin")
    )
