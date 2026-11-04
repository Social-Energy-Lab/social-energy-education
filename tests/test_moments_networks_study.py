"""The DSA 2026 moments script's own wiring, on invented rows."""

import importlib.util
import sys
from datetime import date
from pathlib import Path

import numpy as np
import polars as pl
import pytest

from social_energy.exploratory import CloseIndex

ANALYSES = Path(__file__).resolve().parents[1] / "studies" / "dsa-2026" / "analyses"
D1, D2 = date(2026, 8, 17), date(2026, 8, 19)


@pytest.fixture(scope="module")
def m():
    sys.path.insert(0, str(ANALYSES))
    spec = importlib.util.spec_from_file_location(
        "moments_script", ANALYSES / "moments_networks.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_halves_do_not_overlap_and_special_days_fall_one_each(m):
    assert not set(m.DISCOVERY) & set(m.REPLICATION)
    assert date(2026, 8, 18) in m.REPLICATION and date(2026, 8, 22) in m.DISCOVERY
    assert m.half_mask([date(2026, 8, 29)], "all").tolist() == [False]


def _close(*triples):
    both = [*triples, *[(o, b, e) for e, b, o in triples]]
    return CloseIndex(both, bin_size=300)


def test_pair_days_sorts_shared_comparison_and_near(m):
    # a and b press 60 s apart, close: shared. c presses alone with d close: comparison.
    # e and f press 5 s apart, close: neither, unless include_near.
    entity = ["a", "b", "c", "e", "f"]
    ts = np.array([0, 60, 3000, 6000, 6005])
    day = [D1] * 5
    close = _close(("a", 0, "b"), ("c", 3000, "d"), ("e", 6000, "f"))
    partners = {("a", 0): ["b"], ("b", 0): ["a"], ("c", 3000): ["d"],
                ("e", 6000): ["f"], ("f", 6000): ["e"]}  # fmt: skip
    shared, comparison = m.pair_days(entity, ts, day, close, partners)
    assert shared == {("a", "b", D1)}
    assert comparison == {("c", "d", D1)}
    shared, _ = m.pair_days(entity, ts, day, close, partners, include_near=True)
    assert shared == {("a", "b", D1), ("e", "f", D1)}


def test_pair_days_a_shared_day_is_not_also_comparison_but_another_day_can_be(m):
    # On D1 a and b co-press at 0 and 60; a also presses at 3000 with b close and no answer. D1 is
    # shared only. On D2 a presses with b close and no answer: comparison.
    entity = ["a", "b", "a", "a"]
    ts = np.array([0, 60, 3000, 90000])
    day = [D1, D1, D1, D2]
    close = _close(("a", 0, "b"), ("a", 3000, "b"), ("a", 90000, "b"))
    partners = {("a", 0): ["b"], ("b", 0): ["a"], ("a", 3000): ["b"], ("a", 90000): ["b"]}
    shared, comparison = m.pair_days(entity, ts, day, close, partners)
    assert shared == {("a", "b", D1)}
    assert comparison == {("a", "b", D2)}


def test_features_by_hand(m):
    # Bin 0: a-b close, a-z close (z is company without a row), c seen alone.
    # Bin 1 (300 s): only a is exposed, nobody close.
    # a and b tie on an earlier day? first tie is this day, so b still counts as unfamiliar.
    day = D1
    exposure = pl.DataFrame({"entity": ["a", "b", "c", "a"], "bs": [0, 0, 0, 300]})
    rows = [("a", "b"), ("b", "a"), ("a", "z"), ("z", "a")]
    close = pl.DataFrame(
        {"entity": [r[0] for r in rows], "other": [r[1] for r in rows], "bs": [0] * 4,
         "day": [day] * 4}
    )  # fmt: skip
    g = m.features(exposure, close, {"a": "X", "b": "X", "c": "Y", "z": "Y"}, ["a", "b", "c"], 0, 2)
    assert g["close"][0].tolist() == [2.0, 0.0]
    assert g["close"][1, 0] == 1.0
    assert np.isnan(g["close"][1, 1])
    assert g["gathering"][:, 0].tolist() == [3.0, 3.0, 1.0]
    assert g["unfamiliar"][0, 0] == 2.0
    # a's others: b same course, z other course. b's other: a same course. c alone: missing.
    assert g["cross_course"][0, 0] == 0.5
    assert g["cross_course"][1, 0] == 0.0
    assert np.isnan(g["cross_course"][2, 0])
    # A star around a with two leaves, over the bins around 0 and 1: a 1, b 1/sqrt(2), c 0.
    assert g["centrality"][:, 0] == pytest.approx([1.0, 2**-0.5, 0.0])
    assert g["centrality"][0, 1] == 1.0  # the window around bin 1 still holds bin 0


def test_unfamiliar_drops_someone_tied_on_an_earlier_day(m):
    # a and b close for a tie's worth of bins on D1; on D2 b no longer counts as unfamiliar.
    n = m.TIE_BINS
    bs = [300 * k for k in range(n)]
    later = 300 * (n + 1)
    rows = [("a", "b", b, D1) for b in bs] + [("a", "b", later, D2)]
    close = pl.DataFrame(rows, schema=["entity", "other", "bs", "day"], orient="row")
    exposure = pl.DataFrame({"entity": ["a"] * (n + 1), "bs": [*bs, later]})
    g = m.features(exposure, close, {}, ["a"], 0, n + 2)
    assert g["unfamiliar"][0, 0] == 1.0
    assert g["unfamiliar"][0, n + 1] == 0.0


def test_fit_recovers_a_planted_effect_past_collinear_dummies(m):
    # y = 2 * shared + person levels: the coefficient is 2, whatever the dummies' rank.
    rng = np.random.default_rng(0)
    n = 400
    i, j = rng.integers(0, 10, n), rng.integers(10, 20, n)
    level = rng.normal(0, 1, 20)
    shared = rng.integers(0, 2, n)
    y = 2.0 * shared + level[i] + level[j]
    rows = pl.DataFrame({"i": i, "j": j, "d": rng.integers(0, 3, n), "shared": shared == 1})
    X = m.design(rows, [], 20, 3)
    assert m.fit(y, X) == pytest.approx(2.0, abs=1e-6)


def test_lag_effects_are_zero_when_shuffles_read_the_same_bins(m):
    grid = np.arange(40.0).reshape(2, 20)
    person = np.array([0, 0, 0])
    at = np.array([5, 8, 11])
    mask = {"k": np.ones(3, dtype=bool)}
    eff = m.lag_effects(grid, person, at, at[None, :], mask, np.array([-1, 0, 1]))
    assert np.nansum(np.abs(eff["k"])) == 0.0
    assert np.isnan(eff["k"][1]).all()  # person 1 has no presses
