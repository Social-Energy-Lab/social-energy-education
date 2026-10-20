"""Mixing by day and period, persistence of new ties, node bootstrap, within-strata correlation.

Synthetic, hand-written tables; every expected value is derived by hand in the comments.
"""

import math
from datetime import date

import numpy as np
import polars as pl
import pytest

from social_energy.rhythm import (
    daily_mixing,
    node_bootstrap_weights,
    period_mixing,
    retie_opportunities,
    within_strata_correlation,
)

D1, D2, D3, D4 = (date(2030, 1, d) for d in (1, 2, 3, 4))
GROUPS = {"p0": "B", "p1": "A", "p2": "A", "p3": "B", "p4": "B", "p5": None}


def ties(rows):
    return pl.DataFrame(
        rows,
        schema={"day": pl.Date, "a": pl.String, "b": pl.String, "minutes": pl.Int64},
        orient="row",
    )


def present(rows):
    return pl.DataFrame(rows, schema={"entity": pl.String, "day": pl.Date}, orient="row")


# Day 1: p1-p5 present; p5 has no group. Day 2: p4 absent. p0 is never present.
TIES = ties(
    [
        (D1, "p1", "p2", 60),  # same group
        (D1, "p1", "p3", 120),  # cross
        (D1, "p3", "p5", 60),  # p5's group unknown: never counts
        (D2, "p1", "p3", 60),  # cross
        (D2, "p2", "p4", 60),  # cross, p4 absent on day 2
        (D2, "p0", "p1", 60),  # cross, p0 never present
    ]
)
PRESENT = present(
    [(p, D1) for p in ("p1", "p2", "p3", "p4", "p5")] + [(p, D2) for p in ("p1", "p2", "p3")]
)


def test_daily_mixing_against_random_pairs():
    m = daily_mixing(TIES, PRESENT, GROUPS).to_dicts()
    # Day 1: known people N = 4, two per group: same-group ordered pairs 2*1 + 2*1 = 4 of
    # 4*3 = 12, expected = 1 - 4/12 = 2/3. Ties p1-p2 (same), p1-p3 (cross): share 1/2; minutes
    # 180 of which 120 cross: 2/3. Excess 1/2 - 2/3 = -1/6.
    d1 = m[0]
    assert (d1["day"], d1["people"], d1["ties"], d1["cross_ties"]) == (D1, 4, 2, 1)
    assert d1["cross_share"] == pytest.approx(0.5)
    assert d1["cross_share_minutes"] == pytest.approx(2 / 3)
    assert d1["expected"] == pytest.approx(2 / 3)
    assert d1["excess"] == pytest.approx(-1 / 6)
    # Day 2: N = 3 (A, A, B): same 2*1 = 2 of 3*2 = 6, expected 2/3. p2-p4 and p0-p1 drop (p4
    # and p0 absent): one tie, cross.
    d2 = m[1]
    assert (d2["people"], d2["ties"], d2["cross_ties"]) == (3, 1, 1)
    assert d2["cross_share"] == pytest.approx(1.0)
    assert d2["expected"] == pytest.approx(2 / 3)


def test_period_mixing_within_person():
    m = period_mixing(TIES, PRESENT, GROUPS, {D1: "special", D2: "ordinary"})
    row = {(r["entity"], r["period"]): r for r in m.to_dicts()}
    # p1, day 1: 60 min with p2 (A) + 120 with p3 (B) = 180, 120 cross, share 2/3; own expected
    # (N - n_A)/(N - 1) = (4 - 2)/3 = 2/3; excess 0.
    s = row[("p1", "special")]
    assert (s["minutes"], s["cross_minutes"], s["days"]) == (180, 120, 1)
    assert s["cross_share"] == pytest.approx(2 / 3)
    assert s["expected"] == pytest.approx(2 / 3)
    assert s["excess"] == pytest.approx(0.0)
    # p1, day 2: 60 min with p3 and 60 with p0 (absent, but only p1's presence is required, as
    # in C2), all cross; expected (3 - 2)/2 = 1/2; excess 1/2.
    o = row[("p1", "ordinary")]
    assert o["minutes"] == 120
    assert o["cross_share"] == pytest.approx(1.0)
    assert o["expected"] == pytest.approx(0.5)
    assert o["excess"] == pytest.approx(0.5)
    # p3, day 1: the tie with p5 (no group) is left out; 120 min with p1, cross; expected 2/3.
    assert row[("p3", "special")]["minutes"] == 120
    assert row[("p3", "special")]["excess"] == pytest.approx(1 / 3)
    # p3, day 2: expected (3 - 1)/2 = 1.
    assert row[("p3", "ordinary")]["expected"] == pytest.approx(1.0)
    # As in C2, only the person's own presence is required: p2 keeps the tie with p4 on day 2.
    assert row[("p2", "ordinary")]["cross_share"] == pytest.approx(1.0)
    # p5 has no group; p0 is never present.
    assert not any(e in ("p0", "p5") for e, _ in row)


