"""SD cards and Shimmer Base exports → canonical per-second, SCR and wear tables.

Pure: raw files in, ``polars`` frames out (AGENTS.md invariant 3). Devices are processed one
at a time and runs one at a time, so a card of a week's recording never sits in memory whole.
Nothing is resolved to people here; that is the spine's job (``person_minutes``).

Two passes. The first places every SD run on its device's own clock and collects the sync
records and run spans; ``eda.clock`` builds the per-run clock model from them. The second
places the runs again, corrects their times through the model, and builds the tables.
Exports are matched against the SD run of the same device (their clock is the device's
plus one constant per file) and corrected through that run's model; an export with no SD
counterpart gets its unit's fallback, flagged ``clock_uncertain``.
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
from .clock import RECORDS_SCHEMA, RUNS_SCHEMA, ClockConfig, ClockModel, comotion, match_lag
from .export import SATURATED_US, export_device, export_span, read_export
from .features import (
    ScrConfig,
    WearConfig,
    _resample,
    artifact_seconds,
    detect_scr,
    wear_bouts,
)
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
    "clock_uncertain": pl.Boolean,
    "clock_correction_s": pl.Float32,
}
SOURCE_PRIORITY = {"sd": 0, "export": 1}
#: Rate of the conductance series used to match an export against its SD card.
MATCH_HZ = 8.0
#: Rate of the motion series used for the co-motion check.
COMOTION_HZ = 64.0


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
    #: Correct device clocks through their sync records (``eda.clock``); False keeps them.
    correct_clocks: bool = True
    clock: ClockConfig = field(default_factory=ClockConfig)
    #: Windows (UTC epoch seconds) in which devices lay together: the co-motion check.
    comotion_windows: tuple[tuple[float, float], ...] = ()
    comotion_window_s: float = 600.0  # sub-window length of the co-motion check
    #: Export file name -> UTC epoch seconds of its first row, for exports without a clock.
    export_starts: dict[str, float] = field(default_factory=dict)
    sample_rate_hz: float = 128.0
    #: How far apart an export's clock and its SD card's may be (s).
    export_max_lag_s: float = 120.0
    export_min_match: float = 0.3

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
    clock: pl.DataFrame = field(default_factory=pl.DataFrame)  # one row per run's clock model
    comotion: pl.DataFrame = field(default_factory=pl.DataFrame)  # co-motion residuals


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
    uncertain: np.ndarray | None = None,
    correction: np.ndarray | None = None,
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

    def any_of(flag: np.ndarray | None) -> np.ndarray:
        if flag is None:
            return np.zeros(m, bool)
        return np.bincount(inv, flag[placed], minlength=m) > 0

    corr = (
        np.bincount(inv, correction[placed], minlength=m) / n
        if correction is not None
        else np.zeros(m)
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
                "gap_ambiguous": any_of(ambiguous),
                "clock_uncertain": any_of(uncertain),
                "clock_correction_s": corr,
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
    """Decode the chunks ``keep`` of ``run`` and place their records on the device's own
    clock (correct it with ``ClockModel.correct``)."""
    chunks = [sd.read_chunk(p) for p in keep]
    present = {int(p.name) for p in run.chunks}
    infos = [
        ChunkInfo(
            mtime_s=p.stat().st_mtime,
            truncated=c.size % 4096 == 0 and c.size != config.full_chunk_bytes,
            rotated=int(p.name) + 1 in present,
            header_ticks=c.header.start_ticks if c.header is not None else None,
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


def scan_run(device: str, run: sd.SdRun, keep: list[Path], config: EdaConfig):
    """Pass 1: the run's span on the device clock, its master flag, and its sync records
    (only those in a block whose first record is good and placed)."""
    chunks, _, tl = place_sd_run(run, keep, config)
    records = []
    offset = 0
    for c in chunks:
        for blk, ticks in zip(c.sync_block, c.sync_offset_ticks, strict=True):
            i = offset + int(blk) * sd.RECORDS_PER_BLOCK
            if i < len(tl.t) and not tl.bad[i] and np.isfinite(tl.t[i]):
                records.append((device, run.name, float(tl.t[i]), int(ticks) / sd.TICK_HZ))
        offset += len(c.ticks)
    fin = tl.t[np.isfinite(tl.t)]
    span = (float(fin.min()), float(fin.max())) if len(fin) else None
    # A unit flagged master with sync off leads no group.
    master = any(c.header is not None and c.header.master and c.header.sync_on for c in chunks)
    return records, span, master


def _jerk(acc: np.ndarray) -> np.ndarray:
    d = np.diff(np.asarray(acc, float), axis=0, prepend=np.asarray(acc[:1], float))
    return np.sqrt((d**2).sum(axis=1))


@dataclass
class _ComotionGrid:
    lo: float
    hi: float
    signals: dict[str, np.ndarray] = field(default_factory=dict)

    def add(self, device: str, t: np.ndarray, jerk: np.ndarray) -> None:
        m = np.isfinite(t) & (t >= self.lo) & (t < self.hi)
        if not m.any():
            return
        n = int((self.hi - self.lo) * COMOTION_HZ)
        grid = self.signals.setdefault(device, np.full(n, np.nan, np.float32))
        i = np.clip(((t[m] - self.lo) * COMOTION_HZ).astype(np.int64), 0, n - 1)
        np.fmax.at(grid, i, jerk[m].astype(np.float32))


def _process_run(
    device: str,
    run: sd.SdRun,
    keep: list[Path],
    config: EdaConfig,
    model: ClockModel | None,
    grids: list[_ComotionGrid],
    keep_series: bool,
):
    chunks, infos, tl = place_sd_run(run, keep, config)
    t_dev = tl.t
    if model is not None:
        t, uncertain = model.correct(device, run.name, t_dev)
        rc = model.runs.get((device, run.name))
        kind = rc.kind if rc is not None else "rate"
    else:
        t, uncertain, kind = t_dev, np.zeros(len(t_dev), bool), "none"
    uncertain = uncertain | tl.by_mtime
    rng = np.concatenate([c.gsr_range for c in chunks])
    us = calibration.gsr_microsiemens(rng, np.concatenate([c.gsr_adc for c in chunks]))
    us[us >= SATURATED_US] = np.nan
    acc_raw = np.concatenate([c.acc for c in chunks])
    acc = calibration.accel_g(acc_raw)
    ppg = calibration.ppg_mv(np.concatenate([c.ppg for c in chunks]))
    seconds = _with_artifacts(
        _seconds(
            device,
            "sd",
            run.name,
            t,
            us,
            rng,
            acc,
            ppg,
            uncertain=uncertain,
            correction=t - t_dev,
        ),
        t,
        us,
        config.scr,
    )
    fin = np.isfinite(t)
    scr = _scr_frame(device, "sd", run.name, t[fin], us[fin], config.scr)
    if grids:
        good = fin & ~tl.bad
        jerk = np.full(len(t), np.nan)
        jerk[good] = _jerk(acc_raw[good])
        for g in grids:
            g.add(device, t, jerk)
    series = None
    if keep_series and fin.any():
        series = _resample(t_dev, us, MATCH_HZ)
    files = []
    offset = 0
    lo, hi = config.window_s
    for p, c, info in zip(keep, chunks, infos, strict=True):
        sl = slice(offset, offset + len(c.ticks))
        offset += len(c.ticks)
        tt = t[sl]
        ok = np.isfinite(tt)
        files.append(
            {
                "device": device,
                "source": "sd",
                "run": run.name,
                "path": p.as_posix(),
                "records": len(c.ticks),
                "records_bad": int(tl.bad[sl].sum()),
                "records_unanchored": int(tl.unanchored[sl].sum()),
                "records_placed": int(ok.sum()),
                "records_implausible": int(((tt[ok] < lo) | (tt[ok] >= hi)).sum()),
                "records_by_mtime": int(tl.by_mtime[sl].sum()),
                "start": float(tt[ok].min()) if ok.any() else None,
                "end": float(tt[ok].max()) if ok.any() else None,
                "truncated": info.truncated,
                "duplicate": False,
                "clock_model": kind,
                "clock_uncertain": bool(uncertain[sl][ok].any()) if ok.any() else None,
                "clock_correction_s": float(np.median((tt - t_dev[sl])[ok])) if ok.any() else None,
            }
        )
    return seconds, scr, files, tl.qa, series


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


def _session(path: Path) -> str:
    """``day3_Session1_SH14_Calibrated_SD.csv`` -> ``day3_Session1``."""
    return path.name.rsplit("_SH", 1)[0]


def build_clock_model(
    kept: dict[str, list[tuple[sd.SdRun, list[Path]]]], config: EdaConfig
) -> tuple[ClockModel, dict[str, list[tuple[str, float, float]]]]:
    """Pass 1 over every kept SD run: the clock model, and each device's run spans."""
    records, runs = [], []
    spans: dict[str, list[tuple[str, float, float]]] = defaultdict(list)
    for device, items in kept.items():
        for run, keep in items:
            rec, span, master = scan_run(device, run, keep, config)
            records += rec
            if span is not None:
                runs.append((device, run.name, span[0], span[1], master))
                spans[device].append((run.name, span[0], span[1]))
    model = ClockModel(
        pl.DataFrame(records, schema=RECORDS_SCHEMA, orient="row"),
        pl.DataFrame(runs, schema=RUNS_SCHEMA, orient="row"),
        config.clock,
    )
    return model, spans


