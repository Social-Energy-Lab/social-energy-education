"""Purged devices: the ingest refuses raw logs that still name one; ``purge-device`` cleans them.

A device's records can be removed from the raw logs by ruling (for example, collected without
consent). A later re-import of the delivery would silently restore them, so the study's private
``local.yaml`` lists purged devices under ``beacons.purged_devices`` and every ingest path refuses
logs that name one as ``ID`` or ``ID2``. Refusing, not dropping: the raw files must be cleaned.

All logs here are hand-written in tmp_path. Device 14 is the purged one; 140 and 147 share its
leading digits and must survive both the guard and the purge.
"""

from __future__ import annotations

import hashlib
from datetime import date
from pathlib import Path

import pytest
import yaml

from social_energy import cli
from social_energy.beacons import (
    BeaconConfig,
    PurgedDeviceError,
    find_purged_lines,
    ingest_logs,
    ingest_logs_to,
    ingest_with_witnesses,
)
from social_energy.study import StudyConfig

# Lines naming 14: line 2-6 (ID: 14 header + records) in a.log is 5 lines; in b.log the contact
# "ID2: 14" on line 4 is 1 line. Total 6 lines, in 2 files.
A_LOG = """\
2026-08-14 12:00:00,ID: 140,Current Timer: 7200
2026-08-14 12:01:00,ID: 14,Status: 0
2026-08-14 12:01:00,ID: 14,Current Timer: 3600
2026-08-14 12:01:00,ID: 14,Contact Count: 1
2026-08-14 12:01:00,ID: 14,Voltage: 3000
2026-08-14 12:01:00,ID: 14,ID2: 140, Timer: 3000, RSSI: -70
2026-08-14 12:00:00,ID: 140,ID2: 147, Timer: 7000, RSSI: -60
"""
B_LOG = """\
2026-08-14 13:00:00,ID: 147,Status: 0
2026-08-14 13:00:00,ID: 147,Current Timer: 9000
2026-08-14 13:00:00,ID: 147,Contact Count: 2
2026-08-14 13:00:00,ID: 147,ID2: 14, Timer: 8000, RSSI: -80
2026-08-14 13:00:00,ID: 147,ID2: 140, Timer: 8500, RSSI: -75
"""
CLEAN_A = [line for line in A_LOG.splitlines() if ",ID: 14," not in line]
CLEAN_B = [line for line in B_LOG.splitlines() if ",ID2: 14," not in line]

CONFIG = BeaconConfig(
    timezone="Europe/Berlin",
    valid_from=date(2026, 8, 12),
    valid_to=date(2026, 8, 29),
    purged_devices=(14,),
)


def _logs(folder: Path) -> list[Path]:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "a.log").write_text(A_LOG, encoding="utf-8")
    (folder / "b.log").write_text(B_LOG, encoding="utf-8")
    return [folder / "a.log", folder / "b.log"]


def test_find_purged_lines_counts_id_and_id2_but_not_longer_ids(tmp_path):
    found = find_purged_lines(_logs(tmp_path), [14])
    assert {(p.name, n): c for (p, n), c in found.items()} == {("a.log", 14): 5, ("b.log", 14): 1}
    assert find_purged_lines(_logs(tmp_path), [148]) == {}


def test_a_doubled_comma_after_the_header_still_counts(tmp_path):
    log = tmp_path / "c.log"
    log.write_text("2026-08-14 12:00:00,ID: 14,,Current Timer: 1\n", encoding="utf-8")
    assert sum(find_purged_lines([log], [14]).values()) == 1


def test_ingest_refuses_logs_naming_a_purged_device(tmp_path):
    with pytest.raises(PurgedDeviceError) as err:
        ingest_logs(_logs(tmp_path), CONFIG)
    message = str(err.value)
    assert "device 14" in message
    assert "6 lines" in message
    assert "IMPORT.md" in message


def test_file_by_file_ingest_refuses_before_writing_anything(tmp_path):
    out = tmp_path / "out"
    with pytest.raises(PurgedDeviceError, match="device 14"):
        ingest_logs_to(_logs(tmp_path / "raw"), CONFIG, out)
    assert not out.exists()
    with pytest.raises(PurgedDeviceError, match="6 lines"):
        ingest_with_witnesses(_logs(tmp_path / "raw"), CONFIG, out)
    assert not out.exists()


def test_ingest_accepts_cleaned_logs_and_ids_sharing_the_digits(tmp_path):
    (tmp_path / "a.log").write_text("\n".join(CLEAN_A) + "\n", encoding="utf-8")
    (tmp_path / "b.log").write_text("\n".join(CLEAN_B) + "\n", encoding="utf-8")
    tables = ingest_logs([tmp_path / "a.log", tmp_path / "b.log"], CONFIG)
    assert set(tables.contacts["beacon"].to_list()) == {140, 147}
    assert 14 not in tables.contacts["observed"].to_list()


def test_no_purged_devices_means_no_check(tmp_path):
    from dataclasses import replace

    tables = ingest_logs(_logs(tmp_path), replace(CONFIG, purged_devices=()))
    assert 14 in tables.contacts["beacon"].to_list()


# ---- study config --------------------------------------------------------------------------

