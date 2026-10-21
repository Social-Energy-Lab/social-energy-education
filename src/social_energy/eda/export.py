"""Shimmer Base calibrated CSV exports: read one file and repair its clock.

The export's timestamps come from the device's 24-bit tick counter, unwrapped by software
that inserts spurious whole 512-s periods (docs/context/instruments/eda.md). Two facts make
them repairable: the first row is right, and every row is right modulo 512 s. So the ticks
are rebuilt from the timestamps (ms x 32.768, modulo 2^24), cleaned and segmented exactly as
on an SD card, the first segment placed at its first timestamp, and each later segment at
the smallest gap after its predecessor that agrees with its own timestamp modulo 512 s. A gap
beyond ``max_step_s`` could hide whole wraps: those segments are flagged ``gap_ambiguous``.

Some exports carry no clock at all (``-1`` in every timestamp). They are not placed unless a
start is given (``start_s``): then row ``i`` sits at ``start_s + i / sample_rate_hz`` and the
file's clock is ``recovered``. Sampling pauses are invisible in such a file.

The repaired export clock is the device's clock plus one constant per file (Shimmer Base
subtracts one sync offset, or none); ``eda.ingest`` measures it against the SD card and
corrects it with ``eda.clock``.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl

from .sd import TICK_HZ, TICK_WRAP
from .timeline import TimelineConfig, clean_ticks, tick_steps

STANDARD_GRAVITY = 9.80665
#: Shimmer clamps skin resistance at 8 kOhm (125 uS) and writes ~0.00022 uS for an open input.
SATURATED_US = 125.0
SENTINEL_MAX_US = 0.0003

#: A device in a sync group exports the synchronised clock; one outside it, its own.
_CLOCKS = {"TimestampSync_Unix_CAL": "sync", "Timestamp_Unix_CAL": "device"}
_COLUMNS = {
    "LIS2DW12_ACC_X_CAL": "ax",
    "LIS2DW12_ACC_Y_CAL": "ay",
    "LIS2DW12_ACC_Z_CAL": "az",
    "GSR_Range_CAL": "gsr_range",
    "GSR_Skin_Conductance_CAL": "us",
    "PPG_A1_CAL": "ppg_mv",
    "PPGtoHR_CAL": "hr",
}


@dataclass(frozen=True)
class ExportFile:
    path: Path
    device: str
    t: np.ndarray  # UTC epoch seconds; NaN for bad rows
    bad: np.ndarray
    gap_ambiguous: np.ndarray
    conductance_us: np.ndarray  # NaN where not a reading
    gsr_valid: np.ndarray
    gsr_range: np.ndarray
    acc_g: np.ndarray  # (n, 3)
    ppg_mv: np.ndarray
    hr_bpm: np.ndarray  # NaN where the export has none
    qa: dict[str, Any]
    segment: np.ndarray | None = None  # per row: its clock segment, -1 for bad rows


def _separator(path: Path) -> str:
    with path.open(encoding="utf-8") as f:
        first = f.readline().strip().strip('"')
    if not first.startswith("sep="):
        raise ValueError(f"{path}: not a Shimmer export (no sep= line)")
    return first[4:] or ","


def export_device(path: Path) -> str:
    """The device an export belongs to, from its column names (without reading the data)."""
    sep = _separator(path)
    with path.open(encoding="utf-8") as f:
        f.readline()
        return f.readline().split(sep)[0].strip().strip('"').partition("_")[0]


def _data_rows(path: Path) -> tuple[str, list[str]]:
    sep = _separator(path)
    with path.open(encoding="utf-8") as f:
        for _ in range(3):
            f.readline()
        first = f.readline()
    with path.open("rb") as f:
        f.seek(0, 2)
        size = f.tell()
        f.seek(max(0, size - 4096))
        tail = f.read().decode("utf-8", "replace").splitlines()
    return sep, [first, *[x for x in tail if x.strip()][-1:]]


def export_span(path: Path) -> tuple[float | None, float | None]:
    """First and last timestamp (epoch seconds, as written; None for ``-1`` or unreadable)
    without reading the file. The last one can carry spurious whole 512-s wraps."""
    sep, (first, last) = _data_rows(Path(path))

    def stamp(line: str) -> float | None:
        try:
            v = float(line.split(sep)[0].strip().strip('"'))
        except ValueError:
            return None
        return v / 1000 if v > 0 else None

    return stamp(first), stamp(last)


def _header(path: Path) -> tuple[str, dict[str, str], str | None, str | None]:
    """Separator, {column: canonical name} (with ``ts_ms`` for the clock), device, clock."""
    sep = _separator(path)
    with path.open(encoding="utf-8") as f:
        f.readline()
        cols = [c.strip().strip('"') for c in f.readline().rstrip("\r\n").split(sep)]
    names: dict[str, str] = {}
    device = clock = None
    for col in cols:
        prefix, _, rest = col.partition("_")
        if rest in _COLUMNS:
            names[col] = _COLUMNS[rest]
            device = device or prefix
        elif rest in _CLOCKS and clock != "sync":
            names = {c: n for c, n in names.items() if n != "ts_ms"}
            names[col] = "ts_ms"
            clock = _CLOCKS[rest]
    return sep, names, device, clock


def _read(path: Path, wanted: set[str] | None = None) -> tuple[pl.DataFrame, str, str | None]:
    """The export's columns (all calibrated ones, or ``wanted`` plus the clock) as floats."""
    sep, names, device, clock = _header(path)
    missing = ({*_COLUMNS.values(), "ts_ms"}) - set(names.values())
    if missing or device is None:
        raise ValueError(f"{path}: missing calibrated columns {sorted(missing)}")
    if wanted is not None:
        names = {c: n for c, n in names.items() if n in wanted | {"ts_ms"}}
    df = pl.read_csv(
        path,
        separator=sep,
        skip_rows=1,
        skip_rows_after_header=1,
        columns=list(names),
        schema_overrides={c: pl.Float64 for c in names},
    ).rename(names)
    return df, device, clock


