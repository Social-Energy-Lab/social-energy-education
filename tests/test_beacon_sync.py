"""Uptime periods from the shape of the implied boots, and boots checked against partners.

Implied boot = stamp - uptime. Stamps can only be late, so within one period the boot is the lower
edge of the implied boots: it never rises unless the tag's uptime really fell behind. Expectations
are worked out by hand in each test. All values are made up.
"""

from datetime import UTC, datetime, timedelta

import numpy as np
import polars as pl
import pytest

from social_energy.beacons.sync import apply_boots, change_point, mirror_lag, uptime_periods


def at(hh: int, mm: int = 0, day: int = 14) -> datetime:
    return datetime(2026, 8, day, hh, mm, tzinfo=UTC)


def anchors(rows: list[tuple]) -> pl.DataFrame:
    """Rows of (ts, timer) or (ts, timer, oldest) for one tag, keyed r0, r1, ..."""
    return pl.DataFrame(
        [
            {
                "readout_key": f"r{i}",
                "beacon": 1,
                "ts": r[0],
                "timer": r[1],
                "oldest": r[2] if len(r) > 2 else None,
            }
            for i, r in enumerate(rows)
        ],
        schema={
            "readout_key": pl.String,
            "beacon": pl.Int64,
            "ts": pl.Datetime("us", "UTC"),
            "timer": pl.Int64,
            "oldest": pl.Int64,
        },
    )


def test_a_late_stamp_hours_long_is_not_a_reboot():
    # Boot 08:00. The 14:00 readout says 7200 s more than 10:00 would allow only if stamped 4 h
    # late: implied 12:00. The 18:00 readout implies 08:00 again, so the edge never rose.
    p = uptime_periods(anchors([(at(10), 7200), (at(14), 7200), (at(18), 36000)]), step_s=120)
    assert p["period"].to_list() == [1, 1, 1]
    assert p["boot"].to_list() == [at(8)] * 3


def test_a_small_lasting_step_starts_a_period_though_it_is_under_an_hour():
    # Boot 08:00 at 10:00. Then implied 08:40 at both 14:00 and 18:00: 40 min behind for good.
    # The old one-hour margin kept this in one period and dated all of it 40 min early.
    p = uptime_periods(
        anchors([(at(10), 7200), (at(14), 19200, 100), (at(18), 33600, 19200)]), step_s=120
    )
    assert p["period"].to_list() == [1, 2, 2]
    assert p["boot"].to_list() == [at(8), at(8, 40), at(8, 40)]
    assert p["evidence"].to_list() == ["first", "fresh_records", None]


def test_a_smaller_timer_is_a_reboot_whatever_the_step():
    # 60 s of uptime at 10:00, 50 s at 10:10. The edge rises by less than this large step, but a
    # timer that falls is proof whatever the step.
    p = uptime_periods(anchors([(at(10), 60), (at(10, 10), 50)]), step_s=1200)
    assert p["period"].to_list() == [1, 2]
    assert p["evidence"].to_list() == ["first", "timer_back"]


def test_a_small_fall_with_the_same_boot_is_two_readouts_out_of_order():
    # 7200 s then 7190 s, 5 s apart: implied boots 15 s apart. A reboot needs more than that.
    p = uptime_periods(anchors([(at(10), 7200), (at(10) + timedelta(seconds=5), 7190)]))
    assert p["period"].to_list() == [1, 1]


def test_a_step_whose_records_continue_is_marked_for_the_partners_to_settle():
    # Implied rises from 08:00 to 10:00 and stays, but the oldest record (7300) continues the
    # previous timer (7200): nothing was wiped, so no reboot shows in the records. Late stamps with
    # no clean readout after them, or a timer step: only partners can tell.
    p = uptime_periods(
        anchors([(at(10), 7200), (at(14), 14400, 7300), (at(18), 28800, 14500)]), step_s=120
    )
    assert p["period"].to_list() == [1, 2, 2]
    assert p["evidence"].to_list() == ["first", "continues", None]


def test_records_older_than_the_previous_timer_are_fresh_only_by_the_margin():
    # Oldest 7100 is 100 s under the previous timer: inside the margin, so it continues.
    p = uptime_periods(
        anchors([(at(10), 7200), (at(14), 14400, 7100)]), step_s=120, fresh_margin_s=300
    )
    assert p["evidence"].to_list() == ["first", "continues"]


