"""Place one SD run's records in time: clean the tick counter, segment it, anchor it.

The device's 24-bit tick counter (32768 Hz) is reliable between records; the absolute clock
is each chunk file's modification time, written when the file was closed. So:

1. Drop all-zero records, then records whose tick is out of sequence with both neighbours (or
   whose removal makes the sequence consistent again). Flagged ``bad``, never placed.
2. Split where consecutive good records are further apart than ``max_step_s`` (or go
   backwards): the counter cannot tell how many 512-s wraps such a gap holds. A segment of
   fewer than ``min_segment_records`` records is garbage (corrupt stretches hold random ticks,
   some of which chain up by chance) and becomes bad.
3. Elapsed time inside a segment is the sum of tick steps, so pauses and dropped samples keep
   their real length.
4. Each chunk offers up to two anchors. *End*: its last good record sits at its modification
   time, unless the chunk is truncated (it lost its tail). *Start*: a chunk closed by the
   device's file rotation (its successor exists) began ``rotation_s`` before its modification
   time, truncated or not. Times outside the anchor window are not eligible. Per segment, the
   anchors within ``anchor_tolerance_s`` of the median are used; with enough of them spread
   over ``drift_min_span_s``, a clock rate is fitted too. A segment without anchors is
   ``unanchored`` and gets no time.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import polars as pl

from .sd import TICK_HZ, TICK_WRAP


@dataclass(frozen=True)
class TimelineConfig:
    #: Added to a stored modification time (epoch seconds) to give UTC.
    mtime_to_utc_s: float = 0.0
    #: Anchors (in UTC epoch seconds) outside this window are not eligible.
    anchor_from_s: float | None = None
    anchor_to_s: float | None = None
    max_step_s: float = 60.0
    anchor_tolerance_s: float = 5.0
    min_segment_records: int = 128
    #: Wall-clock length of a chunk the device closed to start the next one (None: unknown).
    rotation_s: float | None = None
    drift_min_span_s: float = 7200.0
    drift_min_anchors: int = 3


@dataclass(frozen=True)
class ChunkInfo:
    mtime_s: float  # stored modification time, epoch seconds
    truncated: bool = False  # lost its tail: the last record is not at the modification time
    rotated: bool = False  # the device closed it to open the next chunk number


@dataclass(frozen=True)
class RunTimeline:
    t: np.ndarray  # UTC epoch seconds per record; NaN if bad or unanchored
    bad: np.ndarray  # bool: all-zero or out-of-sequence record
    segment: np.ndarray  # int: segment index, -1 for bad records
    unanchored: np.ndarray  # bool: good record in a segment with no usable anchor
    anchors: pl.DataFrame  # one row per chunk
    qa: dict[str, Any]


def tick_steps(v: np.ndarray) -> np.ndarray:
    return (v[1:] - v[:-1]) % TICK_WRAP


def clean_ticks(ticks: np.ndarray, good: np.ndarray, config: TimelineConfig) -> np.ndarray:
    max_step = int(config.max_step_s * TICK_HZ)
    good = good.copy()
    while True:
        idx = np.flatnonzero(good)
        if len(idx) == 0:
            return good
        v = ticks[idx]
        ok = tick_steps(v) <= max_step
        in_ok = np.r_[False, ok]
        out_ok = np.r_[ok, False]
        lone = ~in_ok & ~out_ok
        if lone.any():
            good[idx[lone]] = False
            continue
        # A record whose removal joins its neighbours into one consistent step.
        skip_ok = np.zeros(len(v), bool)
        if len(v) >= 3:
            skip_ok[1:-1] = ((v[2:] - v[:-2]) % TICK_WRAP) <= max_step
        skippable = skip_ok & (~in_ok | ~out_ok)
        if skippable.any():
            good[idx[skippable]] = False
            continue
        # Segments too short to be real data.
        starts = np.flatnonzero(~in_ok)
        ends = np.r_[starts[1:], len(v)]
        short = (ends - starts) < config.min_segment_records
        if not short.any():
            return good
        for s, e in zip(starts[short], ends[short], strict=True):
            good[idx[s:e]] = False


def pick_inliers(residuals: np.ndarray, tolerance: float) -> np.ndarray:
    """The largest cluster of agreeing anchors; on a tie, the one with the smallest residual,
    since a chunk can be closed (or lose its tail) after its last surviving record, never
    before it."""
    r = np.asarray(residuals, dtype=np.float64)
    support = (np.abs(r[:, None] - r[None, :]) <= tolerance).sum(axis=1)
    best = r[support == support.max()].min()
    return np.abs(r - best) <= tolerance


def _anchor_table(
    chunks: list[ChunkInfo],
    chunk_of: np.ndarray,
    seg: np.ndarray,
    tau: np.ndarray,
    config: TimelineConfig,
) -> pl.DataFrame:
    """End and start anchors per chunk, over the good records (``chunk_of`` per good record)."""

    def eligible(utc: float) -> bool:
        return (config.anchor_from_s is None or utc >= config.anchor_from_s) and (
            config.anchor_to_s is None or utc <= config.anchor_to_s
        )

    rows = []
    for c, info in enumerate(chunks):
        mine = np.flatnonzero(chunk_of == c)
        if not len(mine):
            continue
        close = info.mtime_s + config.mtime_to_utc_s
        first, last = mine[0], mine[-1]
        rows.append(
            (
                c,
                "end",
                int(seg[last]),
                float(tau[last]),
                close,
                not info.truncated and eligible(close),
            )
        )
        if info.rotated and config.rotation_s is not None:
            opened = close - config.rotation_s
            rows.append((c, "start", int(seg[first]), float(tau[first]), opened, eligible(opened)))
    return pl.DataFrame(
        rows,
        schema={
            "chunk": pl.Int64,
            "kind": pl.String,
            "segment": pl.Int64,
            "tau_s": pl.Float64,
            "utc_s": pl.Float64,
            "eligible": pl.Boolean,
        },
        orient="row",
    ).with_columns((pl.col("utc_s") - pl.col("tau_s")).alias("residual_s"))


def _hidden_gap(
    anchors: pl.DataFrame,
    seg: np.ndarray,
    tau: np.ndarray,
    d: np.ndarray,
    config: TimelineConfig,
) -> int | None:
    """Position (in good records) where a segment hides a gap of whole 512-s wraps, or None.

    Inside one segment the anchors' residuals should agree. A device that stops and resumes
    at a counter value one sample on (modulo 2^24) shows up as a residual step of k x 512 s,
    k >= 1, between consecutive anchors, confirmed by a neighbouring anchor on either side.
    The gap is put at the largest tick step between the two anchors.
    """
    wrap_s = TICK_WRAP / TICK_HZ
    tol = config.anchor_tolerance_s
    for s in anchors.filter("eligible")["segment"].unique().sort().to_list():
        a = anchors.filter(pl.col("eligible") & (pl.col("segment") == s)).sort("tau_s", "kind")
        r, at = a["residual_s"].to_numpy(), a["tau_s"].to_numpy()
        for i in range(1, len(r)):
            jump = r[i] - r[i - 1]
            k = round(jump / wrap_s)
            if k < 1 or abs(jump - k * wrap_s) > tol:
                continue
            right = i + 1 < len(r) and abs(r[i + 1] - r[i]) <= tol
            left = i >= 2 and abs(r[i - 1] - r[i - 2]) <= tol
            if not (right or left):
                continue
            within = np.flatnonzero((seg == s) & (tau > at[i - 1]) & (tau <= at[i]))
            if len(within):
                incoming = np.r_[0, d][within]
                return int(within[np.argmax(incoming)])
    return None


def place_run(
    ticks: list[np.ndarray],
    zero: list[np.ndarray],
    chunks: list[ChunkInfo],
    config: TimelineConfig,
) -> RunTimeline:
    T = np.concatenate(ticks) if ticks else np.zeros(0, np.int64)
    Z = np.concatenate(zero) if zero else np.zeros(0, bool)
    chunk_of = np.concatenate([np.full(len(t), i) for i, t in enumerate(ticks)]) if ticks else T
    good = clean_ticks(T, ~Z, config)
    n = len(T)
    t = np.full(n, np.nan)
    segment = np.full(n, -1)
    unanchored = np.zeros(n, bool)

    idx = np.flatnonzero(good)
    max_step = int(config.max_step_s * TICK_HZ)
    d = tick_steps(T[idx]) if len(idx) else np.zeros(0, np.int64)
    hidden: set[int] = set()
    while True:
        brk = np.r_[True, d > max_step] if len(idx) else np.zeros(0, bool)
        if hidden:
            brk[sorted(hidden)] = True
        seg = np.cumsum(brk) - 1
        tau_ticks = np.cumsum(np.r_[0, np.where(brk[1:], 0, d)]) if len(idx) else d
        if len(idx):
            tau_ticks = tau_ticks - tau_ticks[np.flatnonzero(brk)][seg]
        tau = tau_ticks / TICK_HZ
        anchors = _anchor_table(chunks, chunk_of[idx], seg, tau, config)
        split = _hidden_gap(anchors, seg, tau, d, config)
        if split is None or split in hidden:
            break
        hidden.add(split)
    segment[idx] = seg

    used = np.zeros(anchors.height, bool)
    rates: list[float] = []
    n_segments = int(seg.max()) + 1 if len(idx) else 0
    unanchored_segments = 0
    for s in range(n_segments):
        members = idx[seg == s]
        a = anchors.with_row_index("_i").filter(pl.col("eligible") & (pl.col("segment") == s))
        if a.height == 0:
            unanchored[members] = True
            unanchored_segments += 1
            continue
        r = a["residual_s"].to_numpy()
        inlier = pick_inliers(r, config.anchor_tolerance_s)
        a_tau, a_r = a["tau_s"].to_numpy()[inlier], r[inlier]
        used[a["_i"].to_numpy()[inlier]] = True
        span = a_tau.max() - a_tau.min()
        if len(a_tau) >= config.drift_min_anchors and span >= config.drift_min_span_s:
            rate, offset = np.polyfit(a_tau, a_r, 1)
        else:
            rate, offset = 0.0, float(np.mean(a_r))
        rates.append(float(rate) * 1e6)
        seg_tau = tau[seg == s]
        t[members] = seg_tau + offset + rate * seg_tau

    anchors = anchors.with_columns(pl.Series("used", used))
    qa = {
        "records": int(n),
        "records_zero": int(Z.sum()),
        "records_bad": int((~good).sum()),
        "records_unanchored": int(unanchored.sum()),
        "segments": n_segments,
        "segments_unanchored": unanchored_segments,
        "hidden_gaps": len(hidden),
        "anchors_eligible": int(anchors["eligible"].sum()),
        "anchors_used": int(used.sum()),
        "segment_rates_ppm": rates,
    }
    return RunTimeline(
        t=t, bad=~good, segment=segment, unanchored=unanchored, anchors=anchors, qa=qa
    )