PUBLIC = {
    "study_id": "synthetic-camp",
    "timezone": "Europe/Berlin",
    "beacons": {"valid_from": "2026-08-12", "valid_to": "2026-08-29"},
}


def _study(tmp_path: Path, public: dict | None = None, local: str | None = None) -> Path:
    study = tmp_path / "studies" / "synthetic-camp"
    study.mkdir(parents=True)
    (study / "study.yaml").write_text(yaml.safe_dump(public or PUBLIC), encoding="utf-8")
    root = tmp_path / "data" / "synthetic-camp"
    root.mkdir(parents=True)
    if local is not None:
        (root / "local.yaml").write_text(local, encoding="utf-8")
    return study / "study.yaml"


def test_purged_devices_come_from_local_yaml(tmp_path, monkeypatch):
    path = _study(tmp_path, local="beacons:\n  purged_devices: [14, 99]\n")
    monkeypatch.setenv("SOCIAL_ENERGY_DATA", str(tmp_path / "data"))
    assert StudyConfig.load(path).beacon_config().purged_devices == (14, 99)


def test_no_local_yaml_means_nothing_purged(tmp_path, monkeypatch):
    monkeypatch.delenv("SOCIAL_ENERGY_DATA", raising=False)
    path = _study(tmp_path)
    assert StudyConfig.load(path).beacon_config().purged_devices == ()


def test_public_study_yaml_may_not_list_purged_devices(tmp_path, monkeypatch):
    """Who was purged is a fact about a person's consent: never in the public file."""
    public = {**PUBLIC, "beacons": {**PUBLIC["beacons"], "purged_devices": [14]}}
    path = _study(tmp_path, public=public)
    monkeypatch.setenv("SOCIAL_ENERGY_DATA", str(tmp_path / "data"))
    with pytest.raises(ValueError, match=r"local\.yaml"):
        StudyConfig.load(path)


# ---- CLI -----------------------------------------------------------------------------------


def _camp(tmp_path: Path, monkeypatch) -> tuple[Path, Path]:
    path = _study(tmp_path, local="beacons:\n  purged_devices: [14]\n")
    monkeypatch.setenv("SOCIAL_ENERGY_DATA", str(tmp_path / "data"))
    raw = tmp_path / "data" / "synthetic-camp" / "raw" / "beacons"
    logs = _logs(raw / "delivery")
    sums = [f"{hashlib.sha256(p.read_bytes()).hexdigest()}  delivery/{p.name}" for p in logs]
    (raw / "SHA256SUMS").write_text("\n".join(sums) + "\n", encoding="utf-8")
    (raw / "IMPORT.md").write_text("# Import\n", encoding="utf-8")
    return path, raw


def test_ingest_beacons_cli_refuses_and_exits_non_zero(tmp_path, monkeypatch, capsys):
    path, _ = _camp(tmp_path, monkeypatch)
    derived = tmp_path / "data" / "synthetic-camp" / "derived" / "beacons"
    derived.mkdir(parents=True)
    (derived / "keep.txt").write_text("previous run", encoding="utf-8")

    assert cli.main(["ingest-beacons", str(path)]) != 0
    printed = capsys.readouterr().out
    assert "device 14" in printed and "6 lines" in printed and "IMPORT.md" in printed
    assert (derived / "keep.txt").exists()  # refused before touching derived/


def test_purge_device_dry_run_changes_nothing(tmp_path, monkeypatch, capsys):
    path, raw = _camp(tmp_path, monkeypatch)
    before = {p: p.read_bytes() for p in raw.rglob("*") if p.is_file()}

    assert cli.main(["purge-device", str(path), "--device", "14"]) == 0
    printed = capsys.readouterr().out
    assert "dry run" in printed.lower()
    assert "delivery/a.log: 5" in printed and "delivery/b.log: 1" in printed
    assert {p: p.read_bytes() for p in raw.rglob("*") if p.is_file()} == before


def test_purge_device_apply_cleans_logs_and_records_it(tmp_path, monkeypatch, capsys):
    path, raw = _camp(tmp_path, monkeypatch)
    delivered = (raw / "SHA256SUMS").read_text(encoding="utf-8")

    assert cli.main(["purge-device", str(path), "--device", "14", "--apply"]) == 0
    capsys.readouterr()

    assert (raw / "delivery" / "a.log").read_text(encoding="utf-8").splitlines() == CLEAN_A
    assert (raw / "delivery" / "b.log").read_text(encoding="utf-8").splitlines() == CLEAN_B
    assert (raw / "SHA256SUMS.as-delivered").read_text(encoding="utf-8") == delivered
    for line in (raw / "SHA256SUMS").read_text(encoding="utf-8").splitlines():
        digest, name = line.split("  ", 1)
        assert hashlib.sha256((raw / name).read_bytes()).hexdigest() == digest
    record = (raw / "IMPORT.md").read_text(encoding="utf-8")
    assert "device 14" in record and "6 lines" in record

    # The ingest now runs.
    assert cli.main(["ingest-beacons", str(path)]) == 0

    # A second purge keeps the first, as-delivered manifest.
    assert cli.main(["purge-device", str(path), "--device", "147", "--apply"]) == 0
    assert (raw / "SHA256SUMS.as-delivered").read_text(encoding="utf-8") == delivered
