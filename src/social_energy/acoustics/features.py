"""AudioMoth WAV → coarse, non-invertible acoustic features, then verified deletion.

Ethics constraint (see docs/context/instruments/acoustics.md): recordings are
temporary. Only frequency and level features may be kept, never content. Features
here are per-window aggregates over a few wide frequency bands. They can show
applause, singing, laughter or silence, but they cannot reconstruct speech.
"""

from __future__ import annotations

import hashlib
import re
import struct
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, timezone
from itertools import pairwise
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import polars as pl

COMMENT_RE = re.compile(
    r"Recorded at (\d{2}:\d{2}:\d{2} \d{2}/\d{2}/\d{4}) \(UTC(?:([+-])(\d{1,2})(?::(\d{2}))?)?\)"
)
FILENAME_RE = re.compile(r"(\d{8}_\d{6})")
EPS = 1e-12


@dataclass(frozen=True)
class AcousticsConfig:
    window_s: float = 1.0
    band_edges_hz: tuple[float, ...] = (0, 300, 1000, 2000, 4000, 8000, 24000)
    # Used only when the WAV has no AudioMoth comment. AudioMoth names files in UTC
    # unless configured otherwise; confirm per deployment.
    filename_timezone: str = "UTC"


@dataclass(frozen=True)
class _Wav:
    sample_rate: int
    data_offset: int
    n_samples: int
    comment: str | None


