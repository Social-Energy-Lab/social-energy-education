"""SD cards and Shimmer Base exports → canonical per-second, SCR and wear tables.

Pure: raw files in, ``polars`` frames out (AGENTS.md invariant 3). Devices are processed one
at a time and runs one at a time, so a card of a week's recording never sits in memory whole.
Nothing is resolved to people here; that is the spine's job (``person_minutes``).
"""

from __future__ import annotations

import hashlib
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl

from . import calibration, sd
from .export import SATURATED_US, export_device, read_export
from .features import ScrConfig, WearConfig, artifact_seconds, detect_scr, wear_bouts
from .timeline import ChunkInfo, RunTimeline, TimelineConfig, place_run

SECONDS_SCHEMA = {
    "device": pl.String,
    "t": pl.Datetime("us", "UTC"),
    "source": pl.String,
    "run": pl.String,
    "samples": pl.Int32,
    "gsr_samples": pl.Int32,
    "conductance_us": pl.Float32,
    "gsr_range": pl.Int8,
    "motion_g": pl.Float32,
    "motion_sd_g": pl.Float32,
    "ppg_mv": pl.Float32,
    "hr_bpm": pl.Float32,
    "gap_ambiguous": pl.Boolean,
}
SOURCE_PRIORITY = {"sd": 0, "export": 1}


@dataclass(frozen=True)
class EdaConfig:
    #: Plausibility window (UTC dates, inclusive): times and anchors outside it are suspect.
    valid_from: date
    valid_to: date
    #: Added to a chunk's stored modification time to give UTC (see the study config).
    mtime_to_utc_s: float = 0.0
    rotation_s: float | None = 3600.0
    full_chunk_bytes: int = 6_100_265
    max_step_s: float = 60.0
    anchor_tolerance_s: float = 5.0
    min_segment_records: int = 128
    drift_min_span_s: float = 7200.0
    scr: ScrConfig = field(default_factory=ScrConfig)
    wear: WearConfig = field(default_factory=WearConfig)

    @property
    def window_s(self) -> tuple[float, float]:
        lo = datetime.combine(self.valid_from, time(), UTC)
        hi = datetime.combine(self.valid_to + timedelta(days=1), time(), UTC)
        return lo.timestamp(), hi.timestamp()

    def timeline(self) -> TimelineConfig:
        lo, hi = self.window_s
        return TimelineConfig(
            mtime_to_utc_s=self.mtime_to_utc_s,
            anchor_from_s=lo,
            anchor_to_s=hi,
            max_step_s=self.max_step_s,
            anchor_tolerance_s=self.anchor_tolerance_s,
            min_segment_records=self.min_segment_records,
            rotation_s=self.rotation_s,
            drift_min_span_s=self.drift_min_span_s,
        )


@dataclass(frozen=True)
class EdaTables:
    files: pl.DataFrame  # one row per chunk or export file
    seconds: pl.DataFrame  # one row per device-second and source
    scr: pl.DataFrame  # one row per SCR
    wear: pl.DataFrame  # wear bouts per device
    qa: dict[str, Any]


def _seconds(
    device: str,
    source: str,
    run: str,
    t: np.ndarray,
    us: np.ndarray,
    gsr_range: np.ndarray,
    acc_g: np.ndarray,
    ppg_mv: np.ndarray,
    hr_bpm: np.ndarray | None = None,
    ambiguous: np.ndarray | None = None,
) -> pl.DataFrame:
    placed = np.isfinite(t)
    if not placed.any():
        return pl.DataFrame(schema=SECONDS_SCHEMA)
    sec = np.floor(t[placed]).astype(np.int64)
    uniq, inv = np.unique(sec, return_inverse=True)
    m = len(uniq)
    us = us[placed]
    valid = np.isfinite(us)
    n = np.bincount(inv, minlength=m)
    nv = np.bincount(inv, valid, minlength=m)
    mag = np.sqrt((acc_g[placed] ** 2).sum(axis=1))
    mag_mean = np.bincount(inv, mag, minlength=m) / n
    mag_sd = np.sqrt(np.maximum(np.bincount(inv, mag**2, minlength=m) / n - mag_mean**2, 0))
    rng = np.clip(gsr_range[placed], 0, 3)
    mode = np.bincount(inv * 4 + rng, minlength=m * 4).reshape(m, 4).argmax(axis=1)
    with np.errstate(invalid="ignore", divide="ignore"):
        cond = np.bincount(inv, np.where(valid, us, 0), minlength=m) / nv
        if hr_bpm is not None:
            hr = hr_bpm[placed]
            hv = np.isfinite(hr)
            hr_mean = np.bincount(inv, np.where(hv, hr, 0), minlength=m) / np.bincount(
                inv, hv, minlength=m
            )
        else:
            hr_mean = np.full(m, np.nan)
    amb = (
        np.bincount(inv, ambiguous[placed], minlength=m) > 0
        if ambiguous is not None
        else np.zeros(m, bool)
    )
    return (
        pl.DataFrame(
            {
                "device": [device] * m,
                "t": uniq * 1_000_000,
                "source": [source] * m,
                "run": [run] * m,
                "samples": n,
                "gsr_samples": nv.astype(np.int64),
                "conductance_us": cond,
                "gsr_range": mode,
                "motion_g": mag_mean,
                "motion_sd_g": mag_sd,
                "ppg_mv": np.bincount(inv, ppg_mv[placed], minlength=m) / n,
                "hr_bpm": hr_mean,
                "gap_ambiguous": amb,
            }
        )
        .with_columns(
            pl.col("t").cast(pl.Datetime("us", "UTC")),
            pl.col("conductance_us", "hr_bpm").fill_nan(None),
        )
        .cast(SECONDS_SCHEMA)
    )


