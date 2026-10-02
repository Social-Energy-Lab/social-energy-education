"""Power cycles and lost windows from the readouts' clock anchors.

Expectations are derived by hand: implied start = readout PC time - Current Timer; a restart is
an anchor whose uptime falls more than the margin behind the wall time elapsed since the previous
anchor of the same tag.
"""

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import polars as pl

from social_energy.beacons import lost_windows, power_cycles, read_clock_anchors, read_deliveries

GOLDEN = Path(__file__).parent / "fixtures" / "beacon_logs" / "golden.log"
TZ = "Europe/Berlin"
UTC = ZoneInfo("UTC")


def at(hh: int, mm: int = 0, ss: int = 0, day: int = 14) -> datetime:
    return datetime(2026, 8, day, hh, mm, ss, tzinfo=UTC)


def anchors(rows: list[tuple[int, datetime, int]]) -> pl.DataFrame:
    return pl.DataFrame(
        rows,
        schema={"beacon": pl.Int64, "ts": pl.Datetime("us", "UTC"), "timer": pl.Int64},
        orient="row",
    )


def test_stamps_within_one_cycle_share_the_earliest_start():
    # Booted at 08:00. The second readout was stamped 4 min late (implied 08:04).
    c = power_cycles(anchors([(1, at(10), 7200), (1, at(14, 4), 21600)]), restart_margin_s=3600)
    assert c["cycle"].to_list() == [1, 1]
    assert c["restart"].to_list() == [False, False]
    assert c["cycle_start"].to_list() == [at(8), at(8)]
    assert c["delay_s"].to_list() == [0, 240]


def test_a_restart_starts_a_new_cycle_and_wipes_since_the_last_readout():
    # Readout at 10:00 (booted 08:00), restarted at 12:00 (uptime 1 h at 13:00).
    c = power_cycles(
        anchors([(1, at(10), 7200), (1, at(13), 3600), (1, at(15), 10800)]),
        restart_margin_s=3600,
    )
    assert c["restart"].to_list() == [False, True, False]
    assert c["cycle"].to_list() == [1, 2, 2]
    assert c["cycle_start"].to_list() == [at(8), at(12), at(12)]
    w = lost_windows(c)
    assert w.rows() == [(1, at(10), at(12))]


def test_drift_below_the_margin_is_not_a_restart():
    # Uptime 50 min behind the wall clock: a late stamp, not a restart.
    c = power_cycles(anchors([(1, at(10), 7200), (1, at(13), 15000)]), restart_margin_s=3600)
    assert not c["restart"].any()
    assert lost_windows(c).height == 0


def test_the_lost_window_ends_at_the_restart_and_never_before_the_last_readout():
    c = power_cycles(anchors([(1, at(10), 7200), (1, at(16), 100)]), restart_margin_s=3600)
    assert c["restart"].to_list() == [False, True]
    assert lost_windows(c).rows() == [(1, at(10), at(15, 58, 20))]
    # Implied boot 09:36:40 lies before the 10:00 readout (a late stamp): nothing measurable lost.
    c = power_cycles(anchors([(1, at(10), 7200), (1, at(11), 5000)]), restart_margin_s=3600)
    assert c["restart"].to_list() == [False, True]
    assert lost_windows(c).height == 0


def test_tags_are_kept_apart():
    c = power_cycles(
        anchors([(1, at(10), 7200), (2, at(11), 600), (1, at(12), 14400)]),
        restart_margin_s=3600,
    )
    assert c.filter(pl.col("beacon") == 1)["cycle"].to_list() == [1, 1]
    assert not c["restart"].any()


def test_anchors_from_the_golden_log():
    a = read_clock_anchors([GOLDEN], TZ)
    tag37 = a.filter(pl.col("beacon") == 37)
    assert tag37["timer"].to_list() == [7200, 600, 2400]
    # 12:00 Berlin (CEST) is 10:00 UTC.
    assert tag37["ts"][0] == at(10)
    c = power_cycles(a, restart_margin_s=3600).filter(pl.col("beacon") == 37)
    assert c["restart"].to_list() == [False, True, False]
    # Rebooted 13:50 local: 14:00 - 600 s, confirmed by 14:30 - 2400 s.
    assert c["cycle_start"].to_list()[1:] == [at(11, 50), at(11, 50)]
    w = lost_windows(c)
    assert w.rows() == [(37, at(10), at(11, 50))]


HEADERLESS = GOLDEN.parent / "headerless.log"


def test_deliveries_are_readout_lines_that_carry_records():
    d = read_deliveries([HEADERLESS], TZ)
    # 12:00 (contact), 18:00 (headerless contact + press), 09:00 next day (eco); the lone Status
    # at 20:00 delivered nothing and the malformed ID is skipped. Berlin is UTC+2.
    assert d.sort("ts").rows() == [(7, at(10, day=20)), (7, at(16, day=20)), (7, at(7, day=21))]


def test_a_readout_without_anchor_shortens_the_lost_window():
    c = power_cycles(read_clock_anchors([HEADERLESS], TZ), restart_margin_s=3600)
    # Booted 00:00 UTC on 20 Aug, restarted 06:00 UTC on 21 Aug (09:00 local - 3600 s).
    assert lost_windows(c).rows() == [(7, at(10, day=20), at(6, day=21))]
    d = read_deliveries([HEADERLESS], TZ)
    assert lost_windows(c, d).rows() == [(7, at(16, day=20), at(6, day=21))]


def test_deliveries_after_the_restart_do_not_count():
    c = power_cycles(anchors([(1, at(10), 7200), (1, at(16), 3600)]), restart_margin_s=3600)
    d = anchors([(1, at(15, 30), 0), (1, at(12), 0), (1, at(11), 0)]).select("beacon", "ts")
    # Restart at 15:00; the latest delivery before it wins, and 15:30 belongs to the new boot.
    assert lost_windows(c, d).rows() == [(1, at(12), at(15))]
