"""Pair-level comparisons against node-permutation nulls.

Invented rows only; every expected value is derived by hand in the test.
"""

import math

import numpy as np
import pytest

from social_energy.dyads import (
    Residualiser,
    attribute_distance,
    event_times,
    node_dummies,
    node_permutation_null,
    null_position,
    pair_index,
    partial_fit,
    partner_coevents,
)


def test_pair_index_row_by_row():
    i, j = pair_index(3)
    assert i.tolist() == [0, 0, 1]
    assert j.tolist() == [1, 2, 2]
    assert len(pair_index(5)[0]) == 10


def test_attribute_distance_one_attribute_is_absolute_difference():
    i, j = pair_index(3)
    assert attribute_distance(np.array([0.0, 1.0, 3.0]), i, j).tolist() == [1.0, 3.0, 2.0]


def test_attribute_distance_several_attributes_is_euclidean_and_nan_propagates():
    i, j = pair_index(3)
    X = np.array([[0.0, 0.0], [3.0, 4.0], [0.0, 1.0]])
    d = attribute_distance(X, i, j)
    # (0,0)-(3,4) = 5; (0,0)-(0,1) = 1; (3,4)-(0,1) = sqrt(9 + 9).
    assert d.tolist() == pytest.approx([5.0, 1.0, math.sqrt(18)])
    X[2, 1] = np.nan
    d = attribute_distance(X, i, j)
    assert d[0] == 5.0 and math.isnan(d[1]) and math.isnan(d[2])


def test_node_dummies_mark_both_people():
    i, j = pair_index(3)
    assert node_dummies(i, j, 3).tolist() == [[1, 1, 0], [1, 0, 1], [0, 1, 1]]


def test_partial_fit_with_intercept_only_is_simple_regression():
    # x = 1, 2, 3; y = 2, 4, 7. Centred: dx = -1, 0, 1; dy = -7/3, -1/3, 8/3.
    # Sxy = 7/3 + 8/3 = 5; Sxx = 2 -> slope 2.5; Syy = (49 + 1 + 64) / 9 = 114/9.
    # r = 5 / sqrt(2 * 114/9) = 0.99339.
    r = Residualiser(np.ones((3, 1)))
    f = partial_fit(r(np.array([2.0, 4.0, 7.0])), r(np.array([1.0, 2.0, 3.0])))
    assert f.slope == pytest.approx(2.5)
    assert f.partial_r == pytest.approx(5 / math.sqrt(2 * 114 / 9))
    assert f.n == 3


def test_partial_fit_equals_full_regression_coefficient():
    # Oracle: Frisch-Waugh-Lovell against a direct least-squares fit with the controls.
    rng = np.random.default_rng(1)
    n = 8
    i, j = pair_index(n)
    Z = np.column_stack([rng.normal(size=len(i)), node_dummies(i, j, n)])
    x = rng.normal(size=len(i))
    y = 0.7 * x + Z @ rng.normal(size=Z.shape[1]) + rng.normal(scale=0.1, size=len(i))
    full = np.linalg.lstsq(np.column_stack([x, Z]), y, rcond=None)[0][0]
    r = Residualiser(Z)
    assert partial_fit(r(y), r(x)).slope == pytest.approx(full)


def test_residualiser_handles_rank_deficient_controls():
    Z = np.column_stack([np.ones(4), np.ones(4), np.arange(4.0)])
    r = Residualiser(Z)
    assert r.rank == 2
    # A vector in the column space is projected to zero.
    assert np.allclose(r(2 + 3 * np.arange(4.0)), 0)


def test_partial_fit_constant_predictor_is_nan():
    r = Residualiser(np.ones((3, 1)))
    f = partial_fit(r(np.array([1.0, 2.0, 4.0])), r(np.array([5.0, 5.0, 5.0])))
    assert math.isnan(f.slope) and math.isnan(f.partial_r)