def test_period_expected_is_weighted_by_tie_minutes():
    m = period_mixing(TIES, PRESENT, GROUPS, {D1: "all", D2: "all"})
    p1 = m.filter(pl.col("entity") == "p1").to_dicts()[0]
    # 180 min on day 1 at 2/3, 120 min on day 2 at 1/2: (120 + 60)/300 = 0.6. Share 240/300.
    assert p1["expected"] == pytest.approx(0.6)
    assert p1["cross_share"] == pytest.approx(0.8)
    assert p1["days"] == 2


def test_retie_opportunities():
    t = ties(
        [
            (D1, "p1", "p2", 60),  # first tie before first_from: baseline, never new
            (D3, "p1", "p2", 60),
            (D2, "p1", "p3", 60),  # new on D2
            (D4, "p1", "p3", 60),
            (D3, "p2", "p3", 60),  # new on D3; p2 absent on D4: no follow-up
        ]
    )
    p = present(
        [(e, d) for e in ["p1"] for d in (D1, D2, D3, D4)]
        + [("p2", d) for d in (D1, D2, D3)]
        + [("p3", d) for d in (D2, D3, D4)]
    )
    o = retie_opportunities(t, p, first_from=D2, days=[D1, D2, D3, D4])
    assert o.select("a", "b", "formed", "day", "lag", "tied").rows() == [
        ("p1", "p3", D2, D3, 1, False),
        ("p1", "p3", D2, D4, 2, True),
    ]


def test_retie_ignores_days_outside_the_list():
    # The D4 tie is outside ``days``: the follow-up on D3 is the only opportunity.
    t = ties([(D2, "p1", "p3", 60), (D4, "p1", "p3", 60)])
    p = present([(e, d) for e in ("p1", "p3") for d in (D2, D3, D4)])
    o = retie_opportunities(t, p, first_from=D2, days=[D2, D3])
    assert o.select("day", "tied").rows() == [(D3, False)]


def test_node_bootstrap_weights_draw_people():
    draws = list(node_bootstrap_weights(5, n_boot=50, seed=1))
    assert len(draws) == 50
    assert all(len(w) == 5 and w.sum() == 5 and (w >= 0).all() for w in draws)
    # Not every draw is the identity: resampling with replacement repeats people.
    assert any((w != 1).any() for w in draws)
    again = list(node_bootstrap_weights(5, n_boot=50, seed=1))
    assert all(np.array_equal(a, b) for a, b in zip(draws, again, strict=True))


def test_within_strata_removes_the_stratum_level():
    # Three strata at very different levels; inside each, y falls as x rises. Pooled, x and y
    # rise together; within strata the ranks run against each other.
    x = [1, 2, 10, 11, 20, 21]
    y = [2, 1, 11, 10, 21, 20]
    s = ["a", "a", "b", "b", "c", "c"]
    # Ranks x 1..6, y 2 1 4 3 6 5; stratum means removed: x -.5 .5 ..., y .5 -.5 ...: r = -1.
    c = within_strata_correlation(x, y, s, s, n_boot=200, seed=0)
    assert c.r == pytest.approx(-1.0)
    assert c.n == 6 and c.clusters == 3
    # Every draw is made of whole strata, so every draw is -1 too.
    assert c.lo == pytest.approx(-1.0) and c.hi == pytest.approx(-1.0)
    # Without strata (one stratum) the same data correlate positively.
    pooled = within_strata_correlation(x, y, ["z"] * 6, s, n_boot=50)
    assert pooled.r > 0.8


def test_within_strata_drops_missing_and_needs_three_clusters():
    c = within_strata_correlation(
        [1, 2, None, 3, 4], [1, 2, 5, 4, 3], ["a"] * 5, ["k", "k", "k", "m", "m"], n_boot=10
    )
    assert c.n == 4 and c.clusters == 2
    assert math.isnan(c.lo) and math.isnan(c.hi)
    with pytest.raises(ValueError):
        within_strata_correlation([1, 2, 3], [1, 2, 3], "aaa", "abc", method="kendall")


def test_ranks_average_ties():
    from social_energy.rhythm import _ranks

    # 3 1 3 2 -> sorted 1 2 3 3: ranks 1, 2, and 3.5 for both 3s.
    assert _ranks(np.array([3.0, 1.0, 3.0, 2.0])).tolist() == [3.5, 1.0, 3.5, 2.0]
