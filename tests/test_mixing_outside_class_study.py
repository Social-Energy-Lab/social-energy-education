"""The DSA 2026 mixing-outside-class script's own wiring, on invented rows."""

import importlib.util
import sys
from datetime import UTC, date, datetime
from pathlib import Path

import polars as pl
import pytest

ANALYSES = Path(__file__).resolve().parents[1] / "studies" / "dsa-2026" / "analyses"


@pytest.fixture(scope="module")
def m():
    sys.path.insert(0, str(ANALYSES))
    spec = importlib.util.spec_from_file_location(
        "mixing_outside_class_script", ANALYSES / "exploratory_mixing_outside_class.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def utc(month, day, hour, minute=0):
    return datetime(2026, month, day, hour, minute, tzinfo=UTC)


def test_course_windows_take_the_day_s_own_timetable(m):
    hours = {
        "default": [["09:00", "12:15"], ["16:30", "18:30"]],
        "exceptions": {date(2026, 8, 2): [["14:00", "16:00"]], "2026-08-03": []},
    }
    windows = m.course_windows([date(2026, 8, d) for d in (1, 2, 3)], hours, "Europe/Berlin")
    # Berlin in August is UTC+2. The 1st has both blocks, the 2nd its own, the 3rd none.
    assert windows == [
        (utc(8, 1, 7), utc(8, 1, 10, 15)),
        (utc(8, 1, 14, 30), utc(8, 1, 16, 30)),
        (utc(8, 2, 12), utc(8, 2, 14)),
    ]


def test_in_windows_includes_the_start_and_not_the_end(m):
    t = pl.DataFrame({"bin": [utc(8, 1, 6, 55), utc(8, 1, 7), utc(8, 1, 10, 15)]})
    window = [(utc(8, 1, 7), utc(8, 1, 10, 15))]
    assert t.select(m.in_windows("bin", window).alias("x"))["x"].to_list() == [False, True, False]


ROSTER = """Some text

| Study-ID | Kurs | Zimmer |
|---|---|---|
| 1 | a | 3 |
| 2 | b | 3 |
| 3 | a | 4 |
| OTHER9 | a | 4 |
| 4 | a | --- |

Between lists

| Study-ID | Teilnehmer::RKurs | Zimmer | Bemerkung |
|---|---|---|---|
| 5 | a | 3 | |
| 6 | b | 9 | |
"""


def test_sleeping_rooms_keep_lists_apart_and_skip_what_is_not_numeric(m):
    assert m.sleeping_rooms(ROSTER) == {
        "person:1": (1, 3),
        "person:2": (1, 3),
        "person:3": (1, 4),
        "person:5": (2, 3),
        "person:6": (2, 9),
    }


def test_room_pairs_find_roommates_and_with_adjacent_next_door_only_in_the_same_list(m):
    rooms = m.sleeping_rooms(ROSTER)
    pairs = pl.DataFrame(
        {
            "a": ["person:1", "person:1", "person:1", "person:5", "person:4"],
            "b": ["person:2", "person:3", "person:5", "person:6", "person:1"],
        }
    )
    same = pairs.select(m.room_pairs(rooms).alias("x"))["x"].to_list()
    # 1-2 share room 3. 1-3 are next door. 1-5 have the same number in different lists.
    assert same == [True, False, False, False, False]
    near = pairs.select(m.room_pairs(rooms, adjacent=True).alias("x"))["x"].to_list()
    assert near == [True, True, False, False, False]


def test_exposures_split_the_bins_as_named(m):
    rooms = {"person:1": (1, 3), "person:2": (1, 3), "person:3": (1, 4)}
    bins = [
        ("person:1", "person:3", utc(8, 1, 8)),  # class
        ("person:1", "person:4", utc(8, 1, 12)),  # free time, no known room
        ("person:1", "person:2", utc(8, 1, 12)),  # roommates
        ("person:2", "person:3", utc(8, 1, 12)),  # next door
        ("person:1", "person:4", utc(8, 1, 2)),  # 04:00 local, night
    ]
    pairs = pl.DataFrame(bins, schema=["a", "b", "bin"], orient="row")
    kept = m.exposures(pairs, [(utc(8, 1, 7), utc(8, 1, 10))], rooms, "Europe/Berlin")
    assert {k: v.height for k, v in kept.items()} == {
        "all_day": 5,
        "class_only": 1,
        "no_class": 4,
        "no_class_no_night": 3,
        "no_class_no_room": 3,
        "no_class_no_neighbours": 2,
    }