def ingest_eda(cards: list[Path], exports: list[Path], config: EdaConfig) -> EdaTables:
    """Every SD card in ``cards`` and every calibrated export in ``exports``, one device at a
    time. Byte-identical chunks and export files are read once (copies flagged ``duplicate``
    in ``files``); where SD and export cover the same device-second, the SD row is kept and
    the other flagged ``duplicate`` in ``seconds``. Times are corrected per run through the
    clock model (``config.correct_clocks``)."""
    runs_by_device: dict[str, list[sd.SdRun]] = defaultdict(list)
    for card in cards:
        for run in sd.find_runs(Path(card)):
            runs_by_device[run.device].append(run)
    exports_by_device: dict[str, list[Path]] = defaultdict(list)
    for path in exports:
        exports_by_device[export_device(Path(path))].append(Path(path))
    devices = sorted(set(runs_by_device) | set(exports_by_device))

    qa: dict[str, Any] = defaultdict(int)
    files_rows: list[dict] = []
    seen: dict[str, set[str]] = {d: set() for d in devices}
    kept: dict[str, list[tuple[sd.SdRun, list[Path]]]] = {}
    for device in devices:
        kept[device], copies = unique_sd_runs(runs_by_device[device], seen[device])
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

    model, run_spans = build_clock_model(kept, config) if config.correct_clocks else (None, {})
    spans = {p: export_span(p) for d in devices for p in exports_by_device[d]}
    # Exports without a clock are placed from the corrected start of the other exports of
    # their session (the units were started together), so their devices come last.
    raw_starts: dict[str, list[float]] = defaultdict(list)
    for p, (first, _) in spans.items():
        if first is not None:
            raw_starts[_session(p)].append(first)
    starts: dict[str, list[float]] = defaultdict(list)
    clockless = {d for d in devices for p in exports_by_device[d] if spans[p][0] is None}
    devices = [d for d in devices if d not in clockless] + sorted(clockless)
    grids = [_ComotionGrid(lo, hi) for lo, hi in config.comotion_windows]

    seconds_parts, scr_parts = [], []
    lo, hi = config.window_s
    for device in devices:
        dev_seconds, dev_scr = [], []
        exp_spans = [
            (a - 3600, b + 3600) for p in exports_by_device[device] for a, b in [spans[p]] if a
        ]
        series: dict[str, tuple[np.ndarray, np.ndarray]] = {}
        for run, keep in kept[device]:
            span = next((s for s in run_spans.get(device, []) if s[0] == run.name), None)
            near = span is not None and any(a < span[2] and b > span[1] for a, b in exp_spans)
            seconds, scr, files, tqa, ser = _process_run(
                device, run, keep, config, model, grids, near
            )
            if ser is not None:
                series[run.name] = ser
            dev_seconds.append(seconds)
            dev_scr.append(scr)
            files_rows += files
            qa["chunks"] += len(keep)
            for k in (
                "records",
                "records_zero",
                "records_bad",
                "records_unanchored",
                "records_by_mtime",
                "segments",
                "segments_unanchored",
                "segments_by_mtime",
                "hidden_gaps",
                "mtime_disagreements",
            ):
                qa[f"sd_{k}"] += tqa[k]
        for path in sorted(exports_by_device[device]):
            digest = _sha256(path)
            if digest in seen[device]:
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
            seen[device].add(digest)
            start = config.export_starts.get(path.name)
            if start is None and spans[path][0] is None:
                peers = starts.get(_session(path)) or raw_starts.get(_session(path))
                if peers:
                    start = float(np.median(peers))
            e = read_export(path, config.timeline(), start, config.sample_rate_hz)
            t, unc, info = _correct_export(device, path, e, series, model, config)
            export_seconds = _seconds(
                device,
                "export",
                path.name,
                t,
                e.conductance_us,
                e.gsr_range,
                e.acc_g,
                e.ppg_mv,
                e.hr_bpm,
                e.gap_ambiguous,
                unc,
                t - e.t,
            )
            dev_seconds.append(_with_artifacts(export_seconds, t, e.conductance_us, config.scr))
            fin = np.isfinite(t)
            dev_scr.append(
                _scr_frame(device, "export", path.name, t[fin], e.conductance_us[fin], config.scr)
            )
            placed = t[fin]
            if len(placed) and e.qa["clock"] != "recovered":
                starts[_session(path)].append(float(placed[0]))
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
                    "clock_uncertain": bool(unc[fin].any()) if fin.any() else None,
                    "clock_correction_s": (float(np.median((t - e.t)[fin])) if fin.any() else None),
                    **info,
                }
            )
            qa["export_files"] += 1
            qa["export_records"] += e.qa["records"]
            qa["export_records_bad"] += e.qa["records_bad"]
            qa["export_segments_gap_ambiguous"] += e.qa["segments_gap_ambiguous"]
            qa[f"export_files_clock_{e.qa['clock']}"] += 1
            qa[f"export_files_{info['clock_model']}"] += 1
            del e
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
    wear = _wear_uncertain(wear, seconds)

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
                "device",
                "source",
                "run",
                pl.col("t").dt.epoch("s").alias("_sec"),
                "ok",
                "worn",
                "clock_uncertain",
            ),
            on=["device", "source", "run", "_sec"],
            how="left",
        )
        .with_columns(pl.col("ok", "worn", "clock_uncertain").fill_null(False))
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
            "clock_uncertain",
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
    worn_ok = seconds["ok"] & seconds["worn"]
    qa["seconds_worn"] = int(worn_ok.sum())
    qa["seconds_worn_artifact"] = int((worn_ok & seconds["artifact"]).sum())
    qa["seconds_worn_clock_uncertain"] = int((worn_ok & seconds["clock_uncertain"]).sum())
    qa["scr"] = scr.height
    qa["scr_ok_worn_clean"] = int((scr["ok"] & scr["worn"] & ~scr["artifact"]).sum())
    qa["scr_ok_worn"] = int((scr["ok"] & scr["worn"]).sum())
    qa["wear_bouts"] = wear.height
    clock = model.summary() if model is not None else pl.DataFrame()
    if model is not None:
        qa["clock"] = model.qa
    comotion_table = _comotion_table(grids, config)
    qa["comotion"] = comotion_summary(comotion_table)
    return EdaTables(
        files=files,
        seconds=seconds,
        scr=scr,
        wear=wear,
        qa=qa,
        clock=clock,
        comotion=comotion_table,
    )


