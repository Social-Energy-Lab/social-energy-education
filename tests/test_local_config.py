"""A study's private configuration lives with the data, never in the repo.

Platform identifiers (which interview agent to fetch, which question holds the typed study ID)
name a private deployment, so they belong under $SOCIAL_ENERGY_DATA/<study-id>/local.yaml
alongside the data, not in the public studies/<id>/study.yaml.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from social_energy.study import StudyConfig

PUBLIC = "study_id: synthetic-camp\ntimezone: UTC\n"


def _study(tmp_path: Path) -> StudyConfig:
    path = tmp_path / "study.yaml"
    path.write_text(PUBLIC, encoding="utf-8")
    return StudyConfig.load(path)


def _local(tmp_path: Path, text: str) -> None:
    root = tmp_path / "data" / "synthetic-camp"
    root.mkdir(parents=True)
    (root / "local.yaml").write_text(text, encoding="utf-8")


def test_local_config_is_read_from_the_data_root(tmp_path, monkeypatch):
    _local(tmp_path, "survey:\n  zeitgeist:\n    study_id_item: q_private\n")
    monkeypatch.setenv("SOCIAL_ENERGY_DATA", str(tmp_path / "data"))
    assert _study(tmp_path).survey_config().study_id_item == "q_private"


def test_missing_local_config_is_not_an_error(tmp_path, monkeypatch):
    monkeypatch.setenv("SOCIAL_ENERGY_DATA", str(tmp_path / "data"))
    assert _study(tmp_path).survey_config().study_id_item is None


def test_unset_data_root_is_not_an_error(tmp_path, monkeypatch):
    """Ingest-free commands (and CI) must work without a data root."""
    monkeypatch.delenv("SOCIAL_ENERGY_DATA", raising=False)
    assert _study(tmp_path).local == {}


def test_agents_come_from_the_local_config(tmp_path, monkeypatch):
    _local(
        tmp_path, 'ai_interviews:\n  zeitgeist:\n    agents:\n      - id: "abc"\n        label: a\n'
    )
    monkeypatch.setenv("SOCIAL_ENERGY_DATA", str(tmp_path / "data"))
    assert _study(tmp_path).zeitgeist_agents() == [{"id": "abc", "label": "a"}]


def test_public_study_yaml_may_not_carry_platform_identifiers(tmp_path, monkeypatch):
    """A leftover section in the public file is refused rather than silently used."""
    path = tmp_path / "study.yaml"
    path.write_text(PUBLIC + "survey:\n  zeitgeist:\n    study_id_item: q_public\n")
    monkeypatch.setenv("SOCIAL_ENERGY_DATA", str(tmp_path / "data"))
    with pytest.raises(ValueError, match=r"local\.yaml"):
        StudyConfig.load(path)
