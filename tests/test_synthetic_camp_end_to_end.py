"""Oracle test: synthetic camp → beacon ingest → spine → the true contacts come back."""

import polars as pl
import pytest

from social_energy.beacons import BeaconConfig, ingest_logs
from social_energy.spine import Spine
from social_energy.synth import CampSpec, generate


@pytest.fixture(scope="module")
def camp(tmp_path_factory):
    return generate(CampSpec(), tmp_path_factory.mktemp("camp"))


@pytest.fixture(scope="module")
def resolved(camp):
    spec = camp.spec
    config = BeaconConfig(
        timezone=spec.timezone,
        valid_from=spec.start.date(),
        valid_to=spec.start.date(),
        ambiguous_id_cutoff=camp.id_bug_cutoff,
    )
    tables = ingest_logs(camp.log_paths, config)
    spine = Spine.load(camp.spine_dir)
    contacts = spine.resolve(
        tables.contacts, device_col="beacon", time_col="t", kind="beacon", out="observer_entity"
    )
    contacts = spine.resolve(
        contacts, device_col="observed", time_col="t", kind="beacon", out="observed_entity"
    )
    for side in ("beacon", "observed"):
        contacts = spine.flag_excluded(
            contacts, device_col=side, time_col="t", kind="beacon", out=f"excluded_{side}"
        )
    return tables, contacts, spine


def test_generator_writes_logs_and_spine(camp):
    assert camp.log_paths and all(p.exists() for p in camp.log_paths)
    assert (camp.spine_dir / "assignments.yaml").exists()
    assert camp.truth_contacts.height > 0


def test_the_traps_are_actually_present(resolved):
    tables, _, _ = resolved
    assert tables.qa["ids_repaired"] > 0  # logger ID bug
    assert tables.qa["reboots"] == 1
    assert tables.contacts["pre_reboot"].any()
    assert tables.qa["ids_ambiguous"] == 0


def test_every_contact_is_placed_in_time(resolved):
    tables, _, _ = resolved
    assert tables.qa["contacts_unplaced_in_time"] == 0
    assert tables.contacts["ok"].all()


def test_recovered_contacts_equal_ground_truth(camp, resolved):
    _, contacts, _ = resolved
    got = contacts.filter(
        pl.col("ok") & ~pl.col("excluded_beacon") & ~pl.col("excluded_observed")
    ).select("observer_entity", "observed_entity", "t")
    key = ["observer_entity", "observed_entity", "t"]
    assert got.height > 1000
    assert got.sort(key).equals(camp.truth_contacts.sort(key))


def test_swapped_tag_maps_to_the_same_person(camp, resolved):
    _, contacts, _ = resolved
    person, new_beacon, _ = camp.spec.swap
    after = contacts.filter(pl.col("beacon") == new_beacon)
    assert after.height > 0
    assert set(after["observer_entity"].to_list()) == {f"person:{person}"}


def test_self_reports_recovered(camp, resolved):
    tables, _, spine = resolved
    sr = spine.resolve(
        tables.self_reports, device_col="beacon", time_col="t", kind="beacon", out="entity"
    ).filter(pl.col("ok"))
    key = ["entity", "t"]
    assert sr.select(key).sort(key).equals(camp.truth_self_reports.sort(key))


def test_generator_rejects_colliding_device_ids(tmp_path):
    with pytest.raises(ValueError, match="swap beacon 99"):
        generate(CampSpec(people=tuple(range(20, 110))), tmp_path)
    with pytest.raises(ValueError, match="room tags"):
        generate(CampSpec(people=(44, 114)), tmp_path)
