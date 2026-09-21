"""Study configs stay loadable and free of person-level fields."""

from pathlib import Path

import yaml

STUDIES = Path(__file__).resolve().parents[1] / "studies"


def test_every_study_has_readme_and_config():
    for study in (p for p in STUDIES.iterdir() if p.is_dir()):
        assert (study / "README.md").exists(), study
        config = yaml.safe_load((study / "study.yaml").read_text(encoding="utf-8"))
        assert config["study_id"] == study.name
        assert config["timezone"]


def test_location_rosters_are_well_formed():
    for roster in STUDIES.glob("*/locations.yaml"):
        entries = yaml.safe_load(roster.read_text(encoding="utf-8"))
        assert all(set(e) == {"tag", "room", "label", "zone", "kind"} for e in entries), roster
        tags = [e["tag"] for e in entries]
        assert len(tags) == len(set(tags)), f"duplicate tags in {roster}"


def test_study_files_contain_no_person_level_keys():
    forbidden = {"person", "people", "participant_id", "name", "assignments", "exclusions"}
    for path in STUDIES.rglob("*.yaml"):
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))

        def keys(node):
            if isinstance(node, dict):
                for k, v in node.items():
                    yield k
                    yield from keys(v)
            elif isinstance(node, list):
                for item in node:
                    yield from keys(item)

        assert not (set(keys(doc)) & forbidden), path
