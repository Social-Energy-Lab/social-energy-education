"""Study config loading and the CLI that turns local raw data into derived tables."""

import dataclasses
import json
from datetime import date, datetime
from pathlib import Path

import polars as pl
import yaml

from social_energy import cli
from social_energy.spine import Spine
from social_energy.study import StudyConfig
from social_energy.synth import CampSpec, generate

REPO = Path(__file__).resolve().parents[1]


def test_dsa_study_config_builds_beacon_config():
    config = StudyConfig.load(REPO / "studies" / "dsa-2026" / "study.yaml")
    beacons = config.beacon_config()
    assert config.study_id == "dsa-2026"
    assert beacons.timezone == "Europe/Berlin"
    assert beacons.valid_from == date(2026, 8, 12)
    assert beacons.ambiguous_id_cutoff == datetime(2026, 8, 15, 22, 0, 0)
    assert beacons.valid_id_ranges == ((1, 170), (252, 254))
    assert beacons.rssi_range == (-110, -10)
    assert beacons.storage_full_count == 215000
    assert len(config.locations) == 67


def _study_yaml(tmp_path: Path, camp) -> Path:
    spec = camp.spec
    study = tmp_path / "studies" / "synthetic-camp"
    study.mkdir(parents=True)
    (study / "study.yaml").write_text(
        yaml.safe_dump(
            {
                "study_id": "synthetic-camp",
                "timezone": spec.timezone,
                "dates": {"arrival": spec.start.date(), "departure": spec.start.date()},
                "beacons": {
                    "valid_from": spec.start.date(),
                    "valid_to": spec.start.date(),
                    "ambiguous_id_cutoff": camp.id_bug_cutoff.strftime("%Y-%m-%d %H:%M:%S"),
                },
            }
        )
    )
    (study / "locations.yaml").write_text(
        yaml.safe_dump(
            [
                {"tag": tag, "room": name, "label": name, "zone": name, "kind": "room"}
                for tag, name in spec.rooms
            ]
        )
    )
    return study / "study.yaml"


def test_ingest_beacons_cli_writes_parquet_and_qa(tmp_path, monkeypatch):
    data_root = tmp_path / "data-root"
    camp = generate(CampSpec(), data_root / "synthetic-camp")
    monkeypatch.setenv("SOCIAL_ENERGY_DATA", str(data_root))
    study_yaml = _study_yaml(tmp_path, camp)

    assert cli.main(["ingest-beacons", str(study_yaml)]) == 0

    out = data_root / "synthetic-camp" / "derived" / "beacons"
    contacts = pl.read_parquet(out / "contacts" / "*.parquet")
    assert contacts.height > 1000
    qa = json.loads((out / "qa.json").read_text())
    assert qa["contacts"] == contacts.height
    assert qa["ids_repaired"] > 0


def test_init_spine_seeds_locations_and_templates(tmp_path, monkeypatch):
    data_root = tmp_path / "data-root"
    camp = generate(CampSpec(), tmp_path / "unused")
    monkeypatch.setenv("SOCIAL_ENERGY_DATA", str(data_root))
    study_yaml = _study_yaml(tmp_path, camp)

    assert cli.main(["init-spine", str(study_yaml)]) == 0

    spine_dir = data_root / "synthetic-camp" / "spine"
    for name in ("meta", "people", "locations", "assignments", "events", "exclusions"):
        assert (spine_dir / f"{name}.yaml").exists(), name
    spine = Spine.load(spine_dir)
    assert {loc.id for loc in spine.locations} == {"tag-114", "tag-115", "tag-116"}
    assert {a.device for a in spine.assignments} == {"beacon:114", "beacon:115", "beacon:116"}

    # never overwrites local work
    assert cli.main(["init-spine", str(study_yaml)]) == 1


