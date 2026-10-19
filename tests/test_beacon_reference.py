"""Hand labels from a relabelled copy of the logs, and their use as a last-resort ID fallback.

Fixture ``hand_split.log`` (15 Aug, before the cutoff): readouts printed "5" at 10:00 (anchored),
"5" at 10:30 (anchored), a headerless "5" block at 11:00, and "7" at 12:00. No other tag is read
out, so neither anchors nor witnesses can settle any of them. ``hand_split_cleaned.log`` is the
same log relabelled by hand, with CRLF line ends: the 10:00 readout and the 11:00 block as 53, the
10:30 readout as 5 (its Contact Count line dropped), and the 7 readout split 3 lines to 55 against
2 to 7, which settles nothing at a 0.9 share.
"""

from datetime import date, datetime
from pathlib import Path

import polars as pl
import pytest

from social_energy.beacons import (
    BeaconConfig,
    PurgedDeviceError,
    ingest_logs,
    ingest_with_witnesses,
    reference_labels,
)

LOGS = Path(__file__).parent / "fixtures" / "beacon_logs"
ORIGINAL, COPY = LOGS / "hand_split.log", LOGS / "hand_split_cleaned.log"
K = "hand_split.log#"


def config(**kw) -> BeaconConfig:
    kw.setdefault("ambiguous_id_cutoff", datetime(2026, 8, 15, 22, 0, 0))
    return BeaconConfig(
        timezone="Europe/Berlin", valid_from=date(2026, 8, 12), valid_to=date(2026, 8, 29), **kw
    )


@pytest.fixture(scope="module")
def labels() -> pl.DataFrame:
    return reference_labels([(ORIGINAL, COPY)], config())


def test_each_printed_digit_readout_gets_the_label_of_its_lines_twins(labels):
    rows = {r["readout_key"]: r for r in labels.iter_rows(named=True)}
    assert sorted(rows) == [K + "5#1", K + "5#2", K + "5#3", K + "7#1"]
    one, two, block = rows[K + "5#1"], rows[K + "5#2"], rows[K + "5#3"]
    assert (one["header"], one["lines"], one["matched"], one["beacon"]) == (5, 5, 5, 53)
    # a line the copy dropped is unmatched, and shifts nothing after it
    assert (two["lines"], two["matched"], two["beacon"], two["share"]) == (4, 3, 5, 1.0)
    assert (block["lines"], block["beacon"]) == (1, 53)


def test_a_split_label_below_the_share_settles_nothing(labels):
    seven = labels.filter(pl.col("readout_key") == K + "7#1").row(0, named=True)
    assert seven["share"] == pytest.approx(0.6)
    assert seven["beacon"] is None
    looser = reference_labels([(ORIGINAL, COPY)], config(), min_share=0.5)
    assert looser.filter(pl.col("readout_key") == K + "7#1")["beacon"].to_list() == [55]


def test_a_copy_of_another_log_matches_nothing():
    other = reference_labels([(ORIGINAL, LOGS / "id_bug_cleaned.log")], config())
    assert other["matched"].to_list() == [0, 0, 0, 0]
    assert other["beacon"].null_count() == 4


def test_a_purged_device_in_the_copy_is_refused():
    with pytest.raises(PurgedDeviceError):
        reference_labels([(ORIGINAL, COPY)], config(purged_devices=(53,)))


def fallback(labels: pl.DataFrame) -> tuple[tuple[str, int], ...]:
    settled = labels.drop_nulls("beacon")
    return tuple(zip(settled["readout_key"], settled["beacon"], strict=True))


def test_without_a_fallback_every_readout_stays_ambiguous():
    assert ingest_logs([ORIGINAL], config()).qa["ids_ambiguous"] == 4


def test_the_fallback_settles_the_readouts_left_ambiguous_and_dates_the_headerless_block(
    labels, tmp_path
):
    out = tmp_path / "out"
    qa = ingest_with_witnesses([ORIGINAL], config(id_fallback=fallback(labels)), out)
    assert (qa["ids_fallback"], qa["ids_ambiguous"], qa["ids_witnessed"]) == (3, 1, 0)
    r = pl.read_parquet(out / "readouts.parquet").sort("readout_key")
    assert r["beacon"].to_list() == [53, 5, 53, 7]
    assert r["id_status"].to_list() == ["fallback", "fallback", "fallback", "ambiguous"]
    c = pl.read_parquet(out / "contacts" / "2026-08-15.parquet")
    by_tag = c.group_by("beacon").agg(pl.col("ok").all(), pl.len()).sort("beacon")
    assert by_tag.rows() == [(5, True, 1), (53, True, 3)]
    # the 11:00 block now belongs to tag 53's cycle (booted 00:00): 37000 s after it
    block = c.filter(pl.col("readout_key") == K + "5#3")
    local = block["t"].dt.convert_time_zone("Europe/Berlin").dt.strftime("%H:%M:%S")
    assert local.to_list() == ["10:16:40"]


# ---- precedence: anchors, then witnesses, then the fallback ------------------------------------

GOLDEN = LOGS / "golden.log"
WITNESS_LOG = LOGS / "witness.log"


def test_an_anchor_repair_and_a_witness_override_both_beat_the_fallback():
    base = config(ambiguous_id_cutoff=datetime(2026, 8, 15, 20, 17, 48))
    t = ingest_logs([GOLDEN], base)
    three = t.readouts.filter(pl.col("id_status") == "repaired")["readout_key"][0]
    four = t.readouts.filter(pl.col("header_id") == "4")["readout_key"][0]
    t = ingest_logs(
        [GOLDEN],
        config(
            ambiguous_id_cutoff=base.ambiguous_id_cutoff,
            id_overrides=((four, 52),),
            id_fallback=((three, 3), (four, 4)),
        ),
    )
    r = dict(t.readouts.select("readout_key", "id_status").iter_rows())
    assert (r[three], r[four]) == ("repaired", "witnessed")
    assert t.qa["ids_fallback"] == 0
    t = ingest_logs(
        [GOLDEN], config(ambiguous_id_cutoff=base.ambiguous_id_cutoff, id_fallback=((four, 52),))
    )
    four_row = t.readouts.filter(pl.col("readout_key") == four).row(0, named=True)
    assert (four_row["beacon"], four_row["id_status"]) == (52, "fallback")


def test_witnesses_vote_without_the_fallback(tmp_path):
    # witness.log's "3" readout is tag 51 by its partners. A fallback saying 3 must not pre-empt
    # the vote: it applies only to what the vote leaves open.
    key = "witness.log#3#1"
    qa = ingest_with_witnesses([WITNESS_LOG], config(id_fallback=((key, 3),)), tmp_path / "o")
    assert (qa["ids_witnessed"], qa["ids_fallback"]) == (1, 0)
    r = pl.read_parquet(tmp_path / "o" / "readouts.parquet").filter(pl.col("readout_key") == key)
    assert r.select("beacon", "id_status").row(0) == (51, "witnessed")