def _with_artifacts(
    seconds: pl.DataFrame, t: np.ndarray, us: np.ndarray, config: ScrConfig
) -> pl.DataFrame:
    fin = np.isfinite(t)
    bad = artifact_seconds(t[fin], us[fin], config)
    return seconds.with_columns(
        pl.col("t").dt.epoch("s").is_in(pl.Series(bad, dtype=pl.Int64).implode()).alias("artifact")
    )


def _scr_frame(
    device: str, source: str, run: str, t: np.ndarray, us: np.ndarray, config: ScrConfig
) -> pl.DataFrame:
    order = np.argsort(t, kind="stable")
    scr = detect_scr(t[order], us[order], config)
    return scr.with_columns(
        pl.lit(device).alias("device"), pl.lit(source).alias("source"), pl.lit(run).alias("run")
    )


def _sha256(path: Path) -> str:
    with path.open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def place_sd_run(
    run: sd.SdRun, keep: list[Path], config: EdaConfig
) -> tuple[list[sd.SdChunk], list[ChunkInfo], RunTimeline]:
    """Decode the chunks ``keep`` of ``run`` and place their records in time."""
    chunks = [sd.read_chunk(p) for p in keep]
    present = {int(p.name) for p in run.chunks}
    infos = [
        ChunkInfo(
            mtime_s=p.stat().st_mtime,
            truncated=c.size % 4096 == 0 and c.size != config.full_chunk_bytes,
            rotated=int(p.name) + 1 in present,
        )
        for p, c in zip(keep, chunks, strict=True)
    ]
    tl = place_run([c.ticks for c in chunks], [c.zero for c in chunks], infos, config.timeline())
    return chunks, infos, tl


def unique_sd_runs(
    runs: list[sd.SdRun], seen: set[str]
) -> tuple[list[tuple[sd.SdRun, list[Path]]], list[tuple[sd.SdRun, Path]]]:
    """One device's runs, most complete copy first, each with its chunks not byte-identical
    to one already taken (``seen`` holds their digests and is updated), and the skipped
    copies."""
    kept, copies = [], []
    for run in sorted(runs, key=lambda r: (-len(r.chunks), r.name)):
        keep = []
        for p in run.chunks:
            digest = _sha256(p)
            if digest in seen:
                copies.append((run, p))
                continue
            seen.add(digest)
            keep.append(p)
        if keep:
            kept.append((run, keep))
    return kept, copies


