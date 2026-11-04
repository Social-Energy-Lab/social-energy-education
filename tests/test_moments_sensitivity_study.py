"""The DSA 2026 sensitivity script's own wiring, on invented rows."""

import importlib.util
import sys
from datetime import date
from pathlib import Path

import numpy as np
import polars as pl
import pytest

ANALYSES = Path(__file__).resolve().parents[1] / "studies" / "dsa-2026" / "analyses"
DISC, REP = date(2026, 8, 20), date(2026, 8, 21)


@pytest.fixture(scope="module")
def s():
    sys.path.insert(0, str(ANALYSES))
    spec = importlib.util.spec_from_file_location(
        "sens_script", ANALYSES / "moments_sensitivity.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _rows(n=60, shared=6):
    rng = np.random.default_rng(0)
    return pl.DataFrame({
        "shared": [k < shared for k in range(n)],
        "day": [DISC if k % 2 == 0 else REP for k in range(n)],
        "same_course": [k % 3 == 0 for k in range(n)],
        "tied_earlier": [k % 5 == 0 for k in range(n)],
        "today": rng.normal(3, 1, n).tolist(),
        "later": np.log1p(np.full(n, 99.0)).tolist(),
        "tied_later": [False] * n,
    })  # fmt: skip


def test_pseudo_shared_drops_the_real_ones_and_never_marks_more_than_they_were(s):
    rows = _rows()
    out = s.pseudo_shared(rows, np.random.default_rng(1))
    assert out.height == rows.height - 6  # the real shared rows are gone
    assert 0 < out["shared"].sum() <= 6
    assert set(out.columns) == set(rows.columns)


def test_pseudo_shared_keeps_the_real_count_per_half_when_the_strata_have_room(s):
    # Same stratum for everyone, so every real shared row finds a partner in its half.
    rows = _rows(n=60, shared=6).with_columns(
        pl.lit(True).alias("same_course"),
        pl.lit(True).alias("tied_earlier"),
        pl.lit(3.0).alias("today"),
    )
    out = s.pseudo_shared(rows, np.random.default_rng(1))
    assert out.filter(pl.col("shared") & (pl.col("day") == DISC)).height == 3
    assert out.filter(pl.col("shared") & (pl.col("day") == REP)).height == 3


def test_plant_rows_multiplies_only_shared_minutes(s):
    # 99 minutes on every row. Times 2 on shared rows gives 198, others stay 99.
    rows = _rows()
    out = s.plant_rows(rows, np.random.default_rng(0), factor=2.0)
    assert np.expm1(out.filter(pl.col("shared"))["later"]).to_list() == pytest.approx([198.0] * 6)
    assert np.expm1(out.filter(~pl.col("shared"))["later"]).to_list() == pytest.approx([99.0] * 54)


def test_plant_rows_adds_about_the_points_asked_and_only_on_shared(s):
    # 2,000 shared rows, none tied: asking for 30 points gives a share near 0.30.
    rows = _rows(n=4000, shared=2000)
    out = s.plant_rows(rows, np.random.default_rng(0), points=0.3)
    assert out.filter(pl.col("shared"))["tied_later"].mean() == pytest.approx(0.3, abs=0.03)
    assert out.filter(~pl.col("shared"))["tied_later"].sum() == 0


def test_plant_rows_at_level_zero_changes_nothing(s):
    rows = _rows()
    assert s.plant_rows(rows, np.random.default_rng(0)).equals(rows)


def test_detection_rates(s):
    runs = [
        {
            "k": 1,
            "detected": True,
            "all_excludes_zero": True,
            "all_est": 1.0,
            "all_lo": 0.5,
            "all_hi": 1.5,
        },
        {
            "k": 1,
            "detected": False,
            "all_excludes_zero": False,
            "all_est": 3.0,
            "all_lo": 0.0,
            "all_hi": 1.0,
        },
    ]
    row = s.detection(runs, ["k"]).row(0, named=True)
    assert row["runs"] == 2 and row["detected"] == 0.5
    assert row["median_all_estimate"] == 2.0
    assert row["median_all_width"] == 1.0


def test_positive_lead_needs_the_verdict_and_the_sign(s):
    assert s.positive_lead({"verdict": "replicates", "discovery": 0.2})
    assert not s.positive_lead({"verdict": "replicates", "discovery": -0.2})
    assert not s.positive_lead({"verdict": "no lead", "discovery": 0.2})
