"""Per-second acoustic features → one row per time bin, for joining with other instruments.

Every expected value is derived by hand in the test. Levels are averaged as energy (a loud second
weighs more than a quiet one), percentiles are taken over the seconds of the bin, and a bin with too
few seconds of recording is left out rather than reported from a fragment.
"""

import math
from datetime import UTC, datetime, timedelta

import polars as pl
import pytest

from social_energy.acoustics import bin_features

T0 = datetime(2026, 1, 5, 9, 0, 0, tzinfo=UTC)
BIN = timedelta(seconds=10)


def features(rows: list[tuple[int, float, float, float]]) -> pl.DataFrame:
    """Rows of (second after T0, rms dBFS, spectral centroid Hz, band dB)."""
    return pl.DataFrame(
        {
            "t": [T0 + timedelta(seconds=s) for s, *_ in rows],
            "rms_dbfs": [r for _, r, _, _ in rows],
            "peak_dbfs": [r + 6 for _, r, _, _ in rows],
            "zcr": [0.1 for _ in rows],
            "spectral_centroid_hz": [c for _, _, c, _ in rows],
            "spectral_flatness": [0.2 for _ in rows],
            "band_0_300_db": [b for *_, b in rows],
        },
        schema_overrides={"t": pl.Datetime("us", "UTC")},
    )


def test_level_is_an_energy_mean_and_percentiles_are_over_seconds():
    # Bin 0 (seconds 0-9): one second at -10 dBFS, nine at -20.
    rows = [(0, -10.0, 5000.0, 10.0)] + [(s, -20.0, 1000.0, 0.0) for s in range(1, 10)]
    out = bin_features(features(rows), every=BIN)
    assert out.height == 1
    row = out.row(0, named=True)
    assert row["bin"] == T0
    assert row["seconds"] == 10
    assert row["coverage"] == pytest.approx(1.0)
    # Energy: (10^-1 + 9 * 10^-2) / 10 = 0.019 -> 10 log10(0.019) = -17.212 dB.
    assert row["leq_dbfs"] == pytest.approx(10 * math.log10(0.019))
    assert row["leq_dbfs"] == pytest.approx(-17.212, abs=1e-3)
    # Sorted levels: nine at -20 then -10. 90th percentile sits at position 0.9 * 9 = 8.1,
    # a tenth of the way from -20 to -10 -> -19. The 10th percentile and the median are -20.
    assert row["l10_dbfs"] == pytest.approx(-19.0)
    assert row["l50_dbfs"] == pytest.approx(-20.0)
    assert row["l90_dbfs"] == pytest.approx(-20.0)
    # Spectral shape: the median second, so one loud second does not move it.
    assert row["spectral_centroid_hz"] == pytest.approx(1000.0)
    assert row["spectral_flatness"] == pytest.approx(0.2)
    # Bands are energy means too: (10^1 + 9 * 10^0) / 10 = 1.9 -> 10 log10(1.9) = 2.788 dB.
    assert row["band_0_300_db"] == pytest.approx(10 * math.log10(1.9))


def test_bins_with_too_little_recording_are_left_out():
    # Bin 0 holds 7 of 10 seconds (coverage 0.7, below 0.8): dropped.
    # Bin 1 holds 8 of 10 seconds (coverage 0.8): kept.
    rows = [(s, -30.0, 800.0, 0.0) for s in range(7)]
    rows += [(s, -40.0, 800.0, 0.0) for s in range(10, 18)]
    out = bin_features(features(rows), every=BIN, min_coverage=0.8)
    assert out["bin"].to_list() == [T0 + BIN]
    assert out["seconds"].to_list() == [8]
    assert out["coverage"].to_list() == [pytest.approx(0.8)]
    assert out["leq_dbfs"].to_list() == [pytest.approx(-40.0)]


def test_bins_are_aligned_to_the_clock_not_to_the_first_second():
    # A recording starting at 09:00:05 fills the second half of the 09:00:00 bin and the first
    # half of the 09:00:10 bin; with no coverage threshold both are kept, five seconds each.
    rows = [(s, -30.0, 800.0, 0.0) for s in range(5, 15)]
    out = bin_features(features(rows), every=BIN, min_coverage=0.0)
    assert out["bin"].to_list() == [T0, T0 + BIN]
    assert out["seconds"].to_list() == [5, 5]


def test_empty_input_gives_an_empty_table_with_the_columns():
    out = bin_features(features([]), every=BIN)
    assert out.height == 0
    assert {"bin", "seconds", "coverage", "leq_dbfs", "band_0_300_db"} <= set(out.columns)