def test_dsa_explorer_config_names_six_courses_and_defaults():
    ex = StudyConfig.load(REPO / "studies" / "dsa-2026" / "study.yaml").explorer_config()
    assert list(ex.courses) == ["1.1", "1.2", "1.3", "1.4", "1.5", "1.6"]
    assert ex.defaults == {"close_rssi": -65, "min_minutes": 15, "window_minutes": 120}
    assert ex.day_start == "07:30"
    assert [name for name, _ in ex.phases][:2] == ["morning", "midday"]


def test_explorer_config_defaults_when_section_missing(tmp_path):
    study = tmp_path / "study.yaml"
    study.write_text("study_id: x\ntimezone: UTC\n", encoding="utf-8")
    ex = StudyConfig.load(study).explorer_config()
    assert (ex.courses, ex.phases, ex.notes, ex.shade) == ({}, [], [], [])
    assert ex.defaults == {"close_rssi": -65, "min_minutes": 15, "window_minutes": 120}
    assert ex.min_group == 5


def test_explorer_phase_wraps_past_midnight():
    from datetime import time

    ex = StudyConfig.load(REPO / "studies" / "dsa-2026" / "study.yaml").explorer_config()
    names = [name for name, _ in ex.phases]
    assert names[ex.phase_of(time(1, 0))] == "late"
    assert names[ex.phase_of(time(3, 0))] == "night"
    assert names[ex.phase_of(time(7, 29))] == "night"
    assert names[ex.phase_of(time(7, 30))] == "morning"
    assert names[ex.phase_of(time(23, 0))] == "late"


def test_ingest_beacons_with_a_changed_config_writes_only_its_own_folder(tmp_path, monkeypatch):
    # A camp whose tags count 500 ppm fast: dating with rate 0 instead moves its records.
    data_root = tmp_path / "data-root"
    camp = generate(CampSpec(clock_rate_ppm=500), data_root / "synthetic-camp")
    monkeypatch.setenv("SOCIAL_ENERGY_DATA", str(data_root))
    study = StudyConfig.load(_study_yaml(tmp_path, camp))
    derived = data_root / "synthetic-camp" / "derived"
    fast = dataclasses.replace(study.beacon_config(), clock_rate_ppm=500)
    no_drift = dataclasses.replace(fast, clock_rate_ppm=0)

    assert cli.ingest_beacons(study, fast, derived / "fast" / "beacons") == 0
    before = pl.read_parquet(derived / "fast" / "beacons" / "contacts" / "*.parquet")
    alt = derived / "sensitivity" / "no_drift" / "beacons"
    assert cli.ingest_beacons(study, no_drift, alt) == 0
    after = pl.read_parquet(derived / "fast" / "beacons" / "contacts" / "*.parquet")
    assert after.equals(before)
    moved = pl.read_parquet(alt / "contacts" / "*.parquet")
    assert moved.height == before.height
    late = moved.join(before, on=["source", "line_no"], suffix="_fast").filter(
        pl.col("t").is_not_null() & pl.col("t_fast").is_not_null()
    )
    shift = (late["t"] - late["t_fast"]).dt.total_seconds().abs()
    assert shift.max() > 1
    assert shift.max() <= 500e-6 * late["uptime_s"].max() + 1  # rate x span of a power cycle
    assert json.loads((alt / "qa.json").read_text())["contacts"] == moved.height


def test_ingest_beacons_refuses_a_changed_config_in_the_main_folder(tmp_path, monkeypatch):
    data_root = tmp_path / "data-root"
    camp = generate(CampSpec(), data_root / "synthetic-camp")
    monkeypatch.setenv("SOCIAL_ENERGY_DATA", str(data_root))
    study = StudyConfig.load(_study_yaml(tmp_path, camp))
    changed = dataclasses.replace(study.beacon_config(), clock_rate_ppm=0)
    derived = data_root / "synthetic-camp" / "derived"
    assert cli.ingest_beacons(study, changed) == 2
    assert cli.ingest_beacons(study, changed, derived / "beacons") == 2
    assert cli.ingest_beacons(study, changed, tmp_path / "elsewhere") == 2
    assert not (derived / "beacons").exists()
    assert not (tmp_path / "elsewhere").exists()
