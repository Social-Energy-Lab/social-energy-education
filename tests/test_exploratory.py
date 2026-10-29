"""Exploratory comparisons: within-person contrasts, rates by category, co-located co-events.

Invented rows only; every expected value is derived by hand in the test.
"""

import math

import numpy as np
import polars as pl
import pytest

from social_energy.exploratory import (
    CloseIndex,
    bootstrap_mean,
    cluster_ratio,
    co_event_pairs,
    co_events,
    first_mover_logit,
    group_members,
    group_sizes,
    null_compare,
    person_rates,
    shuffle_events,
    within_person_contrast,
)

# Person a: event bins have 3 and 5 close others, other bins 1, 1, 2 -> 4 - 4/3 = 2.6667.
# Person b: one event bin with 0, other bins 2 and 4 -> 0 - 3 = -3.
# Person c: no event at all -> left out.
BINS = pl.DataFrame(
    {
        "entity": ["a"] * 5 + ["b"] * 3 + ["c"] * 2,
        "phase": ["eve", "eve", "eve", "day", "day", "eve", "eve", "day", "eve", "day"],
        "close": [3, 1, 2, 5, 1, 0, 2, 4, 7, 8],
        "event": [True, False, False, True, False, True, False, False, False, False],
    }
)


def test_within_person_contrast_unmatched():
    c = within_person_contrast(BINS, value="close", event="event")
    assert c["entity"].to_list() == ["a", "b"]
    assert c["events"].to_list() == [2, 1]
    assert c["diff"].to_list() == pytest.approx([4 - 4 / 3, -3.0])


def test_within_person_contrast_matches_within_strata():
    # a, eve: event 3 vs others 1, 2 -> 1.5, diff 1.5; a, day: 5 vs 1, diff 4. Weighted by one
    # event each: (1.5 + 4) / 2 = 2.75. b, eve: 0 vs 2 -> -2; b, day has no event -> dropped.
    c = within_person_contrast(BINS, value="close", event="event", strata=["phase"])
    assert c["diff"].to_list() == pytest.approx([2.75, -2.0])
    assert c["baseline"].to_list() == pytest.approx([(1.5 + 1) / 2, 2.0])


def test_bootstrap_mean_interval_brackets_and_is_seeded():
    r = bootstrap_mean([1.0, 2.0, 3.0, 4.0, float("nan")], n_boot=2000, seed=3)
    assert r.n == 4
    assert r.estimate == pytest.approx(2.5)
    assert 1.0 <= r.lo < 2.5 < r.hi <= 4.0
    assert bootstrap_mean([1.0, 2.0, 3.0, 4.0], n_boot=2000, seed=3) == r
    # A constant sample has a degenerate interval.
    k = bootstrap_mean([2.0, 2.0, 2.0])
    assert (k.lo, k.hi) == (2.0, 2.0)


def test_person_rates_pool_events_over_hours_and_suppress_small_cells():
    # Exposure, bins of half an hour: course: p1 4 bins, p2 2 bins (3 h); late: p1 2 bins (1 h).
    # Events: course p1 x2, p2 x1 -> 3 / 3 h = 1.0 per hour; late p1 x3 -> 3 per hour.
    exposure = pl.DataFrame(
        {
            "entity": ["p1"] * 6 + ["p2"] * 2,
            "where": ["course"] * 4 + ["late"] * 2 + ["course"] * 2,
        }
    )
    events = pl.DataFrame(
        {"entity": ["p1", "p1", "p2", "p1", "p1", "p1"], "where": ["course"] * 3 + ["late"] * 3}
    )
    r = person_rates(events, exposure, category="where", bin_hours=0.5, n_boot=500, seed=1)
    assert r.categories == ["course", "late"]
    assert r.rate.tolist() == pytest.approx([1.0, 3.0])
    assert r.people_exposed.tolist() == [2, 1]
    assert r.people_with_events.tolist() == [2, 1]
    # late / course = 3; when p2 is drawn alone, late has no hours and that draw is skipped.
    ratio = r.ratio(["late"], ["course"])
    assert ratio.estimate == pytest.approx(3.0)
    t = r.table(min_people=2, per=10)
    assert t["rate"].to_list()[0] == pytest.approx(10.0)
    assert t["suppressed"].to_list() == [False, True]
    assert t["rate"].to_list()[1] is None


