"""Shimmer Base calibrated CSV exports: parsing and repairing the export clock.

Hand-written exports with made-up values. The export clock is right for the first row and
right modulo 512 s afterwards (spurious whole wraps are inserted).
"""

import math

import numpy as np
import pytest

from social_energy.eda.export import export_span, read_export

UNITS = ["ms", "m/(s^2)", "m/(s^2)", "m/(s^2)", "no_units", "uS", "kOhms", "mV", "ms", "BPM"]
COLS = [
    "TimestampSync_Unix_CAL",
    "LIS2DW12_ACC_X_CAL",
    "LIS2DW12_ACC_Y_CAL",
    "LIS2DW12_ACC_Z_CAL",
    "GSR_Range_CAL",
    "GSR_Skin_Conductance_CAL",
    "GSR_Skin_Resistance_CAL",
    "PPG_A1_CAL",
    "PPG_IBI_CAL",
    "PPGtoHR_CAL",
]
T0_MS = 1_786_000_000_000.0
STEP = 1000 / 128


def close(a, b, atol=1e-6):
    """Absolute tolerance only: a relative one would accept hours on epoch-second times."""
    return np.allclose(a, b, rtol=0, atol=atol)


def write_export(path, stamps_ms, sep=",", us=2.0, hr=-1.0, device="SH07"):
    lines = [f'"sep={sep}"', sep.join(f"{device}_{c}" for c in COLS) + sep, sep.join(UNITS) + sep]
    for i, ts in enumerate(stamps_ms):
        u = us[i] if isinstance(us, list) else us
        h = hr[i] if isinstance(hr, list) else hr
        row = [ts, 0.0, 0.0, 9.81, 2.0, u, 1000 / u if u else 0.0, 1650.0, -1.0, h]
        lines.append(sep.join(repr(float(v)) for v in row) + sep)
    path.write_text("\n".join(lines) + "\n")


@pytest.mark.parametrize("sep", [",", "\t"])
def test_reads_device_columns_and_units(tmp_path, sep):
    """200 rows at exactly 128 Hz from T0: times are T0/1000 + i/128, conductance 2.0 uS,
    accelerometer 9.81 m/s^2 = 1.0003 g on z, PPG 1650 mV, no heart rate (-1 -> NaN)."""
    path = tmp_path / "day1_Session1_SH07_Calibrated_SD.csv"
    write_export(path, [T0_MS + i * STEP for i in range(200)], sep=sep)
    e = read_export(path)
    assert e.device == "SH07"
    assert close(e.t, T0_MS / 1000 + np.arange(200) / 128)
    assert close(e.conductance_us, 2.0) and e.gsr_valid.all()
    assert math.isclose(e.acc_g[0, 2], 9.81 / 9.80665, rel_tol=1e-9)
    assert np.isnan(e.hr_bpm).all()
    assert e.qa["segments"] == 1 and e.qa["records_bad"] == 0


def test_spurious_wraps_are_removed_and_a_later_segment_is_placed_modulo_512(tmp_path):
    """Rows 0-299 continuous. After row 149 the export inserts one spurious wrap (+512 s).
    After row 299 there is a real 100 s pause (beyond the 60 s step: a new segment), stamped
    with 3 more spurious wraps on top: the export says 100 + 4*512 s after row 299's stamp.
    True times: i/128 for i < 300; then 299/128 + 100 + (i - 300)/128.
    The new segment is placed at the smallest gap that agrees modulo 512 s (100 s) and is
    flagged ambiguous, since a gap over 60 s could hide whole wraps."""
    stamps = []
    for i in range(300):
        stamps.append(T0_MS + i * STEP + (512_000 if i >= 150 else 0))
    for j in range(200):
        stamps.append(stamps[299] + 100_000 + 3 * 512_000 + j * STEP)
    path = tmp_path / "x_SH07_Calibrated_SD.csv"
    write_export(path, stamps)
    e = read_export(path)
    true = np.r_[np.arange(300) / 128, 299 / 128 + 100 + np.arange(200) / 128] + T0_MS / 1000
    assert close(e.t, true)
    assert e.qa["segments"] == 2 and e.qa["segments_gap_ambiguous"] == 1
    assert e.gap_ambiguous[300:].all() and not e.gap_ambiguous[:300].any()


def test_saturated_and_sentinel_conductance_is_invalid(tmp_path):
    """125 uS is Shimmer's clamp (saturated); 0.00022 uS its open-input sentinel. Neither is a
    reading. 0.5 uS is."""
    path = tmp_path / "x_SH07_Calibrated_SD.csv"
    write_export(path, [T0_MS + i * STEP for i in range(200)], us=[125.0, 0.00022] + [0.5] * 198)
    e = read_export(path)
    assert e.gsr_valid.tolist() == [False, False] + [True] * 198
    assert np.isnan(e.conductance_us[:2]).all()


def test_heart_rate_where_the_export_has_it(tmp_path):
    path = tmp_path / "x_SH07_Calibrated_SD.csv"
    write_export(path, [T0_MS + i * STEP for i in range(200)], hr=[-1.0] * 100 + [72.0] * 100)
    e = read_export(path)
    assert np.isnan(e.hr_bpm[:100]).all() and np.allclose(e.hr_bpm[100:], 72.0)


def test_unsynced_devices_export_a_plain_timestamp(tmp_path):
    """Devices outside a sync group write Timestamp_Unix_CAL instead; same handling, and the
    file records which clock it carried."""
    path = tmp_path / "x_SH04_Calibrated_SD.csv"
    write_export(path, [T0_MS + i * STEP for i in range(200)], device="SH04")
    text = path.read_text().replace("SH04_TimestampSync_Unix_CAL", "SH04_Timestamp_Unix_CAL")
    path.write_text(text)
    e = read_export(path)
    assert close(e.t, T0_MS / 1000 + np.arange(200) / 128)
    assert e.qa["clock"] == "device"
    write_export(path, [T0_MS + i * STEP for i in range(200)], device="SH04")
    assert read_export(path).qa["clock"] == "sync"


def test_an_export_without_a_clock_is_unplaced_unless_given_a_start(tmp_path):
    """Every timestamp -1: no time at all (not 1969). With a start, row i sits at
    start + i / 128 and the clock is 'recovered'."""
    path = tmp_path / "day1_Session1_SH15_Calibrated_SD.csv"
    write_export(path, [-1.0] * 300)
    e = read_export(path)
    assert np.isnan(e.t).all() and e.qa["clock"] == "none"
    e = read_export(path, start_s=T0_MS / 1000)
    assert close(e.t, T0_MS / 1000 + np.arange(300) / 128)
    assert e.qa["clock"] == "recovered" and e.qa["records_bad"] == 0


def test_export_span_reads_only_the_first_and_last_rows(tmp_path):
    path = tmp_path / "x_SH07_Calibrated_SD.csv"
    write_export(path, [T0_MS + i * STEP for i in range(1000)])
    first, last = export_span(path)
    assert math.isclose(first, T0_MS / 1000) and math.isclose(last, (T0_MS + 999 * STEP) / 1000)
    write_export(path, [-1.0] * 10)
    assert export_span(path) == (None, None)
