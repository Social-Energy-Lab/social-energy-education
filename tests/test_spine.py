import re
from datetime import UTC, datetime
from pathlib import Path

import polars as pl
import pytest
import yaml

from social_energy.spine import Spine, SpineError

TZ = "Europe/Berlin"


def _dump(directory: Path, name: str, content) -> None:
    (directory / name).write_text(yaml.safe_dump(content, sort_keys=False))


@pytest.fixture
def spine_dir(tmp_path: Path) -> Path:
    _dump(tmp_path, "meta.yaml", {"study_id": "test-camp", "timezone": TZ})
    _dump(
        tmp_path,
        "people.yaml",
        [
            {"id": "74", "role": "participant", "consent": ["beacons", "survey"]},
            {"id": "75", "role": "participant", "consent": ["beacons"]},
            {"id": "L1", "role": "course_leader", "consent": []},
        ],
    )
    _dump(
        tmp_path,
        "locations.yaml",
        [{"id": "aula-stage", "label": "Aula near stage", "zone": "aula", "kind": "room"}],
    )
    _dump(
        tmp_path,
        "assignments.yaml",
        [
            # person 74 wore beacon 74 until it failed, then spare beacon 7
            {"device": "beacon:74", "entity": "person:74",
             "start": "2026-08-13 11:30:00", "end": "2026-08-14 15:40:00"},
            {"device": "beacon:7", "entity": "person:74", "start": "2026-08-14 15:40:00"},
            {"device": "beacon:75", "entity": "person:75", "start": "2026-08-13 11:30:00"},
            {"device": "beacon:134", "entity": "location:aula-stage",
             "start": "2026-08-13 11:30:00"},
        ],
    )  # fmt: skip
    _dump(
        tmp_path,
        "events.yaml",
        [
            {"id": "plenum-0814", "label": "Plenum", "kind": "plenum",
             "start": "2026-08-14 08:30:00", "end": "2026-08-14 09:20:00",
             "locations": ["aula-stage"]},
        ],
    )  # fmt: skip
    _dump(
        tmp_path,
        "exclusions.yaml",
        [
            {"target": "beacon:75", "start": "2026-08-15 15:30:00",
             "end": "2026-08-15 16:10:00", "reason": "taken off for swimming"},
            {"target": "person:74", "start": "2026-08-16 22:00:00",
             "end": "2026-08-17 10:00:00", "reason": "badge lost overnight"},
        ],
    )  # fmt: skip
    return tmp_path


def berlin(s: str) -> datetime:
    return pl.Series([s]).str.to_datetime().dt.replace_time_zone(TZ).dt.convert_time_zone("UTC")[0]


def test_load_parses_naive_times_in_study_timezone(spine_dir):
    spine = Spine.load(spine_dir)
    first = spine.assignments[0]
    assert first.start == datetime(2026, 8, 13, 9, 30, tzinfo=UTC)  # 11:30 CEST
    assert first.end == datetime(2026, 8, 14, 13, 40, tzinfo=UTC)
    assert spine.assignments[1].end is None


def test_entity_for_follows_device_swaps(spine_dir):
    spine = Spine.load(spine_dir)
    assert spine.entity_for("beacon:74", berlin("2026-08-14 10:00:00")) == "person:74"
    assert spine.entity_for("beacon:74", berlin("2026-08-14 16:00:00")) is None
    assert spine.entity_for("beacon:7", berlin("2026-08-14 16:00:00")) == "person:74"
    assert spine.entity_for("beacon:134", berlin("2026-08-20 12:00:00")) == "location:aula-stage"


def test_resolve_adds_entity_column(spine_dir):
    spine = Spine.load(spine_dir)
    df = pl.DataFrame(
        {
            "observer": [74, 7, 75, 99],
            "t": [berlin(s) for s in ["2026-08-14 10:00:00", "2026-08-14 16:00:00",
                                      "2026-08-14 16:00:00", "2026-08-14 16:00:00"]],
        }
    )  # fmt: skip
    out = spine.resolve(df, device_col="observer", time_col="t", kind="beacon", out="who")
    assert out["who"].to_list() == ["person:74", "person:74", "person:75", None]
    assert out.columns == ["observer", "t", "who"]


