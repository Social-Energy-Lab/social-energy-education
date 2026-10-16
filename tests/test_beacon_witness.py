"""Witness repair of the logger ID bug: partners' ID2 values decide between ``n`` and ``n + 48``.

Hand-built tables, times in UTC on 2026-08-14. The ambiguous readout ``A`` was printed as "3", so
it came from tag 3 or tag 51. It heard tags 20, 21 and 22 at 10:00, 10:10 and 10:20 (its own
clock). Tags 20 and 21 recorded tag 51 within a minute of each of those times; tag 22 recorded
tag 3 once, an hour off. So every vote within tolerance is for 51.
"""

from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import polars as pl

from social_energy.beacons import BeaconConfig, ingest_logs_to
from social_energy.beacons.witness import decide, ingest_with_witnesses, witness_votes


def at(h: int, m: int, s: int = 0) -> datetime:
    return datetime(2026, 8, 14, h, m, s, tzinfo=UTC)


def ambiguous_contacts() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "readout_key": ["A"] * 6 + ["B"],
            "header": [3] * 6 + [4],
            "observed": [20, 21, 20, 21, 22, 22, 20],
            "t_own": [at(10, 0), at(10, 0), at(10, 10), at(10, 10), at(10, 20), at(10, 21),
                      at(11, 0)],
        }
    )  # fmt: skip


def witnesses() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "beacon": [20, 21, 20, 21, 22],
            "observed": [51, 51, 51, 51, 3],
            "t": [at(10, 0, 30), at(9, 59), at(10, 10, 50), at(10, 9, 30), at(11, 20)],
        }
    )


def test_votes_count_partner_sightings_of_each_candidate_within_tolerance():
    v = witness_votes(ambiguous_contacts(), witnesses(), tolerance_s=120).sort("readout_key")
    a = v.row(0, named=True)
    assert (a["readout_key"], a["contacts"], a["votes_low"], a["votes_high"]) == ("A", 6, 0, 4)
    b = v.row(1, named=True)
    assert (b["readout_key"], b["votes_low"], b["votes_high"]) == ("B", 0, 0)


def test_a_wider_tolerance_lets_the_far_sighting_vote():
    v = witness_votes(ambiguous_contacts(), witnesses(), tolerance_s=3600).sort("readout_key")
    assert v.row(0, named=True)["votes_low"] == 2  # tag 22's 11:20 record of tag 3, twice


def test_decide_needs_enough_votes_and_a_clear_majority():
    votes = pl.DataFrame(
        {
            "readout_key": ["clear", "few", "split", "none"],
            "header": [3, 3, 3, 3],
            "contacts": [50, 50, 50, 50],
            "votes_low": [1, 0, 10, 0],
            "votes_high": [40, 4, 10, 0],
        }
    )
    d = decide(votes, min_votes=5, min_share=0.9).sort("readout_key")
    assert d["readout_key"].to_list() == ["clear"]
    assert d["beacon"].to_list() == [51]


def test_a_low_majority_picks_the_printed_digit():
    votes = pl.DataFrame(
        {"readout_key": ["x"], "header": [7], "contacts": [9], "votes_low": [9], "votes_high": [0]}
    )
    assert decide(votes, min_votes=5, min_share=0.9)["beacon"].to_list() == [7]


def test_tolerance_is_symmetric():
    # At 45 s only tag 20's sighting 30 s after 10:00 and tag 21's 30 s before 10:10 count.
    v = witness_votes(ambiguous_contacts(), witnesses(), tolerance_s=45)
    assert v["votes_high"].sum() == 2


def test_a_tag_is_not_its_own_witness():
    # Tag 51 hearing "51" is impossible, but a candidate must never vote for itself.
    w = pl.concat([witnesses(), pl.DataFrame({"beacon": [51], "observed": [51], "t": [at(10, 0)]})])
    amb = pl.concat(
        [ambiguous_contacts(), pl.DataFrame({"readout_key": ["A"], "header": [3], "observed": [51],
                                             "t_own": [at(10, 0)]})]
    )  # fmt: skip
    v = witness_votes(amb, w, tolerance_s=120).filter(pl.col("readout_key") == "A")
    assert v["votes_high"].to_list() == [4]
    assert v["contacts"].to_list() == [7]


# ---- two passes over real log files (tests/fixtures/beacon_logs/witness.log) ---------------------
# The "3" readout (15 Aug 10:00 local, Current Timer 36000, so booted at midnight) matches no power
# cycle: neither tag 3 nor tag 51 has another readout. Its six contacts date to 09:00, 09:10 and
# 09:20. Tag 20 (booted 08:00:05) and tag 21 (booted 08:00:10) each heard tag 51 at exactly those
# three times. Six votes for 51, none for 3.


