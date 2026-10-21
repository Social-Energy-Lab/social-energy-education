"""Exploratory EDA tools: scaling, event-locked profiles, fixed-effects contrasts, synchrony.

Invented rows only; every expected value is derived by hand in the test.
"""

import math
from datetime import UTC, datetime

import numpy as np
import polars as pl
import pytest

from social_energy.eda.arousal import (
    centred_detrend,
    dense_series,
    draw_positions,
    eligible,
    lagged_products,
    node_bootstrap_mean,
    pools,
    profile,
    residualise,
    window_means,
    zscore_within,
)
from social_energy.stats import within_ols


def t(h: int, m: int, s: int = 0) -> datetime:
    return datetime(2026, 8, 20, h, m, s, tzinfo=UTC)


def test_zscore_within_groups():
    df = pl.DataFrame({"g": ["a", "a", "a", "b", "c", "c", "a"],
                       "v": [1.0, 2.0, 3.0, 5.0, 2.0, 2.0, None]})  # fmt: skip
    z = zscore_within(df, "v", ["g"], "z")["z"].to_list()
    # a: mean 2, sd 1 -> -1, 0, 1; b: one value -> null; c: no spread -> null; null stays null.
    assert z == [-1.0, 0.0, 1.0, None, None, None, None]


def test_residualise_removes_the_linear_fit():
    df = pl.DataFrame({"y": [1.0, 3.0, 5.0, 9.0, 2.0], "x": [0.0, 1.0, 2.0, 3.0, None]})
    # y = 1 + 2x on the first three; the fourth is 2 above the line. Least squares on 4 points:
    # x mean 1.5, y mean 4.5; Sxy = (-1.5)(-3.5) + (-0.5)(-1.5) + (0.5)(0.5) + (1.5)(4.5) = 13,
    # Sxx = 5 -> slope 2.6, intercept 4.5 - 3.9 = 0.6.
    out, coef = residualise(df, "y", ["x"], "r")
    assert coef == pytest.approx([0.6, 2.6])
    r = out["r"].to_list()
    assert r[:4] == pytest.approx([0.4, -0.2, -0.8, 0.6])
    assert r[4] is None


def test_centred_detrend_skips_missing_values():
    x = np.array([1.0, 2.0, np.nan, 4.0, 5.0])
    # Window 3: trends 1.5, 1.5, -, 4.5, 4.5 (only finite neighbours count).
    out = centred_detrend(x, window=3, min_valid=2)
    assert out[[0, 1, 3, 4]] == pytest.approx([-0.5, 0.5, -0.5, 0.5])
    assert math.isnan(out[2])
    # Requiring three finite values leaves only the full windows -> none here except none.
    strict = centred_detrend(np.array([1.0, 2.0, 3.0, 4.0]), window=3, min_valid=3)
    assert math.isnan(strict[0]) and math.isnan(strict[3])
    assert strict[1:3] == pytest.approx([0.0, 0.0])
    with pytest.raises(ValueError):
        centred_detrend(x, window=4, min_valid=1)


def series():
    df = pl.DataFrame(
        {
            "entity": ["A", "A", "A", "B", "B"],
            "minute": [t(10, 0), t(10, 1), t(10, 3), t(11, 0), t(11, 1)],
            "v": [1.0, 2.0, 4.0, 7.0, 8.0],
        }
    )
    return dense_series(df, keys=["entity"], time="minute", values=["v"], pad=2)


def test_dense_series_layout_and_positions():
    s = series()
    # A spans 10:00-10:03 (4 minutes) from position 2; B starts at 2 + 4 + 2 = 8; size 12.
    assert s.index["start"].to_list() == [2, 8]
    assert s.index["n"].to_list() == [4, 2]
    assert s.size == 12
    v = s.values["v"]
    assert v[[2, 3, 5, 8, 9]].tolist() == [1.0, 2.0, 4.0, 7.0, 8.0]
    assert math.isnan(v[4]) and math.isnan(v[1]) and math.isnan(v[10])
    assert s.group_of.tolist() == [-1, -1, 0, 0, 0, 0, -1, -1, 1, 1, -1, -1]
    ev = pl.DataFrame(
        {"entity": ["A", "B", "A", "C"], "minute": [t(10, 1, 30), t(11, 1), t(10, 5), t(10, 0)]}
    )
    # 10:01:30 falls in minute 10:01; 10:05 is outside A's span; C is not in the series.
    assert s.positions(ev).tolist() == [3, 9, -1, -1]


def test_profile_and_window_means():
    s = series()
    p = profile(s.values["v"], np.array([3, 9]), np.array([-1, 0, 1]))
    assert p[0, :2].tolist() == [1.0, 2.0] and math.isnan(p[0, 2])
    assert p[1, :2].tolist() == [7.0, 8.0] and math.isnan(p[1, 2])
    w = window_means(np.array([[1.0, np.nan, 3.0], [np.nan] * 3]), np.array([-1, 0, 1]), -1, 1)
    assert w[0] == 2.0 and math.isnan(w[1])
    assert window_means(p, np.array([-1, 0, 1]), 0, 1).tolist() == [2.0, 8.0]


def test_eligible_counts_valid_positions_in_the_window():
    valid = np.array([False, True, True, False, True])
    assert eligible(valid, np.array([-1, 0, 1]), 2).tolist() == [False, True, True, True, False]