def test_drift_is_taken_out_before_the_edge_is_read():
    # A counter 1000 ppm fast: 86400 real seconds count 86486.4. Without the correction the implied
    # boot would sink by 86 s; with it both readouts imply the same boot, within rounding.
    p = uptime_periods(
        anchors([(at(10), 0), (at(10, day=15), 86486)]), step_s=30, clock_rate_ppm=1000
    )
    assert p["period"].to_list() == [1, 1]
    assert abs((p["boot"][1] - at(10)).total_seconds()) < 1


def test_tags_are_kept_apart():
    a = anchors([(at(10), 7200)])
    b = a.with_columns(pl.lit(2).cast(pl.Int64).alias("beacon"), pl.lit("x").alias("readout_key"))
    p = uptime_periods(pl.concat([a, b]), step_s=120)
    assert p.sort("beacon")["period"].to_list() == [1, 1]


def test_records_starting_well_after_the_previous_timer_leave_a_gap():
    # Oldest 12000 against a previous timer of 7200: 80 min of records went missing in between. A
    # readout vanished, and the tag may or may not have rebooted before it did.
    p = uptime_periods(
        anchors([(at(10), 7200), (at(14), 14400, 12000)]), step_s=120, continuity_s=1800
    )
    assert p["evidence"].to_list() == ["first", "gap"]


def bins(rng: np.random.Generator, n: int) -> np.ndarray:
    """A made-up on/off pattern: bursts of contact at random bins."""
    x = np.zeros(n, dtype=bool)
    for s in rng.integers(0, n - 40, 60):
        x[s : s + int(rng.integers(5, 40))] = True
    return np.flatnonzero(x)


def test_mirror_lag_recovers_a_known_offset_in_bins():
    rng = np.random.default_rng(1)
    partners = {k: bins(rng, 3000) for k in range(12)}
    own = {k: v + 37 for k, v in partners.items()}
    r = mirror_lag(own, partners, max_lag=200, seed=1)
    assert r["lag"] == 37
    assert r["lag_a"] == 37 and r["lag_b"] == 37
    assert r["partners"] == 12


def test_mirror_lag_is_not_fooled_by_contact_that_never_stops():
    # Nearest-record matching would find offset zero here: both sides have a record at nearly every
    # moment. Only the edges of the long stay carry the offset, and they do carry it.
    partners = {k: np.arange(500 + k * 7, 2500 - k * 11) for k in range(8)}
    own = {k: v + 90 for k, v in partners.items()}
    assert mirror_lag(own, partners, max_lag=200, seed=1)["lag"] == 90


def test_mirror_lag_halves_disagree_on_noise_and_nothing_shared_gives_no_lag():
    rng = np.random.default_rng(2)
    own = {k: bins(rng, 3000) for k in range(12)}
    partners = {k: bins(rng, 3000) for k in range(12)}
    r = mirror_lag(own, partners, max_lag=200, seed=1)
    assert abs(r["lag_a"] - r["lag_b"]) > 10
    empty = mirror_lag({}, {}, max_lag=200, seed=1)
    assert empty["partners"] == 0 and empty["lag"] is None


def test_apply_boots_moves_a_period_only_earlier_and_merges_what_then_joins():
    # Period 2 was a run of late stamps: 2 h late. Partners say lag 7200, which lands its boot on
    # period 1's boot, so the two are one period and the step never happened.
    p = uptime_periods(
        anchors([(at(10), 7200), (at(14), 14400, 7300), (at(18), 28800, 14500)]), step_s=120
    )
    fitted = apply_boots(
        p,
        pl.DataFrame(
            {"beacon": [1], "period": [2], "lag_s": [7200.0], "settled": [True]},
            schema={
                "beacon": pl.Int64,
                "period": pl.Int64,
                "lag_s": pl.Float64,
                "settled": pl.Boolean,
            },
        ),
        merge_s=300,
    )
    assert fitted["period"].to_list() == [1, 1, 1]
    assert fitted["boot"].to_list() == [at(8)] * 3


