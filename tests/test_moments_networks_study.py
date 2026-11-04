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


def test_window_row_gives_a_verdict_and_withholds_small_cells(m):
    big = np.array([1.0, 1.1, 0.9, 1.2, 0.8, 1.0])
    row = m.window_row({"discovery": big, "replication": big, "all": big})
    assert row["all"] == pytest.approx(1.0)
    assert row["all_people"] == 6
    assert row["verdict"] == "replicates"
    few = np.array([1.0, 1.1, 0.9, np.nan, np.nan, np.nan])
    row = m.window_row({"discovery": big, "replication": few, "all": big})
    assert row["replication"] is None
    assert row["verdict"] == "withheld"


def test_run_lags_writes_every_window_of_every_kind(m):
    grid = np.ones((2, 40))
    person = np.array([0, 0, 0, 1, 1, 1])
    at = np.array([10, 15, 20, 10, 15, 20])
    days = [date(2026, 8, 15), date(2026, 8, 16)] * 3
    kinds = {"all": np.ones(6, dtype=bool)}
    rows, eff = m.run_lags(
        {"close": grid}, person, at, days, at[None, :], kinds, m.LAGS, m.WINDOWS, {"null": "x"}
    )
    assert [r["window"] for r in rows] == ["before", "near", "after", "asymmetry"]
    assert rows[0]["null"] == "x" and rows[0]["verdict"] == "withheld"  # two people only
    assert set(eff["close"]) == {("all", "discovery"), ("all", "replication"), ("all", "all")}


def _days():
    return [date(2026, 8, 13 + k) for k in range(16)]


def test_pair_table_row_by_row(m):
    # Pair a-b, moment on 20 Aug (index 7). Minutes: 10 on each of the three days before, 60 that
    # day, 70 on the day after. Earlier = 10 + 10 + 10 = 30, prior (before those three) = 0.
    # Tie needs 60 minutes: that day and the next tie, none before.
    days = _days()
    minutes = np.zeros((2, 2, 16))
    minutes[0, 1, 4:7] = 10
    minutes[0, 1, 7] = 60
    minutes[0, 1, 8] = 70
    seen = np.zeros((2, 2, 16))
    seen[0, 1, 8:11] = 5  # 15 bins both seen in the follow-up
    d = date(2026, 8, 20)
    rows = m.pair_table(
        {("a", "b", d)}, set(), minutes, seen, {"a": 0, "b": 1}, {"a": 1, "b": 1}, days
    )
    r = rows.row(0, named=True)
    assert r["shared"] and r["same_course"]
    assert r["today"] == pytest.approx(np.log1p(60))
    assert r["earlier"] == pytest.approx(np.log1p(30))
    assert r["previous"] == pytest.approx(np.log1p(30))
    assert r["prior"] == 0.0
    assert r["later"] == pytest.approx(np.log1p(70))
    assert r["seen_later"] == pytest.approx(np.log1p(15))
    assert r["tied_later"] and not r["tied_earlier"]


def test_pair_table_leaves_days_outside_the_moment_range_out(m):
    z = np.zeros((2, 2, 16))
    early = ("a", "b", date(2026, 8, 16))
    d = date(2026, 8, 20)
    rows = m.pair_table({early}, {("a", "b", d)}, z, z, {"a": 0, "b": 1}, {}, _days())
    assert rows.height == 1 and not rows["shared"][0]


def test_come_back_gives_all_three_outcomes_and_a_verdict(m, monkeypatch):
    # Planted: shared pair-days have log minutes 1 higher afterwards, on both halves.
    monkeypatch.setattr(m, "N_BOOT_NODE", 20)
    rng = np.random.default_rng(0)
    days = _days()
    n, rows = 12, []
    use = [date(2026, 8, x) for x in (20, 21, 22, 23)]
    for k in range(600):
        i, j = sorted(rng.choice(n, 2, replace=False).tolist())
        day = use[k % 4]
        shared = bool(rng.integers(0, 2))
        rows.append({
            "i": i, "j": j, "d": days.index(day), "day": day, "shared": shared,
            "same_course": False, "today": rng.normal(), "earlier": rng.normal(),
            "tied_earlier": False, "seen_later": rng.normal(), "prior": rng.normal(),
            "tied_prior": False, "seen_previous": rng.normal(),
            "later": float(shared) + rng.normal(0, 0.1), "tied_later": shared,
            "previous": rng.normal(0, 0.1),
        })  # fmt: skip
    out = m.come_back(pl.DataFrame(rows), "main", n, 16)
    assert [r["outcome"].split(" ")[0] for r in out] == ["close", "tied", "placebo:"]
    assert out[0]["all_est"] == pytest.approx(1.0, abs=0.1)
    assert out[0]["verdict"] == "replicates"
    assert out[2]["verdict"] != "replicates"


def test_pair_table_rows_come_in_sorted_order_whatever_the_sets_order(m):
    z = np.zeros((3, 3, 16))
    d = date(2026, 8, 20)
    pairs = {("b", "c", d), ("a", "c", d), ("a", "b", d)}
    rows = m.pair_table(pairs, set(), z, z, {"a": 0, "b": 1, "c": 2}, {}, _days())
    assert list(zip(rows["i"], rows["j"], strict=True)) == [(0, 1), (0, 2), (1, 2)]
