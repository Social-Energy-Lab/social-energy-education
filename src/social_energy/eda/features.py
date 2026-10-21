"""EDA features: wear bouts from skin contact, skin-conductance responses, person-minutes.

Method choices here (thresholds, smoothing, the trough-to-peak SCR rule) are conventional
defaults from the EDA literature, configurable, and open to the research team's review.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import polars as pl

ONSET_FRACTION = 0.05


@dataclass(frozen=True)
class ScrConfig:
    rate_hz: float = 4.0  # conductance is averaged to this rate before detection
    smooth_s: float = 1.0  # moving-average window
    min_amplitude_us: float = 0.05  # trough to peak
    min_rise_s: float = 0.5
    max_rise_s: float = 5.0
    # Artifact rules (Kleckner et al. 2018, plus a fall-rate rule for pressure drops):
    min_us: float = 0.05  # below: no skin contact
    max_us: float = 60.0  # above: not physiological
    max_rate_us_s: float = 10.0  # faster change in either direction
    #: Faster relative fall per second than a recovery (half-recovery of ~2 s on a large
    #: response falls ~10%/s of the level): a pressure or motion drop.
    max_fall_per_s: float = 0.25
    artifact_pad_s: float = 5.0  # around each bad bin
    #: A rise out of a fall faster than this (share of the level per second, over the second
    #: before the onset) is the recovery from a notch, not a response.
    max_pre_onset_fall_per_s: float = 0.10


@dataclass(frozen=True)
class WearConfig:
    #: An electrode pair on skin conducts; open electrodes read near zero.
    contact_min_us: float = 0.05
    #: Contact gaps up to this long stay inside one bout (adjusting the strap, a dry moment).
    max_gap_s: int = 60
    #: Shorter bouts are handling, not wear.
    min_bout_s: int = 300


_SCR_SCHEMA = {
    "onset_s": pl.Float64,
    "peak_s": pl.Float64,
    "amplitude_us": pl.Float64,
    "rise_s": pl.Float64,
    "onset_us": pl.Float64,
    "artifact": pl.Boolean,
}


def artifact_mask(x: np.ndarray, config: ScrConfig) -> np.ndarray:
    """Bins of a ``rate_hz`` conductance series that are artifacts, or within
    ``artifact_pad_s`` of one: out of range, changing faster than ``max_rate_us_s``, or
    falling faster than ``max_fall_per_s`` of the level. Gaps (NaN) are not artifacts."""
    x = np.asarray(x, float)
    with np.errstate(invalid="ignore", divide="ignore"):
        bad = (x < config.min_us) | (x > config.max_us)
        d = np.diff(x) * config.rate_hz
        fast = np.abs(d) > config.max_rate_us_s
        fall = -d / x[:-1] > config.max_fall_per_s
    bad[1:] |= fast | fall
    pad = round(config.artifact_pad_s * config.rate_hz)
    if pad and bad.any():
        full = np.convolve(bad.astype(np.int64), np.ones(2 * pad + 1, np.int64), "full")
        bad = full[pad : pad + len(bad)] > 0  # "same" would return the longer length
    return bad


def artifact_seconds(t: np.ndarray, us: np.ndarray, config: ScrConfig) -> np.ndarray:
    """Epoch seconds (int) that hold an artifact bin, for one continuous recording."""
    times, x = _resample(np.asarray(t, float), np.asarray(us, float), config.rate_hz)
    if not len(x):
        return np.zeros(0, np.int64)
    return np.unique(np.floor(times[artifact_mask(x, config)]).astype(np.int64))


def _resample(t: np.ndarray, us: np.ndarray, rate: float) -> tuple[np.ndarray, np.ndarray]:
    ok = np.isfinite(t) & np.isfinite(us)
    if not ok.any():
        return np.zeros(0), np.zeros(0)
    b = np.floor(t[ok] * rate).astype(np.int64)
    b0 = b.min()
    k = b - b0
    n = int(k.max()) + 1
    cnt = np.bincount(k, minlength=n)
    with np.errstate(invalid="ignore"):
        x = np.bincount(k, us[ok], minlength=n) / cnt
    return (b0 + np.arange(n) + 0.5) / rate, x


def _stretches(finite: np.ndarray) -> list[tuple[int, int]]:
    edges = np.diff(np.r_[0, finite.astype(np.int8), 0])
    return list(zip(np.flatnonzero(edges == 1), np.flatnonzero(edges == -1), strict=True))


def _notch(s: np.ndarray, onset: int, config: ScrConfig) -> bool:
    """Whether the smoothed signal fell into the trough at ``onset`` faster than a baseline
    can."""
    back = round(config.rate_hz)
    if onset < back or s[onset - back] <= 0:
        return False
    return (s[onset - back] - s[onset]) / s[onset - back] > config.max_pre_onset_fall_per_s


def detect_scr(t: np.ndarray, us: np.ndarray, config: ScrConfig) -> pl.DataFrame:
    """Trough-to-peak SCRs in one continuous recording (``t`` in epoch seconds, ``us`` µS).

    Conductance is averaged to ``rate_hz`` and smoothed; each local maximum is paired with the
    local minimum before it (or the lowest point within ``max_rise_s``), the onset being the
    last point within 5% of the rise above that trough; a pair is an SCR when
    the rise reaches ``min_amplitude_us`` within ``min_rise_s``-``max_rise_s``. Gaps (NaN)
    split the signal; no SCR spans one. An SCR whose rise touches an artifact
    (``artifact_mask``), or that rises out of a notch (``max_pre_onset_fall_per_s``), is kept
    and flagged ``artifact``.
    """
    times, x = _resample(np.asarray(t, float), np.asarray(us, float), config.rate_hz)
    artifact = artifact_mask(x, config)
    w = max(1, round(config.smooth_s * config.rate_hz))
    max_rise = round(config.max_rise_s * config.rate_hz)
    rows = []
    for a, b in _stretches(np.isfinite(x)):
        if b - a < w + 2:
            continue
        # Moving average that divides by the samples actually present, so the edges of a
        # stretch are not pulled towards zero.
        kernel = np.ones(w)
        s = np.convolve(x[a:b], kernel, mode="same") / np.convolve(np.ones(b - a), kernel, "same")
        sgn = np.sign(np.diff(s))
        # Flat steps take the direction of the last move.
        last = np.maximum.accumulate(np.where(sgn != 0, np.arange(len(sgn)), 0))
        sgn = sgn[last]
        turn = np.flatnonzero(sgn[1:] != sgn[:-1]) + 1
        peaks = turn[(sgn[turn - 1] > 0) & (sgn[turn] < 0)]
        troughs = turn[(sgn[turn - 1] < 0) & (sgn[turn] > 0)]
        for p in peaks:
            before = troughs[troughs < p]
            o = int(before[-1]) if len(before) else 0
            if p - o > max_rise:
                lo = p - max_rise
                o = lo + int(np.argmin(s[lo : p + 1]))
            amp = s[p] - s[o]
            notch = _notch(s, o, config)
            # Onset: the last point before the peak still within 5% of the rise above the
            # trough, so a flat baseline does not stretch the rise back to its first sample.
            o = o + int(np.flatnonzero(s[o : p + 1] <= s[o] + ONSET_FRACTION * amp)[-1])
            rise = (p - o) / config.rate_hz
            if amp >= config.min_amplitude_us and config.min_rise_s <= rise <= config.max_rise_s:
                rows.append(
                    (
                        times[a + o],
                        times[a + p],
                        float(amp),
                        rise,
                        float(s[o]),
                        bool(artifact[a + o : a + p + 1].any()) or notch,
                    )
                )
    return pl.DataFrame(rows, schema=_SCR_SCHEMA, orient="row")


def wear_bouts(seconds: pl.DataFrame, config: WearConfig) -> tuple[pl.DataFrame, pl.DataFrame]:
    """Wear bouts per device from per-second conductance.

    Returns ``(bouts, seconds)``: bouts with ``device``, ``start``, ``end`` (half-open) and
    ``contact_s``; and the input with ``contact`` (conductance at or above the threshold) and
    ``worn`` (inside a bout) added.
    """
    s = seconds.sort("device", "t").with_columns(
        (pl.col("conductance_us") >= config.contact_min_us).fill_null(False).alias("contact")
    )
    bout_rows = []
    worn_parts = []
    for (device,), part in s.group_by("device", maintain_order=True):
        epoch = part["t"].dt.epoch("s").to_numpy()
        c = epoch[part["contact"].to_numpy()]
        starts = ends = np.zeros(0, np.int64)
        if len(c):
            new = np.r_[True, np.diff(c) > config.max_gap_s + 1]
            first = np.flatnonzero(new)
            last = np.r_[first[1:], len(c)] - 1
            starts, ends = c[first], c[last] + 1
            n_contact = last - first + 1
            keep = (ends - starts) >= config.min_bout_s
            starts, ends, n_contact = starts[keep], ends[keep], n_contact[keep]
            bout_rows += [
                (device, int(a), int(b), int(n))
                for a, b, n in zip(starts, ends, n_contact, strict=True)
            ]
        i = np.searchsorted(starts, epoch, side="right") - 1
        worn = np.zeros(len(epoch), bool)
        if len(starts):
            inside = i >= 0
            worn[inside] = epoch[inside] < ends[i[inside]]
        worn_parts.append(part.with_columns(pl.Series("worn", worn)))
    bouts = pl.DataFrame(
        bout_rows,
        schema={"device": pl.String, "start": pl.Int64, "end": pl.Int64, "contact_s": pl.Int64},
        orient="row",
    ).with_columns(
        pl.from_epoch("start", "s").dt.replace_time_zone("UTC"),
        pl.from_epoch("end", "s").dt.replace_time_zone("UTC"),
    )
    flagged = pl.concat(worn_parts) if worn_parts else s.with_columns(worn=pl.lit(False))
    return bouts, flagged