def test_person_rates_suppress_a_cell_with_few_people_with_events():
    exposure = pl.DataFrame({"entity": ["p1", "p2", "p3"], "where": ["x", "x", "x"]})
    events = pl.DataFrame({"entity": ["p1"], "where": ["x"]})
    t = person_rates(events, exposure, category="where", bin_hours=1, n_boot=50).table(min_people=2)
    assert t["suppressed"].to_list() == [True]  # one presser out of three exposed
    none = pl.DataFrame({"entity": [], "where": []}, schema={"entity": str, "where": str})
    t0 = person_rates(none, exposure, category="where", bin_hours=1, n_boot=50).table(min_people=2)
    assert t0["suppressed"].to_list() == [False] and t0["rate"].to_list() == [0.0]


def test_co_events_counts_pairs_in_window_and_their_co_location():
    # Bins of 300 s. a@100 and b@250: 150 s apart, a had b close in bin 0 -> close pair.
    # b@250 and c@500: 250 s apart, nobody close -> pair, not close. a@100 and c@500: 400 s,
    # outside 300 s. a@100 and a@200 (same person) never count. c@500 and d@520: close in d's
    # bin 300 only (the "either bin" rule).
    entity = ["a", "a", "b", "c", "d"]
    t = [100, 200, 250, 500, 520]
    close = {("a", 0, "b"), ("d", 300, "c")}
    # Pairs within 300 s by different people: a100-b250, a200-b250, a200-c500 (300 s,
    # inclusive), b250-c500, b250-d520 (270 s), c500-d520 -> 6; close: a100-b250 and a200-b250
    # (a's bin 0 holds b), c500-d520 -> 3.
    assert co_events(entity, t, close, window=300, bin_size=300) == (3, 6)
    # Within 100 s: a200-b250 (close) and c500-d520 (close).
    assert co_events(entity, t, close, window=100, bin_size=300) == (2, 2)