WITNESS_LOG = Path(__file__).parent / "fixtures" / "beacon_logs" / "witness.log"


def witness_config() -> BeaconConfig:
    return BeaconConfig(
        timezone="Europe/Berlin",
        valid_from=date(2026, 8, 12),
        valid_to=date(2026, 8, 29),
        ambiguous_id_cutoff=datetime(2026, 8, 15, 22, 0, 0),
    )


def test_one_pass_leaves_the_readout_ambiguous(tmp_path):
    qa = ingest_logs_to([WITNESS_LOG], witness_config(), tmp_path / "out")
    assert qa["ids_ambiguous"] == 1


def test_two_passes_settle_it_from_the_partners_and_date_its_contacts(tmp_path):
    out = tmp_path / "out"
    qa = ingest_with_witnesses([WITNESS_LOG], witness_config(), out)
    assert (qa["ids_ambiguous"], qa["ids_witnessed"]) == (0, 1)
    r = pl.read_parquet(out / "readouts.parquet").filter(pl.col("header_id") == "3")
    assert (r["beacon"].to_list(), r["id_status"].to_list()) == ([51], ["witnessed"])
    votes = pl.read_parquet(out / "id_witness.parquet")
    assert votes.select("votes_low", "votes_high", "beacon").row(0) == (0, 6, 51)
    c = pl.read_parquet(out / "contacts" / "2026-08-15.parquet").filter(pl.col("beacon") == 51)
    local = c.sort("line_no")["t"].dt.convert_time_zone("Europe/Berlin").dt.strftime("%H:%M")
    assert local.to_list() == ["09:00", "09:00", "09:10", "09:10", "09:20", "09:20"]
    assert c["ok"].all()


# ---- timing peaks ----------------------------------------------------------------------------
# Readout "P" (printed "5": tag 5 or 53) heard tag 30 at 12:00, 12:10, 12:20 and 12:30 by its own,
# 2 min late clock. Tag 30 heard tag 53 exactly 120 s before each: one constant offset, a sharp
# peak. Tag 30 also heard tag 5 near each time, but at scattered offsets (+200, -250, +90, -170 s),
# as when both candidates were around. Counts within 300 s are 4 against 4; timing is not.


def peak_case() -> tuple[pl.DataFrame, pl.DataFrame]:
    own = [at(12, 0), at(12, 10), at(12, 20), at(12, 30)]
    amb = pl.DataFrame({"readout_key": ["P"] * 4, "header": [5] * 4, "observed": [30] * 4,
                        "t_own": own})  # fmt: skip
    s = lambda t, d: t + timedelta(seconds=d)  # noqa: E731
    w = pl.DataFrame(
        {
            "beacon": [30] * 8,
            "observed": [53] * 4 + [5] * 4,
            "t": [s(t, -120) for t in own] + [s(own[0], 200), s(own[1], -250), s(own[2], 90),
                                              s(own[3], -170)],
        }
    )  # fmt: skip
    return amb, w


def test_peaks_measure_how_many_sightings_share_one_offset():
    amb, w = peak_case()
    v = witness_votes(amb, w, tolerance_s=300, peak_s=10).row(0, named=True)
    assert (v["votes_low"], v["votes_high"]) == (4, 4)
    assert v["peak_high"] == 1.0  # all four at -120 s
    # tag 5's offsets +200, -250, +90, -170 have median -40; none lies within 10 s of it
    assert v["peak_low"] == 0.0


def test_a_strong_peak_settles_a_split_count_when_it_agrees_with_the_majority():
    votes = pl.DataFrame(
        {
            "readout_key": ["peak", "against", "weak", "no_majority"],
            "header": [5, 5, 5, 5],
            "contacts": [100] * 4,
            "votes_low": [40, 95, 40, 50],
            "votes_high": [60, 5, 60, 50],
            "peak_low": [0.05, 0.05, 0.30, 0.05],
            "peak_high": [0.40, 0.40, 0.40, 0.40],
        }
    )
    d = decide(votes, min_votes=5, min_share=0.9, min_peak_ratio=3.0).sort("readout_key")
    # "peak": majority high and an 8x peak for high. "against": 95% low, but an 8x peak says high,
    # so neither wins. "weak": peak ratio 1.3. "no_majority": an exact tie has no majority.
    assert d["readout_key"].to_list() == ["peak"]
    assert d["beacon"].to_list() == [53]


def test_a_weak_peak_does_not_overrule_a_clear_count():
    votes = pl.DataFrame(
        {"readout_key": ["x"], "header": [5], "contacts": [500], "votes_low": [122],
         "votes_high": [0], "peak_low": [0.013], "peak_high": [0.015]}
    )  # fmt: skip
    assert decide(votes, min_votes=5, min_share=0.9, min_peak_ratio=3.0)["beacon"].to_list() == [5]