def _process_run(device: str, run: sd.SdRun, keep: list[Path], config: EdaConfig):
    chunks, infos, tl = place_sd_run(run, keep, config)
    rng = np.concatenate([c.gsr_range for c in chunks])
    us = calibration.gsr_microsiemens(rng, np.concatenate([c.gsr_adc for c in chunks]))
    us[us >= SATURATED_US] = np.nan
    acc = calibration.accel_g(np.concatenate([c.acc for c in chunks]))
    ppg = calibration.ppg_mv(np.concatenate([c.ppg for c in chunks]))
    seconds = _with_artifacts(
        _seconds(device, "sd", run.name, tl.t, us, rng, acc, ppg), tl.t, us, config.scr
    )
    scr = _scr_frame(
        device, "sd", run.name, tl.t[np.isfinite(tl.t)], us[np.isfinite(tl.t)], config.scr
    )
    files = []
    offset = 0
    lo, hi = config.window_s
    for p, c, info in zip(keep, chunks, infos, strict=True):
        sl = slice(offset, offset + len(c.ticks))
        offset += len(c.ticks)
        tt = tl.t[sl]
        fin = tt[np.isfinite(tt)]
        files.append(
            {
                "device": device,
                "source": "sd",
                "run": run.name,
                "path": p.as_posix(),
                "records": len(c.ticks),
                "records_bad": int(tl.bad[sl].sum()),
                "records_unanchored": int(tl.unanchored[sl].sum()),
                "records_placed": len(fin),
                "records_implausible": int(((fin < lo) | (fin >= hi)).sum()),
                "start": float(fin.min()) if len(fin) else None,
                "end": float(fin.max()) if len(fin) else None,
                "truncated": info.truncated,
                "duplicate": False,
            }
        )
    return seconds, scr, files, tl.qa


def _empty_scr() -> pl.DataFrame:
    return pl.DataFrame(
        schema={
            "onset_s": pl.Float64,
            "peak_s": pl.Float64,
            "amplitude_us": pl.Float64,
            "rise_s": pl.Float64,
            "onset_us": pl.Float64,
            "artifact": pl.Boolean,
            "device": pl.String,
            "source": pl.String,
            "run": pl.String,
        }
    )