def test_shuffle_events_keeps_person_and_stratum():
    exposure = {("a", 1): np.array([0, 600]), ("b", 1): np.array([3000])}
    rng = np.random.default_rng(0)
    used = set()
    for _ in range(50):
        new = shuffle_events(["a", "a", "b"], [1, 1, 1], exposure, rng, bin_size=300)
        assert all((0 <= v < 300) or (600 <= v < 900) for v in new[:2])
        assert 3000 <= new[2] < 3300
        used |= {int(v) // 300 * 300 for v in new[:2]}
    assert used == {0, 600}  # every exposure bin of the person can be drawn


def test_null_compare():
    c = null_compare(6, [1, 2, 3, 4, 5, 6, 7, 8, 9, 10])
    assert c.null_mean == pytest.approx(5.5)
    assert c.ratio == pytest.approx(6 / 5.5)
    assert c.share_null_at_least == pytest.approx(0.5)
    assert math.isnan(null_compare(1, [0, 0]).ratio)


# --- round 2: the pairs themselves, group moments, who goes first, day-clustered ratios -----------


def test_co_event_pairs_lists_each_pair_in_time_order_with_gap_and_co_location():
    # The same events as test_co_events: within 300 s, six pairs, three close.
    entity = ["a", "a", "b", "c", "d"]
    t = [100, 200, 250, 500, 520]
    close = CloseIndex({("a", 0, "b"), ("d", 300, "c")}, bin_size=300)
    p = co_event_pairs(entity, t, close, window=300, bin_size=300)
    got = sorted(zip(p.first.tolist(), p.second.tolist(), p.gap.tolist(), p.close.tolist(),
                     strict=True))  # fmt: skip
    assert got == [
        (0, 2, 150, True),  # a100-b250
        (1, 2, 50, True),  # a200-b250
        (1, 3, 300, False),  # a200-c500, inclusive edge
        (2, 3, 250, False),  # b250-c500
        (2, 4, 270, False),  # b250-d520
        (3, 4, 20, True),  # c500-d520, close in d's bin only
    ]


def test_co_event_pairs_keep_input_positions_when_times_are_unsorted():
    # Input order is not time order: positions refer to the input, first is the earlier event.
    p = co_event_pairs(["b", "a"], [400, 100], CloseIndex(set(), bin_size=300), window=600,
                       bin_size=300)  # fmt: skip
    assert (p.first.tolist(), p.second.tolist(), p.gap.tolist()) == ([1], [0], [300])


def test_close_index_matches_triples_only():
    idx = CloseIndex({("a", 0, "b"), ("b", 300, "a")}, bin_size=300)
    hit = idx.contains(["a", "a", "b", "b", "z"], [0, 300, 300, 0, 0], ["b", "b", "a", "a", "a"])
    assert hit.tolist() == [True, False, True, False, False]


def test_group_sizes_are_distinct_people_per_connected_component():
    # Events 0-1-2 chain (people a, b, a again) -> one component of 2 people; 3-4-5 a triangle of
    # c, d, e -> 3 people; event 6 has no edge and is not a group.
    entity = ["a", "b", "a", "c", "d", "e", "f"]
    sizes = group_sizes(entity, np.array([0, 1, 3, 3, 4]), np.array([1, 2, 4, 5, 5]))
    assert sorted(sizes.tolist()) == [2, 3]
    assert group_sizes(entity, np.array([], dtype=int), np.array([], dtype=int)).size == 0


def test_group_members_are_the_people_of_each_component():
    entity = ["a", "b", "a", "c", "d", "e", "f"]
    groups = group_members(entity, np.array([0, 1, 3, 3, 4]), np.array([1, 2, 4, 5, 5]))
    assert sorted(sorted(g) for g in groups) == [["a", "b"], ["c", "d", "e"]]


def test_first_mover_logit_recovers_direction_and_is_zero_when_balanced():
    # x_first - x_second: positive differences go first 3 times out of 4 -> log-odds per unit
    # of difference = log(3) for |d| = 1 (pairs with d = +1 three times and d = -1 once).
    d = np.array([[1.0], [1.0], [1.0], [-1.0]])
    assert first_mover_logit(d)[0] == pytest.approx(math.log(3), abs=1e-6)
    assert first_mover_logit(np.array([[1.0], [-1.0]]))[0] == pytest.approx(0.0, abs=1e-9)


def test_cluster_ratio_sums_then_resamples_clusters():
    # Observed 2, 4, 6 against expected 1, 2, 3 per day -> ratio 2 in every resample.
    r = cluster_ratio(np.array([2.0, 4.0, 6.0]), np.array([1.0, 2.0, 3.0]), n_boot=200, seed=1)
    assert (r.estimate, r.lo, r.hi, r.n) == pytest.approx((2.0, 2.0, 2.0, 3))
    # Uneven days: the pooled ratio is 12 / 6 = 2 (not the mean of daily ratios, 0 + 1 + 10/3
    # over 3 = 1.44), and resamples spread around it.
    u = cluster_ratio(np.array([0.0, 2.0, 10.0]), np.array([1.0, 2.0, 3.0]), n_boot=2000, seed=1)
    assert u.estimate == pytest.approx(2.0)
    assert u.lo < 2.0 < u.hi
    # Several categories at once (days x categories).
    m = cluster_ratio(np.array([[2.0, 1.0], [4.0, 1.0]]), np.array([[1.0, 1.0], [2.0, 1.0]]),
                      n_boot=100, seed=0)  # fmt: skip
    assert [i.estimate for i in m] == pytest.approx([2.0, 1.0])
