"""Written descriptions of self-report moments: the card's ID and when-text read, flagged.

Golden: hand-written rows in the shapes the transcribed cards take (made-up text), with
hand-derived dates, clocks and flags.
"""

from datetime import date, time

import polars as pl
import pytest

from social_energy.beacons.descriptions import parse_descriptions, parse_when

FIRST, LAST = date(2026, 8, 13), date(2026, 8, 29)


@pytest.mark.parametrize(
    ("when", "day", "clock", "flags"),
    [
        ("21.08.2026", date(2026, 8, 21), None, set()),
        ("18.08.", date(2026, 8, 18), None, set()),
        ("20.08.2026 um 14:05 Uhr", date(2026, 8, 20), time(14, 5), set()),
        ("19.08.2026; 15-16 Uhr", date(2026, 8, 19), time(15, 0), set()),
        ("17.08.2026 (22-0 Uhr)", date(2026, 8, 17), time(22, 0), set()),
        ("16.08.2026 (1:15 Uhr hall)", date(2026, 8, 16), time(1, 15), set()),
        ("22.08.2026 ca. 9-10:30 Uhr", date(2026, 8, 22), time(9, 0), set()),
        ("20.-21.08.", date(2026, 8, 20), None, {"date_range"}),
        ("14./15.08.2026", date(2026, 8, 14), None, {"date_range"}),
        ("16.-18.08.2026 (early on)", date(2026, 8, 16), None, {"date_range"}),
        ("23.08.2026 (und weitere)", date(2026, 8, 23), None, {"date_range"}),
        ("24.08.2026 (?)", date(2026, 8, 24), None, {"uncertain"}),
        ("12.07.2026", None, None, {"implausible_date"}),  # outside the study
        ("Abendkonzert", None, None, {"no_date"}),
        ("keine Angabe", None, None, {"no_date"}),
        (None, None, None, {"no_date"}),
    ],
)
def test_parse_when(when, day, clock, flags):
    got = parse_when(when, year=2026, first_day=FIRST, last_day=LAST)
    assert (got.day, got.clock, got.flags) == (day, clock, flags)


def test_parse_descriptions_flags_and_accounts_for_every_row():
    raw = pl.DataFrame(
        {
            "id": ["5", "no ID", None, "keine ID", "7", " 12 ", "8"],
            "when": ["21.08.2026", "no time", "14.08.2026", "28.08.2026", "Konzert",
                     "20.08.2026 um 14:05 Uhr", None],
            "text": ['"a made-up moment"', "made up", "made up", "made up", "  ", "x", None],
        }
    )  # fmt: skip
    df, qa = parse_descriptions(raw, year=2026, first_day=FIRST, last_day=LAST)
    assert df.height == raw.height  # flag, don't drop
    assert df["study_id"].to_list() == ["5", None, None, None, "7", "12", "8"]
    assert df["no_id"].to_list() == [False, True, True, True, False, False, False]
    assert df["empty"].to_list() == [False, False, False, False, True, False, True]
    assert df["text"][0] == "a made-up moment"  # the transcriber's outer quotes removed
    assert df["ok"].to_list() == [True, False, False, False, False, True, False]
    assert df["clock"][5] == time(14, 5)
    assert qa == {"rows": 7, "ok": 2, "no_id": 3, "empty": 2, "dated": 4, "timed": 1}
