"""SD cards and Shimmer Base exports → canonical per-second, SCR and wear tables.

Pure: raw files in, ``polars`` frames out (AGENTS.md invariant 3). Devices are processed one
at a time and runs one at a time, so a card of a week's recording never sits in memory whole.
Nothing is resolved to people here; that is the spine's job (``person_minutes``).

Two passes. The first places every SD run on its device's own clock and collects the sync
records and run spans; ``eda.clock`` builds the per-run clock model from them. The second
places the runs again, corrects their times through the model, and builds the tables.
Exports are matched row for row against the SD run of the same device (their repaired
clock is the device's plus a constant per clock segment) and corrected through that run's
model; an export with no SD
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
from .box import (
    BoxConfig,
    BoxStretch,
    find_stretches,
    leave_one_out,
    loo_summary,
    measure,
    nodes_summary,
)
from .box import jerk as motion_jerk
from .clock import (
    RECORDS_SCHEMA,
    RUNS_SCHEMA,
    SOURCE_DTYPE,
    SOURCES,
    ClockConfig,
    ClockModel,
    comotion,
)
from .export import SATURATED_US, export_device, export_span, read_export
from .features import (
    ScrConfig,
    WearConfig,
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
    "clock_source": SOURCE_DTYPE,
    "clock_correction_s": pl.Float32,
}
NO_MODEL = SOURCES.index("none")
SOURCE_PRIORITY = {"sd": 0, "export": 1}
#: Samples per key, and per confirmation, when matching an export's rows to its SD card.
MATCH_KEY = 4
MATCH_CONFIRM = 32
MATCH_EVERY = 128 * 300  # rows between probes (5 min)
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
    #: Box co-motion as a clock anchor (``eda.box``); ``enabled=False`` skips it.
    box: BoxConfig = field(default_factory=BoxConfig)
    #: Windows (UTC epoch seconds) in which devices lay together: the co-motion check.
    comotion_windows: tuple[tuple[float, float], ...] = ()
    comotion_window_s: float = 600.0  # sub-window length of the co-motion check
    #: Export file name -> UTC epoch seconds of its first row, for exports without a clock.
    export_starts: dict[str, float] = field(default_factory=dict)
    sample_rate_hz: float = 128.0

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
    box: pl.DataFrame = field(default_factory=pl.DataFrame)  # box anchors and checks
    box_pairs: pl.DataFrame = field(default_factory=pl.DataFrame)  # the pairs they rest on
    box_loo: pl.DataFrame = field(default_factory=pl.DataFrame)  # leave-one-out validation


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
    clock_source: np.ndarray | None = None,
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
    # The worst source among the second's samples.
    src = np.zeros(m, np.int8)
    if clock_source is None:
        src[:] = NO_MODEL
    else:
        np.maximum.at(src, inv, np.asarray(clock_source, np.int8)[placed])
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
                "clock_source": src,
                "clock_correction_s": corr,
            }
        )
        .with_columns(
            pl.col("t").cast(pl.Datetime("us", "UTC")),
            pl.col("clock_source").replace_strict(
                dict(enumerate(SOURCES)), return_dtype=SOURCE_DTYPE
            ),
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
    """Pass 1: the run's span on the device clock, its master flag, its sync records (only
    those in a block whose first record is good and placed), and its off-skin stretches for
    the box anchor."""
    chunks, _, tl = place_sd_run(run, keep, config)
    stretches: list[BoxStretch] = []
    if config.correct_clocks and config.box.enabled:
        us = calibration.gsr_microsiemens(
            np.concatenate([c.gsr_range for c in chunks]),
            np.concatenate([c.gsr_adc for c in chunks]),
        )
        acc = np.concatenate([c.acc for c in chunks])
        stretches = find_stretches(device, run.name, tl.t, us, acc, tl.bad, config.box)
        del us, acc
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
    return records, span, master, stretches


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
    plan: ClockPlan,
    grids: list[_ComotionGrid],
    keep_series: bool,
):
    chunks, infos, tl = place_sd_run(run, keep, config)
    t_dev = tl.t
    t, uncertain, kind, source = plan.sd_times(device, run.name, tl)
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
            clock_source=source,
        ),
        t,
        us,
        config.scr,
    )
    fin = np.isfinite(t)
    scr = _scr_frame(device, "sd", run.name, t[fin], us[fin], config.scr)
    if grids:
        good = fin & ~tl.bad
        j = np.full(len(t), np.nan)
        j[good] = motion_jerk(acc_raw[good])
        for g in grids:
            g.add(device, t, j)
    series = None
    if keep_series and fin.any():
        series = (t_dev, np.concatenate([c.ppg for c in chunks]).astype(np.int16))
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


@dataclass
class ClockBuild:
    model: ClockModel
    spans: dict[str, list[tuple[str, float, float]]]
    box: pl.DataFrame  # anchors and checks (eda.box.solve)
    box_pairs: pl.DataFrame
    box_loo: pl.DataFrame
    qa: dict[str, Any]


def build_clock_model(
    kept: dict[str, list[tuple[sd.SdRun, list[Path]]]], config: EdaConfig
) -> ClockBuild:
    """Pass 1 over every kept SD run: the clock model from the sync records, then box
    anchors measured against it and the model again with them; and each device's run spans."""
    records, runs, stretches = [], [], []
    spans: dict[str, list[tuple[str, float, float]]] = defaultdict(list)
    for device, items in kept.items():
        for run, keep in items:
            rec, span, master, st = scan_run(device, run, keep, config)
            records += rec
            stretches += st
            if span is not None:
                runs.append((device, run.name, span[0], span[1], master))
                spans[device].append((run.name, span[0], span[1]))
    rec_df = pl.DataFrame(records, schema=RECORDS_SCHEMA, orient="row")
    runs_df = pl.DataFrame(runs, schema=RUNS_SCHEMA, orient="row")
    model = ClockModel(rec_df, runs_df, config.clock)
    pairs, nodes = measure(model, stretches, config.box)
    del stretches
    qa: dict[str, Any] = {}
    loo = pl.DataFrame()
    if pairs.height:
        loo = leave_one_out(model.records, runs_df, pairs, config.clock, config.box)
        model = ClockModel(rec_df, runs_df, config.clock, anchors=nodes)
        qa = {
            "pairs": pairs.height,
            **nodes_summary(nodes),
            "leave_one_out": loo_summary(loo, config.clock.anchor_tolerance_s),
        }
    return ClockBuild(model, spans, nodes, pairs, loo, qa)