def _correct_export(
    device: str,
    path: Path,
    e,
    series: dict[str, tuple[np.ndarray, np.ndarray]],
    model: ClockModel | None,
    config: EdaConfig,
) -> tuple[np.ndarray, np.ndarray, dict[str, Any]]:
    """Corrected times, ``clock_uncertain`` and file info for one export.

    The export's clock is the device's plus one constant: matched against an SD run of the
    same device (conductance, ``MATCH_HZ``), the constant is removed and the run's clock model
    applied. Without a match the export's clock is taken as the device's and gets the
    unit's fallback (flagged)."""
    info: dict[str, Any] = {"export_offset_s": None, "export_match": None, "matched_run": None}
    n = len(e.t)
    if model is None:
        info["clock_model"] = "none"
        return e.t, np.zeros(n, bool), info
    fin = np.isfinite(e.t)
    best = None
    if fin.any() and series:
        tb, xb = _resample(e.t, e.conductance_us, MATCH_HZ)
        for run, (ta, xa) in series.items():
            if ta[0] > tb[-1] + config.export_max_lag_s or ta[-1] < tb[0] - config.export_max_lag_s:
                continue
            lag, peak = match_lag(ta, xa, tb, xb, config.export_max_lag_s, MATCH_HZ)
            ok = np.isfinite(lag) and peak >= config.export_min_match
            if ok and (best is None or peak > best[2]):
                best = (run, lag, peak)
    if best is not None:
        run, lag, peak = best
        t, unc = model.correct(device, run, e.t - lag)
        rc = model.runs.get((device, run))
        info.update(
            export_offset_s=float(lag),
            export_match=float(peak),
            matched_run=run,
            clock_model=f"sd-{rc.kind if rc else 'rate'}",
        )
    else:
        t, unc = model.correct(device, path.name, e.t)
        unc = np.ones(n, bool)
        info["clock_model"] = "rate"
    if e.qa["clock"] == "recovered":
        unc = np.ones(n, bool)
    return t, unc, info


