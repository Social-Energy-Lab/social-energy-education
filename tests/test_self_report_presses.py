"""Self-report presses → episodes, with long accidental runs (a tag pressed in a bag) removed.

Each case is written by hand: seconds after a fixed start, per person.
"""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import polars as pl

from social_energy.beacons import press_episodes

T0 = datetime(2026, 8, 14, 10, 0, 0, tzinfo=ZoneInfo("UTC"))
RULES = {"chain_s": 20, "accidental_s": 60, "accidental_n": 8, "episode_s": 60}


def presses(rows: list[tuple[str, int]]) -> pl.DataFrame:
    return pl.DataFrame(
        [(e, T0 + timedelta(seconds=s)) for e, s in rows],
        schema={"entity": pl.String, "t": pl.Datetime("us", "UTC")},
        orient="row",
    )


def secs(df: pl.DataFrame) -> list[tuple[str, int, int]]:
    return sorted(
        (e, int((t - T0).total_seconds()), n)
        for e, t, n in df.select("entity", "t", "raw_presses").iter_rows()
    )


def test_a_held_press_is_one_episode():
    ep, qa = press_episodes(presses([("a", 0), ("a", 5), ("a", 11)]), **RULES)
    assert secs(ep) == [("a", 0, 3)]
    assert qa == {"accidental_chains": 0, "accidental_presses": 0, "episodes": 1, "pressers": 1}


def test_presses_a_minute_apart_are_separate_episodes():
    ep, _ = press_episodes(presses([("a", 0), ("a", 59), ("a", 119)]), **RULES)
    # 0 and 59 merge (59 < 60); 119 is 60 s after 59 and opens a new episode.
    assert secs(ep) == [("a", 0, 2), ("a", 119, 1)]


def test_a_long_run_is_accidental_and_dropped():
    # 7 presses 10 s apart: one chain lasting exactly 60 s, under the count limit.
    run = [("a", s) for s in range(0, 70, 10)]
    ep, qa = press_episodes(presses([*run, ("a", 300)]), **RULES)
    assert secs(ep) == [("a", 300, 1)]
    assert qa["accidental_chains"] == 1
    assert qa["accidental_presses"] == 7
    # One press shorter and the run is a held press: one episode.
    ep, _ = press_episodes(presses(run[:-1]), **RULES)
    assert secs(ep) == [("a", 0, 6)]


def test_many_quick_presses_are_accidental_even_if_short():
    run = [("a", s) for s in range(0, 40, 5)]  # 8 presses in 35 s
    ep, qa = press_episodes(presses(run), **RULES)
    assert ep.height == 0
    assert qa["accidental_presses"] == 8


def test_a_gap_over_the_chain_limit_breaks_the_run():
    # 0, 15, 30 | 55, 70, 85: two chains of 30 s each, neither accidental; one episode.
    rows = [("a", s) for s in (0, 15, 30, 55, 70, 85)]
    ep, qa = press_episodes(presses(rows), **RULES)
    assert qa["accidental_chains"] == 0
    assert secs(ep) == [("a", 0, 6)]


def test_people_are_kept_apart():
    ep, qa = press_episodes(presses([("a", 0), ("b", 10), ("a", 30)]), **RULES)
    assert secs(ep) == [("a", 0, 2), ("b", 10, 1)]
    assert qa["pressers"] == 2