@dataclass
class ClockPlan:
    """What places every sample at its corrected time, shared by ``ingest_eda`` and
    ``eda.heart`` so both give a sample the same time: the per-run clock model, each SD run's
    span on its device's clock, every export's first and last timestamp, the order devices
    are processed in (devices with a clockless export last), and the corrected first times
    of the exports placed so far, per session (a clockless export starts at their median).
    """

    build: ClockBuild | None  # the clock model with its box anchors and their tables
    run_spans: dict[str, list[tuple[str, float, float]]]
    spans: dict[Path, tuple[float | None, float | None]]
    devices: list[str]
    raw_starts: dict[str, list[float]]
    starts: dict[str, list[float]] = field(default_factory=lambda: defaultdict(list))

    @property
    def model(self) -> ClockModel | None:
        return self.build.model if self.build is not None else None

    def sd_times(
        self, device: str, run: str, tl: RunTimeline
    ) -> tuple[np.ndarray, np.ndarray, str, np.ndarray]:
        """Corrected times of an SD run's records, ``clock_uncertain`` per record (the model's
        fallback, or placed by modification time), the run's clock model kind, and each
        record's clock source (an index into ``SOURCES``)."""
        if self.model is not None:
            t, uncertain, source = self.model.correct_full(device, run, tl.t)
            rc = self.model.runs.get((device, run))
            kind = rc.kind if rc is not None else "rate"
        else:
            t, uncertain, kind = tl.t, np.zeros(len(tl.t), bool), "none"
            source = np.full(len(tl.t), NO_MODEL, np.int8)
        return t, uncertain | tl.by_mtime, kind, source

    def near_export(self, device: str, run: str, exports: list[Path]) -> bool:
        """Whether an SD run overlaps one of ``exports`` (so its samples are kept for the
        row-for-row match)."""
        span = next((s for s in self.run_spans.get(device, []) if s[0] == run), None)
        if span is None:
            return False
        # Wide: an export's clock can be off by whole 512-s wraps.
        wide = [(a - 12 * 3600, b + 12 * 3600) for p in exports for a, b in [self.spans[p]] if a]
        return any(a < span[2] and b > span[1] for a, b in wide)

    def export_start(self, path: Path, config: EdaConfig) -> float | None:
        """The start to place a clockless export from (configured, else its session's)."""
        start = config.export_starts.get(path.name)
        if start is None and self.spans[path][0] is None:
            peers = self.starts.get(_session(path)) or self.raw_starts.get(_session(path))
            if peers:
                start = float(np.median(peers))
        return start

    def correct_export(
        self,
        device: str,
        path: Path,
        e,
        series: dict[str, tuple[np.ndarray, np.ndarray]],
        config: EdaConfig,
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray, dict[str, Any]]:
        """``_correct_export``, then the export's corrected start is recorded for its session."""
        t, unc, src, info = _correct_export(device, path, e, series, self.model, config)
        placed = t[np.isfinite(t)]
        if len(placed) and e.qa["clock"] != "recovered":
            self.starts[_session(path)].append(float(placed[0]))
        return t, unc, src, info


