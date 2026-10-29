"""The DSA 2026 gradients script's own wiring, on invented rows."""

import importlib.util
import sys
from pathlib import Path

import numpy as np
import polars as pl
import pytest

ANALYSES = Path(__file__).resolve().parents[1] / "studies" / "dsa-2026" / "analyses"


@pytest.fixture(scope="module")
def g():
    sys.path.insert(0, str(ANALYSES))
    spec = importlib.util.spec_from_file_location(
        "gradients_script", ANALYSES / "exploratory_gradients.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_press_stats_by_hand(g):
    # Distances: 0-1 = 1, 0-2 = 3, 1-2 = 2. Instances (0,1) co-pressed, (0,2) not, (1,2) co-pressed.
    # Co-pressed mean (1 + 2) / 2 = 1.5, others 3 -> -1.5 SDs at sd 1.
    # Terciles at cuts 1.5 and 2.5: 1 near, 2 middle, 3 far -> shares 1, 1, 0.
    D = g.distance_matrix(np.array([0.0, 1.0, 3.0]))
    assert D[0, 2] == 3.0 and D[2, 0] == 3.0
    a, b = np.array([0, 0, 1]), np.array([1, 2, 2])
    c = np.array([True, False, True])
    s = g.press_stats(D, 1.0, np.array([1.5, 2.5]), a, b, c, np.ones(3, bool))
    assert s.tolist() == [-1.5, 1.0, 1.0, 0.0]
    # A subset with no non-co-pressed instance has no difference.
    s = g.press_stats(D, 1.0, np.array([1.5, 2.5]), a, b, c, np.array([True, False, True]))
    assert np.isnan(s[0])


def test_pair_sample_splits_courses_and_drops_pairs_never_heard_together(g):
    # People 0, 1 in course x; 2, 3 in course y. Pair (2,3) was never heard together.
    i, j = np.triu_indices(4, 1)
    contact = pl.DataFrame({"i": i, "j": j, "joint_bins": [10, 20, 30, 40, 50, 0],
                            "close_minutes": [60, 0, 5, 10, 0, 0],
                            "tie_days": [1, 0, 0, 0, 0, 0]})  # fmt: skip
    course = np.array(["x", "x", "y", "y"])
    within = g.PairSample(contact, course, "within course", fe=False)
    between = g.PairSample(contact, course, "between course", fe=False)
    every = g.PairSample(contact, course, "all", fe=True)
    assert (within.pairs, between.pairs, every.pairs) == (1, 4, 5)
    assert within.raw["tied"].tolist() == [1.0]
    assert between.raw["log_close"].tolist() == pytest.approx(np.log1p([0, 5, 10, 0]).tolist())


def test_two_partial_matches_regression_with_both_distances(g):
    # Oracle: the partial correlation equals the one from residualising on the other directly.
    rng = np.random.default_rng(3)
    x, o = rng.normal(size=40), rng.normal(size=40)
    y = 0.5 * x - 0.4 * o + rng.normal(size=40)
    c = lambda v: v - v.mean()  # noqa: E731
    X = np.column_stack([np.ones(40), o])
    res = lambda v: v - X @ np.linalg.lstsq(X, v, rcond=None)[0]  # noqa: E731
    expected = np.corrcoef(res(y), res(x))[0, 1]
    assert g.two_partial(c(y), c(x), c(o)) == pytest.approx(expected)
