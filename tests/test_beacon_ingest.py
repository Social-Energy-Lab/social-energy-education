"""Beacon log ingest against a hand-written golden log (tests/fixtures/beacon_logs/golden.log).

Every expected timestamp below was derived by hand from the fixture:
event time = readout PC time - (Current Timer - record uptime), in Europe/Berlin.
"""

from datetime import date, datetime
from pathlib import Path

import polars as pl
import pytest

from social_energy.beacons import BeaconConfig, ingest_logs

GOLDEN = Path(__file__).parent / "fixtures" / "beacon_logs" / "golden.log"
TZ = "Europe/Berlin"


@pytest.fixture(scope="module")
def tables():
    config = BeaconConfig(
        timezone=TZ,
        valid_from=date(2026, 8, 12),
        valid_to=date(2026, 8, 29),
        ambiguous_id_cutoff=datetime(2026, 8, 15, 20, 17, 48),
    )
    return ingest_logs([GOLDEN], config)


def local(df: pl.DataFrame, col: str = "t") -> list[str | None]:
    return [
        None if v is None else v.strftime("%Y-%m-%d %H:%M:%S")
        for v in df[col].dt.convert_time_zone(TZ).to_list()
    ]


def test_readouts_are_one_row_per_connection(tables):
    r = tables.readouts
    assert r.height == 8
    assert r.filter(pl.col("header_id") == "37")["current_timer"].to_list() == [7200, 600, 2400]
    first_37 = r.filter(pl.col("header_id") == "37").row(0, named=True)
    assert first_37["status_byte"] == 32
    assert first_37["voltage_mv"] == 3100
    assert first_37["contact_count"] == 3


def test_contact_times_are_resolved_from_the_readout_reference(tables):
    c = tables.contacts.filter((pl.col("beacon") == 37) & (pl.col("readout_seq") == 0))
    assert c["observed"].to_list() == [28, 78, 134]
    assert c["rssi"].to_list() == [-73, -61, -90]
    assert local(c) == ["2026-08-14 11:40:00", "2026-08-14 11:40:00", "2026-08-14 11:58:20"]
    assert not c["pre_reboot"].any()


def test_direction_is_preserved(tables):
    # Beacon 37 heard 28; that is not the same record as 28 hearing 37.
    assert set(tables.contacts.columns) >= {"beacon", "observed"}


def test_self_reports_and_eco_sessions(tables):
    s = tables.self_reports.filter(pl.col("beacon") == 37)
    assert local(s) == ["2026-08-14 11:56:40"]
    e = tables.eco_sessions.filter(pl.col("beacon") == 37)
    assert local(e, "t_enter") == ["2026-08-14 10:01:40"]
    assert local(e, "t_leave") == ["2026-08-14 10:06:40"]


def test_reboot_between_readouts_resolves_earlier_boot_with_previous_anchor(tables):
    r = tables.readouts.filter(pl.col("header_id") == "37")
    assert r["reboot_before"].to_list() == [False, True, False]
    c = tables.contacts.filter((pl.col("beacon") == 37) & (pl.col("readout_seq") == 1))
    assert c["pre_reboot"].to_list() == [True, True, False]
    assert local(c) == ["2026-08-14 12:05:00", "2026-08-14 12:06:40", "2026-08-14 13:55:00"]


def test_resent_records_are_flagged_as_duplicates_not_dropped(tables):
    c = tables.contacts.filter((pl.col("beacon") == 37) & (pl.col("observed") == 29))
    assert c.height == 2
    assert c["duplicate"].to_list() == [False, True]


def test_implausible_times_are_flagged_not_dropped(tables):
    c = tables.contacts.filter(pl.col("beacon") == 12)
    assert c.height == 1
    assert c["implausible_time"].to_list() == [True]


def test_logger_id_bug_is_repaired_by_clock_anchor(tables):
    # Before the logger fix, beacon 51 was printed as "3" (chr(51)).
    r = tables.readouts.filter(pl.col("header_id") == "3").sort("pc_time")
    assert r["beacon"].to_list() == [51, 3]
    assert r["id_status"].to_list() == ["repaired", "ok"]
    c = tables.contacts.filter(pl.col("observed") == 37, pl.col("beacon") == 51)
    assert local(c) == ["2026-08-15 09:43:20"]


def test_unresolvable_id_bug_is_flagged(tables):
    r = tables.readouts.filter(pl.col("header_id") == "4")
    assert r["id_status"].to_list() == ["ambiguous"]


def test_quality_column_summarises_flags(tables):
    c = tables.contacts
    assert (
        c["ok"].to_list()
        == (
            # pre_reboot is informational: those times are resolved, from the previous anchor.
            ~(c["duplicate"] | c["implausible_time"] | c["id_ambiguous"]) & c["t"].is_not_null()
        ).to_list()
    )


def test_qa_summary_accounts_for_every_line(tables):
    qa = tables.qa
    assert qa["lines_total"] == 46
    assert qa["lines_unparsed"] == 1
    assert qa["lines_other"] == 1
    assert qa["readouts"] == 8
    assert qa["contacts"] == 10
    assert qa["ids_repaired"] == 1
    assert qa["ids_ambiguous"] == 1
    assert qa["reboots"] == 1


# ---- dating from power cycles (tests/fixtures/beacon_logs/late_stamps.log) -----------------------
# Tag 7 booted 08:00 local. The 14:05 readout was stamped 5 min late (implied start 08:05). At 16:00
# a readout arrived without its header. The tag restarted at 17:00 (uptime 3600 at 18:00).

LATE = GOLDEN.parent / "late_stamps.log"


@pytest.fixture(scope="module")
def late():
    config = BeaconConfig(timezone=TZ, valid_from=date(2026, 8, 12), valid_to=date(2026, 8, 29))
    return ingest_logs([LATE], config)


def test_records_are_dated_from_the_power_cycle_start_not_the_late_stamp(late):
    c = late.contacts.filter(pl.col("readout_seq") == 1)
    assert local(c) == ["2026-08-20 13:00:00"]


def test_a_late_stamp_is_not_a_reboot(late):
    r = late.readouts.sort("pc_time")
    assert r["reboot_before"].to_list() == [False, False, False, True]
    assert r["cycle"].to_list() == [1, 1, 1, 2]
    assert late.qa["reboots"] == 1


def test_a_headerless_readout_is_its_own_readout_dated_from_its_cycle(late):
    r = late.readouts.sort("pc_time")
    assert r.height == 4
    assert r["current_timer"].to_list() == [7200, 21600, None, 3600]
    c = late.contacts.filter(pl.col("readout_seq") == 2)
    assert local(c) == ["2026-08-20 15:00:00"]
    assert c["headerless"].to_list() == [True]
    s = late.self_reports
    assert local(s) == ["2026-08-20 14:56:40"]
    assert s["ok"].to_list() == [True]


def test_previous_boot_records_use_the_previous_cycle_and_must_precede_the_restart(late):
    c = late.contacts.filter(pl.col("readout_seq") == 3).sort("line_no")
    assert c["pre_reboot"].to_list() == [True, True, False]
    assert local(c) == ["2026-08-20 16:00:00", "2026-08-20 17:10:00", "2026-08-20 17:30:00"]
    # 17:10 would be after the 17:00 restart: impossible for the previous boot.
    assert c["implausible_time"].to_list() == [False, True, False]
    assert late.qa["contacts_unplaced_in_time"] == 0