def plan_clocks(
    kept: dict[str, list[tuple[sd.SdRun, list[Path]]]],
    exports_by_device: dict[str, list[Path]],
    config: EdaConfig,
) -> ClockPlan:
    """Pass 1 (the clock model with its box anchors, if ``config.correct_clocks``) and the
    exports' spans."""
    build = build_clock_model(kept, config) if config.correct_clocks else None
    run_spans = build.spans if build is not None else {}
    devices = sorted(set(kept) | set(exports_by_device))
    spans = {p: export_span(p) for d in devices for p in exports_by_device.get(d, [])}
    raw_starts: dict[str, list[float]] = defaultdict(list)
    for p, (first, _) in spans.items():
        if first is not None:
            raw_starts[_session(p)].append(first)
    # Exports without a clock are placed from the corrected start of the other exports of
    # their session (the units were started together), so their devices come last.
    clockless = {d for d in devices for p in exports_by_device.get(d, []) if spans[p][0] is None}
    order = [d for d in devices if d not in clockless] + sorted(clockless)
    return ClockPlan(build, run_spans, spans, order, raw_starts)


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

    plan = plan_clocks(kept, exports_by_device, config)
    model, build = plan.model, plan.build
    grids = [_ComotionGrid(lo, hi) for lo, hi in config.comotion_windows]

    seconds_parts, scr_parts = [], []
    lo, hi = config.window_s
    for device in plan.devices:
        dev_seconds, dev_scr = [], []
        series: dict[str, tuple[np.ndarray, np.ndarray]] = {}
        for run, keep in kept[device]:
            near = plan.near_export(device, run.name, exports_by_device[device])
            seconds, scr, files, tqa, ser = _process_run(
                device, run, keep, config, plan, grids, near
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
            start = plan.export_start(path, config)
            e = read_export(path, config.timeline(), start, config.sample_rate_hz)
            t, unc, src, info = plan.correct_export(device, path, e, series, config)
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
                src,
            )
            dev_seconds.append(_with_artifacts(export_seconds, t, e.conductance_us, config.scr))
            fin = np.isfinite(t)
            dev_scr.append(
                _scr_frame(device, "export", path.name, t[fin], e.conductance_us[fin], config.scr)
            )
            placed = t[fin]
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
                "clock_source",
            ),
            on=["device", "source", "run", "_sec"],
            how="left",
        )
        .with_columns(
            pl.col("ok", "worn", "clock_uncertain").fill_null(False),
            pl.col("clock_source").fill_null("none"),
        )
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
            "clock_source",
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
    qa["seconds_worn_by_clock_source"] = {
        str(k): int(v)
        for k, v in seconds.filter(worn_ok)
        .group_by("clock_source")
        .len()
        .sort("clock_source")
        .iter_rows()
    }
    qa["scr"] = scr.height
    qa["scr_ok_worn_clean"] = int((scr["ok"] & scr["worn"] & ~scr["artifact"]).sum())
    qa["scr_ok_worn"] = int((scr["ok"] & scr["worn"]).sum())
    qa["wear_bouts"] = wear.height
    clock = model.summary() if model is not None else pl.DataFrame()
    if model is not None:
        qa["clock"] = model.qa
    if build is not None and build.qa:
        qa["box"] = build.qa
    comotion_table = _comotion_uncertain(_comotion_table(grids, config), seconds)
    qa["comotion"] = comotion_summary(comotion_table)
    return EdaTables(
        files=files,
        seconds=seconds,
        scr=scr,
        wear=wear,
        qa=qa,
        clock=clock,
        comotion=comotion_table,
        box=build.box if build is not None else pl.DataFrame(),
        box_pairs=build.box_pairs if build is not None else pl.DataFrame(),
        box_loo=build.box_loo if build is not None else pl.DataFrame(),
    )