@dataclass(frozen=True)
class RepairedClock:
    t: np.ndarray  # UTC epoch seconds per row; NaN for bad rows
    good: np.ndarray
    ambiguous: np.ndarray  # placed after a gap that could hide whole wraps
    segment: np.ndarray  # per row: its clock segment, -1 for bad rows
    n_segments: int
    n_ambiguous: int
    #: ``recovered`` (no timestamps, placed from ``start_s``), ``none`` (no timestamps and no
    #: start) or None (the file's own clock).
    kind: str | None


def repair_clock(
    ts_ms: np.ndarray,
    config: TimelineConfig,
    start_s: float | None = None,
    sample_rate_hz: float = 128.0,
) -> RepairedClock:
    """UTC seconds per row from the export's timestamps (NaN for bad rows, including rows
    without a timestamp), with the good rows, the rows placed after an ambiguous gap and the
    clock segments. A file without any timestamp is placed from ``start_s`` if given."""
    ts = np.asarray(ts_ms, float)
    n = len(ts)
    if not n:
        z = np.zeros(0, bool)
        return RepairedClock(np.zeros(0), z, z, np.zeros(0, np.int64), 0, 0, None)
    # A timestamp of -1 (or none) is an export written without a clock: not a time.
    has_time = np.isfinite(ts) & (ts > 0)
    kind = None
    if not has_time.any():
        # No clock in the file: placed only from a given start, by the sample index.
        if start_s is not None:
            kind = "recovered"
            ts = (start_s + np.arange(n) / sample_rate_hz) * 1000
            has_time[:] = True
        else:
            kind = "none"
    first = ts[np.argmax(has_time)] if has_time.any() else 0.0
    ticks = np.rint((np.where(has_time, ts, first) - first) * TICK_HZ / 1000).astype(np.int64)
    ticks %= TICK_WRAP
    good = clean_ticks(ticks, has_time, config)
    gi = np.flatnonzero(good)
    t = np.full(n, np.nan)
    ambiguous = np.zeros(n, bool)
    n_segments = n_ambiguous = 0
    segment = np.full(n, -1, np.int64)
    if len(gi):
        d = tick_steps(ticks[gi])
        max_step = int(config.max_step_s * TICK_HZ)
        brk = np.r_[True, d > max_step]
        seg = np.cumsum(brk) - 1
        tau = np.cumsum(np.r_[0, np.where(brk[1:], 0, d)])
        tau = (tau - tau[np.flatnonzero(brk)][seg]) / TICK_HZ
        wrap_s = TICK_WRAP / TICK_HZ
        prev_end = None
        n_segments = int(seg[-1]) + 1
        for s in range(n_segments):
            members = gi[seg == s]
            own = ts[members[0]] / 1000
            if prev_end is None:
                start = own
            else:
                gap = (own - prev_end) % wrap_s
                start = prev_end + gap
                if gap > config.max_step_s:
                    ambiguous[members] = True
                    n_ambiguous += 1
            t[members] = start + tau[seg == s]
            segment[members] = s
            prev_end = t[members[-1]]
    return RepairedClock(t, good, ambiguous, segment, n_segments, n_ambiguous, kind)