def ingest_eda(cards: list[Path], exports: list[Path], config: EdaConfig) -> EdaTables:
    """Every SD card in ``cards`` and every calibrated export in ``exports``, one device at a
    time. Byte-identical chunks and export files are read once (copies flagged ``duplicate``
    in ``files``); where SD and export cover the same device-second, the SD row is kept and
    the other flagged ``duplicate`` in ``seconds``."""
    runs_by_device: dict[str, list[sd.SdRun]] = defaultdict(list)
    for card in cards:
        for run in sd.find_runs(Path(card)):
            runs_by_device[run.device].append(run)
    exports_by_device: dict[str, list[Path]] = defaultdict(list)
    for path in exports:
        exports_by_device[export_device(Path(path))].append(Path(path))

    qa: dict[str, Any] = defaultdict(int)
    files_rows: list[dict] = []
    seconds_parts, scr_parts = [], []
    lo, hi = config.window_s
    for device in sorted(set(runs_by_device) | set(exports_by_device)):
        seen: set[str] = set()
        dev_seconds, dev_scr = [], []
        # Most complete copy first, so a partial copy's chunks are the ones skipped.
        kept, copies = unique_sd_runs(runs_by_device[device], seen)
        for run, p in copies:
            files_rows.append(
                {
                    "device": device,
                    "source": "sd",
                    "run": run.name,
                    "path": p.as_posix(),
                    "duplicate": True,
                }
            )
            qa["chunks_duplicate"] += 1
        for run, keep in kept:
            seconds, scr, files, tqa = _process_run(device, run, keep, config)
            dev_seconds.append(seconds)
            dev_scr.append(scr)
            files_rows += files
            qa["chunks"] += len(keep)
            for k in (
                "records",
                "records_zero",
                "records_bad",
                "records_unanchored",
                "segments",
                "segments_unanchored",
                "hidden_gaps",
            ):
                qa[f"sd_{k}"] += tqa[k]
        for path in sorted(exports_by_device[device]):
            digest = _sha256(path)
            if digest in seen:
                files_rows.append(
                    {
                        "device": device,
                        "source": "export",
                        "run": path.name,
                        "path": path.as_posix(),
                        "duplicate": True,
                    }
                )
                qa["export_files_duplicate"] += 1
                continue
            seen.add(digest)
            e = read_export(path, config.timeline())
            export_seconds = _seconds(
                device,
                "export",
                path.name,
                e.t,
                e.conductance_us,
                e.gsr_range,
                e.acc_g,
                e.ppg_mv,
                e.hr_bpm,
                e.gap_ambiguous,
            )
            dev_seconds.append(_with_artifacts(export_seconds, e.t, e.conductance_us, config.scr))
            fin = np.isfinite(e.t)
            dev_scr.append(
                _scr_frame(device, "export", path.name, e.t[fin], e.conductance_us[fin], config.scr)
            )
            placed = e.t[fin]
            files_rows.append(
                {
                    "device": device,
                    "source": "export",
                    "run": path.name,
                    "path": path.as_posix(),
                    "records": e.qa["records"],
                    "records_bad": e.qa["records_bad"],
                    "records_unanchored": 0,
                    "records_placed": int(fin.sum()),
                    "records_implausible": int(((placed < lo) | (placed >= hi)).sum()),
                    "start": float(placed.min()) if len(placed) else None,
                    "end": float(placed.max()) if len(placed) else None,
                    "truncated": False,
                    "duplicate": False,
                    "clock": e.qa["clock"],
                    "segments_gap_ambiguous": e.qa["segments_gap_ambiguous"],
                }
            )
            qa["export_files"] += 1
            qa["export_records"] += e.qa["records"]
            qa["export_records_bad"] += e.qa["records_bad"]
            qa["export_segments_gap_ambiguous"] += e.qa["segments_gap_ambiguous"]
        if dev_seconds:
            s = (
                pl.concat(dev_seconds)
                .with_columns(pl.col("source").replace_strict(SOURCE_PRIORITY).alias("_p"))
                .sort("t", "_p", "run")
            )
            s = s.with_columns(pl.col("t").is_first_distinct().not_().alias("duplicate")).drop("_p")
            seconds_parts.append(s)
        if dev_scr:
            scr_parts.append(pl.concat(dev_scr, how="vertical_relaxed"))

    seconds = (
        pl.concat(seconds_parts)
        if seconds_parts
        else pl.DataFrame(
            schema={**SECONDS_SCHEMA, "artifact": pl.Boolean, "duplicate": pl.Boolean}
        )
    )
    t_s = pl.col("t").dt.epoch("s")
    seconds = seconds.with_columns(((t_s < lo) | (t_s >= hi)).alias("implausible_time"))
    seconds = seconds.with_columns((~pl.col("duplicate") & ~pl.col("implausible_time")).alias("ok"))
    wear, flagged = wear_bouts(
        seconds.filter("ok").select("device", "t", "conductance_us"), config.wear
    )
    seconds = seconds.join(
        flagged.select("device", "t", "contact", "worn"), on=["device", "t"], how="left"
    ).with_columns(pl.col("contact", "worn").fill_null(False))

    scr = pl.concat(scr_parts, how="vertical_relaxed") if scr_parts else _empty_scr()
    scr = (
        scr.with_columns(
            (pl.col("onset_s") * 1_000_000)
            .cast(pl.Int64)
            .cast(pl.Datetime("us", "UTC"))
            .alias("onset"),
            (pl.col("peak_s") * 1_000_000)
            .cast(pl.Int64)
            .cast(pl.Datetime("us", "UTC"))
            .alias("peak"),
            pl.col("onset_s").floor().cast(pl.Int64).alias("_sec"),
        )
        .join(
            seconds.select(
                "device", "source", "run", pl.col("t").dt.epoch("s").alias("_sec"), "ok", "worn"
            ),
            on=["device", "source", "run", "_sec"],
            how="left",
        )
        .with_columns(pl.col("ok", "worn").fill_null(False))
        .select(
            "device",
            "source",
            "run",
            "onset",
            "peak",
            "amplitude_us",
            "rise_s",
            "onset_us",
            "artifact",
            "ok",
            "worn",
        )
        .sort("device", "onset")
    )
    files = (
        pl.DataFrame(files_rows, infer_schema_length=None).with_columns(
            pl.col(c).cast(pl.Float64).mul(1_000_000).cast(pl.Int64).cast(pl.Datetime("us", "UTC"))
            for c in ("start", "end")
        )
        if files_rows
        else pl.DataFrame()
    )

    qa = dict(qa)
    qa["seconds"] = seconds.height
    qa["seconds_duplicate"] = int(seconds["duplicate"].sum())
    qa["seconds_implausible"] = int(seconds["implausible_time"].sum())
    qa["seconds_ok"] = int(seconds["ok"].sum())
    qa["seconds_worn"] = int((seconds["ok"] & seconds["worn"]).sum())
    qa["seconds_worn_artifact"] = int((seconds["ok"] & seconds["worn"] & seconds["artifact"]).sum())
    qa["scr"] = scr.height
    qa["scr_ok_worn_clean"] = int((scr["ok"] & scr["worn"] & ~scr["artifact"]).sum())
    qa["scr_ok_worn"] = int((scr["ok"] & scr["worn"]).sum())
    qa["wear_bouts"] = wear.height
    return EdaTables(files=files, seconds=seconds, scr=scr, wear=wear, qa=qa)
