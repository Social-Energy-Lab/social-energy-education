"""The study's EDA config and `social-energy ingest-eda` on a synthetic data root."""

import json
import shutil
from datetime import date
from pathlib import Path

import polars as pl
import yaml

from social_energy import cli
from social_energy.study import StudyConfig
from social_energy.synth.eda import EdaSpec, generate_eda

REPO = Path(__file__).resolve().parents[1]


def test_dsa_study_config_builds_eda_config():
    eda = StudyConfig.load(REPO / "studies" / "dsa-2026" / "study.yaml").eda_config()
    assert eda.valid_from == date(2026, 8, 14) and eda.valid_to == date(2026, 8, 29)
    assert eda.rotation_s == 3600
    assert 7199 < eda.mtime_to_utc_s < 7203


def test_ingest_eda_cli_writes_tables_and_person_minutes(tmp_path, monkeypatch):
    """Cards under raw/eda/sd-cards/, spine under spine/: the command writes files, seconds,
    scr, wear and person_minutes parquet plus qa.json under derived/eda/."""
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
    assert cli.main(["ingest-eda", str(study / "study.yaml")]) == 0
    out = root / "synthetic-eda" / "derived" / "eda"
    for name in ("files", "seconds", "scr", "wear", "person_minutes"):
        assert (out / f"{name}.parquet").exists(), name
    qa = json.loads((out / "qa.json").read_text())
    assert qa["ingest"]["wear_bouts"] == synth.truth_wear.height
    assert qa["person_minutes"]["people"] == 1
    assert pl.read_parquet(out / "person_minutes.parquet")["scr_n"].sum() >= 1
