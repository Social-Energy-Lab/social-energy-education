"""Per-person outcome measures: close-contact strength, cross-group share, new ties, event rate.

Golden cases are written by hand; the expected values are derived in the docstrings. The oracle
test recomputes the close-contact outcomes from the synthetic camp's ground truth with a plain
Python implementation and compares them with the toolkit run on the ingested logs.
"""

from collections import defaultdict
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import polars as pl
import pytest

from social_energy.beacons import BeaconConfig, ingest_logs
from social_energy.outcomes import (
    camp_day,
    close_contact_outcomes,
    daily_close_ties,
    drop_pair_bins,
    event_rate,
    present_days,
    windows_to_bins,
)
from social_energy.presence import copresence
from social_energy.spine import Spine
from social_energy.synth import CampSpec, generate

UTC = ZoneInfo("UTC")
D0, D1, D2, D3, D4 = (date(2030, 5, d) for d in range(1, 6))
DAYS = [D1, D2, D3, D4]  # D0 lies outside the days in scope
PEOPLE = [f"person:p{i}" for i in range(1, 8)]
GROUPS = {"person:p1": "A", "person:p2": "A", "person:p3": "B", "person:p4": "B",
          "person:p5": "B", "person:p6": "A", "person:p7": None}  # fmt: skip
RULES = {"close_rssi": -65, "min_minutes": 15, "bin_minutes": 5}


def _bins(day: date, a: str, b: str, n: int, rssi: int, first: int = 0) -> list[dict]:
    """``n`` distinct 5-minute bins for the pair on ``day``, starting at 12:00 + first bins."""
    t0 = datetime(day.year, day.month, day.day, 12, tzinfo=UTC)
    return [
        {"day": day, "a": f"person:{a}", "b": f"person:{b}",
         "bin": t0 + timedelta(minutes=5 * (first + i)), "max_rssi": rssi}
        for i in range(n)
    ]  # fmt: skip


def golden_pairs() -> pl.DataFrame:
    rows = [
        *_bins(D0, "p2", "p4", 6, -50),  # outside the days in scope: ignored
        *_bins(D1, "p1", "p2", 4, -60),
        *_bins(D1, "p1", "p2", 2, -70, first=4),  # not close: 20 min, not 30
        *_bins(D1, "p1", "p3", 2, -65),  # close (inclusive) but only 10 min: no tie
        *_bins(D1, "p1", "x9", 3, -60),  # partner outside the people in scope: ignored
        *_bins(D2, "p1", "p3", 3, -65),  # exactly 15 min: a tie
        *_bins(D2, "p2", "p3", 6, -50),
        *_bins(D3, "p1", "p2", 3, -60),
        *_bins(D3, "p1", "p4", 5, -60),
        *_bins(D3, "p3", "p4", 12, -60),
        *_bins(D3, "p2", "p5", 3, -60),  # p5 is not present on D3
        *_bins(D4, "p2", "p4", 3, -66),  # just too weak: not close
        *_bins(D4, "p1", "p3", 4, -60),
        *_bins(D4, "p4", "p5", 3, -60),
        *_bins(D4, "p4", "p7", 3, -60),  # p7 has no group
    ]
    return pl.DataFrame(rows, schema_overrides={"bin": pl.Datetime("us", "UTC")})


def golden_seen() -> pl.DataFrame:
    """Seen bins per person-day; present means at least 2 bins (``min_bins=2`` below)."""
    counts = {
        ("p1", D1): 3, ("p1", D2): 3, ("p1", D3): 3, ("p1", D4): 3,
        ("p2", D0): 9, ("p2", D1): 3, ("p2", D2): 3, ("p2", D3): 3, ("p2", D4): 1,
        ("p3", D1): 3, ("p3", D2): 3, ("p3", D3): 3, ("p3", D4): 3,
        ("p4", D3): 3, ("p4", D4): 3,
        ("p5", D3): 1, ("p5", D4): 2,
        ("p7", D4): 2,
    }  # fmt: skip
    rows = [
        {"entity": f"person:{p}", "day": d,
         "bin": datetime(d.year, d.month, d.day, 9, tzinfo=UTC) + timedelta(minutes=5 * i)}
        for (p, d), n in counts.items()
        for i in range(n)
    ]  # fmt: skip
    return pl.DataFrame(rows, schema_overrides={"bin": pl.Datetime("us", "UTC")})


