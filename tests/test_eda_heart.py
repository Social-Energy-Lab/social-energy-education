"""Oracle test: synthetic SD cards (and a hand-written export) -> heart rate from the raw
PPG -> the true beats and rates come back; a dead sensor and unworn time are never good."""

import numpy as np
import polars as pl
import pytest

from social_energy.eda.heart import agreement, heart_rate, usability, with_heart_rate
from social_energy.eda.ingest import EdaConfig, ingest_eda
from social_energy.eda.person import person_minutes
from social_energy.spine import Spine
from social_energy.synth.eda import EdaSpec, generate_eda, pulse_wave


@pytest.fixture(scope="module")
def synth(tmp_path_factory):
    return generate_eda(EdaSpec(), tmp_path_factory.mktemp("eda"))


@pytest.fixture(scope="module")
def config(synth):
    day = synth.spec.start.date()
    return EdaConfig(
        valid_from=day,
        valid_to=day,
        mtime_to_utc_s=synth.spec.mtime_offset_s,
        rotation_s=synth.spec.chunk_s,
    )


@pytest.fixture(scope="module")
def tables(synth, config):
    return ingest_eda(synth.cards, [], config)


@pytest.fixture(scope="module")
def heart(synth, config, tables):
    return heart_rate(synth.cards, [], config, wear=tables.wear)


def _truth_hr(beats: np.ndarray, start: float, w: int = 10) -> float:
    """60 / median true interval of the beats in [start, start + w), counting the interval
    into the window's first beat."""
    inside = np.flatnonzero((beats >= start) & (beats < start + w))
    if len(inside) < 2:
        return float("nan")
    lo = max(inside[0] - 1, 0)
    return 60 / float(np.median(np.diff(beats[lo : inside[-1] + 1])))


def test_the_true_beats_come_back_where_the_sensor_works(synth, heart):
    """SH01's worn time: every true beat within 40 ms of an ok detected beat (placement plus
    the 128 Hz grid), and at most 1% extra detections."""
    truth = synth.truth_beats.filter(device="SH01")["t"].dt.epoch("us").to_numpy() / 1e6
    got = heart.beats.filter(pl.col("device") == "SH01", pl.col("ok"))
    got_t = np.sort(got["t"].dt.epoch("us").to_numpy() / 1e6)
    worn = got_t[(got_t >= truth[0] - 1) & (got_t <= truth[-1] + 1)]
    i = np.clip(np.searchsorted(worn, truth), 1, len(worn) - 1)
    err = np.minimum(np.abs(worn[i] - truth), np.abs(worn[i - 1] - truth))
    assert np.quantile(err, 0.99) < 0.040
    assert abs(len(worn) - len(truth)) <= 0.01 * len(truth)


def test_worn_windows_give_the_true_heart_rate(synth, heart):
    """SH01's worn, ok windows: at least 90% good quality, each good one within 2 bpm of the
    true rate."""
    truth = synth.truth_beats.filter(device="SH01")["t"].dt.epoch("us").to_numpy() / 1e6
    win = heart.windows.filter(pl.col("device") == "SH01", pl.col("ok"), pl.col("worn"))
    full = win.filter(pl.col("covered_s") >= 9.9)
    assert full["quality_ok"].mean() >= 0.9
    good = full.filter("quality_ok")
    want = np.array([_truth_hr(truth, t.timestamp()) for t in good["t"]])
    assert np.nanmax(np.abs(good["hr_bpm"].to_numpy() - want)) < 2.0


def test_a_dead_sensor_and_unworn_time_are_flagged_not_dropped(heart):
    """SH02's sensor is dead and SH01 is off skin outside its wear: their windows are all
    there, none good quality."""
    w = heart.windows.filter("ok")
    sh02 = w.filter(device="SH02")
    assert sh02.height > 200 and not sh02["quality_ok"].any()
    off = w.filter(pl.col("device") == "SH01", ~pl.col("worn"), pl.col("covered_s") >= 9.9)
    assert off.height > 50 and not off["quality_ok"].any()


def test_copies_and_late_runs_are_not_counted_twice(heart, synth):
    """The run copy is skipped; the run recorded after the study is unanchored, so it has no
    windows; each device-window appears once among the ok rows."""
    assert heart.qa["chunks_duplicate"] > 0
    ok = heart.windows.filter("ok")
    assert ok.select("device", "t").is_unique().all()
    assert heart.windows["implausible_time"].sum() == 0


