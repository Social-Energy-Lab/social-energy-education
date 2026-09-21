"""Synthetic AudioMoth-style WAV files (16-bit PCM mono with an ICMT comment chunk)."""

from __future__ import annotations

import struct
from datetime import datetime
from pathlib import Path

import numpy as np


def audiomoth_comment(recorded_at: datetime, tz_label: str = "UTC") -> str:
    return (
        f"Recorded at {recorded_at:%H:%M:%S %d/%m/%Y} ({tz_label}) by AudioMoth "
        "0000000000000000 at medium gain while battery was greater than 4.9V "
        "and temperature was 21.0C."
    )


def write_wav(
    path: Path, samples: np.ndarray, sample_rate: int, comment: str | None = None
) -> Path:
    """Write mono 16-bit PCM. ``samples`` are floats in [-1, 1]."""
    pcm = (np.clip(samples, -1, 1) * 32767).astype("<i2").tobytes()
    fmt = struct.pack("<HHIIHH", 1, 1, sample_rate, sample_rate * 2, 2, 16)
    chunks = [b"fmt " + struct.pack("<I", len(fmt)) + fmt]
    if comment is not None:
        text = comment.encode("ascii") + b"\x00"
        if len(text) % 2:
            text += b"\x00"
        info = b"INFO" + b"ICMT" + struct.pack("<I", len(text)) + text
        chunks.append(b"LIST" + struct.pack("<I", len(info)) + info)
    chunks.append(b"data" + struct.pack("<I", len(pcm)) + pcm)
    body = b"WAVE" + b"".join(chunks)
    Path(path).write_bytes(b"RIFF" + struct.pack("<I", len(body)) + body)
    return Path(path)


def tone_with_bursts(
    seconds: int, sample_rate: int, *, loud_from_s: int, loud_to_s: int, seed: int = 0
) -> np.ndarray:
    """Quiet noise with a loud, broadband burst (think applause) in a known window."""
    rng = np.random.default_rng(seed)
    t = np.arange(seconds * sample_rate) / sample_rate
    signal = 0.01 * rng.standard_normal(t.size) + 0.02 * np.sin(2 * np.pi * 440 * t)
    burst = (t >= loud_from_s) & (t < loud_to_s)
    signal[burst] += 0.5 * rng.standard_normal(burst.sum())
    return signal