def golden_outcomes() -> dict[str, dict]:
    ties = daily_close_ties(golden_pairs(), **RULES)
    present = present_days(golden_seen(), min_bins=2)
    out = close_contact_outcomes(
        ties, present, people=PEOPLE, days=DAYS, groups=GROUPS, burn_in_days=2
    )
    assert out["entity"].to_list() == PEOPLE  # one row per person, in order
    return {r["entity"].removeprefix("person:"): r for r in out.iter_rows(named=True)}


def test_daily_close_ties_counts_close_minutes_and_applies_the_minimum():
    ties = daily_close_ties(golden_pairs(), **RULES)
    got = {(r["day"], r["a"][-2:], r["b"][-2:]): r["minutes"] for r in ties.iter_rows(named=True)}
    assert got[(D1, "p1", "p2")] == 20  # the two -70 bins are not close
    assert (D1, "p1", "p3") not in got  # 10 close minutes < 15
    assert got[(D2, "p1", "p3")] == 15  # the minimum is inclusive
    assert got[(D3, "p3", "p4")] == 60
    assert (D4, "p2", "p4") not in got  # -66 is weaker than -65
    assert got[(D0, "p2", "p4")] == 30  # days are filtered later, not here
    assert set(ties.columns) == {"day", "a", "b", "minutes"}


def test_present_days_need_the_minimum_bins():
    present = present_days(golden_seen(), min_bins=2)
    p2 = sorted(present.filter(pl.col("entity") == "person:p2")["day"].to_list())
    assert p2 == [D0, D1, D2, D3]  # one bin on D4 is not presence
    assert present.filter(pl.col("entity") == "person:p5")["day"].to_list() == [D4]


def test_strength_is_mean_tie_minutes_over_present_days():
    """C1, minutes in ties per present day, ties counted on the person's present days only.

    p1: D1 20 (p2) · D2 15 (p3) · D3 15 (p2) + 25 (p4) · D4 20 (p3) = 95 / 4 = 23.75
    p2: D1 20 · D2 30 (p3) · D3 15 + 15 (p5); D4 absent; D0 out of scope = 80 / 3
    p3: D1 0 (10 min is no tie) · D2 15 + 30 · D3 60 · D4 20 = 125 / 4 = 31.25
    p4: D3 25 + 60 · D4 15 (p5) + 15 (p7) = 115 / 2 = 57.5
    p5: D3 absent (its tie with p2 does not count for p5) · D4 15 = 15
    p6: never present → no value · p7: D4 15 = 15
    """
    o = golden_outcomes()
    assert o["p1"]["strength_min_per_day"] == pytest.approx(23.75)
    assert o["p2"]["strength_min_per_day"] == pytest.approx(80 / 3)
    assert o["p3"]["strength_min_per_day"] == pytest.approx(31.25)
    assert o["p4"]["strength_min_per_day"] == pytest.approx(57.5)
    assert o["p5"]["strength_min_per_day"] == pytest.approx(15.0)
    assert o["p6"]["strength_min_per_day"] is None
    assert o["p7"]["strength_min_per_day"] == pytest.approx(15.0)
    assert [o[p]["days_present"] for p in ("p1", "p2", "p3", "p4", "p5", "p6", "p7")] == [
        4, 3, 4, 2, 1, 0, 1,
    ]  # fmt: skip