@dataclass(frozen=True)
class ExportPulse:
    """The pulse columns of one export, its clock repaired (enough to match it to its SD card
    and correct it as ``eda.ingest`` does)."""

    path: Path
    device: str
    t: np.ndarray  # UTC epoch seconds; NaN for bad rows
    gap_ambiguous: np.ndarray
    ppg_mv: np.ndarray
    hr_bpm: np.ndarray  # Shimmer's own heart rate; NaN where it has none
    qa: dict[str, Any]
    segment: np.ndarray | None = None


def _clock_qa(clock: str | None, n: int, rc: RepairedClock) -> dict[str, Any]:
    return {
        "clock": rc.kind or clock,
        "records": n,
        "records_bad": int((~rc.good).sum()),
        "segments": rc.n_segments,
        "segments_gap_ambiguous": rc.n_ambiguous,
    }


def read_export_pulse(
    path: Path,
    config: TimelineConfig | None = None,
    start_s: float | None = None,
    sample_rate_hz: float = 128.0,
) -> ExportPulse:
    """PPG and Shimmer's heart rate only: a fraction of ``read_export``'s memory, same clock."""
    path = Path(path)
    df, device, clock = _read(path, {"ppg_mv", "hr"})
    rc = repair_clock(df["ts_ms"].to_numpy(), config or TimelineConfig(), start_s, sample_rate_hz)
    hr = df["hr"].to_numpy()
    return ExportPulse(
        path=path,
        device=device,
        t=rc.t,
        gap_ambiguous=rc.ambiguous,
        ppg_mv=df["ppg_mv"].to_numpy(),
        hr_bpm=np.where(hr > 0, hr, np.nan),
        qa=_clock_qa(clock, df.height, rc),
        segment=rc.segment,
    )


def read_export(
    path: Path,
    config: TimelineConfig | None = None,
    start_s: float | None = None,
    sample_rate_hz: float = 128.0,
) -> ExportFile:
    path = Path(path)
    config = config or TimelineConfig()
    df, device, clock = _read(path)
    rc = repair_clock(df["ts_ms"].to_numpy(), config, start_s, sample_rate_hz)

    us = df["us"].to_numpy()
    valid = np.isfinite(us) & (us < SATURATED_US) & (us > SENTINEL_MAX_US)
    hr = df["hr"].to_numpy()
    return ExportFile(
        path=path,
        device=device,
        t=rc.t,
        bad=~rc.good,
        gap_ambiguous=rc.ambiguous,
        segment=rc.segment,
        conductance_us=np.where(valid, us, np.nan),
        gsr_valid=valid,
        gsr_range=df["gsr_range"].fill_nan(0).to_numpy().astype(np.int64),
        acc_g=df.select("ax", "ay", "az").to_numpy() / STANDARD_GRAVITY,
        ppg_mv=df["ppg_mv"].to_numpy(),
        hr_bpm=np.where(hr > 0, hr, np.nan),
        qa=_clock_qa(clock, df.height, rc),
    )
