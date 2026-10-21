"""Shimmer SD-card logs: find the recording runs on a card and decode their chunk files.

Layout (docs/context/instruments/eda.md): a 384-byte header, then blocks of 503 bytes, each
9 bytes of ``0xFF`` filler and 38 records of 13 bytes. Decoding is pure byte arithmetic; time
placement is ``eda.timeline``'s job.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import numpy as np

HEADER_BYTES = 384
FILLER_BYTES = 9
RECORD_BYTES = 13
RECORDS_PER_BLOCK = 38
BLOCK_BYTES = FILLER_BYTES + RECORDS_PER_BLOCK * RECORD_BYTES  # 503
TICK_HZ = 32768
TICK_WRAP = 1 << 24  # the counter is 24 bits: it wraps every 512 s

RUN_RE = re.compile(r"(SH\d+)-\d{3}( \d+)?")
CHUNK_RE = re.compile(r"\d{3}")


@dataclass(frozen=True)
class SdChunk:
    path: Path
    size: int
    sample_rate_hz: float
    ticks: np.ndarray  # int64, raw 24-bit counter
    acc: np.ndarray  # int16, (n, 3) counts
    ppg: np.ndarray  # int64, 12-bit ADC
    gsr_range: np.ndarray  # int64, 0-3
    gsr_adc: np.ndarray  # int64, bits 13-0
    zero: np.ndarray  # bool: every byte of the record is 0
    trailing_bytes: int  # bytes after the last complete block (a partial block, not read)


@dataclass(frozen=True)
class SdRun:
    """One recording run: ``<DEV>-<run>`` and its chunk files in order."""

    device: str
    name: str  # path below data/, e.g. "day3_1787119190/SH10-000"
    chunks: tuple[Path, ...]


def read_chunk(path: Path) -> SdChunk:
    path = Path(path)
    raw = path.read_bytes()
    divisor = int.from_bytes(raw[0:2], "little") if len(raw) >= 2 else 0
    n_blocks = max(0, (len(raw) - HEADER_BYTES) // BLOCK_BYTES)
    end = HEADER_BYTES + n_blocks * BLOCK_BYTES
    blocks = np.frombuffer(raw, dtype=np.uint8, count=end - HEADER_BYTES, offset=HEADER_BYTES)
    rec = blocks.reshape(n_blocks, BLOCK_BYTES)[:, FILLER_BYTES:].reshape(-1, RECORD_BYTES)
    u = rec.astype(np.int64)
    gsr = u[:, 11] | (u[:, 12] << 8)
    return SdChunk(
        path=path,
        size=len(raw),
        sample_rate_hz=TICK_HZ / divisor if divisor else float("nan"),
        ticks=u[:, 0] | (u[:, 1] << 8) | (u[:, 2] << 16),
        acc=np.ascontiguousarray(rec[:, 3:9]).view("<i2").reshape(-1, 3),
        ppg=u[:, 9] | (u[:, 10] << 8),
        gsr_range=gsr >> 14,
        gsr_adc=gsr & 0x3FFF,
        zero=~rec.any(axis=1),
        trailing_bytes=max(0, len(raw) - end) if len(raw) >= HEADER_BYTES else len(raw),
    )


def find_runs(card: Path) -> list[SdRun]:
    """Every ``<DEV>-<run>`` folder under ``card/data`` with its ``NNN`` chunks, sorted by name.

    Only three-digit chunk names count, so OS files (Spotlight indexes, ``.DS_Store``, copy
    temporaries) are ignored. A copy's ``<DEV>-<run> 2`` is a run of its own; deduplication is
    by content, later.
    """
    data = Path(card) / "data"
    runs = []
    for folder in sorted(p for p in data.rglob("*") if p.is_dir()):
        m = RUN_RE.fullmatch(folder.name)
        if not m or any(part.startswith(".") for part in folder.relative_to(data).parts):
            continue
        chunks = tuple(
            sorted(p for p in folder.iterdir() if p.is_file() and CHUNK_RE.fullmatch(p.name))
        )
        if chunks:
            runs.append(SdRun(m.group(1), folder.relative_to(data).as_posix(), chunks))
    return sorted(runs, key=lambda r: r.name)