def test_cross_group_share_and_its_random_mixing_baseline():
    """C2, tie minutes with partners outside one's group / tie minutes with partners of known group.

    p1: p2 (A) 35 · p3 (B) 35 · p4 (B) 25 → 60 / 95
    p2: p1 (A) 35 · p3 (B) 30 · p5 (B) 15 → 45 / 80
    p3: p1 (A) 35 · p2 (A) 30 · p4 (B) 60 → 65 / 125
    p4: p1 (A) 25 · p3 (B) 60 · p5 (B) 15 · p7 (no group, left out) 15 → 25 / 100
    p5: p4 (B) 15; not p2, met on a day p5 was absent → 0 / 15 · p7: no group of its own → no share
    Baseline: present people with a known group are p1, p2 (A) and p3, p4, p5 (B), five in all.
    A: (5 - 2) / (5 - 1) = 0.75 · B: (5 - 3) / 4 = 0.5 · p6 never present, p7 no group: none.
    """
    o = golden_outcomes()
    assert o["p1"]["cross_share"] == pytest.approx(60 / 95)
    assert o["p2"]["cross_share"] == pytest.approx(45 / 80)
    assert o["p3"]["cross_share"] == pytest.approx(65 / 125)
    assert o["p4"]["cross_share"] == pytest.approx(0.25)
    assert o["p5"]["cross_share"] == pytest.approx(0.0)
    assert o["p6"]["cross_share"] is None
    assert o["p7"]["cross_share"] is None
    assert o["p4"]["close_minutes"] == 115
    assert o["p4"]["cross_minutes"] == 25
    assert [o[p]["cross_share_expected"] for p in ("p1", "p2", "p3", "p4", "p5")] == (
        pytest.approx([0.75, 0.75, 0.5, 0.5, 0.5])
    )
    assert o["p6"]["cross_share_expected"] is None
    assert o["p7"]["cross_share_expected"] is None


def test_new_ties_per_present_day_after_the_burn_in():
    """C3, ties first seen on a day after the first two, per present day after them.

    First tie day per pair: p1p2 D1, p1p3 D2, p2p3 D2, p1p4 D3, p3p4 D3, p2p5 D3, p4p5 D4,
    p4p7 D4. Days after the burn-in: D3, D4.
    p1: D3 p1p4 → 1 / 2 · p2: D3 p2p5, D4 absent → 1 / 1 · p3: D3 p3p4 → 1 / 2
    p4: D3 p1p4, p3p4 · D4 p4p5, p4p7 → 4 / 2 · p5: D3 absent · D4 p4p5 → 1 / 1
    p6: no present day → none · p7: D4 p4p7 → 1 / 1
    """
    o = golden_outcomes()
    got = {p: (o[p]["new_ties"], o[p]["days_after_burn_in"]) for p in o}
    assert got == {"p1": (1, 2), "p2": (1, 1), "p3": (1, 2), "p4": (4, 2),
                   "p5": (1, 1), "p6": (0, 0), "p7": (1, 1)}  # fmt: skip
    assert o["p4"]["new_ties_per_day"] == pytest.approx(2.0)
    assert o["p2"]["new_ties_per_day"] == pytest.approx(1.0)
    assert o["p3"]["new_ties_per_day"] == pytest.approx(0.5)
    assert o["p6"]["new_ties_per_day"] is None


def test_partners_over_the_whole_camp_on_the_golden_camp():
    """C3 candidates: distinct partners, from the person's own ties on their present days.

    Partners and the first day each is tied, from each person's side:
    p1: p2 D1, p3 D2, p4 D3 · p2: p1 D1, p3 D2, p5 D3 · p3: p1 D2, p2 D2, p4 D3
    p4: p1 D3, p3 D3, p5 D4, p7 D4 · p5: p4 D4 (p2 on D3 is not p5's: absent) · p7: p4 D4
    New partners (first tied on D3 or D4) per present day after the burn-in:
    p1 1/2 · p2 1/1 · p3 1/2 · p4 4/2 · p5 1/1 · p7 1/1 · p6 none.
    All partners per present day: p1 3/4 · p2 3/3 · p3 3/4 · p4 4/2 · p5 1/1 · p7 1/1 · p6 none.
    """
    o = golden_outcomes()
    got = {p: (o[p]["new_partners"], o[p]["partners"]) for p in o}
    assert got == {"p1": (1, 3), "p2": (1, 3), "p3": (1, 3), "p4": (4, 4),
                   "p5": (1, 1), "p6": (0, 0), "p7": (1, 1)}  # fmt: skip
    assert o["p1"]["new_partners_per_day"] == pytest.approx(0.5)
    assert o["p4"]["new_partners_per_day"] == pytest.approx(2.0)
    assert o["p1"]["partners_per_day"] == pytest.approx(0.75)
    assert o["p2"]["partners_per_day"] == pytest.approx(1.0)
    assert o["p4"]["partners_per_day"] == pytest.approx(2.0)
    assert o["p6"]["new_partners_per_day"] is None
    assert o["p6"]["partners_per_day"] is None


