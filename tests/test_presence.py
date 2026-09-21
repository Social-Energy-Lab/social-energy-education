"""Presence: co-presence per bin, room per bin, and context around self-reports.

Oracle: in the synthetic camp everyone in a room hears everyone else and the room's
tag at every scan (detection_p=1), and a person is in exactly one room per hour.
"""

from datetime import timedelta

import polars as pl
import pytest

from social_energy.beacons import BeaconConfig, ingest_logs
from social_energy.presence import copresence, event_context, room_per_bin
from social_energy.spine import Spine
from social_energy.synth import CampSpec, generate

# Isolate presence logic from the traps; lossy detection creates one-sided observations.
SPEC = CampSpec(lost=None, reboot=None, swap=None, detection_p=0.7)


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    camp = generate(SPEC, tmp_path_factory.mktemp("camp"))
    config = BeaconConfig(
        timezone=SPEC.timezone,
        valid_from=SPEC.start.date(),
        valid_to=SPEC.start.date(),
        ambiguous_id_cutoff=camp.id_bug_cutoff,
    )
    tables = ingest_logs(camp.log_paths, config)
    spine = Spine.load(camp.spine_dir)
    contacts = spine.resolve(
        tables.contacts, device_col="beacon", time_col="t", kind="beacon", out="observer_entity"
    )
    contacts = spine.resolve(
        contacts, device_col="observed", time_col="t", kind="beacon", out="observed_entity"
    ).filter(pl.col("ok"))
    reports = spine.resolve(
        tables.self_reports, device_col="beacon", time_col="t", kind="beacon", out="entity"
    ).filter(pl.col("ok"))
    return camp, contacts, reports


def _truth_rooms(camp) -> pl.DataFrame:
    """Room per person per hour, from ground truth (who heard which room tag)."""
    return (
        camp.truth_contacts.filter(pl.col("observed_entity").str.starts_with("location:"))
        .with_columns(pl.col("t").dt.truncate("1h").alias("bin"))
        .select(pl.col("observer_entity").alias("entity"), "bin",
                pl.col("observed_entity").alias("location"))
        .unique()
    )  # fmt: skip


def test_room_per_bin_matches_ground_truth(world):
    camp, contacts, _ = world
    rooms = room_per_bin(contacts, every="1h", min_hits=1)
    key = ["entity", "bin"]
    got = rooms.select(*key, "location").sort(key)
    assert got.equals(_truth_rooms(camp).sort(key))


def test_copresence_is_undirected_and_matches_rooms(world):
    camp, contacts, _ = world
    pairs = copresence(contacts, every="1h")
    assert (pairs["a"] < pairs["b"]).all()  # one row per unordered pair
    truth = _truth_rooms(camp)
    same_room = (
        truth.join(truth, on=["bin", "location"], suffix="_2")
        .filter(pl.col("entity") < pl.col("entity_2"))
        .select(pl.col("entity").alias("a"), pl.col("entity_2").alias("b"), "bin")
    )
    key = ["a", "b", "bin"]
    assert pairs.select(key).sort(key).equals(same_room.sort(key))
    assert (pairs["observations"] > 0).all()


def test_event_context_lists_who_was_around_and_where(world):
    camp, contacts, reports = world
    window = timedelta(minutes=5)
    ctx = event_context(reports, contacts, window=window)
    assert ctx.height == reports.height > 0
    truth = camp.truth_contacts
    for row in ctx.iter_rows(named=True):
        near = truth.filter(pl.col("t").is_between(row["t"] - window, row["t"] + window))
        me = f"{row['entity']}"
        expected = set(
            near.filter(
                (pl.col("observer_entity") == me)
                & pl.col("observed_entity").str.starts_with("person:")
            )["observed_entity"].to_list()
        ) | set(near.filter(pl.col("observed_entity") == me)["observer_entity"].to_list())
        assert set(row["copresent"]) == expected - {me}
        rooms = (
            near.filter((pl.col("observer_entity") == me)
                        & pl.col("observed_entity").str.starts_with("location:"))
            ["observed_entity"].value_counts(sort=True)
        )  # fmt: skip
        if rooms.height == 0:
            assert row["location"] is None  # heard no room tag in the window
        else:
            top = rooms.filter(pl.col("count") == pl.col("count").max())["observed_entity"]
            assert row["location"] in top.to_list()  # ties may go either way
        assert row["n_copresent"] == len(row["copresent"])


def test_room_per_bin_picks_majority_and_respects_min_hits():
    t0 = pl.datetime(2026, 8, 14, 10, 0, 0, time_zone="UTC")
    df = pl.DataFrame(
        {
            "observer_entity": ["person:1"] * 5 + ["person:2"],
            "observed_entity": ["location:hall", "location:hall", "location:hall",
                                "location:corridor", "location:corridor", "location:hall"],
            "rssi": [-90, -88, -91, -60, -61, -70],
        }
    ).with_columns(t=t0)  # fmt: skip
    rooms = room_per_bin(df, every="5m", min_hits=2)
    assert rooms["entity"].to_list() == ["person:1"]  # person:2 has only one hit
    assert rooms["location"].to_list() == ["location:hall"]  # 3 weak hits beat 2 strong ones
    assert rooms["share"].to_list() == [0.6]