def _keys(v: np.ndarray) -> np.ndarray:
    """``MATCH_KEY`` consecutive 12-bit values packed into one integer, per position."""
    v = np.asarray(v, np.int64) & 0xFFF
    n = max(len(v) - MATCH_KEY + 1, 0)
    k = np.zeros(n, np.int64)
    for j in range(MATCH_KEY):
        k = (k << 12) | v[j : j + n]
    return k


class _SdIndex:
    """One SD run's PPG sequence, indexed for exact lookups of an export's rows."""

    def __init__(self, t: np.ndarray, ppg: np.ndarray):
        self.t, self.ppg = t, ppg
        keys = _keys(ppg)
        self.order = np.argsort(keys, kind="stable")
        self.keys = keys[self.order]

    def find(self, pat: np.ndarray) -> int | None:
        """The one placed record where ``pat`` starts, or None if none or several."""
        key = _keys(pat[:MATCH_KEY])[0]
        lo, hi = np.searchsorted(self.keys, [key, key + 1])
        hits = [
            int(i)
            for i in self.order[lo : min(hi, lo + 50)]
            if i + len(pat) <= len(self.ppg)
            and np.array_equal(self.ppg[i : i + len(pat)], pat)
            and np.isfinite(self.t[i])
        ]
        return hits[0] if len(hits) == 1 else None


