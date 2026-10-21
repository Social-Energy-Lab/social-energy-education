"""PPG beat detection and quality (``eda.ppg``) on made-up pulses with known beats."""

from datetime import UTC, datetime

import numpy as np
import polars as pl

from social_energy.eda.ppg import PpgConfig, analyse, bandpass, plausible_ibis, stretches
from social_energy.synth.eda import beat_times, pulse_wave

FS = 128.0
T0 = datetime(2030, 1, 1, tzinfo=UTC).timestamp()  # a multiple of 10 s
CFG = PpgConfig()


def _pulse(seconds: float, bpm: float = 72.0, seed: int = 0, noise_mv: float = 1.0):
    rng = np.random.default_rng(seed)
    rel = np.arange(0, seconds, 1 / FS)
    beats = beat_times(2.0, seconds - 2.0, bpm, rng)
    x = 1400 + pulse_wave(rel, beats) + 20 * np.sin(2 * np.pi * 0.07 * rel)
    return T0 + rel, x + noise_mv * rng.standard_normal(len(rel)), T0 + beats


def _match(got: np.ndarray, want: np.ndarray) -> np.ndarray:
    """Distance from each true beat to the nearest detected one."""
    i = np.clip(np.searchsorted(got, want), 1, len(got) - 1)
    return np.minimum(np.abs(got[i] - want), np.abs(got[i - 1] - want))


def test_bandpass_keeps_the_pulse_band_in_phase_and_removes_the_rest():
    """DC 50 mV, a 0.03 Hz drift (10 mV), 1.5 Hz (3 mV) and 30 Hz (2 mV) over 120 s. Expected
    from the forward-backward Butterworth magnitude (order 2, 0.5-8 Hz): 1.5 Hz kept at
    gain ((1/(1+(0.5/1.5)^4)) * (1/(1+(1.5/8)^4)))^2 = 0.973, in phase; the others gone."""
    t = np.arange(0, 120, 1 / FS)
    keep = 3 * np.sin(2 * np.pi * 1.5 * t)
    x = 50 + 10 * np.sin(2 * np.pi * 0.03 * t) + keep + 2 * np.sin(2 * np.pi * 30 * t)
    y = bandpass(x, CFG)
    mid = slice(int(20 * FS), int(100 * FS))  # away from the ends
    gain = np.std(y[mid]) / np.std(keep[mid])
    assert abs(gain - 0.973) < 0.01
    assert np.corrcoef(y[mid], keep[mid])[0, 1] > 0.999  # zero phase
    assert np.abs(y[mid] - 0.973 * keep[mid]).max() < 0.1


def test_bandpass_over_several_blocks_matches_one_block():
    """The overlapping blocks join seamlessly: a 20-min signal filtered in 2^16-sample blocks
    equals the same signal filtered in one FFT."""
    rng = np.random.default_rng(1)
    x = np.cumsum(rng.standard_normal(int(1200 * FS)))
    a = bandpass(x, CFG)
    b = bandpass(x, CFG, block=1 << 18)
    assert np.abs(a - b)[int(30 * FS) : -int(30 * FS)].max() < 1e-6 * np.abs(b).max()


def test_every_beat_of_a_clean_pulse_is_found_and_no_other():
    """5 min at 72 bpm with drift and jitter: each true systolic peak within 20 ms of a
    detected one, as many detections as true beats."""
    t, x, truth = _pulse(300)
    beats, _ = analyse(t, x, CFG)
    got = beats["t"].to_numpy()
    assert len(got) == len(truth)
    assert _match(got, truth).max() < 0.020
    assert beats["plausible"].sum() == len(truth) - 1  # the first has no interval


def test_clean_windows_are_good_and_give_the_true_heart_rate():
    """Every full window of a clean pulse passes every quality rule; its heart rate is within
    1 bpm of 60 / the median true interval in it."""
    t, x, truth = _pulse(300, bpm=95, seed=2)
    _, win = analyse(t, x, CFG)
    full = win.filter(
        (pl.col("t").dt.epoch("s") >= T0 + 10) & (pl.col("t").dt.epoch("s") < T0 + 280)
    )
    assert full.height == 27 and full["quality_ok"].all()
    for row in full.iter_rows(named=True):
        lo = row["t"].timestamp()
        inside = truth[(truth >= lo) & (truth < lo + 10)]
        want = 60 / np.median(np.diff(np.r_[truth[truth < lo][-1:], inside]))
        assert abs(row["hr_bpm"] - want) < 1.0


def test_sensor_noise_is_never_good_quality():
    """A dead sensor (1 mV noise) and loud white noise (50 mV): no window passes."""
    rng = np.random.default_rng(3)
    t = T0 + np.arange(0, 300, 1 / FS)
    for sd in (1.0, 50.0):
        _, win = analyse(t, 1400 + sd * rng.standard_normal(len(t)), CFG)
        assert win.height == 30
        assert not win["quality_ok"].any(), sd
    _, dead = analyse(t, 1400 + rng.standard_normal(len(t)), CFG)
    assert not dead["amplitude_ok"].any()


