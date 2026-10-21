"""Synthetic Shimmer SD cards with known ground truth (wear, SCRs, who wore what).

The cards use the real binary format (``social_energy.eda.sd``) and reproduce the traps found
on real cards: all-zero records, a burst of out-of-sequence ticks, a ~28.7 s sampling pause,
a chunk that lost its tail, a run copied as ``<run> 2``, and a run recorded after the study
(its modification time is outside the window). Values are invented.
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
from ..eda.sd import (
    BLOCK_BYTES,
    FILLER_BYTES,
    HEADER_BYTES,
    RECORDS_PER_BLOCK,
    TICK_HZ,
    TICK_WRAP,
)

RATE = 128


def encode_chunk(
    ticks: np.ndarray,
    acc: np.ndarray,
    ppg: np.ndarray,
    gsr_range: np.ndarray,
    gsr_adc: np.ndarray,
    zero: np.ndarray | None = None,
    tail: bytes = b"",
) -> bytes:
    """Bytes of one SD chunk. Records beyond the last full block are not written."""
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
    header = bytearray(HEADER_BYTES)
    header[0:2] = struct.pack("<H", TICK_HZ // RATE)
    return bytes(header) + np.hstack([filler, blocks]).tobytes() + tail


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
    minutes: int = 40
    chunk_s: int = 600  # the device rotates chunks this often (rotation_s)
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
    #: the stored modification time is UTC minus this (as an archive in another zone gives)
    mtime_offset_s: float = 7200.0
    seed: int = 3


@dataclass
class SyntheticEda:
    spec: EdaSpec
    cards: list[Path]
    spine_dir: Path
    truth_wear: pl.DataFrame  # device, start, end (UTC)
    truth_scr: pl.DataFrame  # device, onset (UTC), amplitude_us
    notes: dict[str, object] = field(default_factory=dict)


def _scr_wave(t: np.ndarray, onset: float, amp: float) -> np.ndarray:
    x = np.zeros_like(t)
    up = (t >= onset) & (t < onset + 2.0)
    x[up] = amp * (t[up] - onset) / 2.0
    down = t >= onset + 2.0
    x[down] = amp * np.exp(-(t[down] - onset - 2.0) / 5.0)
    return x


def generate_eda(spec: EdaSpec, out_dir: Path) -> SyntheticEda:
    out_dir = Path(out_dir)
    rng = np.random.default_rng(spec.seed)
    t0 = spec.start.timestamp()
    n = spec.minutes * 60 * RATE
    rel = np.arange(n) / RATE
    cards, wear_rows, scr_rows = [], [], []
    # The device's counter has a 28.7 s sampling pause in the middle of chunk 1: samples after
    # it are 28.703125 s later than their index says. Signals live on wall time ``wall``.
    pause_at = spec.chunk_s * RATE + 200 * RATE
    lag = np.where(np.arange(n) >= pause_at, 940544, 0)
    wall = rel + lag / TICK_HZ
    for i, (device, _person, w_from, w_to) in enumerate(spec.wear):
        worn = (wall >= w_from * 60) & (wall < w_to * 60)
        us = np.where(worn, 2.0 + 0.2 * i, 0.01)
        for dev, minute, amp in spec.scrs:
            if dev == device:
                us = us + np.where(worn, _scr_wave(wall, minute * 60, amp), 0.0)
                scr_rows.append((device, spec.start + timedelta(minutes=minute), amp))
        wear_rows.append(
            (device, spec.start + timedelta(minutes=w_from), spec.start + timedelta(minutes=w_to))
        )
        g_rng, g_adc = gsr_raw(us)
        acc = np.zeros((n, 3), np.int64)
        acc[:, 2] = 8192
        acc[worn, 0] = rng.integers(-400, 400, worn.sum())
        ppg = (2000 + 300 * np.sin(2 * np.pi * 1.2 * wall)).astype(np.int64)
        ticks = (12345 + 256 * np.arange(n) + lag) % TICK_WRAP
        true_t = t0 + wall
        # The record stream is shorter than wall time by the pause; chunks cut on wall time.
        card = out_dir / device
        run = card / "data" / "session_1700000000" / f"{device}-000"
        run.mkdir(parents=True)
        bounds = np.searchsorted(true_t, t0 + np.arange(0, 3600 * 24, spec.chunk_s))
        bounds = np.r_[bounds[bounds < n], n]
        bounds = np.unique(bounds)
        for k, (a, b) in enumerate(pairwise(bounds)):
            zero = np.zeros(b - a, bool)
            tk = ticks[a:b].copy()
            if k == 0:
                zero[1000:1003] = True  # all-zero records
                tk[5000:5004] = [1, 0, 1405, 7_000_000]  # out-of-sequence burst
            keep_to = b
            if k == 2:
                keep_to = a + (b - a) // 2  # this chunk lost its tail
            data = encode_chunk(
                tk[: keep_to - a],
                acc[a:keep_to],
                ppg[a:keep_to],
                g_rng[a:keep_to],
                g_adc[a:keep_to],
                zero[: keep_to - a],
            )
            if k == 2:
                data = data[: len(data) - len(data) % 4096]  # cut at a 4 KiB boundary
                kept = (len(data) - HEADER_BYTES) // BLOCK_BYTES * RECORDS_PER_BLOCK
                lost = (true_t[a + kept], true_t[b] if b < n else true_t[-1])
            path = run / f"{k:03d}"
            path.write_bytes(data)
            # A rotated chunk closes at its rotation time (even the one that lost its tail);
            # the last one when recording stops, at its final record.
            close = t0 + (k + 1) * spec.chunk_s if b < n else true_t[n - 1]
            stored = close - spec.mtime_offset_s
            os.utime(path, (stored, stored))
        # What the data can show: wear and SCRs inside the lost tail are gone.
        lo, hi = (datetime.fromtimestamp(x, UTC) for x in lost)
        dev_wear = [r for r in wear_rows if r[0] == device]
        wear_rows = [r for r in wear_rows if r[0] != device]
        for dev, a_, b_ in dev_wear:
            for x, y in ((a_, min(b_, lo)), (max(a_, hi), b_)):
                if (y - x).total_seconds() >= 300:  # shorter bouts are not wear
                    wear_rows.append((dev, x, y))
        scr_rows = [r for r in scr_rows if r[0] != device or not lo <= r[1] < hi]
        # A copy of the run, as a card copy leaves it.
        shutil.copytree(run, run.with_name(f"{device}-000 2"))
        # A run recorded after the study: its modification time is outside the window.
        junk = card / "data" / "session_1700000000" / f"{device}-001"
        junk.mkdir()
        m = 38 * 100
        jt = 256 * np.arange(m)
        jbytes = encode_chunk(
            jt, np.zeros((m, 3)), np.full(m, 2000), np.full(m, 3), np.full(m, 700)
        )
        (junk / "000").write_bytes(jbytes)
        late = (spec.start + timedelta(days=60)).timestamp() - spec.mtime_offset_s
        os.utime(junk / "000", (late, late))
        cards.append(card)

    spine_dir = out_dir / "spine"
    spine_dir.mkdir()

    def dump(name: str, content) -> None:
        (spine_dir / f"{name}.yaml").write_text(yaml.safe_dump(content, sort_keys=False))

    dump("meta", {"study_id": "synthetic-eda", "timezone": "UTC"})
    dump(
        "people",
        [
            {
                "id": person,
                "role": "participant",
                "consent": [] if person == spec.no_consent else ["eda"],
            }
            for _, person, _, _ in spec.wear
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
            for device, person, _, _ in spec.wear
        ],
    )
    for name in ("locations", "events", "exclusions"):
        dump(name, [])
    utc = pl.Datetime("us", "UTC")
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
        notes={"pause_after_s": pause_at / RATE, "lost_tail": lost},
    )