def test_a_partner_is_new_from_the_persons_own_first_tie():
    """Where C3 by first pair tie and C3 by new partners part ways.

    Days E1, E2, E3, burn-in one day (after: E2, E3). q2 is absent on E1; everyone else is
    present every day. Ties: E1 q1q2, E1 q1q3, E2 q1q2, E3 q1q3, E3 q2q3.
    Pair first tie (daily definition): q1q2 E1, q1q3 E1, q2q3 E3, so q2 gets one new tie (q3).
    Own first tie (partner definition): q2 first meets q1 on E2 (the E1 tie is not on q2's
    present day), so q2 has two new partners over 2 present days after the burn-in = 1.0, against
    0.5 for the daily definition. q1: partners q2 E1, q3 E1 → 0 new / 2 = 0; 2 partners / 3 days.
    q3: q1 E1, q2 E3 → 1 new / 2 = 0.5; 2 partners / 3 days.
    """
    e1, e2, e3 = date(2030, 6, 1), date(2030, 6, 2), date(2030, 6, 3)
    ties = pl.DataFrame(
        {"day": [e1, e1, e2, e3, e3], "a": ["q1", "q1", "q1", "q1", "q2"],
         "b": ["q2", "q3", "q2", "q3", "q3"], "minutes": [60] * 5},
    )  # fmt: skip
    present = pl.DataFrame(
        {"entity": ["q1"] * 3 + ["q2"] * 2 + ["q3"] * 3, "day": [e1, e2, e3, e2, e3, e1, e2, e3]}
    )
    out = close_contact_outcomes(
        ties, present, people=["q1", "q2", "q3"], days=[e1, e2, e3], groups={}, burn_in_days=1
    )
    o = {r["entity"]: r for r in out.iter_rows(named=True)}
    assert [o[q]["new_ties_per_day"] for q in ("q1", "q2", "q3")] == pytest.approx([0, 0.5, 0.5])
    assert [o[q]["new_partners"] for q in ("q1", "q2", "q3")] == [0, 2, 1]
    assert [o[q]["new_partners_per_day"] for q in ("q1", "q2", "q3")] == pytest.approx(
        [0, 1.0, 0.5]
    )
    assert [o[q]["partners_per_day"] for q in ("q1", "q2", "q3")] == pytest.approx(
        [2 / 3, 1.0, 2 / 3]
    )


def _t(h: int, m: int) -> datetime:
    return datetime(2030, 5, 1, h, m, tzinfo=UTC)


def test_windows_to_bins_covers_each_bin_the_window_touches():
    windows = pl.DataFrame(
        {"entity": ["e1", "e2", "e3"], "start": [_t(10, 3), _t(10, 5), _t(10, 0)],
         "end": [_t(10, 12), _t(10, 10), _t(10, 0)]},
        schema_overrides={"start": pl.Datetime("us", "UTC"), "end": pl.Datetime("us", "UTC")},
    )  # fmt: skip
    got = windows_to_bins(windows, bin_minutes=5).sort("entity", "bin")
    assert got.rows() == [
        ("e1", _t(10, 0)), ("e1", _t(10, 5)), ("e1", _t(10, 10)),  # [10:03, 10:12)
        ("e2", _t(10, 5)),  # [10:05, 10:10): the bin at the end is not touched
    ]  # fmt: skip  # e3 is empty


def test_drop_pair_bins_removes_bins_where_either_side_is_removed():
    pairs = pl.DataFrame(
        {"a": ["p1", "p1", "p2", "p3"], "b": ["p2", "p3", "p3", "p4"],
         "bin": [_t(10, 0), _t(10, 5), _t(10, 0), _t(10, 0)]},
        schema_overrides={"bin": pl.Datetime("us", "UTC")},
    )  # fmt: skip
    removed = pl.DataFrame(
        {"entity": ["p1", "p4"], "bin": [_t(10, 0), _t(10, 5)]},
        schema_overrides={"bin": pl.Datetime("us", "UTC")},
    )
    got = drop_pair_bins(pairs, removed).sort("a", "b")
    # p1-p2 at 10:00 goes (p1 removed then); p4 is removed at 10:05, not at 10:00.
    assert got.select("a", "b").rows() == [("p1", "p3"), ("p2", "p3"), ("p3", "p4")]