def test_node_permutation_null_only_swaps_within_groups():
    # Person 2 is alone in group "b", so it always keeps its own attributes.
    null = node_permutation_null(lambda p: float(p[2]), ["a", "a", "b"], n_perm=50, seed=0)
    assert set(null.tolist()) == {2.0}
    # Persons 0 and 1 swap in some permutations and not in others.
    null = node_permutation_null(lambda p: float(p[0]), ["a", "a", "b"], n_perm=50, seed=0)
    assert set(null.tolist()) == {0.0, 1.0}


def test_null_position_by_hand():
    # Null 1, 2, 3, 4: two below 3 and one tie -> (2 + 0.5) / 4. Mean 2.5, every draw at least
    # 0.5 from it -> share as extreme 1.
    p = null_position(3.0, [1.0, 2.0, 3.0, 4.0])
    assert p.percentile == pytest.approx(0.625)
    assert p.null_mean == pytest.approx(2.5)
    assert p.share_as_extreme == pytest.approx(1.0)
    assert p.n == 4
    # Far below the null: percentile 0, and NaN draws are left out.
    p = null_position(-10.0, [1.0, 2.0, float("nan"), 4.0])
    assert p.percentile == 0.0 and p.share_as_extreme == 0.0 and p.n == 3


def test_qap_detects_a_planted_distance_effect_and_not_a_null_one():
    # Oracle: pairs whose people differ more meet less (y = -distance + person effects + noise).
    rng = np.random.default_rng(7)
    n = 30
    i, j = pair_index(n)
    attr = rng.normal(size=n)
    social = rng.normal(size=n)
    d = attribute_distance(attr, i, j)
    noise = rng.normal(scale=0.3, size=len(i))
    r = Residualiser(node_dummies(i, j, n))

    def stat_for(y):
        y_res = r(y)
        return lambda p: partial_fit(y_res, r(attribute_distance(attr[p], i, j))).slope

    groups = [0] * n
    planted = -d + social[i] + social[j] + noise
    obs = stat_for(planted)(np.arange(n))
    pos = null_position(obs, node_permutation_null(stat_for(planted), groups, n_perm=200, seed=1))
    assert obs < 0 and pos.percentile < 0.01
    flat = social[i] + social[j] + noise
    obs = stat_for(flat)(np.arange(n))
    pos = null_position(obs, node_permutation_null(stat_for(flat), groups, n_perm=200, seed=1))
    assert 0.025 < pos.percentile < 0.975


def test_event_times_sorted_per_person():
    t = event_times(["a", "b", "a"], [30, 10, 20])
    assert t["a"].tolist() == [20, 30] and t["b"].tolist() == [10]


def test_partner_coevents_by_hand():
    # a presses at 100, b at 250, c at 1000; bins of 300 s; window 200 s.
    # a@100 (bin 0): partners b (250, 150 s away -> yes) and c (1000 -> no).
    # b@250 (bin 0): partner a (100, 150 s -> yes). c@1000 (bin 900): partner a (no).
    partners = {("a", 0): ["b", "c"], ("b", 0): ["a"], ("c", 900): ["a"]}
    p = partner_coevents(["a", "b", "c"], [100, 250, 1000], partners, window=200, bin_size=300)
    assert p.event.tolist() == [0, 0, 1, 2]
    assert p.partner == ["b", "c", "a", "a"]
    assert p.coevent.tolist() == [True, False, True, False]


def test_partner_coevents_window_is_inclusive_and_partner_without_events_counts():
    partners = {("a", 0): ["b", "d"]}
    p = partner_coevents(["a", "b"], [100, 400], partners, window=300, bin_size=300)
    # b at exactly 300 s after a counts; d never pressed and is still a partner who did not.
    assert p.partner == ["b", "d"]
    assert p.coevent.tolist() == [True, False]
    p = partner_coevents(["a", "b"], [100, 401], partners, window=300, bin_size=300)
    assert p.coevent.tolist() == [False, False]
