"""Heart rate from the raw PPG of SD cards and exports, per device, window and minute.

``eda.ppg`` does the signal processing; this module reads the samples one device and one
run at a time (an export for its clock, PPG and Shimmer's own heart rate only), so memory
stays at one run's worth plus the PPG of the SD runs an export is matched against. Every
sample gets the time ``eda.ingest`` gives it: the same first pass builds the same per-run
clock model (``ClockPlan``), SD runs are corrected through it, and exports are matched row
for row to their card and corrected through that run's model. Windows are flagged, never
dropped (AGENTS.md invariant 3): one source per device-window (SD first, as in ``seconds``),
``implausible_time`` outside the study window, ``worn`` from the wear bouts,
``clock_uncertain`` where any sample's clock fell back (``eda.clock``), with the run's
``clock_model``. Nothing is resolved to people here; ``with_heart_rate`` joins the
device-minutes onto the spine-resolved person-minutes.

Two checks of the method on the data itself:

- ``agreement``: where an export carries Shimmer's heart rate, our heart rate against it per
  device-day (bias, Bland-Altman limits, mean absolute error), on the export's own samples
  (the algorithms compared) and on the SD card's samples of the same windows (what analyses
  get).
- ``usability``: per device-day, the share of worn windows with good-quality heart rate, so a
  dead or badly placed sensor shows in the data.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl

from . import calibration, sd
from .export import export_device, read_export_pulse
from .ingest import (
    SOURCE_PRIORITY,
    EdaConfig,
    _sha256,
    place_sd_run,
    plan_clocks,
    unique_sd_runs,
)
from .ppg import WINDOW_SCHEMA, PpgConfig, analyse


@dataclass(frozen=True)
class HeartTables:
    beats: (
        pl.DataFrame
    )  # one per beat: device, source, run, t, ibi_ms, plausible, ok, clock_uncertain
    windows: pl.DataFrame  # one row per device, source, run and window
    minutes: pl.DataFrame  # one row per device-minute (ok windows only)
    qa: dict[str, Any]


BEAT_SCHEMA = {
    "device": pl.String,
    "source": pl.String,
    "run": pl.String,
    "t": pl.Datetime("us", "UTC"),
    "ibi_ms": pl.Float32,
    "plausible": pl.Boolean,
}


def _beats(beats: pl.DataFrame, device: str, source: str, run: str) -> pl.DataFrame:
    return _tag(beats, device, source, run).select(
        "device",
        "source",
        "run",
        (pl.col("t") * 1_000_000).cast(pl.Int64).cast(pl.Datetime("us", "UTC")).alias("t"),
        (pl.col("ibi_s") * 1000).cast(pl.Float32).alias("ibi_ms"),
        "plausible",
    )


def _export_hr(t: np.ndarray, hr: np.ndarray, window_s: int) -> pl.DataFrame:
    """Shimmer's heart rate per window: mean of the samples that carry one."""
    fin = np.isfinite(t)
    return (
        pl.DataFrame({"w": np.floor(t[fin] / window_s).astype(np.int64), "hr": hr[fin]})
        .with_columns(pl.col("hr").fill_nan(None))
        .group_by("w")
        .agg(
            pl.col("hr").mean().cast(pl.Float32).alias("hr_export_bpm"),
            pl.col("hr").count().cast(pl.Int32).alias("hr_export_samples"),
        )
    )


def _flagged(t: np.ndarray, flag: np.ndarray, window_s: int, name: str) -> pl.DataFrame:
    """The windows with any placed sample flagged, as ``w`` (window index) and ``name``."""
    fin = np.isfinite(t) & flag
    w = np.unique(np.floor(t[fin] / window_s).astype(np.int64))
    return pl.DataFrame({"w": w, name: np.ones(len(w), bool)})