def test_event_rate_drops_removed_bins_from_both_events_and_hours():
    """e1: exposure 10:00-10:15 (4 bins) less the removed 10:05 bin = 3 bins = 0.25 h.
    Events at 10:01 and 10:14 count; 10:07 lies in the removed bin; 10:22 lies outside the
    exposure. 2 / 0.25 = 8 per hour. e2: one hour, no events → 0. e3: an event but no exposure →
    no rate. e4 is not in scope."""
    exposure = pl.DataFrame(
        {"entity": ["e1"] * 4 + ["e2"] * 12,
         "bin": [_t(10, 5 * i) for i in range(4)] + [_t(11, 5 * i) for i in range(12)]},
        schema_overrides={"bin": pl.Datetime("us", "UTC")},
    )  # fmt: skip
    removed = pl.DataFrame(
        {"entity": ["e1"], "bin": [_t(10, 5)]}, schema_overrides={"bin": pl.Datetime("us", "UTC")}
    )
    events = pl.DataFrame(
        {"entity": ["e1", "e1", "e1", "e1", "e3", "e4"],
         "t": [_t(10, 1), _t(10, 7), _t(10, 22), _t(10, 14), _t(10, 1), _t(10, 1)]},
        schema_overrides={"t": pl.Datetime("us", "UTC")},
    )  # fmt: skip
    got = event_rate(events, exposure, removed=removed, people=["e1", "e2", "e3"], bin_minutes=5)
    rows = {r["entity"]: r for r in got.iter_rows(named=True)}
    assert got["entity"].to_list() == ["e1", "e2", "e3"]
    assert (rows["e1"]["events"], rows["e1"]["exposure_hours"]) == (2, pytest.approx(0.25))
    assert rows["e1"]["events_per_hour"] == pytest.approx(8.0)
    assert (rows["e2"]["events"], rows["e2"]["events_per_hour"]) == (0, pytest.approx(0.0))
    assert (rows["e3"]["events"], rows["e3"]["exposure_hours"]) == (0, pytest.approx(0.0))
    assert rows["e3"]["events_per_hour"] is None
    # Without removals the 10:07 event and the bin count again: 3 / (4 / 12) = 9 per hour.
    plain = event_rate(events, exposure, people=["e1"], bin_minutes=5)
    assert plain["events_per_hour"].to_list() == [pytest.approx(9.0)]


def test_camp_day_starts_at_the_given_clock_time():
    # Europe/Berlin is UTC+2 in May: 05:29 UTC is 07:29 local (the day before), 05:30 is 07:30.
    t = pl.DataFrame(
        {"t": [datetime(2030, 5, 2, 5, 29, tzinfo=UTC), datetime(2030, 5, 2, 5, 30, tzinfo=UTC)]}
    )
    got = t.select(camp_day(pl.col("t"), timezone="Europe/Berlin", day_start=timedelta(hours=7.5)))
    assert got.to_series().to_list() == [date(2030, 5, 1), date(2030, 5, 2)]


# ---- oracle: the synthetic camp ---------------------------------------------------------------


@pytest.fixture(scope="module")
def synthetic(tmp_path_factory):
    camp = generate(CampSpec(hours=60), tmp_path_factory.mktemp("camp"))
    spec = camp.spec
    config = BeaconConfig(
        timezone=spec.timezone,
        valid_from=spec.start.date(),
        valid_to=spec.start.date() + timedelta(days=3),
        ambiguous_id_cutoff=camp.id_bug_cutoff,
    )
    spine = Spine.load(camp.spine_dir)
    c = ingest_logs(camp.log_paths, config).contacts.filter(pl.col("ok"))
    for side, out in (("beacon", "observer_entity"), ("observed", "observed_entity")):
        c = spine.resolve(c, device_col=side, time_col="t", kind="beacon", out=out)
        c = spine.flag_excluded(c, device_col=side, time_col="t", kind="beacon", out=f"x_{side}")
    c = c.filter(~pl.col("x_beacon") & ~pl.col("x_observed"))
    return camp, spine, c


