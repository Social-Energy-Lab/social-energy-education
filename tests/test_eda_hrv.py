"""Heart-rate variability (RMSSD) per minute from beat series, on hand-written beats with
hand-derived expectations."""

from datetime import UTC, datetime, timedelta

import numpy as np
import polars as pl
import pytest

from social_energy.eda.heart import rmssd_minutes, successive_differences

T0 = datetime(2030, 1, 1, 10, 0, tzinfo=UTC)


def beats(ibis_ms, *, start=T0, valid=None, device="D1", source="sd", run="r1", first=True):
    """One stretch of beats: the first beat at ``start`` (no interval when ``first``), each next
    one ``ibi`` later, carrying that interval."""
    t, ib = [start], [None if first else float(ibis_ms[0])]
    for x in ibis_ms if first else ibis_ms[1:]:
        t.append(t[-1] + timedelta(milliseconds=float(x)))
        ib.append(float(x))
    n = len(t)
    return pl.DataFrame(
        {
            "device": [device] * n,
            "source": [source] * n,
            "run": [run] * n,
            "t": t,
            "ibi_ms": pl.Series(ib, dtype=pl.Float32),
            "valid": [True] * n if valid is None else valid,
        }
    )


def test_rmssd_of_a_known_alternating_series():
    # 40 intervals alternating 800 / 840 ms: every successive difference is +-40 ms (5 %).
    ibis = [800.0, 840.0] * 20
    out = rmssd_minutes(beats(ibis), min_diffs=30)
    assert out.height == 1
    row = out.row(0, named=True)
    assert row["n_diffs"] == 39  # 40 intervals, 39 differences
    assert row["rmssd_ms"] == pytest.approx(40.0, abs=1e-3)
    assert row["minute"] == T0


def test_rmssd_matches_the_textbook_formula():
    rng = np.random.default_rng(1)
    ibis = 800 + rng.normal(0, 20, 60)
    out = rmssd_minutes(beats(ibis.tolist()), min_diffs=1)
    d = np.diff(np.asarray(ibis, dtype=np.float32).astype(float))
    # Differences in the minute of their later beat.
    t = np.cumsum(ibis)
    minute = (t // 60_000).astype(int)
    exp = {m: float(np.sqrt(np.mean(d[minute[1:] == m] ** 2))) for m in np.unique(minute[1:])}
    got = {int((r["minute"] - T0).total_seconds() // 60): r["rmssd_ms"] for r in out.to_dicts()}
    assert got.keys() == exp.keys()
    for k in exp:
        assert got[k] == pytest.approx(exp[k], rel=1e-4)


def test_a_jump_over_20_percent_is_not_a_successive_difference():
    # 800 -> 1000 is +25 % of the earlier interval: dropped; 1000 -> 800 is -20 %: kept.
    d = successive_differences(beats([800.0, 1000.0, 800.0, 960.0]), max_change=0.2)
    assert d["sd_ms"].to_list() == [None, None, None, -200.0, 160.0]
    # A looser rule keeps the first jump too.
    d = successive_differences(beats([800.0, 1000.0, 800.0]), max_change=0.3)
    assert d["sd_ms"].to_list() == [None, None, 200.0, -200.0]


def test_an_invalid_beat_breaks_both_differences_it_touches():
    valid = [True, True, True, False, True, True]
    d = successive_differences(beats([800.0, 810.0, 820.0, 830.0, 840.0], valid=valid))
    # Beat 3 is invalid: its own difference and the next one's are not counted.
    assert d["sd_ms"].to_list() == [None, None, 10.0, None, None, 10.0]


def test_stretches_and_sources_never_join():
    a = beats([800.0] * 5, run="r1")
    b = beats([900.0] * 5, start=T0 + timedelta(seconds=10), run="r2")
    c = beats([700.0] * 5, start=T0 + timedelta(seconds=20), source="export", run="e1")
    d = successive_differences(pl.concat([a, b, c]))
    assert d["sd_ms"].null_count() == 3 * 2  # first beat and first interval of each stretch
    assert set(d["sd_ms"].drop_nulls().to_list()) == {0.0}


def test_a_gap_between_beats_is_not_a_successive_difference():
    # A beat missing from the table: the next interval does not span the time since the
    # previous row, so it is not that row's successor.
    full = beats([800.0, 800.0, 800.0, 800.0, 800.0])
    gapped = full.filter(pl.int_range(pl.len()) != 3)
    d = successive_differences(gapped)
    assert d["sd_ms"].to_list() == [None, None, 0.0, None, 0.0]


def test_minimum_count_rule():
    ibis = [800.0, 840.0] * 15 + [800.0]  # 31 intervals, 30 differences
    ok = rmssd_minutes(beats(ibis), min_diffs=30).row(0, named=True)
    assert ok["n_diffs"] == 30 and ok["rmssd_ms"] == pytest.approx(40.0, abs=1e-3)
    short = rmssd_minutes(beats(ibis[:-1]), min_diffs=30).row(0, named=True)
    assert short["n_diffs"] == 29 and short["rmssd_ms"] is None
