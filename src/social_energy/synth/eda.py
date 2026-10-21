"""Synthetic Shimmer SD cards with known ground truth (wear, SCRs, who wore what, clocks).

The cards use the real binary format (``social_energy.eda.sd``) and reproduce the traps found
on real cards: all-zero records, a burst of out-of-sequence ticks, a ~28.7 s sampling pause,
a chunk that lost its tail, a run copied as ``<run> 2``, and a run recorded after the study
(its modification time is outside the window).

Clocks: each device has its own clock (``EdaSpec.clocks``): an offset at the start and a
rate (negative = slow), so its records, chunk headers and modification times are all on that
clock. One device is the sync master; every ``sync_every_s`` of device time a slave writes
its offset to the master into a block's sync slot, as real cards do. A plausible-looking but
wrong record and one in a corrupt block test the screening. At the end the devices lie
together (``box_from_min``) and share motion bursts: the co-motion check. Optional exports
(``exports``): one with the device's clock plus a constant, one with no clock at all.

The optical pulse (PPG) has known beats while a device is worn: a two-wave pulse per beat at
a heart rate that drifts and jitters, on a wandering baseline. Off skin, and on a device whose
sensor is dead (``dead_ppg``), it is sensor noise only, as on the real cards. The beats are
true times; a device's samples of them carry its clock. Values are invented.
"""

from __future__ import annotations

import os
import shutil
import struct
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from itertools import pairwise
from pathlib import Path

import numpy as np
import polars as pl
import yaml

from ..eda.calibration import ADC_MAX, GSR_FEEDBACK_KOHM
from ..eda.export import STANDARD_GRAVITY
from ..eda.sd import (
    BLOCK_BYTES,
    FILLER_BYTES,
    HEADER_BYTES,
    HEADER_CONFIG_TIME,
    HEADER_MASTER_BYTE,
    HEADER_RTC_DIFF,
    HEADER_START_HIGH,
    HEADER_START_LOW,
    HEADER_SYNC_BYTE,
    MASTER_FLAG,
    RECORDS_PER_BLOCK,
    TICK_HZ,
    TICK_WRAP,
)

RATE = 128
PAUSE_TICKS = 940544  # 28.703125 s