def _oracle(camp, groups, *, day_of, min_bins, min_minutes, burn_in_days):
    """Plain-Python close-contact outcomes from the ground truth (every reading counts as close:
    the generator's person readings are all at -79 dBm or stronger)."""
    pair_bins, seen = defaultdict(set), defaultdict(set)
    for o, d, t in camp.truth_contacts.iter_rows():
        b = t.replace(minute=t.minute - t.minute % 5, second=0, microsecond=0)
        seen[(o, day_of(b))].add(b)
        if d.startswith("person:"):
            seen[(d, day_of(b))].add(b)
            if o != d:
                pair_bins[(day_of(b), *sorted((o, d)))].add(b)
    ties = {k: 5 * len(v) for k, v in pair_bins.items() if 5 * len(v) >= min_minutes}
    present = {k for k, v in seen.items() if len(v) >= min_bins}
    days = sorted({d for _, d in present})
    people = sorted({k[0] for k in present})
    out = {}
    first_day = {}
    for d, a, b in sorted(ties):
        first_day.setdefault((a, b), d)
    known = [p for p in people if groups.get(p)]
    for p in people:
        pdays = [d for d in days if (p, d) in present]
        mins = {d: 0 for d in pdays}
        cross = same = 0
        for (d, a, b), m in ties.items():
            if p in (a, b) and d in mins:
                mins[d] += m
                other = b if p == a else a
                if groups.get(other):
                    cross += m * (groups[other] != groups[p])
                    same += m * (groups[other] == groups[p])
        after = [d for d in pdays if d in days[burn_in_days:]]
        new = sum(1 for (a, b), d in first_day.items() if p in (a, b) and d in after)
        met = {}
        for d, a, b in sorted(ties):
            if p in (a, b) and d in mins:
                met.setdefault(b if p == a else a, d)
        n_g = sum(groups[q] == groups[p] for q in known)
        out[p] = {
            "strength_min_per_day": sum(mins.values()) / len(pdays),
            "cross_share": cross / (cross + same) if cross + same else None,
            "cross_share_expected": (len(known) - n_g) / (len(known) - 1),
            "new_ties": new,
            "days_after_burn_in": len(after),
            "new_partners": sum(d in after for d in met.values()),
            "partners": len(met),
        }
    return out, days


@pytest.mark.parametrize("min_minutes", [60, 700])
def test_close_contact_outcomes_match_the_synthetic_ground_truth(synthetic, min_minutes):
    """At 60 minutes the plenum ties every pair on the first day, so nothing is new later; at
    700 minutes only the pairs that also share a course room tie, and new ties appear."""
    camp, spine, contacts = synthetic
    tz, start = camp.spec.timezone, timedelta(hours=7, minutes=30)
    people_frame = spine.people_frame()
    groups = dict(zip(people_frame["entity"], people_frame["course"], strict=True))
    assert set(groups.values()) == {"course-a", "course-b"}

    def day_of(t_utc):
        return (t_utc.astimezone(ZoneInfo(tz)) - start).date()

    rules = {"min_bins": 12, "min_minutes": min_minutes, "burn_in_days": 1}
    expected, days = _oracle(camp, groups, day_of=day_of, **rules)
    assert len(days) >= 3 and len(expected) >= 10

    pairs = copresence(contacts, every="5m").with_columns(
        camp_day(pl.col("bin"), timezone=tz, day_start=start).alias("day")
    )
    seen = (
        pl.concat(
            [contacts.select(pl.col(c).alias("entity"), "t")
             for c in ("observer_entity", "observed_entity")]
        )
        .filter(pl.col("entity").str.starts_with("person:"))
        .with_columns(pl.col("t").dt.truncate("5m").alias("bin"))
        .with_columns(camp_day(pl.col("bin"), timezone=tz, day_start=start).alias("day"))
        .select("entity", "day", "bin")
        .unique()
    )  # fmt: skip
    got = close_contact_outcomes(
        daily_close_ties(pairs, close_rssi=-80, min_minutes=rules["min_minutes"], bin_minutes=5),
        present_days(seen, min_bins=rules["min_bins"]),
        people=sorted(expected),
        days=days,
        groups=groups,
        burn_in_days=rules["burn_in_days"],
    )
    assert got.height == len(expected)
    assert (sum(e["new_ties"] for e in expected.values()) > 0) == (min_minutes == 700)
    for row in got.iter_rows(named=True):
        want = expected[row["entity"]]
        for key, value in want.items():
            assert row[key] == pytest.approx(value), (row["entity"], key)