def _row_lags(
    e, adc: np.ndarray, sd: dict[str, _SdIndex]
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Per export row: the lag (export time - device time) of the nearest probe of its own
    clock segment, within ``2 * MATCH_EVERY`` rows, that found its samples on an SD run (NaN
    where none did; a segment with no probe in reach borrows a neighbouring one's); that
    probe's run (None where none); and whether the row is flagged (its segment's probes on
    either side disagree, or its lag is borrowed)."""
    n = len(adc)
    seg = e.segment if e.segment is not None else np.where(np.isfinite(e.t), 0, -1)
    probes = np.arange(0, max(n - MATCH_CONFIRM, 0), MATCH_EVERY)
    p_lag = np.full(len(probes), np.nan)
    p_run = np.full(len(probes), None, dtype=object)
    for j, r in enumerate(probes):
        pat = adc[r : r + MATCH_CONFIRM]
        if seg[r] < 0 or np.ptp(pat) < 3:  # a bad row, or flat (off the finger): not unique
            continue
        for run, idx in sd.items():
            i = idx.find(pat)
            if i is not None:
                p_lag[j], p_run[j] = e.t[r] - idx.t[i], run
                break
    lag = np.full(n, np.nan)
    row_run = np.full(n, None, dtype=object)
    disagree = np.zeros(n, bool)
    ok = np.flatnonzero(np.isfinite(p_lag))
    if not len(ok):
        return lag, row_run, disagree
    pos, pl_, pr = probes[ok], p_lag[ok], p_run[ok]
    rows = np.arange(n)
    reach = 2 * MATCH_EVERY

    def nearest(cands: np.ndarray, rws: np.ndarray, sgs: np.ndarray | None) -> np.ndarray:
        """Index into ``cands`` of the nearest probe (in segment ``sgs`` if given), -1 if none
        within ``reach``."""
        out = np.full(len(rws), -1, np.int64)
        if sgs is None:
            groups = [(np.arange(len(rws)), np.arange(len(cands)))]
        else:
            groups = [
                (np.flatnonzero(sgs == g), np.flatnonzero(seg[pos[cands]] == g))
                for g in np.unique(sgs)
            ]
        for ri, ci in groups:
            if not len(ri) or not len(ci):
                continue
            cp = pos[cands[ci]]
            k = np.searchsorted(cp, rws[ri])
            lo, hi = np.clip(k - 1, 0, len(cp) - 1), np.clip(k, 0, len(cp) - 1)
            pick = np.where(np.abs(rws[ri] - cp[lo]) <= np.abs(cp[hi] - rws[ri]), lo, hi)
            fine = np.abs(rws[ri] - cp[pick]) <= reach
            out[ri[fine]] = ci[pick[fine]]
        return out

    good = seg >= 0
    all_p = np.arange(len(pos))
    own = np.full(n, -1, np.int64)
    own[good] = nearest(all_p, rows[good], seg[good])
    # A row whose own clock segment has no probe in reach borrows a neighbour's lag: flagged.
    other = np.full(n, -1, np.int64)
    need = good & (own < 0)
    other[need] = nearest(all_p, rows[need], None)
    pick = np.where(own >= 0, own, other)
    usable = pick >= 0
    lag[usable] = pl_[pick[usable]]
    row_run[usable] = pr[pick[usable]]
    # Flag rows between two probes of their segment that disagree, and borrowed rows.
    k = np.searchsorted(pos, rows)
    left, right = np.clip(k - 1, 0, len(pos) - 1), np.clip(k, 0, len(pos) - 1)
    same = (seg[pos[left]] == seg) & (seg[pos[right]] == seg) & (left != right)
    disagree = ((same & (np.abs(pl_[left] - pl_[right]) > 0.05)) | (own < 0)) & usable
    return lag, row_run, disagree


def _correct_export(
    device: str,
    path: Path,
    e,
    series: dict[str, tuple[np.ndarray, np.ndarray]],
    model: ClockModel | None,
    config: EdaConfig,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, dict[str, Any]]:
    """Corrected times, ``clock_uncertain``, clock source and file info for one export.

    An export's rows are its SD card's records where both exist, and its repaired clock is
    the device's plus a constant that can change by whole 512-s wraps (after a long gap, or
    where the card has a gap the export has not). So every ``MATCH_EVERY`` rows a probe of
    ``MATCH_CONFIRM`` PPG samples is looked up exactly on the device's SD runs; each row takes
    the lag of its nearest successful probe in the same clock segment (within twice the probe
    spacing), and that run's clock model. Rows between disagreeing probes are flagged. Rows no
    probe reaches keep the export's own clock with the unit's fallback (flagged)."""
    info: dict[str, Any] = {
        "export_offset_s": None,
        "export_rows_matched": 0,
        "export_lag_changes": 0,
        "matched_run": None,
    }
    n = len(e.t)
    if model is None:
        info["clock_model"] = "none"
        return e.t, np.zeros(n, bool), np.full(n, NO_MODEL, np.int8), info
    rate = SOURCES.index("rate")
    t = np.full(n, np.nan)
    unc = np.ones(n, bool)
    src = np.full(n, rate, np.int8)
    lag = np.full(n, np.nan)
    row_run = np.full(n, None, dtype=object)
    disagree = np.zeros(n, bool)
    if np.isfinite(e.t).any() and series and e.qa["clock"] != "recovered":
        adc = np.rint(np.nan_to_num(e.ppg_mv) * 4095 / 3000).astype(np.int64)
        sd = {run: _SdIndex(st, sp) for run, (st, sp) in series.items()}
        lag, row_run, disagree = _row_lags(e, adc, sd)
        del sd
    matched = np.isfinite(lag)
    if matched.any():
        runs = [r for r in row_run[matched]]
        for run in sorted(set(runs)):
            rows = matched & (row_run == run)
            t[rows], u, src[rows] = model.correct_full(device, run, e.t[rows] - lag[rows])
            unc[rows] = u | disagree[rows]
        main = max(set(runs), key=runs.count)
        rc = model.runs.get((device, main))
        info.update(
            export_offset_s=float(lag[matched][0]),
            export_rows_matched=int(matched.sum()),
            export_lag_changes=int((np.abs(np.diff(lag[matched])) > 256).sum()),
            matched_run=main,
            clock_model=f"sd-{rc.kind if rc else 'rate'}",
        )
    else:
        info["clock_model"] = "rate"
    rest = ~matched & np.isfinite(e.t)
    if rest.any():
        t[rest], _ = model.correct(device, path.name, e.t[rest])
        unc[rest] = True
        src[rest] = rate
    if e.qa["clock"] == "recovered":
        unc = np.ones(n, bool)
        src[:] = rate
    return t, unc, src, info


def _wear_uncertain(wear: pl.DataFrame, seconds: pl.DataFrame) -> pl.DataFrame:
    """``clock_uncertain`` on a bout: any of its worn seconds has an uncertain clock; and
    ``clock_source``: the worst source among them."""
    ok = seconds.filter("ok")

    def times(rows: pl.DataFrame) -> dict[str, np.ndarray]:
        return {d: np.sort(g["t"].dt.epoch("s").to_numpy()) for (d,), g in rows.group_by("device")}

    def any_in(by_device: dict[str, np.ndarray]) -> list[bool]:
        out = []
        for device, a, b in zip(
            wear["device"].to_list(),
            wear["start"].dt.epoch("s").to_numpy(),
            wear["end"].dt.epoch("s").to_numpy(),
            strict=True,
        ):
            x = by_device.get(device)
            out.append(x is not None and np.searchsorted(x, b) > np.searchsorted(x, a))
        return out

    flags = any_in(times(ok.filter("clock_uncertain")))
    worst = np.zeros(wear.height, np.int8)
    code = pl.col("clock_source").to_physical()
    for level in range(1, len(SOURCES)):
        worst[np.array(any_in(times(ok.filter(code >= level))), bool)] = level
    return wear.with_columns(
        pl.Series("clock_uncertain", flags, dtype=pl.Boolean),
        pl.Series("clock_source", [SOURCES[k] for k in worst], dtype=SOURCE_DTYPE),
    )


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


def _comotion_uncertain(table: pl.DataFrame, seconds: pl.DataFrame) -> pl.DataFrame:
    """``clock_uncertain`` per co-motion row: any of the device's seconds in the window is;
    ``clock_source``: the worst source among them."""
    flags, worst = [], []
    for d, a, b in zip(
        table["device"].to_list(),
        table["window_start"].to_list(),
        table["window_end"].to_list(),
        strict=True,
    ):
        part = seconds.filter(
            (pl.col("device") == d) & (pl.col("t") >= a) & (pl.col("t") < b) & ~pl.col("duplicate")
        )
        flags.append(bool(part["clock_uncertain"].any()))
        worst.append(part["clock_source"].max() if part.height else "none")
    return table.with_columns(
        pl.Series("clock_uncertain", flags, dtype=pl.Boolean),
        pl.Series("clock_source", worst, dtype=SOURCE_DTYPE),
    )


def comotion_summary(table: pl.DataFrame, min_pairs: int = 2) -> dict[str, Any]:
    """Absolute co-motion residuals per device-day (the median over its windows), for
    device-days resting on at least ``min_pairs`` pairs (one pair cannot say which device is
    off): overall, for clocks the sync records measured, for clocks the box anchored (the box
    measured them, so this is not an independent check: see ``eda.box.leave_one_out``), and for
    fallback (uncertain) clocks."""
    if not table.height:
        return {"device_days": 0}
    per = (
        table.filter(pl.col("pairs") >= min_pairs)
        .group_by("device", "day")
        .agg(
            pl.col("residual_s").median(),
            pl.col("clock_uncertain").any(),
            pl.col("clock_source").max(),
        )
    )
    certain = ~pl.col("clock_uncertain")

    def stats(x: pl.DataFrame) -> dict[str, Any]:
        if not x.height:
            return {"device_days": 0}
        a = x["residual_s"].abs()
        return {
            "device_days": x.height,
            "median_abs_s": round(float(a.median()), 3),
            "max_abs_s": round(float(a.max()), 3),
            "within_1s": int((a <= 1.0).sum()),
        }

    return {
        **stats(per),
        "measured": stats(per.filter(certain & (pl.col("clock_source") == "sync"))),
        "box": stats(per.filter(certain & (pl.col("clock_source") == "box"))),
        "fallback": stats(per.filter("clock_uncertain")),
        "device_days_one_pair": table.filter(pl.col("pairs") < min_pairs)
        .select("device", "day")
        .unique()
        .height,
    }
