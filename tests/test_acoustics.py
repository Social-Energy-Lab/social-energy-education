"""AudioMoth feature extraction: features only, verified, then (optionally) delete the WAV.

The ethics approval requires WAVs to be deleted once frequency/level features exist.
"""

from datetime import UTC, datetime

import numpy as np
import polars as pl
import pytest

from social_energy.acoustics import AcousticsConfig, extract_directory, extract_features
from social_energy.synth.audio import audiomoth_comment, tone_with_bursts, write_wav

SR = 8000


@pytest.fixture
def wav(tmp_path):
    samples = tone_with_bursts(10, SR, loud_from_s=4, loud_to_s=6)
    return write_wav(
        tmp_path / "20260814_082000.WAV",
        samples,
        SR,
        audiomoth_comment(datetime(2026, 8, 14, 8, 20, 0), "UTC+2"),
    )


def test_one_row_per_window_with_absolute_utc_time(wav):
    features = extract_features(wav, AcousticsConfig(window_s=1.0))
    assert features.height == 10
    # 08:20:00 at UTC+2 → 06:20:00 UTC
    assert features["t"][0] == datetime(2026, 8, 14, 6, 20, 0, tzinfo=UTC)
    assert features["t"][9] == datetime(2026, 8, 14, 6, 20, 9, tzinfo=UTC)


def test_loud_burst_is_visible_in_level_features(wav):
    features = extract_features(wav, AcousticsConfig(window_s=1.0))
    rms = features["rms_dbfs"].to_numpy()
    assert rms[4:6].min() > rms[[0, 1, 2, 8, 9]].max() + 20
    # broadband burst raises spectral flatness compared with the tonal background
    flat = features["spectral_flatness"].to_numpy()
    assert flat[4:6].min() > flat[[0, 1, 2, 8, 9]].max()


def test_no_waveform_or_fine_spectrum_is_stored(wav):
    features = extract_features(wav, AcousticsConfig(window_s=1.0))
    band_cols = [c for c in features.columns if c.startswith("band_")]
    assert 3 <= len(band_cols) <= 8  # coarse bands only; not invertible to speech
    assert all(features[c].dtype.is_numeric() for c in features.columns if c != "t")


def test_filename_time_is_used_when_no_comment(tmp_path):
    path = write_wav(tmp_path / "20260814_082000.WAV", np.zeros(SR * 2), SR, comment=None)
    features = extract_features(path, AcousticsConfig(window_s=1.0, filename_timezone="UTC"))
    assert features["t"][0] == datetime(2026, 8, 14, 8, 20, 0, tzinfo=UTC)


def test_directory_extraction_keeps_wavs_by_default(tmp_path, wav):
    out = tmp_path / "features"
    manifest = extract_directory(tmp_path, out, AcousticsConfig(), delete_wavs=False)
    assert wav.exists()
    assert manifest.height == 1
    assert manifest["deleted"].to_list() == [False]
    assert pl.read_parquet(out / "20260814_082000.parquet").height == 10


def test_directory_extraction_deletes_only_after_verified_features(tmp_path, wav):
    out = tmp_path / "features"
    manifest = extract_directory(tmp_path, out, AcousticsConfig(), delete_wavs=True)
    assert not wav.exists()
    row = manifest.row(0, named=True)
    assert row["deleted"] is True
    assert len(row["wav_sha256"]) == 64
    assert row["windows"] == 10
    # manifest persisted next to the features for the audit trail
    assert pl.read_parquet(out / "manifest.parquet").height == 1


def test_corrupt_wav_is_reported_and_never_deleted(tmp_path):
    bad = tmp_path / "20260814_090000.WAV"
    bad.write_bytes(b"RIFF....not a wav")
    manifest = extract_directory(tmp_path, tmp_path / "f", AcousticsConfig(), delete_wavs=True)
    assert bad.exists()
    row = manifest.row(0, named=True)
    assert row["deleted"] is False
    assert row["error"]


def test_cli_extracts_per_device_and_deletes_on_request(tmp_path, monkeypatch):
    import yaml

    from social_energy import cli

    data_root = tmp_path / "root"
    device = data_root / "toy" / "raw" / "audiomoth" / "plenum"
    device.mkdir(parents=True)
    samples = tone_with_bursts(3, SR, loud_from_s=1, loud_to_s=2)
    wav = write_wav(
        device / "20260814_082000.WAV", samples, SR, audiomoth_comment(datetime(2026, 8, 14, 8, 20))
    )
    study = tmp_path / "study.yaml"
    study.write_text(yaml.safe_dump({"study_id": "toy", "timezone": "Europe/Berlin"}))
    monkeypatch.setenv("SOCIAL_ENERGY_DATA", str(data_root))

    assert cli.main(["extract-acoustics", str(study)]) == 0
    assert wav.exists()
    assert cli.main(["extract-acoustics", str(study), "--delete-wavs"]) == 0
    assert not wav.exists()
    features = data_root / "toy" / "derived" / "acoustics" / "plenum" / "20260814_082000.parquet"
    assert pl.read_parquet(features).height == 3