def test_apply_boots_keeps_a_timer_step_as_its_own_period():
    # Boots 08:00 and 11:46:40. Partners move the second by 2 h to 09:46:40, still far from 08:00,
    # and its records continue: the tag's clock really moved.
    p = uptime_periods(anchors([(at(10), 7200), (at(14), 8000, 7300)]), step_s=120)
    fitted = apply_boots(
        p,
        pl.DataFrame(
            {"beacon": [1], "period": [2], "lag_s": [7200.0], "settled": [True]},
            schema={
                "beacon": pl.Int64,
                "period": pl.Int64,
                "lag_s": pl.Float64,
                "settled": pl.Boolean,
            },
        ),
        merge_s=300,
    )
    assert fitted["period"].to_list() == [1, 2]
    assert fitted["evidence"].to_list() == ["first", "timer_step"]
    assert fitted["boot"][1] == p["boot"][1] - timedelta(seconds=7200)


def test_change_point_finds_where_the_clock_switched():
    # First four records agree under the early clock, the last three under the late one.
    early = np.array([1, 1, 1, 1, 0, 0, 0])
    late = np.array([0, 0, 0, 0, 1, 1, 1])
    assert change_point(early, late) == (4, 7)
    # All agree under one clock: the split sits at the end, no records on the other.
    assert change_point(np.ones(5, dtype=int), np.zeros(5, dtype=int)) == (5, 5)
    assert change_point(np.zeros(5, dtype=int), np.ones(5, dtype=int)) == (0, 5)


def no_lags() -> pl.DataFrame:
    return pl.DataFrame(
        schema={"beacon": pl.Int64, "period": pl.Int64, "lag_s": pl.Float64, "settled": pl.Boolean}
    )


def test_apply_boots_joins_records_that_continue_when_partners_cannot_tell():
    # Records continue and the rise is 2 h, within what a logger pause can do: same period.
    p = uptime_periods(anchors([(at(10), 7200), (at(14), 14400, 7300)]), step_s=120)
    fitted = apply_boots(p, no_lags(), merge_s=300, max_delay_s=21600)
    assert fitted["period"].to_list() == [1, 1]
    assert fitted["boot"].to_list() == [at(8)] * 2


def test_apply_boots_does_not_join_a_rise_no_logger_pause_could_make():
    # Rise of 8 h against a longest pause of 6 h: not late stamps, whatever the records say.
    p = uptime_periods(anchors([(at(10), 7200), (at(18), 7300, 7250)]), step_s=120)
    fitted = apply_boots(p, no_lags(), merge_s=300, max_delay_s=21600)
    assert fitted["period"].to_list() == [1, 2]


def test_apply_boots_leaves_a_gap_apart_unless_partners_land_it():
    # A gap with no verdict stays its own period, dated from its edge.
    p = uptime_periods(anchors([(at(10), 7200), (at(14), 14400, 12000)]), step_s=120)
    fitted = apply_boots(p, no_lags(), merge_s=300, max_delay_s=21600)
    assert fitted["period"].to_list() == [1, 2]
    assert fitted["evidence"].to_list() == ["first", "gap"]


@pytest.mark.parametrize("lag", [-600.0, 7200.0])
def test_apply_boots_ignores_unsettled_and_never_moves_a_boot_later(lag):
    # Stamps can only be late, so a negative lag is the partner's error, not this tag's. Unsettled
    # lags (the 7200 here) are not used at all.
    p = uptime_periods(anchors([(at(10), 7200)]), step_s=120)
    fitted = apply_boots(
        p,
        pl.DataFrame(
            {"beacon": [1], "period": [1], "lag_s": [lag], "settled": [lag < 0]},
            schema={
                "beacon": pl.Int64,
                "period": pl.Int64,
                "lag_s": pl.Float64,
                "settled": pl.Boolean,
            },
        ),
        merge_s=300,
    )
    assert fitted["boot"].to_list() == [at(8)]


