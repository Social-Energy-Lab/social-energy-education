"""The study's EDA config, `social-energy ingest-eda` and `social-energy eda-heart-rate` on a
synthetic data root."""

import json
import shutil
from datetime import date
from pathlib import Path

import polars as pl
import yaml

from social_energy import cli
from social_energy.study import StudyConfig
from social_energy.synth.eda import EdaSpec, SyntheticEda, generate_eda

REPO = Path(__file__).resolve().parents[1]


def test_dsa_study_config_builds_eda_config():
    eda = StudyConfig.load(REPO / "studies" / "dsa-2026" / "study.yaml").eda_config()
    assert eda.valid_from == date(2026, 8, 14) and eda.valid_to == date(2026, 8, 29)
    assert eda.rotation_s == 3600
    assert 7199 < eda.mtime_to_utc_s < 7203


def _synthetic_root(tmp_path, monkeypatch) -> tuple[Path, SyntheticEda]:
    """Cards under raw/eda/sd-cards/, spine under spine/, and a study config; returns the
    study.yaml path."""
    synth = generate_eda(EdaSpec(), tmp_path / "gen")
    root = tmp_path / "data"
    raw = root / "synthetic-eda" / "raw" / "eda" / "sd-cards"
    raw.mkdir(parents=True)
    for card in synth.cards:
        shutil.copytree(card, raw / card.name, copy_function=shutil.copy2)  # keeps mtimes
    shutil.copytree(synth.spine_dir, root / "synthetic-eda" / "spine")
    study = tmp_path / "studies" / "synthetic-eda"
    study.mkdir(parents=True)
    day = synth.spec.start.date().isoformat()
    (study / "study.yaml").write_text(
        yaml.safe_dump(
            {
                "study_id": "synthetic-eda",
                "timezone": "UTC",
                "eda": {
                    "valid_from": day,
                    "valid_to": day,
                    "mtime_to_utc_s": synth.spec.mtime_offset_s,
                    "rotation_s": synth.spec.chunk_s,
                },
            }
        )
    )
    monkeypatch.setenv("SOCIAL_ENERGY_DATA", str(root))
    return study / "study.yaml", synth


def test_ingest_eda_cli_writes_tables_and_person_minutes(tmp_path, monkeypatch):
    """The command writes files, seconds, scr, wear and person_minutes parquet plus qa.json
    under derived/eda/."""
    study, synth = _synthetic_root(tmp_path, monkeypatch)
    assert cli.main(["ingest-eda", str(study)]) == 0
    out = tmp_path / "data" / "synthetic-eda" / "derived" / "eda"
    for name in ("files", "seconds", "scr", "wear", "person_minutes"):
        assert (out / f"{name}.parquet").exists(), name
    qa = json.loads((out / "qa.json").read_text())
    assert qa["ingest"]["wear_bouts"] == synth.truth_wear.height
    assert qa["person_minutes"]["people"] == 1
    assert pl.read_parquet(out / "person_minutes.parquet")["scr_n"].sum() >= 1


def test_eda_heart_rate_cli_writes_only_its_own_tables(tmp_path, monkeypatch):
    """After ingest-eda, eda-heart-rate adds the hr_* tables and leaves the ingest's files
    byte for byte as they were; a later ingest-eda keeps the hr_* tables."""
    study, _ = _synthetic_root(tmp_path, monkeypatch)
    assert cli.main(["ingest-eda", str(study)]) == 0
    out = tmp_path / "data" / "synthetic-eda" / "derived" / "eda"
    before = {p.name: p.read_bytes() for p in out.iterdir()}
    assert cli.main(["eda-heart-rate", str(study)]) == 0
    hr = {"hr_beats", "hr_windows", "hr_minutes", "hr_agreement", "hr_usability"}
    for name in hr:
        assert (out / f"{name}.parquet").exists(), name
    assert {p.name: p.read_bytes() for p in out.iterdir() if p.name in before} == before
    qa = json.loads((out / "hr_qa.json").read_text())["heart_rate"]
    assert qa["windows_ok_worn_quality"] > 0
    assert pl.read_parquet(out / "hr_windows.parquet").filter("worn").height > 0
    assert cli.main(["ingest-eda", str(study)]) == 0
    assert all((out / f"{name}.parquet").exists() for name in hr)