def test_minutes_and_the_person_join(synth, heart, tables):
    """Device-minutes: SH01 worn minutes have hr_quality near 1 and the true rate; joined onto
    person-minutes, the existing columns are unchanged and hr_ppg_bpm is filled for SH01. The
    dead sensor's minutes are there with quality 0 and no rate."""
    m = heart.minutes.filter(pl.col("device") == "SH01", pl.col("worn"))
    assert m.filter(pl.col("hr_quality") >= 5 / 6).height >= 0.8 * m.height
    assert ((m["hr_bpm"].drop_nulls() > 60) & (m["hr_bpm"].drop_nulls() < 85)).all()
    dead = heart.minutes.filter(device="SH02")
    assert dead.height > 20 and (dead["hr_quality"] == 0).all() and dead["hr_bpm"].is_null().all()
    pm, _ = person_minutes(tables, Spine.load(synth.spine_dir))
    joined = with_heart_rate(pm, heart.minutes)
    assert joined.select(pm.columns).equals(pm)
    assert joined["hr_ppg_bpm"].drop_nulls().len() >= 0.8 * pm.height


def test_usability_tells_the_dead_sensor_apart(heart):
    u = usability(heart.windows)
    share = dict(zip(u["device"], u["good_share"], strict=True))
    assert share["SH01"] >= 0.85 and share["SH02"] == 0.0


def _export(path, t0: float, seconds: int, bpm: float, shimmer_hr: float):
    """A calibrated export of SH01 with a regular pulse at ``bpm`` and Shimmer's heart rate
    column at ``shimmer_hr`` (missing, -1, in the first 5 s)."""
    rel = np.arange(0, seconds, 1 / 128)
    ppg = 1400 + pulse_wave(rel, np.arange(0.5, seconds, 60 / bpm))
    hr = np.where(rel < 5, -1.0, shimmer_hr)
    lines = [
        '"sep=,"',
        "SH01_TimestampSync_Unix_CAL,SH01_LIS2DW12_ACC_X_CAL,SH01_LIS2DW12_ACC_Y_CAL,"
        "SH01_LIS2DW12_ACC_Z_CAL,SH01_GSR_Range_CAL,SH01_GSR_Skin_Conductance_CAL,"
        "SH01_GSR_Skin_Resistance_CAL,SH01_PPG_A1_CAL,SH01_PPG_IBI_CAL,SH01_PPGtoHR_CAL,",
        "ms,m/(s^2),m/(s^2),m/(s^2),no_units,uS,kOhms,mV,ms,BPM,",
    ]
    for r, p, h in zip(rel, ppg, hr, strict=True):
        lines.append(f"{(t0 + r) * 1000:.3f},0.0,0.0,9.8,1.0,2.0,500.0,{p:.4f},-1.0,{h:.1f},")
    path.write_text("\n".join(lines) + "\n")
    return path


def test_agreement_against_the_exports_heart_rate(synth, config, tables, tmp_path):
    """An export of SH01, 120 s at 75 bpm, before the SD recording starts, with Shimmer's
    heart rate 78 throughout: on the export's samples our rate is 75, so the bias is -3 bpm
    with near-zero spread, and the 5 s without Shimmer's rate are not compared."""
    t0 = synth.spec.start.timestamp() - 600
    path = _export(tmp_path / "day_Session1_SH01_Calibrated_SD.csv", t0, 120, 75.0, 78.0)
    h = heart_rate(synth.cards[:1], [path], config, wear=None)
    ex = h.windows.filter(source="export")
    assert ex.height == 12 and ex["ok"].all()
    assert abs(ex["hr_export_bpm"].drop_nulls().mean() - 78) < 1e-6
    a = agreement(h.windows).filter(samples="export", device="all").row(0, named=True)
    assert a["n"] >= 10
    assert abs(a["bias_bpm"] + 3) < 0.3 and a["sd_bpm"] < 0.3 and abs(a["mae_bpm"] - 3) < 0.3


def test_sd_wins_over_an_export_of_the_same_windows(synth, config, tmp_path):
    """An export of SH01 inside its worn SD time: those windows keep the SD row (the export's
    are flagged duplicate), and the SD-sample agreement compares the SD rate with Shimmer's."""
    t0 = synth.spec.start.timestamp() + 600
    path = _export(tmp_path / "day_Session1_SH01_Calibrated_SD.csv", t0, 60, 72.0, 72.0)
    h = heart_rate(synth.cards[:1], [path], config)
    ex = h.windows.filter(source="export")
    assert ex["duplicate"].sum() >= 5
    sd = agreement(h.windows).filter(samples="sd", device="SH01")
    assert sd["n"].sum() >= 3
    assert h.windows.filter("ok").select("device", "t").is_unique().all()
