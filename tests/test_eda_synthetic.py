"""Oracle test: synthetic SD cards → EDA ingest → spine → the true wear and SCRs come back."""

from datetime import timedelta

import numpy as np
import polars as pl
import pytest

from social_energy.eda.ingest import EdaConfig, ingest_eda
from social_energy.eda.person import person_minutes
from social_energy.spine import Spine
from social_energy.synth.eda import EdaSpec, generate_eda


@pytest.fixture(scope="module")
def synth(tmp_path_factory):
    return generate_eda(EdaSpec(), tmp_path_factory.mktemp("eda"))


@pytest.fixture(scope="module")
def tables(synth):
    day = synth.spec.start.date()
    config = EdaConfig(
        valid_from=day,
        valid_to=day,
        mtime_to_utc_s=synth.spec.mtime_offset_s,
        rotation_s=synth.spec.chunk_s,
    )
    return ingest_eda(synth.cards, [], config)


def test_copies_are_read_once_and_the_late_run_is_unanchored(synth, tables):
    dup = tables.files.filter("duplicate")
    assert dup.height > 0 and dup["run"].str.ends_with(" 2").all()
    assert tables.qa["sd_records_unanchored"] == 2 * 3800  # one late run per device
    assert tables.qa["seconds_implausible"] == 0


def test_the_traps_are_actually_present(tables):
    assert tables.qa["sd_records_zero"] > 0 and tables.qa["sd_records_bad"] > 0
    assert tables.files.filter(pl.col("truncated")).height == 2


def test_wear_bouts_match_the_truth(synth, tables):
    """Each device's bout starts and ends within 2 s of when the electrodes met the skin."""
    got = tables.wear.sort("device")
    want = synth.truth_wear.sort("device")
    assert got["device"].to_list() == want["device"].to_list()
    for g, w in zip(got.iter_rows(named=True), want.iter_rows(named=True), strict=True):
        assert abs(g["start"] - w["start"]) <= timedelta(seconds=2)
        assert abs(g["end"] - w["end"]) <= timedelta(seconds=2)


def test_scr_onsets_and_amplitudes_match_the_truth(synth, tables):
    """Every true SCR is found within 1 s, with no extra ones, amplitudes within 15%."""
    got = tables.scr.filter(pl.col("ok") & pl.col("worn")).sort("device", "onset")
    want = synth.truth_scr.sort("device", "onset")
    assert got.height == want.height
    dt = (got["onset"] - want["onset"]).dt.total_milliseconds().abs().to_numpy()
    assert (dt <= 1000).all()
    assert np.allclose(got["amplitude_us"], want["amplitude_us"], rtol=0.15, atol=0)


def test_person_minutes_respect_consent(synth, tables):
    """Only the consenting wearer (SH01) appears, one row per observable minute of wear, with
    every observable SCR of theirs."""
    minutes, qa = person_minutes(tables, Spine.load(synth.spine_dir))
    assert minutes["entity"].unique().to_list() == ["person:11"]
    wear = synth.truth_wear.filter(device="SH01")
    worn_min = sum((r["end"] - r["start"]).total_seconds() for r in wear.iter_rows(named=True))
    assert abs(minutes.height - worn_min / 60) <= 1
    assert minutes["scr_n"].sum() == synth.truth_scr.filter(device="SH01").height
    assert qa["worn_seconds_no_consent"] > 0


def test_an_export_of_the_same_seconds_loses_to_the_sd_card(synth, tmp_path):
    """An export of SH01 covering the run's first 120 s plus 60 s before it: the 120 shared
    seconds (one more if the boundary second is shared: placement is sub-second, not exact)
    keep the SD row (export rows flagged duplicate); the 60 earlier seconds exist only
    in the export and stay ok. The export carries heart rate, which the SD rows lack."""
    t0 = synth.spec.start.timestamp() - 60
    lines = [
        '"sep=,"',
        "SH01_TimestampSync_Unix_CAL,SH01_LIS2DW12_ACC_X_CAL,SH01_LIS2DW12_ACC_Y_CAL,"
        "SH01_LIS2DW12_ACC_Z_CAL,SH01_GSR_Range_CAL,SH01_GSR_Skin_Conductance_CAL,"
        "SH01_GSR_Skin_Resistance_CAL,SH01_PPG_A1_CAL,SH01_PPG_IBI_CAL,SH01_PPGtoHR_CAL,",
        "ms,m/(s^2),m/(s^2),m/(s^2),no_units,uS,kOhms,mV,ms,BPM,",
    ]
    for i in range(180 * 128):
        lines.append(f"{(t0 + i / 128) * 1000!r},0.0,0.0,9.8,3.0,0.01,100000.0,1500.0,-1.0,70.0,")
    path = tmp_path / "day_Session1_SH01_Calibrated_SD.csv"
    path.write_text("\n".join(lines) + "\n")
    day = synth.spec.start.date()
    config = EdaConfig(day, day, mtime_to_utc_s=synth.spec.mtime_offset_s, rotation_s=600)
    tables = ingest_eda(synth.cards[:1], [path], config)
    exp = tables.seconds.filter(source="export")
    assert exp.height == 180
    assert 120 <= exp["duplicate"].sum() <= 121  # the boundary second may be shared
    assert not tables.seconds.filter(source="sd")["duplicate"].any()
    assert exp.filter(~pl.col("duplicate"))["hr_bpm"].drop_nulls().mean() == 70.0
