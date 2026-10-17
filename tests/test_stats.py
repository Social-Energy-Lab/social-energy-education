"""Correlations with intervals, for exploratory reporting (no p-values).

Expected values are derived by hand in each test.
"""

import math

import pytest

from social_energy.stats import _cluster_draws, cluster_bootstrap, correlation

X = [1.0, 2.0, 3.0, 4.0, 5.0]
Y = [2.0, 1.0, 4.0, 3.0, 5.0]


def test_pearson_with_fisher_interval():
    # Deviations dx = -2 -1 0 1 2, dy = -1 -2 1 0 2: sum dx*dy = 8, sum dx^2 = sum dy^2 = 10,
    # so r = 0.8. z = atanh(0.8) = 1.0986, se = 1/sqrt(5 - 3) = 0.7071, z +- 1.96 * se =
    # (-0.2873, 2.4845), back through tanh: (-0.2797, 0.9862).
    c = correlation(X, Y)
    assert c.r == pytest.approx(0.8)
    assert c.n == 5
    assert c.lo == pytest.approx(-0.2797, abs=1e-4)
    assert c.hi == pytest.approx(0.9862, abs=1e-4)


def test_spearman_uses_average_ranks():
    # y = x^3 is monotone: ranks agree, rho = 1. With ties x = 1 2 2 3 gets ranks 1 2.5 2.5 4.
    assert correlation(X, [x**3 for x in X], method="spearman").r == pytest.approx(1.0)
    # x ranks 1 2.5 2.5 4 against y ranks 1 2 3 4: dx = -1.5 0 0 1.5, dy = -1.5 -0.5 0.5 1.5,
    # sum dx*dy = 4.5, sum dx^2 = 4.5, sum dy^2 = 5 -> rho = 4.5 / sqrt(22.5) = 0.9487.
    rho = correlation([1, 2, 2, 3], [10, 20, 30, 40], method="spearman").r
    assert rho == pytest.approx(4.5 / math.sqrt(22.5))


def test_missing_pairs_are_dropped_and_tiny_samples_get_no_interval():
    c = correlation([1.0, 2.0, None, 3.0, float("nan")], [1.0, 2.0, 5.0, 3.0, 4.0])
    assert c.n == 3
    assert c.r == pytest.approx(1.0)
    assert math.isnan(c.lo) and math.isnan(c.hi)  # n - 3 = 0: no Fisher interval


def test_constant_input_has_no_correlation():
    c = correlation([1.0, 1.0, 1.0, 1.0, 1.0], Y)
    assert math.isnan(c.r)


def test_cluster_bootstrap_resamples_whole_clusters():
    # Cluster a is (0,0),(1,1); cluster b is (0,1),(1,0). Drawing two clusters with replacement:
    # a+a gives r = 1, b+b gives r = -1, a+b gives the four corners and r = 0. Resampling rows
    # instead would produce other values.
    x = [0.0, 1.0, 0.0, 1.0]
    y = [0.0, 1.0, 1.0, 0.0]
    clusters = ["a", "a", "b", "b"]
    draws = _cluster_draws(x, y, clusters, method="pearson", n_boot=400, seed=1)
    assert set(round(d, 9) for d in draws) <= {-1.0, 0.0, 1.0}
    assert len(set(round(d, 9) for d in draws)) == 3


def test_cluster_bootstrap_point_estimate_interval_and_seed():
    x = [float(i) for i in range(12)]
    y = [2 * v + 1 for v in x]  # exactly linear: every resample gives r = 1
    clusters = [i // 3 for i in range(12)]
    c = cluster_bootstrap(x, y, clusters, n_boot=200, seed=3)
    assert (c.n, c.clusters) == (12, 4)
    assert (c.r, c.lo, c.hi) == (pytest.approx(1.0), pytest.approx(1.0), pytest.approx(1.0))
    noisy = [v + (1 if i % 2 else -1) * 3 for i, v in enumerate(x)]
    a = cluster_bootstrap(x, noisy, clusters, n_boot=200, seed=3)
    b = cluster_bootstrap(x, noisy, clusters, n_boot=200, seed=3)
    assert (a.lo, a.hi) == (b.lo, b.hi)
    assert a.r == pytest.approx(correlation(x, noisy).r)
    assert a.lo <= a.r <= a.hi
