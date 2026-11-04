"""Company around events, lag by lag. Invented rows only; expectations derived by hand."""

import math

import numpy as np
import pytest

from social_energy.moments import (
    Cluster,
    cluster_mass,
    component_sizes,
    eigenvector_centrality,
    lag_sums,
    person_lag_means,
    t_cut,
    window_mean,
)


def test_lag_sums_row_by_row():
    # Person 0 holds 0, 1, 2, 3 in bins 0-3. An event at bin 1, lags -1, 0, +1, reads 0, 1, 2.
    # A second event at bin 3 reads 2, 3, and bin 4 lies off the grid: missing, not counted.
    values = np.array([[0.0, 1.0, 2.0, 3.0], [9.0, 9.0, 9.0, 9.0]])
    sums, counts = lag_sums(values, np.array([0, 0]), np.array([1, 3]), np.array([-1, 0, 1]), 2)
    assert sums[0].tolist() == [2.0, 4.0, 2.0]
    assert counts[0].tolist() == [2, 2, 1]
    assert sums[1].tolist() == [0.0, 0.0, 0.0]


def test_lag_sums_skip_missing_values():
    values = np.array([[np.nan, 1.0, np.nan]])
    sums, counts = lag_sums(values, np.array([0]), np.array([1]), np.array([-1, 0, 1]), 1)
    assert sums[0].tolist() == [0.0, 1.0, 0.0]
    assert counts[0].tolist() == [0, 1, 0]


def test_person_lag_means_leave_empty_cells_missing_and_people_below_the_minimum_out():
    sums = np.array([[6.0, 0.0], [4.0, 4.0]])
    counts = np.array([[3, 0], [1, 1]])
    m = person_lag_means(sums, counts, events=np.array([3, 1]), min_events=2)
    assert m[0, 0] == 2.0
    assert math.isnan(m[0, 1])  # no reading at that lag
    assert np.isnan(m[1]).all()  # one event, below the minimum


def test_window_mean_takes_the_lags_named_and_skips_missing():
    d = np.array([[1.0, np.nan, 3.0, 10.0]])
    lags = np.array([-1, 0, 1, 2])
    assert window_mean(d, lags, -1, 1).tolist() == [2.0]  # (1 + 3) / 2
    assert window_mean(d, lags, 2, 2).tolist() == [10.0]


def test_component_sizes():
    # 0-1-2 joined through 1, 3-4 joined, 5 alone.
    a, b = np.array([0, 1, 3]), np.array([1, 2, 4])
    assert component_sizes(6, a, b).tolist() == [3, 3, 3, 2, 2, 1]


def test_eigenvector_centrality_of_a_star():
    # A star's leading eigenvector: centre 1, each of the k leaves 1 / sqrt(k).
    W = np.zeros((5, 5))
    W[0, 1:] = W[1:, 0] = 1.0
    c = eigenvector_centrality(W)
    assert c[0] == pytest.approx(1.0)
    assert c[1:] == pytest.approx([0.5] * 4)


def test_eigenvector_centrality_is_zero_outside_the_leading_component():
    # A triangle (eigenvalue 2) beats a separate pair (eigenvalue 1).
    W = np.zeros((5, 5))
    for i, j in ((0, 1), (1, 2), (0, 2), (3, 4)):
        W[i, j] = W[j, i] = 1.0
    assert eigenvector_centrality(W) == pytest.approx([1, 1, 1, 0, 0])


def test_eigenvector_centrality_without_edges_is_zero():
    assert eigenvector_centrality(np.zeros((3, 3))).tolist() == [0.0, 0.0, 0.0]


def test_t_cut_is_the_two_sided_five_percent_point():
    assert t_cut(10) == pytest.approx(2.262, abs=1e-3)  # table value, df 9


def test_cluster_mass_finds_a_planted_block_and_gives_its_bounds():
    # 20 people: lags 2-4 sit near +1 with small spread; every other lag is noise around 0.
    rng = np.random.default_rng(1)
    d = rng.normal(0, 1, (20, 8))
    d[:, 2:5] = rng.normal(1, 0.2, (20, 3))
    clusters = cluster_mass(d, n_perm=2000, seed=3)
    hit = [c for c in clusters if c.start == 2 and c.stop == 4]
    assert len(hit) == 1
    assert isinstance(hit[0], Cluster)
    assert hit[0].sign == 1
    assert hit[0].p < 0.01


def test_cluster_mass_sign_flip_of_the_input_flips_the_cluster():
    rng = np.random.default_rng(1)
    d = rng.normal(0, 1, (20, 8))
    d[:, 2:5] = rng.normal(1, 0.2, (20, 3))
    pos = [c for c in cluster_mass(d, n_perm=500, seed=3) if c.start == 2]
    neg = [c for c in cluster_mass(-d, n_perm=500, seed=3) if c.start == 2]
    assert pos[0].sign == 1 and neg[0].sign == -1
    assert pos[0].mass == pytest.approx(-neg[0].mass)


def test_cluster_mass_on_pure_noise_is_rarely_significant():
    # With alpha 0.05 over the whole curve, about one curve in twenty has a cluster with p < .05.
    hits = 0
    for seed in range(40):
        d = np.random.default_rng(seed).normal(0, 1, (25, 10))
        hits += any(c.p < 0.05 for c in cluster_mass(d, n_perm=300, seed=seed))
    assert hits <= 6


def test_oracle_a_planted_rise_after_events_shows_after_and_not_before():
    # 30 people, company 1 everywhere except the 3 bins after each event, where it is 3. Against
    # events moved to random bins, lag +1 sits near 2 above the null, lag -5 near 0.
    rng = np.random.default_rng(0)
    n, bins, lags = 30, 400, np.arange(-6, 7)
    values = np.ones((n, bins))
    person = np.repeat(np.arange(n), 5)
    at = np.tile(np.arange(40, 390, 70), n)
    for p, b in zip(person, at, strict=True):
        values[p, b + 1 : b + 4] = 3.0
    s, c = lag_sums(values, person, at, lags, n)
    obs = person_lag_means(s, c, np.bincount(person, minlength=n), min_events=3)
    shuffled = []
    for _ in range(50):
        s, c = lag_sums(values, person, rng.integers(10, 390, len(person)), lags, n)
        shuffled.append(person_lag_means(s, c, np.bincount(person, minlength=n), min_events=3))
    d = obs - np.mean(shuffled, axis=0)
    assert window_mean(d, lags, 1, 3).mean() > 1.5
    assert abs(window_mean(d, lags, -6, -2).mean()) < 0.3
    assert any(c.start <= 7 and c.stop >= 7 and c.p < 0.05 for c in cluster_mass(d, n_perm=500))
