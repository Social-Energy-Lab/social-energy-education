"""The DSA 2026 gradient sensitivity script's own wiring, on invented rows."""

import importlib.util
import sys
from pathlib import Path

import numpy as np
import polars as pl
import pytest

ANALYSES = Path(__file__).resolve().parents[1] / "studies" / "dsa-2026" / "analyses"


@pytest.fixture(scope="module")
def s():
    sys.path.insert(0, str(ANALYSES))
    spec = importlib.util.spec_from_file_location(
        "gradient_sens_script", ANALYSES / "gradient_sensitivity.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_column_reliability_reads_composites_and_scales_and_falls_back_to_the_median(s):
    # Scale alphas 0.6 and 0.8 have median 0.7; the composite row is not one of the scales.
    table = pl.DataFrame({
        "group": ["b1", "b2", "trust_composite"], "alpha": [0.6, 0.8, 0.95],
    })  # fmt: skip
    assert s.column_reliability(["trust"], table) == ([0.95], [])
    assert s.column_reliability(["z_b1", "z_b2"], table) == ([0.6, 0.8], [])
    assert s.column_reliability(["z_b17"], table) == ([pytest.approx(0.7)], ["z_b17"])


def test_detected_needs_the_sign_and_the_rarity(s):
    null = np.arange(-100, 101) / 100.0  # flat from -1 to 1
    assert s.detected(1.5, null)[0]
    assert not s.detected(-1.5, null)[0]  # rare, the wrong way
    assert not s.detected(0.5, null)[0]  # right way, half the null is as extreme


def test_rates_per_level(s):
    runs = [
        {"k": 1, "detected": True, "v": 1.0},
        {"k": 1, "detected": False, "v": 3.0},
        {"k": 2, "detected": True, "v": 5.0},
    ]
    out = s.rates(runs, ["k"], "v")
    assert out["detected"].to_list() == [0.5, 1.0]
    assert out["median_v"].to_list() == [2.0, 5.0]


def test_a_planted_gain_is_detected_and_a_null_rarely_on_invented_contact(s):
    # 30 people, 435 pairs, noise contact. A true 40% per SD on a perfect survey is found; none is
    # found rarely. Uses the analysis's own statistic and null shape, without its loaders.
    from social_energy.dyads import (
        Residualiser,
        attribute_distance,
        node_permutation_null,
        pair_index,
        partial_fit,
    )

    i, j = pair_index(30)
    r = Residualiser(np.ones((len(i), 1)))
    groups = np.zeros(30, dtype=int)

    def hit(gain, seed):
        rng = np.random.default_rng(seed)
        X = rng.normal(0, 1, (30, 1))
        d = attribute_distance(X, i, j)
        y = r(rng.normal(0, 0.3, len(i)) + np.log1p(gain) * s.zscore(d))

        def stat(p):
            return partial_fit(y, r(attribute_distance(X[p], i, j))).partial_r

        null = node_permutation_null(stat, groups, n_perm=200, seed=seed)
        return s.detected(stat(np.arange(30)), null)[0]

    assert sum(hit(0.4, k) for k in range(20)) >= 18
    assert sum(hit(0.0, k) for k in range(20)) <= 3