def _with_flags(
    win: pl.DataFrame, t: np.ndarray, flags: dict[str, np.ndarray], window_s: int
) -> pl.DataFrame:
    win = win.with_columns((pl.col("t").dt.epoch("s") // window_s).alias("w"))
    for name, flag in flags.items():
        win = win.join(_flagged(t, flag, window_s, name), on="w", how="left").with_columns(
            pl.col(name).fill_null(False)
        )
    return win.drop("w")


def _tag(frame: pl.DataFrame, device: str, source: str, run: str) -> pl.DataFrame:
    return frame.with_columns(
        pl.lit(device).alias("device"), pl.lit(source).alias("source"), pl.lit(run).alias("run")
    )


def _flag_worn(windows: pl.DataFrame, wear: pl.DataFrame, window_s: int) -> pl.DataFrame:
    """``worn``: the window's midpoint lies inside one of its device's wear bouts."""
    mid = windows.with_row_index("_i").with_columns(
        (pl.col("t") + pl.duration(milliseconds=window_s * 500)).alias("_mid")
    )
    bouts = wear.select("device", pl.col("start").alias("_mid"), pl.col("end").alias("_end"))
    hit = (
        mid.select("_i", "device", "_mid")
        .sort("_mid")
        .join_asof(
            bouts.sort("_mid"), on="_mid", by="device", strategy="backward", check_sortedness=False
        )
        .select("_i", (pl.col("_mid") < pl.col("_end")).fill_null(False).alias("worn"))
    )
    return mid.join(hit, on="_i", how="left").drop("_i", "_mid")


def heart_rate(
    cards: list[Path],
    exports: list[Path],
    config: EdaConfig,
    ppg: PpgConfig | None = None,
    wear: pl.DataFrame | None = None,
    log: Callable[[str], None] | None = None,
) -> HeartTables:
    """Windows and device-minutes of heart rate from every card and export. ``wear`` (the
    ingest's wear bouts) sets ``worn``; without it ``worn`` is null. ``log`` receives a line
    per device as it is done."""
    ppg = ppg or PpgConfig()
    w = ppg.window_s
    runs_by_device: dict[str, list[sd.SdRun]] = defaultdict(list)
    for card in cards:
        for run in sd.find_runs(Path(card)):
            runs_by_device[run.device].append(run)
    exports_by_device: dict[str, list[Path]] = defaultdict(list)
    for path in exports:
        exports_by_device[export_device(Path(path))].append(Path(path))

    devices = sorted(set(runs_by_device) | set(exports_by_device))

    qa: dict[str, Any] = defaultdict(int)
    seen: dict[str, set[str]] = {d: set() for d in devices}
    kept = {}
    for device in devices:
        kept[device], copies = unique_sd_runs(runs_by_device[device], seen[device])
        qa["chunks_duplicate"] += len(copies)
    # The ingest's pass 1: the same clock model, so the same corrected times.
    plan = plan_clocks(kept, exports_by_device, config)
    parts: list[pl.DataFrame] = []
    beat_parts: list[pl.DataFrame] = []
    for device in plan.devices:
        series: dict[str, tuple[np.ndarray, np.ndarray]] = {}
        for run, keep in kept[device]:
            chunks, _, tl = place_sd_run(run, keep, config)
            raw = np.concatenate([c.ppg for c in chunks])
            del chunks
            t, uncertain, kind = plan.sd_times(device, run.name, tl)
            near = plan.near_export(device, run.name, exports_by_device[device])
            if near and np.isfinite(t).any():  # kept for the exports' row-for-row match
                series[run.name] = (tl.t, raw.astype(np.int16))
            beats, win = analyse(t, calibration.ppg_mv(raw), ppg)
            del raw
            qa["sd_runs"] += 1
            qa["sd_samples_placed"] += int(np.isfinite(t).sum())
            qa["sd_beats"] += beats.height
            beat_parts.append(_beats(beats, device, "sd", run.name))
            parts.append(
                _tag(
                    _with_flags(win, t, {"clock_uncertain": uncertain}, w), device, "sd", run.name
                ).with_columns(
                    pl.lit(None, pl.Float32).alias("hr_export_bpm"),
                    pl.lit(None, pl.Int32).alias("hr_export_samples"),
                    pl.lit(False).alias("gap_ambiguous"),
                    pl.lit(kind).alias("clock_model"),
                )
            )
        for path in sorted(exports_by_device[device]):
            digest = _sha256(path)
            if digest in seen[device]:
                qa["export_files_duplicate"] += 1
                continue
            seen[device].add(digest)
            start = plan.export_start(path, config)
            e = read_export_pulse(path, config.timeline(), start, config.sample_rate_hz)
            t, uncertain, info = plan.correct_export(device, path, e, series, config)
            beats, win = analyse(t, e.ppg_mv, ppg)
            qa["export_files"] += 1
            qa["export_samples_placed"] += int(np.isfinite(t).sum())
            qa["export_beats"] += beats.height
            qa[f"export_files_clock_{e.qa['clock']}"] += 1
            beat_parts.append(_beats(beats, device, "export", path.name))
            flags = {"gap_ambiguous": e.gap_ambiguous, "clock_uncertain": uncertain}
            win = (
                _with_flags(win, t, flags, w)
                .with_columns((pl.col("t").dt.epoch("s") // w).alias("w"))
                .join(_export_hr(t, e.hr_bpm, w), on="w", how="left")
                .drop("w")
                .with_columns(pl.lit(info["clock_model"]).alias("clock_model"))
            )
            parts.append(_tag(win, device, "export", path.name))
            del e
        del series
        if log:
            log(f"{device}: {qa['sd_beats'] + qa['export_beats']} beats so far")

    schema = {
        "device": pl.String,
        "source": pl.String,
        "run": pl.String,
        **WINDOW_SCHEMA,
        "hr_export_bpm": pl.Float32,
        "hr_export_samples": pl.Int32,
        "gap_ambiguous": pl.Boolean,
        "clock_uncertain": pl.Boolean,
        "clock_model": pl.String,
    }
    windows = (
        pl.concat([p.select(list(schema)).cast(schema) for p in parts])
        if parts
        else pl.DataFrame(schema=schema)
    )
    lo, hi = config.window_s
    t_s = pl.col("t").dt.epoch("s")
    windows = (
        windows.with_columns(pl.col("source").replace_strict(SOURCE_PRIORITY).alias("_p"))
        .sort("device", "t", "_p", "run")
        .with_columns(
            pl.struct("device", "t").is_first_distinct().not_().alias("duplicate"),
            ((t_s < lo) | (t_s >= hi)).alias("implausible_time"),
        )
        .drop("_p")
        .with_columns((~pl.col("duplicate") & ~pl.col("implausible_time")).alias("ok"))
    )
    if wear is not None:
        windows = _flag_worn(windows, wear, w)
    else:
        windows = windows.with_columns(pl.lit(None, pl.Boolean).alias("worn"))
    windows = windows.select(*list(schema), "duplicate", "implausible_time", "ok", "worn")
    minutes = device_minutes(windows, ppg)

    qa = dict(qa)
    qa["windows"] = windows.height
    qa["windows_duplicate"] = int(windows["duplicate"].sum())
    qa["windows_implausible"] = int(windows["implausible_time"].sum())
    qa["windows_ok"] = int(windows["ok"].sum())
    qa["windows_ok_quality"] = int((windows["ok"] & windows["quality_ok"]).sum())
    qa["windows_ok_clock_uncertain"] = int((windows["ok"] & windows["clock_uncertain"]).sum())
    if wear is not None:
        worn = windows["ok"] & windows["worn"]
        qa["windows_ok_worn"] = int(worn.sum())
        qa["windows_ok_worn_quality"] = int((worn & windows["quality_ok"]).sum())
    qa["device_minutes"] = minutes.height
    beats = pl.concat(beat_parts) if beat_parts else pl.DataFrame(schema=BEAT_SCHEMA)
    # A beat is ok where its window is (one source per device-window, plausible time).
    beats = (
        beats.with_columns(pl.col("t").dt.truncate(f"{w}s").alias("_w"))
        .join(
            windows.select(
                "device", "source", "run", pl.col("t").alias("_w"), "ok", "clock_uncertain"
            ),
            on=["device", "source", "run", "_w"],
            how="left",
        )
        .drop("_w")
        .with_columns(pl.col("ok", "clock_uncertain").fill_null(False))
    )
    qa["beats"] = beats.height
    qa["beats_ok"] = int(beats["ok"].sum())
    qa["beats_ok_plausible"] = int((beats["ok"] & beats["plausible"]).sum())
    return HeartTables(beats=beats, windows=windows, minutes=minutes, qa=qa)


def device_minutes(windows: pl.DataFrame, ppg: PpgConfig | None = None) -> pl.DataFrame:
    """Per device-minute over ``ok`` windows: ``hr_bpm`` is the median heart rate of the
    good-quality windows (null if none), ``hr_quality`` the share of the minute they cover,
    ``clock_uncertain`` whether any of its windows' clocks fell back."""
    ppg = ppg or PpgConfig()
    per_minute = 60 // ppg.window_s
    good = pl.col("quality_ok")
    return (
        windows.filter("ok")
        .group_by("device", pl.col("t").dt.truncate("1m").alias("minute"))
        .agg(
            pl.col("source").first(),
            pl.len().cast(pl.Int16).alias("hr_windows"),
            good.sum().cast(pl.Int16).alias("hr_windows_good"),
            pl.col("hr_bpm").filter(good).median().cast(pl.Float32).alias("hr_bpm"),
            pl.col("worn").any().alias("worn"),
            pl.col("clock_uncertain").any().alias("clock_uncertain"),
        )
        .with_columns((pl.col("hr_windows_good") / per_minute).cast(pl.Float32).alias("hr_quality"))
        .sort("device", "minute")
    )


def with_heart_rate(person_minutes: pl.DataFrame, minutes: pl.DataFrame) -> pl.DataFrame:
    """The person-minute table with ``hr_ppg_bpm``, ``hr_quality`` and ``hr_clock_uncertain``
    joined on device and minute. Its own columns, ``hr_bpm`` (the export's) and
    ``clock_uncertain`` included, are left as they are."""
    return person_minutes.join(
        minutes.select(
            "device",
            "minute",
            pl.col("hr_bpm").alias("hr_ppg_bpm"),
            "hr_quality",
            pl.col("clock_uncertain").alias("hr_clock_uncertain"),
        ),
        on=["device", "minute"],
        how="left",
    )


def _day(timezone: str) -> pl.Expr:
    return pl.col("t").dt.convert_time_zone(timezone).dt.date().alias("day")


def _stats(diff: pl.Expr) -> list[pl.Expr]:
    return [
        diff.len().alias("n"),
        diff.mean().alias("bias_bpm"),
        diff.std().alias("sd_bpm"),
        diff.abs().mean().alias("mae_bpm"),
        (diff.abs() <= 5).mean().alias("within_5_bpm"),
    ]


def _with_limits(frame: pl.DataFrame) -> pl.DataFrame:
    return frame.with_columns(
        (pl.col("bias_bpm") - 1.96 * pl.col("sd_bpm")).alias("loa_low_bpm"),
        (pl.col("bias_bpm") + 1.96 * pl.col("sd_bpm")).alias("loa_high_bpm"),
    )


def agreement(windows: pl.DataFrame, timezone: str = "UTC") -> pl.DataFrame:
    """Our heart rate against Shimmer's, per device and local day, in plausible-time windows
    where ours is good quality and the export has one. ``samples`` is ``export`` (our method
    on the export's own samples) or ``sd`` (on the SD card's samples of the same windows),
    plus an ``all`` row per comparison over every device-day."""
    base = windows.filter(~pl.col("implausible_time"))
    ex = base.filter(source="export").filter(pl.col("hr_export_bpm").is_not_null())
    ref = ex.group_by("device", "t").agg(pl.col("hr_export_bpm").mean())
    same = ex.filter("quality_ok").select("device", "t", "hr_bpm", "hr_export_bpm")
    sd_ = (
        base.filter(pl.col("source") == "sd", pl.col("quality_ok"))
        .unique(["device", "t"], keep="first")
        .select("device", "t", "hr_bpm")
        .join(ref, on=["device", "t"])
    )
    out = []
    for name, frame in (("export", same), ("sd", sd_)):
        f = frame.with_columns(
            _day(timezone), (pl.col("hr_bpm") - pl.col("hr_export_bpm")).alias("d")
        )
        per = f.group_by("device", "day").agg(_stats(pl.col("d")))
        overall = f.select(_stats(pl.col("d"))).with_columns(
            pl.lit("all").alias("device"), pl.lit(None, pl.Date).alias("day")
        )
        out.append(
            pl.concat([per, overall.select(per.columns)]).with_columns(
                pl.lit(name).alias("samples")
            )
        )
    return _with_limits(pl.concat(out)).sort("samples", "device", "day", nulls_last=True)


def usability(windows: pl.DataFrame, timezone: str = "UTC") -> pl.DataFrame:
    """Per device and local day, over ``ok`` and worn windows: how many, the share with
    good-quality heart rate, the share with a pulse above the noise floor, and medians of
    the template correlation, pulse amplitude and good heart rate."""
    worn = windows.filter(pl.col("ok") & pl.col("worn").fill_null(False))
    return (
        worn.with_columns(_day(timezone))
        .group_by("device", "day")
        .agg(
            pl.len().alias("worn_windows"),
            pl.col("quality_ok").mean().alias("good_share"),
            pl.col("amplitude_ok").mean().alias("pulse_share"),
            pl.col("template_corr").median().alias("template_corr_median"),
            pl.col("ppg_sd_mv").median().alias("ppg_sd_mv_median"),
            pl.col("hr_bpm").filter("quality_ok").median().alias("hr_median_bpm"),
        )
        .sort("device", "day")
    )