def _erased(seconds: float, at: list[float], bpm: float = 75.0, seed: int = 4):
    """A regular pulse with the beats nearest the times ``at`` (s) erased."""
    rng = np.random.default_rng(seed)
    rel = np.arange(0, seconds, 1 / FS)
    truth = 2.0 + np.arange(0, seconds - 4, 60 / bpm)
    gone = sorted({int(np.argmin(np.abs(truth - a))) for a in at})
    x = pulse_wave(rel, truth) - pulse_wave(rel, truth[gone]) + rng.standard_normal(len(rel))
    beats, win = analyse(T0 + rel, 1400 + x, CFG)
    return beats, win.with_columns((pl.col("t").dt.epoch("s") - T0).alias("rel"))


def test_a_missed_beat_is_an_implausible_interval_and_the_rate_survives():
    """One pulse erased at ~154 s: the interval across it (1.6 s, twice the others) is
    implausible; its window's rate comes from the plausible intervals, 75 bpm, and it stays
    good (one doubled interval is a ratio of 2.0, under the 2.2 limit)."""
    beats, win = _erased(300, [154.0])
    long = beats.filter(pl.col("ibi_s") > 1.2)
    assert long.height == 1 and not long["plausible"][0]
    row = win.filter(rel=150).row(0, named=True)
    assert abs(row["hr_bpm"] - 75) < 0.5 and row["quality_ok"]


def test_two_missed_beats_fail_the_window_only():
    """Two consecutive pulses erased at ~154 s: an interval of 2.4 s, three times the others,
    fails the interval-ratio rule in its window; the windows around it stay good."""
    _, win = _erased(300, [154.0, 154.8])
    bad = win.filter(rel=150).row(0, named=True)
    assert not bad["ratio_ok"] and not bad["quality_ok"] and bad["gap_ok"]
    assert win.filter(pl.col("rel").is_in([130, 140, 160, 170]))["quality_ok"].all()


def test_a_gap_splits_the_signal_and_no_interval_spans_it():
    """60 s of pulse, 30 s with no samples, 60 s more: the first beat after the gap has no
    interval, and the empty windows are absent."""
    t, x, _ = _pulse(150, seed=5)
    keep = (t - T0 < 60) | (t - T0 >= 90)
    assert len(stretches(t[keep], CFG)) == 2
    beats, win = analyse(t[keep], x[keep], CFG)
    after = beats.filter(pl.col("t") >= T0 + 90)
    assert after["ibi_s"][0] is None
    assert after["ibi_s"][1:].min() < 1.5
    rel = (win["t"].dt.epoch("s") - T0).to_list()
    assert 60 not in rel and 80 not in rel and 90 in rel


def test_plausible_intervals_by_hand():
    """Range 0.3-1.5 s and within 30% of the neighbours' median (out-of-range ones are left
    out of the median)."""
    ibi = np.array([np.nan, 0.80, 0.82, 0.78, 1.60, 0.80, 0.25, 0.81, 1.10, 0.80])
    got = plausible_ibis(ibi, CFG)
    assert got.tolist() == [False, True, True, True, False, True, False, True, False, True]


def test_window_coverage_and_alignment():
    """Samples from 5 s into a window: that window covers 5 s (coverage rule fails) and
    windows start on multiples of 10 s."""
    t, x, _ = _pulse(60, seed=6)
    _, win = analyse(t[int(5 * FS) :], x[int(5 * FS) :], CFG)
    assert (win["t"].dt.epoch("s") % 10 == 0).all()
    first = win.row(0, named=True)
    assert abs(first["covered_s"] - 5.0) < 0.01 and not first["coverage_ok"]


def test_motion_on_the_pulse_fails_the_template_rule():
    """A 72 bpm pulse with motion noise (1-6 Hz, 40 mV): beats are still found at a plausible
    rhythm in some windows, but their shapes disagree; those windows fail on the template
    rule alone, and no window is good."""
    rng = np.random.default_rng(7)
    rel = np.arange(0, 300, 1 / FS)
    x = 1400 + pulse_wave(rel, beat_times(2, 298, 72, rng))
    f = np.fft.rfftfreq(len(rel), 1 / FS)
    motion = np.fft.irfft(np.fft.rfft(rng.standard_normal(len(rel))) * ((f > 1) & (f < 6)))
    _, w = analyse(T0 + rel, x + 40 * motion / motion.std(), CFG)
    rules = ("hr_range_ok", "gap_ok", "ratio_ok", "coverage_ok", "amplitude_ok")
    others = w.select(pl.all_horizontal(*rules) & (pl.col("ibis_plausible") >= 3))
    only_template = others.to_series() & ~w["template_ok"]
    assert only_template.sum() >= 3
    assert not w["quality_ok"].any()