def test_pools_and_draws_keep_group_and_stratum():
    ok = np.array([False, True, True, True, False, True, True])
    group_of = np.array([-1, 0, 0, 0, -1, 1, 1])
    stratum = np.array(["x", "x", "y", "y", "x", "x", "x"], dtype=object)
    p = pools(ok, group_of, stratum)
    assert {k: v.tolist() for k, v in p.items()} == {
        (0, "x"): [1], (0, "y"): [2, 3], (1, "x"): [5, 6]
    }  # fmt: skip
    rng = np.random.default_rng(1)
    keys = [(0, "y"), (1, "x"), (0, "x")]
    seen = [set(), set(), set()]
    for _ in range(200):
        d = draw_positions(keys, p, rng)
        for k in range(3):
            seen[k].add(int(d[k]))
    assert seen == [{2, 3}, {5, 6}, {1}]
    assert set(pools(ok, group_of)) == {(0, None), (1, None)}


def test_lagged_products():
    signal = pl.DataFrame(
        {
            "entity": ["a", "a", "b", "b", "b"],
            "minute": [t(10, 0), t(10, 1), t(10, 0), t(10, 1), t(10, 2)],
            "z": [1.0, 2.0, 3.0, 4.0, 5.0],
        }
    )
    pm = pl.DataFrame({"a": ["a", "a"], "b": ["b", "b"], "minute": [t(10, 0), t(10, 1)],
                       "label": ["x", "y"]})  # fmt: skip
    out = lagged_products(signal, pm, value="z", lags=[0, 1, -1]).sort("lag", "minute")
    got = {(r["lag"], r["label"]): r["product"] for r in out.iter_rows(named=True)}
    # lag 0: 1*3, 2*4; lag 1: a(10:00)*b(10:01) = 4, a(10:01)*b(10:02) = 10;
    # lag -1: a(10:01)*b(10:00) = 6, a(10:00) has no b at 09:59.
    assert got == {(0, "x"): 3.0, (0, "y"): 8.0, (1, "x"): 4.0, (1, "y"): 10.0, (-1, "y"): 6.0}


def test_node_bootstrap_mean_weights_pairs_by_both_partners():
    a, b, v = np.array([0, 1]), np.array([1, 2]), np.array([1.0, 3.0])
    draws = [np.array([1, 1, 1]), np.array([0, 1, 1]), np.array([2, 1, 0])]
    iv, means = node_bootstrap_mean(a, b, v, draws)
    # Weights (1, 1) -> 2; (0, 1) -> 3; (2, 0) -> 1.
    assert iv.estimate == 2.0
    assert means.tolist() == [2.0, 3.0, 1.0]
    assert iv.lo == pytest.approx(1.05) and iv.hi == pytest.approx(2.95)
    # The same as aggregates: pair (0, 1) holds values 0 and 2 (sum 2, two values), pair (1, 2)
    # holds 3. Pooled mean 5/3; draws: (2 + 3) / 3, 3 / 1, 2*2 / (2*2) = 1.
    iv2, means2 = node_bootstrap_mean(a, b, np.array([2.0, 3.0]), draws,
                                      counts=np.array([2, 1]))  # fmt: skip
    assert iv2.estimate == pytest.approx(5 / 3) and iv2.n == 3
    assert means2 == pytest.approx([5 / 3, 3.0, 1.0])


def test_within_ols_exact_slope_within_groups():
    # Group 1: y = 5 + 2x; group 2: y = 1 + 2x. Different levels, the same slope.
    y = [5.0, 7.0, 1.0, 3.0, 5.0]
    x = np.array([[0.0], [1.0], [0.0], [1.0], [2.0]])
    (c,) = within_ols(y, x, ["x"], absorb=[1, 1, 2, 2, 2], cluster=[1, 1, 2, 2, 2])
    assert c.estimate == pytest.approx(2.0)
    assert c.se == pytest.approx(0.0, abs=1e-9)
    assert (c.n, c.clusters) == (5, 2)


def test_within_ols_matches_dummy_regression():
    import statsmodels.api as sm

    rng = np.random.default_rng(3)
    groups = np.repeat(np.arange(12), 20)
    clusters = groups // 2
    x = rng.normal(size=(240, 2)) + groups[:, None] * 0.1
    y = 0.5 * x[:, 0] - 1.0 * x[:, 1] + groups * 0.3 + rng.normal(size=240)
    got = within_ols(y, x, ["a", "b"], absorb=groups, cluster=clusters)
    dummies = (groups[:, None] == np.arange(12)[None, :]).astype(float)
    full = np.column_stack([x, dummies])
    fit = sm.OLS(y, full).fit(cov_type="cluster", cov_kwds={"groups": clusters})
    # statsmodels counts the 12 dummies in K; ours counts only the 2 slopes.
    scale = math.sqrt((240 - 14) / (240 - 2))
    for j, c in enumerate(got):
        assert c.estimate == pytest.approx(fit.params[j])
        assert c.se == pytest.approx(fit.bse[j] * scale, rel=1e-6)


def test_within_ols_column_without_within_variation_is_nan():
    y = [1.0, 2.0, 3.0, 4.0]
    x = np.array([[1.0, 0.0], [1.0, 1.0], [2.0, 0.0], [2.0, 1.0]])
    c = within_ols(y, x, ["const_in_group", "x"], absorb=[1, 1, 2, 2], cluster=[1, 1, 2, 2])
    assert math.isnan(c[0].estimate)
    assert c[1].estimate == pytest.approx(1.0)