def _wear_uncertain(wear: pl.DataFrame, seconds: pl.DataFrame) -> pl.DataFrame:
    """``clock_uncertain`` on a bout: any of its worn seconds has an uncertain clock."""
    unc = seconds.filter(pl.col("ok") & pl.col("clock_uncertain"))
    by_device = {d: np.sort(g["t"].dt.epoch("s").to_numpy()) for (d,), g in unc.group_by("device")}
    flags = []
    for device, a, b in zip(
        wear["device"].to_list(),
        wear["start"].dt.epoch("s").to_numpy(),
        wear["end"].dt.epoch("s").to_numpy(),
        strict=True,
    ):
        x = by_device.get(device)
        flags.append(x is not None and np.searchsorted(x, b) > np.searchsorted(x, a))
    return wear.with_columns(pl.Series("clock_uncertain", flags, dtype=pl.Boolean))


def _comotion_table(grids: list[_ComotionGrid], config: EdaConfig) -> pl.DataFrame:
    tz = config.clock.timezone
    parts = []
    for g in grids:
        if len(g.signals) < 2:
            continue
        res = comotion(g.signals, g.lo, COMOTION_HZ, window_s=config.comotion_window_s)
        if res.height:
            parts.append(
                res.with_columns(
                    pl.lit(g.lo).alias("window_start_s"),
                    pl.lit(g.hi).alias("window_end_s"),
                )
            )
    if not parts:
        return pl.DataFrame(
            schema={
                "device": pl.String,
                "day": pl.Date,
                "residual_s": pl.Float64,
                "pairs": pl.Int64,
                "pairs_in_window": pl.Int32,
                "window_start": pl.Datetime("us", "UTC"),
                "window_end": pl.Datetime("us", "UTC"),
            }
        )
    out = pl.concat(parts, how="vertical_relaxed")
    as_dt = [
        (pl.col(f"window_{x}_s") * 1e6).cast(pl.Int64).cast(pl.Datetime("us", "UTC"))
        for x in ("start", "end")
    ]
    return out.with_columns(
        as_dt[0].alias("window_start"),
        as_dt[1].alias("window_end"),
        as_dt[0].dt.convert_time_zone(tz).dt.date().alias("day"),
    ).select(
        "device", "day", "residual_s", "pairs", "pairs_in_window", "window_start", "window_end"
    )


def comotion_summary(table: pl.DataFrame) -> dict[str, Any]:
    """Median and maximum absolute co-motion residual over device-days (one per device-day:
    the median over its windows)."""
    if not table.height:
        return {"device_days": 0}
    per = table.group_by("device", "day").agg(pl.col("residual_s").median())
    a = per["residual_s"].abs()
    return {
        "device_days": per.height,
        "median_abs_s": round(float(a.median()), 3),
        "max_abs_s": round(float(a.max()), 3),
        "within_1s": int((a <= 1.0).sum()),
    }
