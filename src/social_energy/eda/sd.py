"""Shimmer SD-card logs: find the recording runs on a card and decode their chunk files.

Layout (docs/context/instruments/eda.md): a 384-byte header, then blocks of 503 bytes, each
a 9-byte sync slot and 38 records of 13 bytes. The header holds the device clock at the
chunk's first record; the sync slot is ``0xFF`` except, about once an hour on a device in a
sync group, for the offset between the device's clock and the sync master's. Decoding is pure
byte arithmetic; time placement is ``eda.timeline``'s job, clock correction ``eda.clock``'s.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

HEADER_BYTES = 384
FILLER_BYTES = 9
RECORD_BYTES = 13
RECORDS_PER_BLOCK = 38
BLOCK_BYTES = FILLER_BYTES + RECORDS_PER_BLOCK * RECORD_BYTES  # 503
TICK_HZ = 32768
TICK_WRAP = 1 << 24  # the counter is 24 bits: it wraps every 512 s

#: Header fields (byte offsets).
HEADER_MASTER_BYTE = 16  # trial config 0: 0x37 sync master, 0x35 slave
MASTER_FLAG = 0x37
HEADER_SYNC_BYTE = 17  # trial config 1: bit 0 = sync on
HEADER_RTC_DIFF = slice(44, 52)  # 8 bytes big-endian: clock origin in ticks
HEADER_CONFIG_TIME = slice(52, 56)  # 4 bytes big-endian: Unix seconds of the configuration
HEADER_START_HIGH = 251  # bits 39-32 of the device clock (ticks) at the first record
HEADER_START_LOW = slice(252, 256)  # bits 31-0, little-endian

RUN_RE = re.compile(r"(SH\d+)-\d{3}( \d+)?")
CHUNK_RE = re.compile(r"\d{3}")
DATA_RE = re.compile(r"data( \d+)?")


@dataclass(frozen=True)
class SdHeader:
    divisor: int  # sample-rate divisor: 32768 / divisor Hz
    master: bool  # the device was the sync master
    sync_on: bool
    config_time_s: int  # Unix seconds of the configuration (not of the data)
    #: Device clock at the chunk's first record, in ticks since the Unix epoch: the 40-bit
    #: header count plus the clock origin. Its low 24 bits are the record's tick counter.
    start_ticks: int

    @property
    def start_s(self) -> float:
        """The device's clock at the chunk's first record (UTC epoch seconds, uncorrected)."""
        return self.start_ticks / TICK_HZ


def read_header(raw: bytes) -> SdHeader | None:
    """The header fields, or None if the chunk is shorter than a header."""
    if len(raw) < HEADER_BYTES:
        return None
    high = raw[HEADER_START_HIGH]
    low = int.from_bytes(raw[HEADER_START_LOW], "little")
    return SdHeader(
        divisor=int.from_bytes(raw[0:2], "little"),
        master=raw[HEADER_MASTER_BYTE] == MASTER_FLAG,
        sync_on=bool(raw[HEADER_SYNC_BYTE] & 1),
        config_time_s=int.from_bytes(raw[HEADER_CONFIG_TIME], "big"),
        start_ticks=((high << 32) | low) + int.from_bytes(raw[HEADER_RTC_DIFF], "big"),
    )


def sync_slots(slots: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Sync records among the blocks' 9-byte slots: ``(block index, offset in ticks)``.

    A slot holds a sign byte (0: +, 1: -) and an 8-byte little-endian tick count: the
    device's clock minus the master's. Untouched slots are ``0xFF``. Corrupt blocks hold
    lookalikes; only the plausible shape is kept here (sign 0 or 1, under 2^32 ticks, not
    all zero) and the rest of the screening is the clock model's.
    """
    slots = np.asarray(slots, np.uint8).reshape(-1, FILLER_BYTES)
    sign = slots[:, 0]
    value = slots[:, 1:].astype(np.int64)
    small = ~value[:, 4:].any(axis=1)
    keep = np.flatnonzero((sign <= 1) & small & slots.any(axis=1))
    v = value[keep]
    ticks = v[:, 0] | (v[:, 1] << 8) | (v[:, 2] << 16) | (v[:, 3] << 24)
    return keep, np.where(sign[keep] == 1, -ticks, ticks)


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
    header: SdHeader | None = None
    sync_block: np.ndarray = field(default_factory=lambda: np.zeros(0, np.int64))
    sync_offset_ticks: np.ndarray = field(default_factory=lambda: np.zeros(0, np.int64))


@dataclass(frozen=True)
class SdRun:
    """One recording run: ``<DEV>-<run>`` and its chunk files in order."""

    device: str
    name: str  # path below the card, e.g. "data/day3_1787119190/SH10-000"
    chunks: tuple[Path, ...]


def read_chunk(path: Path) -> SdChunk:
    path = Path(path)
    raw = path.read_bytes()
    divisor = int.from_bytes(raw[0:2], "little") if len(raw) >= 2 else 0
    n_blocks = max(0, (len(raw) - HEADER_BYTES) // BLOCK_BYTES)
    end = HEADER_BYTES + n_blocks * BLOCK_BYTES
    if n_blocks:
        blocks = np.frombuffer(raw, dtype=np.uint8, count=end - HEADER_BYTES, offset=HEADER_BYTES)
        blocks = blocks.reshape(n_blocks, BLOCK_BYTES)
        rec = blocks[:, FILLER_BYTES:].reshape(-1, RECORD_BYTES)
        sync_block, sync_ticks = sync_slots(blocks[:, :FILLER_BYTES])
    else:
        rec = np.zeros((0, RECORD_BYTES), np.uint8)
        sync_block = sync_ticks = np.zeros(0, np.int64)
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
        header=read_header(raw),
        sync_block=sync_block,
        sync_offset_ticks=sync_ticks,
    )


def find_runs(card: Path) -> list[SdRun]:
    """Every ``<DEV>-<run>`` folder under the card's ``data`` folder (or a copy of it such as
    ``data 2``) with its ``NNN`` chunks, sorted by name.

    Only three-digit chunk names count, so OS files (Spotlight indexes, ``.DS_Store``, copy
    temporaries) are ignored. Copies (``<DEV>-<run> 2``, ``data 2``) are runs of their own;
    deduplication is by content, later.
    """
    card = Path(card)
    runs = []
    for data in sorted(p for p in card.iterdir() if p.is_dir() and DATA_RE.fullmatch(p.name)):
        for folder in sorted(p for p in data.rglob("*") if p.is_dir()):
            m = RUN_RE.fullmatch(folder.name)
            if not m or any(part.startswith(".") for part in folder.relative_to(data).parts):
                continue
            chunks = tuple(
                sorted(p for p in folder.iterdir() if p.is_file() and CHUNK_RE.fullmatch(p.name))
            )
            if chunks:
                runs.append(SdRun(m.group(1), folder.relative_to(card).as_posix(), chunks))
    return sorted(runs, key=lambda r: r.name)