def _read_header(path: Path) -> _Wav:
    with path.open("rb") as f:
        riff = f.read(12)
        if len(riff) < 12 or riff[:4] != b"RIFF" or riff[8:12] != b"WAVE":
            raise ValueError("not a RIFF/WAVE file")
        sample_rate = channels = bits = None
        comment = None
        while True:
            header = f.read(8)
            if len(header) < 8:
                raise ValueError("no data chunk")
            cid, size = header[:4], struct.unpack("<I", header[4:])[0]
            if cid == b"fmt ":
                fmt = f.read(size)
                audio_format, channels, sample_rate = struct.unpack("<HHI", fmt[:8])
                bits = struct.unpack("<H", fmt[14:16])[0]
                if audio_format != 1 or channels != 1 or bits != 16:
                    raise ValueError("expected mono 16-bit PCM")
            elif cid == b"LIST":
                payload = f.read(size)
                idx = payload.find(b"ICMT")
                if idx >= 0:
                    n = struct.unpack("<I", payload[idx + 4 : idx + 8])[0]
                    comment = (
                        payload[idx + 8 : idx + 8 + n].split(b"\x00")[0].decode("ascii", "replace")
                    )
            elif cid == b"data":
                if sample_rate is None:
                    raise ValueError("data chunk before fmt chunk")
                return _Wav(sample_rate, f.tell(), size // 2, comment)
            else:
                f.seek(size, 1)
            if size % 2:
                f.seek(1, 1)


def _start_time(path: Path, wav: _Wav, config: AcousticsConfig) -> datetime:
    if wav.comment and (m := COMMENT_RE.search(wav.comment)):
        local = datetime.strptime(m.group(1), "%H:%M:%S %d/%m/%Y")
        sign, hours, minutes = m.group(2), m.group(3), m.group(4)
        offset = timedelta(hours=int(hours or 0), minutes=int(minutes or 0))
        tz = timezone(-offset if sign == "-" else offset)
        return local.replace(tzinfo=tz).astimezone(UTC)
    if m := FILENAME_RE.search(path.name):
        local = datetime.strptime(m.group(1), "%Y%m%d_%H%M%S")
        return local.replace(tzinfo=ZoneInfo(config.filename_timezone)).astimezone(UTC)
    raise ValueError("no recording time in comment or filename")


def extract_features(path: Path, config: AcousticsConfig) -> pl.DataFrame:
    path = Path(path)
    wav = _read_header(path)
    start = _start_time(path, wav, config)
    window = round(config.window_s * wav.sample_rate)
    n_windows = wav.n_samples // window
    samples = np.memmap(path, dtype="<i2", mode="r", offset=wav.data_offset, shape=(wav.n_samples,))

    freqs = np.fft.rfftfreq(window, d=1 / wav.sample_rate)
    nyquist = wav.sample_rate / 2
    edges = [e for e in config.band_edges_hz if e < nyquist] + [nyquist]
    band_masks = [(freqs >= lo) & (freqs < hi) for lo, hi in pairwise(edges)]
    band_names = [f"band_{int(lo)}_{int(hi)}_db" for lo, hi in pairwise(edges)]

    rows: dict[str, list[float]] = {
        k: [] for k in ["rms_dbfs", "peak_dbfs", "zcr", "spectral_centroid_hz", "spectral_flatness"]
    }
    bands: dict[str, list[float]] = {name: [] for name in band_names}
    hann = np.hanning(window)
    for i in range(n_windows):
        x = samples[i * window : (i + 1) * window].astype(np.float64) / 32768.0
        rms = np.sqrt(np.mean(x**2))
        rows["rms_dbfs"].append(20 * np.log10(rms + EPS))
        rows["peak_dbfs"].append(20 * np.log10(np.max(np.abs(x)) + EPS))
        rows["zcr"].append(float(np.mean(np.abs(np.diff(np.signbit(x).astype(np.int8))))))
        power = np.abs(np.fft.rfft(x * hann)) ** 2
        total = power.sum() + EPS
        rows["spectral_centroid_hz"].append(float((freqs * power).sum() / total))
        rows["spectral_flatness"].append(
            float(np.exp(np.mean(np.log(power + EPS))) / (np.mean(power) + EPS))
        )
        for name, mask in zip(band_names, band_masks, strict=True):
            bands[name].append(10 * np.log10(power[mask].sum() + EPS))

    del samples  # release the memory map so the WAV can be deleted (Windows locks mapped files)
    times = [start + timedelta(seconds=i * config.window_s) for i in range(n_windows)]
    return pl.DataFrame(
        {"t": times, **rows, **bands},
        schema_overrides={"t": pl.Datetime("us", "UTC")},
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def extract_directory(
    wav_dir: Path, out_dir: Path, config: AcousticsConfig, *, delete_wavs: bool
) -> pl.DataFrame:
    """Extract features for every WAV in ``wav_dir``; optionally delete each verified WAV.

    A WAV is deleted only after its feature file has been written, read back, and
    found to have the expected number of windows. Every file gets a manifest row
    (checksum, window count, deletion, error), saved as ``manifest.parquet``.
    """
    wav_dir, out_dir = Path(wav_dir), Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest = []
    for wav in sorted(p for p in wav_dir.iterdir() if p.suffix.lower() == ".wav"):
        row = {"wav": wav.name, "wav_sha256": "", "windows": 0, "deleted": False, "error": ""}
        try:
            row["wav_sha256"] = _sha256(wav)
            features = extract_features(wav, config)
            target = out_dir / f"{wav.stem}.parquet"
            features.write_parquet(target)
            reread = pl.read_parquet(target)
            header = _read_header(wav)
            expected = header.n_samples // round(config.window_s * header.sample_rate)
            if reread.height != expected or reread.height == 0:
                raise ValueError(f"feature rows {reread.height} != expected {expected}")
            row["windows"] = reread.height
            if delete_wavs:
                wav.unlink()
                row["deleted"] = True
        except (ValueError, OSError, struct.error) as err:
            row["error"] = str(err) or type(err).__name__
        manifest.append(row)
    table = pl.DataFrame(
        manifest,
        schema={"wav": pl.String, "wav_sha256": pl.String, "windows": pl.Int64,
                "deleted": pl.Boolean, "error": pl.String},
    )  # fmt: skip
    previous = out_dir / "manifest.parquet"
    if previous.exists():
        table = pl.concat([pl.read_parquet(previous), table])
    table.write_parquet(previous)
    return table.tail(len(manifest))
