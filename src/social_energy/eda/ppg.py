"""Heart rate from the Shimmer's optical pulse (PPG): beats, inter-beat intervals, quality.

Pure signal processing on one device's samples (``t`` in epoch seconds, PPG in mV); placing
the samples in time is ``eda.timeline``'s job and reading them is ``eda.heart``'s.

1. **Cleaning.** A zero-phase band-pass: the magnitude of a forward-backward Butterworth
   filter (``filtfilt``), applied in the frequency domain over overlapping blocks of each
   contiguous stretch. No dependency beyond numpy.
2. **Beats.** Systolic peaks by Elgendi et al. (2013, PLoS ONE 8:e76585): clip the filtered
   signal at zero, square it, compare a short moving average (one systolic peak, 111 ms) with
   a long one (one beat, 667 ms) plus an offset of ``beta`` times the signal's mean energy;
   each block where the short one is above and at least 111 ms long holds one peak, its
   maximum. The offset uses the mean energy over ``level_window_s`` around each sample rather
   than over the whole record, since a day's recording changes amplitude by orders of
   magnitude.
3. **Inter-beat intervals.** The time from the previous beat in the same stretch. An interval
   is *plausible* if it lies within 40-200 bpm and within ``max_ibi_change`` of the median of
   its neighbours (a missed or extra beat breaks it).
4. **Windows** of ``window_s`` (aligned to the epoch), each with heart rate from the median
   plausible interval and a signal-quality index after Orphanidou et al. (2015, IEEE JBHI
   19:832): heart rate 40-200 bpm, no gap between beats over 3 s, longest over shortest
   interval below 2.2, and mean correlation of the beats with their average template of at
   least 0.86; plus enough signal (``min_covered_s``) and a pulse amplitude above the noise of
   a dead sensor (``min_ppg_sd_mv``). Every window is kept, its rules as flags and
   ``quality_ok`` their conjunction (AGENTS.md invariant 3).

The thresholds are the published defaults except the amplitude floor and the interval-change
limit, which are ours `[inferred]`, configurable.
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass
from itertools import pairwise

import numpy as np
import polars as pl


@dataclass(frozen=True)
class PpgConfig:
    fs_hz: float = 128.0
    #: Band-pass, Hz (Elgendi et al. 2013 use 0.5-8 Hz, second order).
    low_hz: float = 0.5
    high_hz: float = 8.0
    order: int = 2
    #: Systolic peak detection (Elgendi et al. 2013).
    peak_window_s: float = 0.111
    beat_window_s: float = 0.667
    beta: float = 0.02
    level_window_s: float = 10.0
    #: Detect on the negated signal. The Shimmer's PPG rises with each pulse as stored (beats
    #: correlate with their template better upright than inverted on the DSA 2026 data).
    invert: bool = False
    #: Plausibility: 200 and 40 bpm; change against the median of the neighbouring intervals.
    min_ibi_s: float = 0.3
    max_ibi_s: float = 1.5
    max_ibi_change: float = 0.3
    ibi_neighbours: int = 9
    #: A step between samples longer than this splits the signal into stretches.
    max_step_s: float = 0.25
    #: Shorter stretches cannot hold a measurable beat and are not filtered (no pulse).
    min_stretch_s: float = 2.0
    #: Windows and their quality rules (Orphanidou et al. 2015).
    window_s: int = 10
    min_hr_bpm: float = 40.0
    max_hr_bpm: float = 200.0
    max_beat_gap_s: float = 3.0
    max_ibi_ratio: float = 2.2
    min_template_corr: float = 0.86
    min_covered_s: float = 8.0
    min_plausible_ibis: int = 3
    #: Below this standard deviation of the filtered pulse the sensor sees only noise.
    min_ppg_sd_mv: float = 5.0


WINDOW_SCHEMA = {
    "t": pl.Datetime("us", "UTC"),
    "covered_s": pl.Float32,
    "beats": pl.Int16,
    "ibis_plausible": pl.Int16,
    "hr_bpm": pl.Float32,
    "ibi_ms": pl.Float32,
    "ppg_sd_mv": pl.Float32,
    "template_corr": pl.Float32,
    "hr_range_ok": pl.Boolean,
    "gap_ok": pl.Boolean,
    "ratio_ok": pl.Boolean,
    "template_ok": pl.Boolean,
    "coverage_ok": pl.Boolean,
    "amplitude_ok": pl.Boolean,
    "quality_ok": pl.Boolean,
}


def stretches(t: np.ndarray, config: PpgConfig) -> list[slice]:
    """Contiguous stretches of sorted sample times: split where a step exceeds
    ``max_step_s`` (pauses, gaps between runs) or goes backwards."""
    t = np.asarray(t, float)
    if not len(t):
        return []
    brk = np.flatnonzero((np.diff(t) > config.max_step_s) | (np.diff(t) <= 0)) + 1
    edges = np.r_[0, brk, len(t)]
    return [slice(a, b) for a, b in pairwise(edges) if b > a]


def _response(n: int, config: PpgConfig) -> np.ndarray:
    """|H(f)|^2 of a Butterworth band-pass: the zero-phase forward-backward magnitude."""
    f = np.fft.rfftfreq(n, 1.0 / config.fs_hz)
    with np.errstate(divide="ignore"):
        hp = 1.0 / (1.0 + (config.low_hz / f) ** (2 * config.order))
    lp = 1.0 / (1.0 + (f / config.high_hz) ** (2 * config.order))
    hp[0] = 0.0
    return (hp * lp) ** 2


def bandpass(x: np.ndarray, config: PpgConfig, block: int = 1 << 16) -> np.ndarray:
    """Zero-phase band-pass of one contiguous stretch, in overlapping FFT blocks. The ends are
    padded by reflection so the filter does not ring on a step."""
    x = np.asarray(x, float)
    n = len(x)
    if n == 0:
        return x.copy()
    margin = int(16 * config.fs_hz)  # the 0.5 Hz high-pass settles well within 16 s
    xp = np.pad(x - x.mean(), margin, mode="reflect") if n > 1 else np.zeros(n + 2 * margin)
    step = block - 2 * margin
    out = np.empty(n)
    pos = 0
    while pos < n:
        take = min(step, n - pos)
        seg = xp[pos : pos + take + 2 * margin]
        size = 1 << int(np.ceil(np.log2(len(seg))))
        spec = np.fft.rfft(seg, size) * _response(size, config)
        out[pos : pos + take] = np.fft.irfft(spec, size)[margin : margin + take]
        pos += take
    return out


def _moving_mean(x: np.ndarray, w: int) -> np.ndarray:
    """Centred moving average over ``w`` samples (shorter at the ends)."""
    w = max(1, int(w))
    c = np.r_[0.0, np.cumsum(x)]
    n = len(x)
    lo = np.clip(np.arange(n) - w // 2, 0, n)
    hi = np.clip(np.arange(n) - w // 2 + w, 0, n)
    return (c[hi] - c[lo]) / np.maximum(hi - lo, 1)


def detect_peaks(y: np.ndarray, config: PpgConfig) -> np.ndarray:
    """Indices of systolic peaks in one filtered stretch (Elgendi et al. 2013)."""
    y = np.asarray(y, float)
    if len(y) < 3:
        return np.zeros(0, np.int64)
    fs = config.fs_hz
    sq = np.maximum(y, 0.0) ** 2
    w1 = round(config.peak_window_s * fs)
    ma_peak = _moving_mean(sq, w1)
    ma_beat = _moving_mean(sq, round(config.beat_window_s * fs))
    level = _moving_mean(sq, round(config.level_window_s * fs))
    above = ma_peak > ma_beat + config.beta * level
    edges = np.flatnonzero(np.diff(np.r_[False, above, False].astype(np.int8)))
    starts, ends = edges[::2], edges[1::2]
    wide = (ends - starts) >= w1
    starts, ends = starts[wide], ends[wide]
    if not len(starts):
        return np.zeros(0, np.int64)
    lengths = ends - starts
    inside = np.zeros(len(y) + 1, np.int64)
    np.add.at(inside, starts, 1)
    np.add.at(inside, ends, -1)
    inside = np.cumsum(inside[:-1]) > 0
    opened = np.zeros(len(y), np.int64)
    opened[starts] = 1
    label = np.cumsum(opened) - 1
    peak_val = np.maximum.reduceat(y[inside], np.r_[0, np.cumsum(lengths)[:-1]])
    cand = np.flatnonzero(inside & (y == peak_val[np.maximum(label, 0)]))
    _, first = np.unique(label[cand], return_index=True)
    peaks = cand[first]
    # Refractory period: of peaks closer than the shortest interval, the largest stays (taken
    # in order of height, each removing its smaller neighbours within reach).
    min_gap = config.min_ibi_s * fs
    close = np.diff(peaks) < min_gap
    if not close.any():
        return peaks
    keep = np.ones(len(peaks), bool)
    for i in np.argsort(-y[peaks], kind="stable"):
        if not keep[i]:
            continue
        j = i - 1
        while j >= 0 and peaks[i] - peaks[j] < min_gap:
            keep[j] = False
            j -= 1
        j = i + 1
        while j < len(peaks) and peaks[j] - peaks[i] < min_gap:
            keep[j] = False
            j += 1
    return peaks[keep]


def plausible_ibis(ibi: np.ndarray, config: PpgConfig) -> np.ndarray:
    """Intervals within 40-200 bpm and within ``max_ibi_change`` of the median of their
    ``ibi_neighbours`` neighbours (NaN for the first beat of a stretch)."""
    ibi = np.asarray(ibi, float)
    ok = (ibi >= config.min_ibi_s) & (ibi <= config.max_ibi_s)
    if not len(ibi):
        return ok
    h = config.ibi_neighbours // 2
    padded = np.pad(np.where(ok, ibi, np.nan), h, constant_values=np.nan)
    view = np.lib.stride_tricks.sliding_window_view(padded, 2 * h + 1)
    with warnings.catch_warnings(), np.errstate(all="ignore"):
        warnings.simplefilter("ignore", RuntimeWarning)  # all-NaN neighbourhoods
        med = np.nanmedian(view, axis=1)
        return ok & (np.abs(ibi / med - 1.0) <= config.max_ibi_change)


def beats(t: np.ndarray, ppg_mv: np.ndarray, config: PpgConfig) -> pl.DataFrame:
    """One row per detected beat of a recording: ``t`` (epoch s), ``ibi_s`` (null for the
    first beat of a stretch), ``plausible``."""
    return _analyse(np.asarray(t, float), np.asarray(ppg_mv, float), config)[0]


def windows(t: np.ndarray, ppg_mv: np.ndarray, config: PpgConfig) -> pl.DataFrame:
    """One row per ``window_s`` window holding samples: heart rate and quality."""
    return _analyse(np.asarray(t, float), np.asarray(ppg_mv, float), config)[1]


def analyse(
    t: np.ndarray, ppg_mv: np.ndarray, config: PpgConfig
) -> tuple[pl.DataFrame, pl.DataFrame]:
    """Beats and windows of one recording (samples sorted by time; NaN times are skipped)."""
    return _analyse(np.asarray(t, float), np.asarray(ppg_mv, float), config)


def _analyse(t: np.ndarray, x: np.ndarray, config: PpgConfig):
    keep = np.isfinite(t) & np.isfinite(x)
    t, x = t[keep], x[keep]
    order = np.argsort(t, kind="stable")
    t, x = t[order], x[order]
    # A sample time seen twice (overlapping copies) is one sample: keep the first.
    first = np.diff(t, prepend=-np.inf) > 0
    t, x = t[first], x[first]
    if config.invert:
        x = -x
    y = np.empty(len(x))
    peak_idx, ibi = [], []
    for sl in stretches(t, config):
        if sl.stop - sl.start < config.min_stretch_s * config.fs_hz:
            y[sl] = 0.0  # too short to hold a beat: no pulse
            continue
        y[sl] = bandpass(x[sl], config)
        p = detect_peaks(y[sl], config) + sl.start
        peak_idx.append(p)
        ibi.append(np.r_[np.nan, np.diff(t[p])] if len(p) else np.zeros(0))
    peak_idx = np.concatenate(peak_idx) if peak_idx else np.zeros(0, np.int64)
    ibi = np.concatenate(ibi) if ibi else np.zeros(0)
    plaus = plausible_ibis(ibi, config)
    beat_t = t[peak_idx]
    beat_frame = pl.DataFrame(
        {"t": beat_t, "ibi_s": ibi, "plausible": plaus},
        schema={"t": pl.Float64, "ibi_s": pl.Float64, "plausible": pl.Boolean},
    ).with_columns(pl.col("ibi_s").fill_nan(None))
    return beat_frame, _windows(t, y, peak_idx, ibi, plaus, config)


def _windows(t, y, peak_idx, ibi, plaus, config: PpgConfig) -> pl.DataFrame:
    if not len(t):
        return pl.DataFrame(schema=WINDOW_SCHEMA)
    w = config.window_s
    fs = config.fs_hz
    win_of_sample = np.floor(t / w).astype(np.int64)
    wins, first = np.unique(win_of_sample, return_index=True)
    counts = np.diff(np.r_[first, len(t)])
    covered = counts / fs
    s1 = np.add.reduceat(y, first)
    s2 = np.add.reduceat(y * y, first)
    sd = np.sqrt(np.maximum(s2 / counts - (s1 / counts) ** 2, 0.0))

    beat_t = t[peak_idx]
    beat_win = np.searchsorted(wins, np.floor(beat_t / w).astype(np.int64))
    bounds = np.searchsorted(beat_win, np.arange(len(wins) + 1))
    m = len(wins)
    n_beats = np.diff(bounds)
    n_plaus = np.zeros(m, np.int64)
    hr = np.full(m, np.nan)
    ibi_med = np.full(m, np.nan)
    corr = np.full(m, np.nan)
    gap_ok = np.zeros(m, bool)
    ratio_ok = np.zeros(m, bool)
    for k in np.flatnonzero(n_beats >= 2):
        a, b = bounds[k], bounds[k + 1]
        iv = ibi[a:b]
        pv = plaus[a:b]
        n_plaus[k] = int(pv.sum())
        good = iv[pv]
        if len(good):
            ibi_med[k] = np.median(good)
            hr[k] = 60.0 / ibi_med[k]
        lo, hi = wins[k] * w, (wins[k] + 1) * w
        bt = beat_t[a:b]
        gaps = np.r_[bt[0] - lo, np.diff(bt), hi - bt[-1]]
        gap_ok[k] = gaps.max() <= config.max_beat_gap_s
        inner = np.diff(bt)
        ratio_ok[k] = inner.max() / inner.min() < config.max_ibi_ratio
        # Template: each beat from half a median interval before its peak to half after.
        half = round(float(np.median(inner)) * fs / 2)
        idx = peak_idx[a:b]
        idx = idx[(idx - half >= 0) & (idx + half < len(y))]
        if half >= 2 and len(idx) >= 2:
            seg = y[idx[:, None] + np.arange(-half, half + 1)[None, :]]
            tpl = seg.mean(axis=0)
            sc = seg - seg.mean(axis=1, keepdims=True)
            tc = tpl - tpl.mean()
            den = np.sqrt((sc * sc).sum(axis=1) * (tc * tc).sum())
            with np.errstate(invalid="ignore", divide="ignore"):
                corr[k] = np.nanmean((sc @ tc) / den)
    hr_ok = (hr >= config.min_hr_bpm) & (hr <= config.max_hr_bpm)
    tpl_ok = corr >= config.min_template_corr
    cov_ok = covered >= config.min_covered_s
    amp_ok = sd >= config.min_ppg_sd_mv
    enough = n_plaus >= config.min_plausible_ibis
    quality = hr_ok & gap_ok & ratio_ok & tpl_ok & cov_ok & amp_ok & enough
    return (
        pl.DataFrame(
            {
                "t": wins * w * 1_000_000,
                "covered_s": covered,
                "beats": n_beats,
                "ibis_plausible": n_plaus,
                "hr_bpm": hr,
                "ibi_ms": ibi_med * 1000,
                "ppg_sd_mv": sd,
                "template_corr": corr,
                "hr_range_ok": hr_ok,
                "gap_ok": gap_ok,
                "ratio_ok": ratio_ok,
                "template_ok": tpl_ok,
                "coverage_ok": cov_ok,
                "amplitude_ok": amp_ok,
                "quality_ok": quality,
            }
        )
        .with_columns(
            pl.col("t").cast(pl.Datetime("us", "UTC")),
            pl.col("hr_bpm", "ibi_ms", "template_corr").fill_nan(None),
        )
        .cast(WINDOW_SCHEMA)
    )