def test_excluded_flags_device_and_person_windows(spine_dir):
    spine = Spine.load(spine_dir)
    df = pl.DataFrame(
        {
            "observer": [75, 75, 7, 7],
            "t": [berlin(s) for s in ["2026-08-15 15:45:00", "2026-08-15 17:00:00",
                                      "2026-08-16 23:00:00", "2026-08-17 11:00:00"]],
        }
    )  # fmt: skip
    out = spine.flag_excluded(df, device_col="observer", time_col="t", kind="beacon")
    assert out["excluded"].to_list() == [True, False, True, False]


def test_consent_by_module(spine_dir):
    spine = Spine.load(spine_dir)
    assert spine.consented("beacons") == {"74", "75"}
    assert spine.consented("survey") == {"74"}


def test_overlapping_assignments_for_one_device_are_rejected(spine_dir):
    doc = yaml.safe_load((spine_dir / "assignments.yaml").read_text())
    doc.append({"device": "beacon:75", "entity": "person:74", "start": "2026-08-20 10:00:00"})
    _dump(spine_dir, "assignments.yaml", doc)
    with pytest.raises(SpineError, match="beacon:75"):
        Spine.load(spine_dir)


def test_person_wearing_two_beacons_at_once_is_rejected(spine_dir):
    doc = yaml.safe_load((spine_dir / "assignments.yaml").read_text())
    doc.append({"device": "beacon:99", "entity": "person:75", "start": "2026-08-20 10:00:00"})
    _dump(spine_dir, "assignments.yaml", doc)
    with pytest.raises(SpineError, match="person:75"):
        Spine.load(spine_dir)


def test_unknown_entities_are_rejected(spine_dir):
    doc = yaml.safe_load((spine_dir / "assignments.yaml").read_text())
    doc.append({"device": "beacon:99", "entity": "person:999", "start": "2026-08-20 10:00:00"})
    _dump(spine_dir, "assignments.yaml", doc)
    with pytest.raises(SpineError, match="person:999"):
        Spine.load(spine_dir)


def test_exclusion_for_a_device_that_was_never_assigned_is_rejected(spine_dir):
    """A typo'd tag number must fail loudly: flag_excluded joins on the exact string, so an
    exclusion nobody can match silently protects nothing."""
    doc = yaml.safe_load((spine_dir / "exclusions.yaml").read_text())
    doc.append({"target": "beacon:999", "start": "2026-08-20 10:00:00", "reason": "typo"})
    _dump(spine_dir, "exclusions.yaml", doc)
    with pytest.raises(SpineError, match="beacon:999"):
        Spine.load(spine_dir)


def test_exclusion_with_an_unknown_target_kind_is_rejected(spine_dir):
    """`study:…` and a stringified None are the two shapes seen in the wild. Neither can ever
    match a device ref or an entity ref, so both must be refused rather than ignored."""
    base = yaml.safe_load((spine_dir / "exclusions.yaml").read_text())
    for target in ("study:test-camp", "zeitgeist:None"):
        bad = {"target": target, "start": "2026-08-20 10:00:00", "reason": "camp-wide"}
        _dump(spine_dir, "exclusions.yaml", [*base, bad])
        with pytest.raises(SpineError, match=re.escape(target)):
            Spine.load(spine_dir)


def test_exclusions_for_assigned_devices_and_known_people_still_load(spine_dir):
    """The guard must not reject the two legitimate shapes the fixture already uses."""
    spine = Spine.load(spine_dir)
    assert {e.target for e in spine.exclusions} == {"beacon:75", "person:74"}


def test_event_notes_carry_uncertainty_markers(spine_dir):
    """Events need a home for [inferred] / [unknown: …]. The field log hedges constantly
    ("gegen 23 Uhr", "Vermutlich"), and a tag cannot carry the question that needs asking."""
    doc = yaml.safe_load((spine_dir / "events.yaml").read_text())
    doc.append({
        "id": "kuea-0814-tabletennis", "label": "Table tennis", "kind": "kuea",
        "start": "2026-08-14 23:00:00", "end": "2026-08-15 00:00:00",
        "notes": 'start [inferred] from "Vermutlich 23 Uhr-0 Uhr"',
    })  # fmt: skip
    _dump(spine_dir, "events.yaml", doc)
    spine = Spine.load(spine_dir)
    by_id = {e.id: e for e in spine.events}
    assert by_id["kuea-0814-tabletennis"].notes.startswith("start [inferred]")
    assert by_id["plenum-0814"].notes == ""
