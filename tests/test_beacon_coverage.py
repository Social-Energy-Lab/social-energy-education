"""What each tag-hour holds: its own records, or why not.

Tag 1 boots at 08:00, is read at 12:00 with records from 08:00 to 09:00 and from 11:00 to 12:00 (so
the 09:00 and 10:00 hours are holes: a readout vanished), then reboots at 15:00 (12:00 to 14:00 were
erased), runs on and is never read again. Hours are UTC on 2026-08-14. All values are made up.
"""

from datetime import UTC, datetime

import polars as pl

from social_energy.beacons.coverage import coverage_by_hour


def at(h: int, m: int = 0) -> datetime:
    return datetime(2026, 8, 14, h, m, tzinfo=UTC)


def table(rows, schema):
    return pl.DataFrame(rows, schema=schema, orient="row")


CONTACT = {
    "beacon": pl.Int64,
    "observed": pl.Int64,
    "t": pl.Datetime("us", "UTC"),
    "ok": pl.Boolean,
}
PERIOD = {"beacon": pl.Int64, "period": pl.Int64, "boot": pl.Datetime("us", "UTC")}
ECO = {"beacon": pl.Int64, "t_enter": pl.Datetime("us", "UTC"), "t_leave": pl.Datetime("us", "UTC"),
       "ok": pl.Boolean}  # fmt: skip


def result(eco=()):
    contacts = table(
        [
            (1, 2, at(8, 30), True),
            (1, 2, at(11, 30), True),
            (1, 2, at(10, 30), False),  # not ok: does not count as a record
            (2, 1, at(10, 30), True),  # tag 2 heard tag 1 in a hole
            (2, 1, at(13, 30), True),
        ],
        CONTACT,
    )
    periods = table([(1, 1, at(8)), (1, 2, at(15))], PERIOD)
    out = coverage_by_hour(
        contacts, periods, table(list(eco), ECO), window=(at(7), at(17)), beacons=[1]
    )
    return {r["hour"].hour: r for r in out.iter_rows(named=True)}


def test_each_hour_gets_the_state_that_explains_it():
    r = result()
    assert [r[h]["state"] for h in range(7, 17)] == [
        "before_first_boot",
        "recorded",
        "not_logged",
        "not_logged",
        "recorded",
        "erased_by_reboot",
        "erased_by_reboot",
        "erased_by_reboot",
        "not_read_out",
        "not_read_out",
    ]


def test_heard_says_whether_a_partner_placed_the_tag_there():
    r = result()
    assert r[10]["heard"] and r[13]["heard"]
    assert not r[9]["heard"] and not r[14]["heard"]


def test_an_hour_overlapping_an_eco_session_is_recorded_eco():
    r = result(eco=[(1, at(11, 10), at(11, 50), True)])
    assert r[11]["state"] == "recorded_eco"
    assert r[8]["state"] == "recorded"
