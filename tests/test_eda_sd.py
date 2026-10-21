"""Shimmer SD chunk decoding and calibration, on hand-built chunks (made-up values)."""

import math
import struct

import numpy as np
import pytest

from social_energy.eda import calibration, sd


def _record(tick, ax=0, ay=0, az=8192, ppg=2000, rng=2, adc=2048):
    return (
        tick.to_bytes(3, "little")
        + struct.pack("<hhh", ax, ay, az)
        + struct.pack("<H", ppg)
        + struct.pack("<H", (rng << 14) | adc)
    )


def _chunk(records: list[bytes], tail: bytes = b"") -> bytes:
    header = bytearray(sd.HEADER_BYTES)
    header[0:2] = (256).to_bytes(2, "little")  # 32768 / 256 = 128 Hz
    body = b""
    for i in range(0, len(records), sd.RECORDS_PER_BLOCK):
        block = records[i : i + sd.RECORDS_PER_BLOCK]
        assert len(block) == sd.RECORDS_PER_BLOCK
        body += b"\xff" * sd.FILLER_BYTES + b"".join(block)
    return bytes(header) + body + tail


def test_layout_constants_give_the_full_hour_size():
    """384 + 12127 blocks x 503 bytes = 6,100,265 bytes, 12127 x 38 = 460,826 samples."""
    assert sd.HEADER_BYTES + 12127 * sd.BLOCK_BYTES == 6_100_265
    assert 12127 * sd.RECORDS_PER_BLOCK == 460_826


def test_read_chunk_decodes_every_field(tmp_path):
    """Two blocks (76 records). Record 0: tick 1000, accel (8192, -8192, 0) = (1, -1, 0) g,
    PPG 1234, GSR range 3, ADC 1365. A 7-byte partial block after them is reported, not read."""
    recs = [_record(1000 + 256 * i) for i in range(76)]
    recs[0] = _record(1000, ax=8192, ay=-8192, az=0, ppg=1234, rng=3, adc=1365)
    path = tmp_path / "000"
    path.write_bytes(_chunk(recs, tail=b"\x01" * 7))
    c = sd.read_chunk(path)
    assert c.sample_rate_hz == 128
    assert len(c.ticks) == 76 and c.trailing_bytes == 7
    assert c.ticks[0] == 1000 and c.ticks[75] == 1000 + 256 * 75
    assert tuple(c.acc[0]) == (8192, -8192, 0)
    assert c.ppg[0] == 1234 and c.gsr_range[0] == 3 and c.gsr_adc[0] == 1365
    assert not c.zero.any()


def test_all_zero_records_are_marked(tmp_path):
    recs = [_record(256 * i) for i in range(38)]
    recs[5] = b"\x00" * sd.RECORD_BYTES
    path = tmp_path / "000"
    path.write_bytes(_chunk(recs))
    c = sd.read_chunk(path)
    assert c.zero.tolist() == [i == 5 for i in range(38)]


def test_find_runs_reads_only_run_chunks_and_names_the_device(tmp_path):
    """Session level optional; OS clutter and copy temporaries ignored; ' 2' runs kept apart."""
    card = tmp_path / "SH03"
    for rel in [
        "data/day1_1/SH03-000/000",
        "data/day1_1/SH03-000/001",
        "data/day1_1/SH03-000 2/000",
        "data/SH03-001/000",
        "data/SH03-001/.006.tmpcopy",
        "data/day1_1/SH03-000/.DS_Store",
        "data/.Spotlight-V100/Store-V2/x/000",
    ]:
        (card / rel).parent.mkdir(parents=True, exist_ok=True)
        (card / rel).write_bytes(b"x")
    runs = sd.find_runs(card)
    assert [(r.device, r.name, [p.name for p in r.chunks]) for r in runs] == [
        ("SH03", "SH03-001", ["000"]),
        ("SH03", "day1_1/SH03-000", ["000", "001"]),
        ("SH03", "day1_1/SH03-000 2", ["000"]),
    ]


@pytest.mark.parametrize(
    ("rng", "adc", "expected_us"),
    [
        # R = Rf / (adc*6/4095 - 1) kOhm; uS = 1000 / R. Values checked against the export.
        (1, 1481, 4.0765306),  # Rf 287 kOhm
        (2, 2028, 1.9714286),  # Rf 1 MOhm
        (3, 698, 0.0068820),  # Rf 3.3 MOhm, just above the open-circuit edge
        (0, 2000, 1000 * (2000 * 6 / 4095 - 1) / 40.2),  # Rf 40.2 kOhm: R = 20.8 kOhm
    ],
)
def test_gsr_conversion(rng, adc, expected_us):
    us = calibration.gsr_microsiemens(np.array([rng]), np.array([adc]))[0]
    assert math.isclose(us, expected_us, rel_tol=1e-6)


def test_gsr_floor_and_invalid_adc():
    """Range 0, ADC 4095: R = 40.2/5 = 8.04 kOhm, kept (124.4 uS). Range 0, ADC 3700:
    R = 40.2/4.421 = 9.09 kOhm, kept. Range 0 can go below 8 kOhm only if Rf were smaller, so
    the floor is tested on a fake Rf through the module constant. Invalid: ADC 0, ADC > 4095,
    and ADC <= 682 (adc*6/4095 - 1 <= 0: open circuit or saturated, no resistance)."""
    us = calibration.gsr_microsiemens(
        np.array([0, 0, 2, 2, 3, 2]), np.array([4095, 0, 5000, 682, 600, 683])
    )
    assert math.isclose(us[0], 1000 / 8.04, rel_tol=1e-9)
    assert np.isnan(us[1:5]).all()
    assert math.isclose(us[5], 1000 * (683 * 6 / 4095 - 1) / 1000.0, rel_tol=1e-9)


def test_gsr_floor_clamps_to_125_us(monkeypatch):
    """With Rf 4 kOhm and ADC 4095, R = 4/5 = 0.8 kOhm < 8 kOhm, so R = 8 and uS = 125."""
    monkeypatch.setattr(calibration, "GSR_FEEDBACK_KOHM", (4.0, 287.0, 1000.0, 3300.0))
    assert calibration.gsr_microsiemens(np.array([0]), np.array([4095]))[0] == 125.0


def test_accel_and_ppg_units():
    assert calibration.accel_g(np.array([8192, -4096])).tolist() == [1.0, -0.5]
    assert math.isclose(calibration.ppg_mv(np.array([2250]))[0], 1648.3516483516482)