def test_oracle_late_periods_and_a_small_step_come_out_on_the_true_times(tmp_path):
    """Logs written from known truth; the ingest must recover the truth, not the stamps.

    Eight tags share bursts of contact over two days. All boot at 2026-08-14 06:00 UTC, except that
    tag 1 reboots at 15 Aug 06:00 and tag 2's clock falls 30 min behind at 15 Aug 06:00 with no
    reboot. Tag 3 reboots at 15 Aug 12:00 and every readout after that is stamped 3 h late, so no
    clean readout shows its boot. Tag 5's clock falls 2 h behind at 15 Aug 00:00, between two
    readouts, so one readout holds records from both sides of the step. Every other readout is
    clean.
    """
    from datetime import date

    from social_energy.beacons import BeaconConfig
    from social_energy.beacons.sync import ingest_with_sync

    rng = np.random.default_rng(7)
    t0 = datetime(2026, 8, 14, 6, tzinfo=UTC)
    minutes = 48 * 60
    on = {}
    tags = list(range(1, 9))
    for a in tags:
        for b in tags:
            if a < b:
                m = np.zeros(minutes, dtype=bool)
                for s in rng.integers(0, minutes - 60, 25):
                    m[s : s + int(rng.integers(5, 45))] = True
                on[(a, b)] = np.flatnonzero(m)

    def boot_of(tag: int, minute: int) -> int:
        """Minute since t0 at which this tag's current uptime began."""
        if tag == 1 and minute >= 24 * 60:
            return 24 * 60
        if tag == 3 and minute >= 30 * 60:
            return 30 * 60
        if tag == 2 and minute >= 24 * 60:
            return 30
        if tag == 5 and minute >= 18 * 60:
            return 120
        return 0

    reads = [12 * 60, 24 * 60 - 5, 30 * 60 - 5, 36 * 60, 42 * 60, 48 * 60 - 1]
    lines = []
    for tag in tags:
        last = -1
        for read in reads:
            late = 180 if tag == 3 and read > 30 * 60 else 0
            stamp = t0 + timedelta(minutes=read + late)
            stamp_s = stamp.strftime("%Y-%m-%d %H:%M:%S")
            uptime = (read - boot_of(tag, read)) * 60
            block = [f"{stamp_s},ID: {tag},Current Timer: {uptime}"]
            for (a, b), minutes_on in on.items():
                if tag not in (a, b):
                    continue
                other = b if tag == a else a
                for m in minutes_on[(minutes_on > last) & (minutes_on <= read)]:
                    if tag in (1, 3) and boot_of(tag, m) != boot_of(tag, read):
                        continue  # the reboot wiped it
                    u = (int(m) - boot_of(tag, int(m))) * 60
                    block.append(f"{stamp_s},ID: {tag},ID2: {other}, Timer: {u}, RSSI: -60")
            head, rest = (
                block[0],
                sorted(block[1:], key=lambda x: int(x.split("Timer: ")[1].split(",")[0])),
            )
            lines.append((stamp, [head, *rest]))
            last = read
    lines.sort(key=lambda x: x[0])
    log = tmp_path / "camp.log"
    log.write_text("\n".join(x for _, b in lines for x in b) + "\n", encoding="utf-8")
    config = BeaconConfig(timezone="UTC", valid_from=date(2026, 8, 13), valid_to=date(2026, 8, 17))
    out = tmp_path / "beacons"
    ingest_with_sync([log], config, out, window=(t0, t0 + timedelta(hours=48)))

    periods = pl.read_parquet(out / "uptime_periods.parquet")
    boots = lambda tag: sorted(  # noqa: E731
        periods.filter(pl.col("beacon") == tag)["boot"].unique().to_list()
    )
    assert boots(1) == [t0, t0 + timedelta(hours=24)]
    assert boots(4) == [t0]
    # Tag 2's clock moved 30 min with no reboot: under the old one-hour margin it stayed one period.
    assert boots(2)[0] == t0
    assert abs((boots(2)[1] - (t0 + timedelta(minutes=30))).total_seconds()) <= 90
    # All of tag 3's last period was 3 h late, and only partners can bring it to the truth.
    found = boots(3)
    assert abs((found[1] - (t0 + timedelta(hours=30))).total_seconds()) <= 90
    contacts = pl.read_parquet(out / "contacts" / "*.parquet").filter(pl.col("beacon") == 3)
    assert contacts.height > 0
    # Tag 5's records land on the truth on both sides of the step inside one readout.
    truth = {int((t0 + timedelta(minutes=int(m))).timestamp()) for m in on[(4, 5)]}
    five = pl.read_parquet(out / "contacts" / "*.parquet").filter(
        (pl.col("beacon") == 5) & (pl.col("observed") == 4)
    )
    stamps = [int(x.timestamp()) for x in five["t"].to_list()]
    hits = sum(x // 60 * 60 in truth or x // 60 * 60 + 60 in truth for x in stamps)
    assert hits / len(stamps) >= 0.98
    steps = pl.read_parquet(out / "timer_steps.parquet")
    assert steps["beacon"].to_list() == [5]
    # Every contact of tag 4, which never moved, sits on a whole minute of the truth.
    four = pl.read_parquet(out / "contacts" / "*.parquet").filter(pl.col("beacon") == 4)
    assert four["t"].dt.second().unique().to_list() == [0]