def encode_header(
    start_ticks: int = 0, rtc_diff_ticks: int = 0, master: bool = False, sync_on: bool = False
) -> bytes:
    """A 384-byte chunk header: 128 Hz, the device clock at the first record (``start_ticks``,
    ticks since the epoch, stored as 40 bits above ``rtc_diff_ticks``), the sync flags."""
    h = bytearray(HEADER_BYTES)
    h[0:2] = struct.pack("<H", TICK_HZ // RATE)
    h[HEADER_MASTER_BYTE] = MASTER_FLAG if master else 0x35
    h[HEADER_SYNC_BYTE] = 1 if sync_on else 0
    h[HEADER_RTC_DIFF] = rtc_diff_ticks.to_bytes(8, "big")
    h[HEADER_CONFIG_TIME] = (rtc_diff_ticks // TICK_HZ).to_bytes(4, "big")
    lt = (start_ticks - rtc_diff_ticks) if start_ticks else 0
    h[HEADER_START_HIGH] = (lt >> 32) & 0xFF
    h[HEADER_START_LOW] = (lt & 0xFFFFFFFF).to_bytes(4, "little")
    return bytes(h)


def sync_slot(offset_s: float) -> bytes:
    """A block's 9-byte sync slot holding ``device - master`` (s)."""
    ticks = round(abs(offset_s) * TICK_HZ)
    return bytes([1 if offset_s < 0 else 0]) + ticks.to_bytes(8, "little")


def encode_chunk(
    ticks: np.ndarray,
    acc: np.ndarray,
    ppg: np.ndarray,
    gsr_range: np.ndarray,
    gsr_adc: np.ndarray,
    zero: np.ndarray | None = None,
    tail: bytes = b"",
    header: bytes | None = None,
    slots: dict[int, bytes] | None = None,
) -> bytes:
    """Bytes of one SD chunk. Records beyond the last full block are not written. ``slots``
    maps block index -> 9-byte sync slot (default ``0xFF``)."""
    n = len(ticks) - len(ticks) % RECORDS_PER_BLOCK
    rec = np.zeros((n, 13), np.uint8)
    t = np.asarray(ticks[:n], np.int64) % TICK_WRAP
    rec[:, 0], rec[:, 1], rec[:, 2] = t & 0xFF, (t >> 8) & 0xFF, (t >> 16) & 0xFF
    rec[:, 3:9] = np.asarray(acc[:n], "<i2").view(np.uint8).reshape(n, 6)
    rec[:, 9:11] = np.asarray(ppg[:n], "<u2").view(np.uint8).reshape(n, 2)
    g = (np.asarray(gsr_range[:n], np.int64) << 14) | np.asarray(gsr_adc[:n], np.int64)
    rec[:, 11:13] = g.astype("<u2").view(np.uint8).reshape(n, 2)
    if zero is not None:
        rec[np.asarray(zero[:n], bool)] = 0
    blocks = rec.reshape(-1, RECORDS_PER_BLOCK * 13)
    filler = np.full((len(blocks), FILLER_BYTES), 0xFF, np.uint8)
    for b, slot in (slots or {}).items():
        if b < len(blocks):
            filler[b] = np.frombuffer(slot, np.uint8)
    if header is None:
        header = encode_header()
    return header + np.hstack([filler, blocks]).tobytes() + tail


def gsr_raw(us: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Range and ADC that encode each conductance: the most sensitive range that fits."""
    us = np.asarray(us, float)
    r_kohm = 1000.0 / us
    rng = np.zeros(len(us), np.int64)
    adc = np.zeros(len(us), np.int64)
    for k, rf in enumerate(GSR_FEEDBACK_KOHM):
        a = np.rint(ADC_MAX / 6 * (1 + rf / r_kohm)).astype(np.int64)
        fits = a <= 4000
        rng = np.where(fits, k, rng)
        adc = np.where(fits, a, adc)
    return rng, adc


@dataclass(frozen=True)
class EdaSpec:
    start: datetime = datetime(2026, 8, 15, 6, 0, tzinfo=UTC)  # first sample, UTC
    minutes: int = 56
    chunk_s: int = 600  # the device rotates chunks this often (device time)
    #: device -> (person id, worn from min, worn to min); the rest of the run is off skin
    wear: tuple[tuple[str, str, float, float], ...] = (
        ("SH01", "11", 5.0, 30.0),
        ("SH02", "12", 2.0, 38.0),
    )
    #: (device, minute, amplitude uS) of each SCR, all while worn
    scrs: tuple[tuple[str, float, float], ...] = (
        ("SH01", 8.0, 0.30),
        ("SH01", 15.5, 0.12),
        ("SH01", 22.0, 0.50),
        ("SH02", 4.0, 0.20),
        ("SH02", 26.0, 0.08),
    )
    no_consent: str = "12"  # this person wore a device without consenting to EDA
    #: device -> mean heart rate (bpm) while worn
    heart_bpm: tuple[tuple[str, float], ...] = (("SH01", 72.0), ("SH02", 88.0))
    #: devices whose PPG sensor shows no pulse
    dead_ppg: tuple[str, ...] = ("SH02",)
    #: the stored modification time is the device clock minus this (as an archive in another
    #: zone gives)
    mtime_offset_s: float = 7200.0
    #: device -> (role, rate, offset at start s): device clock = true + offset + rate * elapsed.
    #: SH01 runs 3 % slow (a slave), SH02 0.6 % slow (the master), SH03 keeps time (a slave,
    #: never worn: the reference).
    clocks: tuple[tuple[str, str, float, float], ...] = (
        ("SH01", "slave", -0.03, 0.4),
        ("SH02", "master", -0.006, 0.0),
        ("SH03", "slave", 0.0, 0.2),
    )
    sync_every_s: float = 240.0
    #: From this minute the devices lie together and share motion bursts.
    box_from_min: float = 40.0
    #: Write calibrated exports: SH01 minutes 0-32 with its clock minus a sync offset, and a
    #: device SH04 with no SD card and no clock (-1), a copy of SH02's signal, worn by "14".
    exports: bool = False
    seed: int = 3


@dataclass
class SyntheticEda:
    spec: EdaSpec
    cards: list[Path]
    spine_dir: Path
    truth_wear: pl.DataFrame  # device, start, end (UTC)
    truth_scr: pl.DataFrame  # device, onset (UTC), amplitude_us
    truth_beats: pl.DataFrame  # device, t (true UTC): systolic peaks a working sensor shows
    exports: list[Path] = field(default_factory=list)
    notes: dict[str, object] = field(default_factory=dict)


def _scr_wave(t: np.ndarray, onset: float, amp: float) -> np.ndarray:
    x = np.zeros_like(t)
    up = (t >= onset) & (t < onset + 2.0)
    x[up] = amp * (t[up] - onset) / 2.0
    down = t >= onset + 2.0
    x[down] = amp * np.exp(-(t[down] - onset - 2.0) / 5.0)
    return x


def beat_times(start_s: float, end_s: float, bpm: float, rng: np.random.Generator) -> np.ndarray:
    """Beats from ``start_s`` to ``end_s``: the rate drifts +-6% over a minute and each
    interval jitters by 2% (heart-rate variability)."""
    t = [start_s + rng.uniform(0, 60 / bpm)]
    while t[-1] < end_s:
        rate = bpm * (1 + 0.06 * np.sin(2 * np.pi * t[-1] / 60.0))
        t.append(t[-1] + 60.0 / rate * (1 + 0.02 * rng.standard_normal()))
    return np.asarray(t[:-1])


def pulse_wave(t: np.ndarray, beats: np.ndarray, amplitude_mv: float = 150.0) -> np.ndarray:
    """A PPG pulse per beat: a systolic wave peaking at the beat and a smaller diastolic one
    after it (two Gaussians, a common synthetic model), in mV."""
    x = np.zeros_like(t)
    if not len(beats):
        return x
    last = beats[-1] - beats[-2] if len(beats) > 1 else 0.8
    for b, d in zip(beats, np.diff(beats, append=beats[-1] + last), strict=True):
        lo, hi = np.searchsorted(t, [b - 0.5 * d, b + 1.2 * d])  # t is sorted
        u = t[lo:hi] - b
        x[lo:hi] += amplitude_mv * (
            np.exp(-0.5 * (u / (0.11 * d)) ** 2)
            + 0.4 * np.exp(-0.5 * ((u - 0.4 * d) / (0.13 * d)) ** 2)
        )
    return x


def _clock(spec: EdaSpec, device: str) -> tuple[str, float, float]:
    for d, role, rate, off in spec.clocks:
        if d == device:
            return role, rate, off
    return "none", 0.0, 0.0


def device_clock(spec: EdaSpec, device: str, true_t: np.ndarray) -> np.ndarray:
    """What ``device``'s clock reads at true UTC times ``true_t``."""
    _, rate, off = _clock(spec, device)
    t0 = spec.start.timestamp()
    return np.asarray(true_t, float) + off + rate * (np.asarray(true_t, float) - t0)


def _write_export(path: Path, device: str, stamps_ms: np.ndarray, sig: dict) -> None:
    """A calibrated Shimmer Base export (comma-separated) of the given samples."""
    names = [
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
    units = ["ms", "m/(s^2)", "m/(s^2)", "m/(s^2)", "no_units", "uS", "kOhms", "mV", "ms", "BPM"]
    acc = sig["acc"] / 8192 * STANDARD_GRAVITY
    df = pl.DataFrame(
        {
            names[0]: stamps_ms,
            names[1]: acc[:, 0],
            names[2]: acc[:, 1],
            names[3]: acc[:, 2],
            names[4]: sig["range"].astype(float),
            names[5]: sig["us"],
            names[6]: 1000 / sig["us"],
            names[7]: sig["ppg"] * 3000 / 4095,
            names[8]: np.full(len(stamps_ms), -1.0),
            names[9]: np.full(len(stamps_ms), -1.0),
        }
    )
    head = '"sep=,"\n' + ",".join(f"{device}_{n}" for n in names) + ",\n" + ",".join(units) + ",\n"
    body = df.write_csv(include_header=False)
    path.write_text(head + body.replace("\n", ",\n"))


def generate_eda(spec: EdaSpec, out_dir: Path) -> SyntheticEda:
    out_dir = Path(out_dir)
    rng = np.random.default_rng(spec.seed)
    t0 = spec.start.timestamp()
    n = spec.minutes * 60 * RATE
    rel = np.arange(n) / RATE
    cards, wear_rows, scr_rows, beat_rows = [], [], [], []
    heart = dict(spec.heart_bpm)
    exports: list[Path] = []
    # The device's counter has a 28.7 s sampling pause in the middle of chunk 1: samples after
    # it are 28.703125 s later (device time) than their index says.
    pause_at = spec.chunk_s * RATE + 200 * RATE
    lag = np.where(np.arange(n) >= pause_at, PAUSE_TICKS, 0)
    dev_el = rel + lag / TICK_HZ  # device elapsed time
    rtc_diff = (int(t0) - 100_000) * TICK_HZ
    # Shared motion while the devices lie together: bursts at random true times.
    box_from = spec.box_from_min * 60
    bursts = np.sort(rng.uniform(box_from, spec.minutes * 60, int(spec.minutes * 60 - box_from)))
    master = next((d for d, role, *_ in spec.clocks if role == "master"), None)
    devices = [w[0] for w in spec.wear] + [
        d for d, *_ in spec.clocks if d not in {w[0] for w in spec.wear}
    ]
    signals: dict[str, dict] = {}
    for i, device in enumerate(devices):
        role, rate, off0 = _clock(spec, device)
        wall = dev_el / (1 + rate)  # true elapsed time of each sample
        wearing = [w for w in spec.wear if w[0] == device]
        worn = np.zeros(n, bool)
        for _, _, w_from, w_to in wearing:
            worn |= (wall >= w_from * 60) & (wall < w_to * 60)
        us = np.where(worn, 2.0 + 0.2 * i, 0.01)
        for dev, minute, amp in spec.scrs:
            if dev == device:
                us = us + np.where(worn, _scr_wave(wall, minute * 60, amp), 0.0)
                scr_rows.append((device, spec.start + timedelta(minutes=minute), amp))
        for _, _, w_from, w_to in wearing:
            wear_rows.append(
                (
                    device,
                    spec.start + timedelta(minutes=w_from),
                    spec.start + timedelta(minutes=w_to),
                )
            )
        g_rng, g_adc = gsr_raw(us)
        acc = np.zeros((n, 3), np.int64)
        acc[:, 2] = 8192
        acc[worn, 0] = rng.integers(-400, 400, worn.sum())
        hit = np.searchsorted(bursts, wall)
        near = (hit > 0) & (wall - bursts[np.maximum(hit - 1, 0)] < 0.15)
        acc[near & (wall >= box_from), 0] = 3000
        # Sensor noise under the pulse, as on real cards: PPG sequences do not repeat.
        ppg_mv = 1400 + 1.0 * rng.standard_normal(n)
        if device in heart and device not in spec.dead_ppg:
            beats = beat_times(w_from * 60, w_to * 60, heart[device], rng)
            ppg_mv += np.where(worn, pulse_wave(wall, beats), 0.0)
            ppg_mv += np.where(worn, 20 * np.sin(2 * np.pi * 0.07 * wall), 0.0)  # baseline
            # Beats inside the sampling pause were never sampled.
            beats = beats[(beats < wall[pause_at - 1]) | (beats > wall[pause_at])]
            beat_rows += [(device, spec.start + timedelta(seconds=float(b))) for b in beats]
        ppg = np.rint(ppg_mv * ADC_MAX / 3000).astype(np.int64)
        dev_ticks = round((t0 + off0) * TICK_HZ) + 256 * np.arange(n) + lag
        ticks = dev_ticks % TICK_WRAP
        true_t = t0 + wall
        dev_t = dev_ticks / TICK_HZ
        signals[device] = {"us": us, "range": g_rng, "acc": acc, "ppg": ppg, "true_t": true_t}
        signals[device]["dev_t"] = dev_t
        # Sync records: device - master at the moment of each block, every sync_every_s.
        offsets = np.full(n, np.nan)
        if role == "slave" and master is not None:
            offsets = dev_t - device_clock(spec, master, true_t)
        sync_at = set()
        if role == "slave":
            for x in np.arange(spec.sync_every_s / 2, dev_el[-1], spec.sync_every_s):
                sync_at.add(int(np.searchsorted(dev_el, x)) // RECORDS_PER_BLOCK)
        signals[device]["offsets"] = offsets
        card = out_dir / device
        run = card / "data" / "session_1700000000" / f"{device}-000"
        run.mkdir(parents=True)
        bounds = np.searchsorted(dev_el, np.arange(0, 3600 * 24, spec.chunk_s))
        bounds = np.unique(np.r_[bounds[bounds < n], n])
        lost = None
        for k, (a, b) in enumerate(pairwise(bounds)):
            zero = np.zeros(b - a, bool)
            tk = ticks[a:b].copy()
            slots: dict[int, bytes] = {}
            # Sync slots of the blocks inside this chunk (blocks count from the chunk start).
            for gb in sync_at:
                rec = gb * RECORDS_PER_BLOCK
                if a <= rec < b:
                    local = (rec - a) // RECORDS_PER_BLOCK
                    slots[local] = sync_slot(offsets[a + local * RECORDS_PER_BLOCK])
            if k == 0:
                zero[988:991] = True  # all-zero records (the first opens block 26)
                tk[5000:5004] = [1, 0, 1405, 7_000_000]  # out-of-sequence burst
                if role == "slave":
                    slots[26] = sync_slot(-12.0)  # a record in a corrupt block
                    slots[60] = sync_slot(3112.0)  # a plausible shape, but wrong
            keep_to = b
            if k == 2:
                keep_to = a + (b - a) // 2  # this chunk lost its tail
            header = encode_header(int(dev_ticks[a]), rtc_diff, role == "master", role != "none")
            data = encode_chunk(
                tk[: keep_to - a],
                acc[a:keep_to],
                ppg[a:keep_to],
                g_rng[a:keep_to],
                g_adc[a:keep_to],
                zero[: keep_to - a],
                header=header,
                slots=slots,
            )
            if k == 2:
                data = data[: len(data) - len(data) % 4096]  # cut at a 4 KiB boundary
                kept = (len(data) - HEADER_BYTES) // BLOCK_BYTES * RECORDS_PER_BLOCK
                lost = (true_t[a + kept], true_t[b] if b < n else true_t[-1])
            path = run / f"{k:03d}"
            path.write_bytes(data)
            # A rotated chunk closes at its rotation time on the device clock (even the one
            # that lost its tail); the last one when recording stops, at its final record.
            close = t0 + off0 + (k + 1) * spec.chunk_s if b < n else dev_t[n - 1]
            stored = close - spec.mtime_offset_s
            os.utime(path, (stored, stored))
        signals[device]["lost"] = lost
        # What the data can show: wear and SCRs inside the lost tail are gone.
        lo, hi = (datetime.fromtimestamp(x, UTC) for x in lost)
        dev_wear = [r for r in wear_rows if r[0] == device]
        wear_rows = [r for r in wear_rows if r[0] != device]
        for dev, a_, b_ in dev_wear:
            for x, y in ((a_, min(b_, lo)), (max(a_, hi), b_)):
                if (y - x).total_seconds() >= 300:  # shorter bouts are not wear
                    wear_rows.append((dev, x, y))
        scr_rows = [r for r in scr_rows if r[0] != device or not lo <= r[1] < hi]
        beat_rows = [r for r in beat_rows if r[0] != device or not lo <= r[1] < hi]
        # A copy of the run, as a card copy leaves it.
        shutil.copytree(run, run.with_name(f"{device}-000 2"))
        # A run recorded after the study: its clock is outside the window.
        junk = card / "data" / "session_1700000000" / f"{device}-001"
        junk.mkdir()
        m = 38 * 100
        late = (spec.start + timedelta(days=60)).timestamp()
        jt = round(late * TICK_HZ) + 256 * np.arange(m)
        jbytes = encode_chunk(
            jt,
            np.zeros((m, 3)),
            np.full(m, 2000),
            np.full(m, 3),
            np.full(m, 700),
            header=encode_header(int(jt[0]), rtc_diff),
        )
        (junk / "000").write_bytes(jbytes)
        os.utime(junk / "000", (late - spec.mtime_offset_s, late - spec.mtime_offset_s))
        cards.append(card)

    people = [(p, p != spec.no_consent) for _, p, _, _ in spec.wear]
    assignments = [(d, p) for d, p, _, _ in spec.wear]
    notes: dict[str, object] = {"pause_after_s": pause_at / RATE, "box_from_s": box_from}
    if spec.exports:
        exp_dir = out_dir / "exports"
        exp_dir.mkdir()
        s1 = signals["SH01"]
        upto = int(np.searchsorted(s1["true_t"], t0 + 40 * 60))
        # Shimmer Base subtracts one sync record: here SH01's at 10 min of device time.
        constant = float(s1["offsets"][int(np.searchsorted(dev_el, 600.0))])
        # The export lacks 630 s of device time from minute 10: a gap the 512-s repair can
        # only place modulo 512 (118 s), so its second segment lands 512 s early.
        # Two more 70-s holes cut out a segment (device 1570-1700 s) that lies wholly in the
        # tail the card lost: it can only borrow its neighbours' lag.
        d = dev_el[:upto]
        keep = ((d < 600) | (d >= 1230)) & ~((d >= 1500) & (d < 1570)) & ~((d >= 1700) & (d < 1770))
        rows = np.flatnonzero(keep)
        notes["sh01_unmatched_segment"] = tuple(
            t0 + x / (1 + _clock(spec, "SH01")[1]) for x in (1570, 1700)
        )
        stamps = (s1["dev_t"][rows] - constant) * 1000
        sig = {k: s1[k][rows] for k in ("acc", "range", "us", "ppg")}
        p1 = exp_dir / "day_Session1_SH01_Calibrated_SD.csv"
        _write_export(p1, "SH01", stamps, sig)
        s2 = signals["SH02"]
        p4 = exp_dir / "day_Session1_SH04_Calibrated_SD.csv"
        sig = {k: s2[k] for k in ("acc", "range", "us", "ppg")}
        _write_export(p4, "SH04", np.full(n, -1.0), sig)
        exports = [p1, p4]
        notes["export_constant_s"] = constant
        notes["sh01_export_end"] = datetime.fromtimestamp(s1["true_t"][upto - 1], UTC)
        notes["sh01_lost"] = signals["SH01"]["lost"]
        # SH04 is SH02's signal under another name, from the same moment, on no card.
        sh04_wear = [w for w in spec.wear if w[0] == "SH02"]
        for _, _, w_from, w_to in sh04_wear:
            wear_rows.append(
                (
                    "SH04",
                    spec.start + timedelta(minutes=w_from),
                    spec.start + timedelta(minutes=w_to),
                )
            )
        people.append(("14", True))
        assignments.append(("SH04", "14"))
    spine_dir = out_dir / "spine"
    spine_dir.mkdir()

    def dump(name: str, content) -> None:
        (spine_dir / f"{name}.yaml").write_text(yaml.safe_dump(content, sort_keys=False))

    dump("meta", {"study_id": "synthetic-eda", "timezone": "UTC"})
    dump(
        "people",
        [
            {"id": person, "role": "participant", "consent": ["eda"] if ok else []}
            for person, ok in people
        ],
    )
    day = spec.start.replace(hour=0, minute=0, second=0, microsecond=0)
    dump(
        "assignments",
        [
            {
                "device": f"eda:{device}",
                "entity": f"person:{person}",
                "start": day.strftime("%Y-%m-%d %H:%M:%S"),
                "end": (day + timedelta(days=1)).strftime("%Y-%m-%d %H:%M:%S"),
            }
            for device, person in assignments
        ],
    )
    for name in ("locations", "events", "exclusions"):
        dump(name, [])
    utc = pl.Datetime("us", "UTC")
    notes["lost_tail"] = signals[devices[-1]]["lost"]
    return SyntheticEda(
        spec=spec,
        cards=cards,
        spine_dir=spine_dir,
        truth_wear=pl.DataFrame(
            wear_rows, schema={"device": pl.String, "start": utc, "end": utc}, orient="row"
        ),
        truth_scr=pl.DataFrame(
            scr_rows,
            schema={"device": pl.String, "onset": utc, "amplitude_us": pl.Float64},
            orient="row",
        ),
        truth_beats=pl.DataFrame(
            beat_rows, schema={"device": pl.String, "t": utc}, orient="row"
        ).sort("device", "t"),
        exports=exports,
        notes=notes,
    )
