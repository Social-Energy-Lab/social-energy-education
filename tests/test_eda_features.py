"""EDA features: wear bouts from skin contact, and skin-conductance responses (SCRs).

Made-up signals with hand-placed events.
"""

from datetime import UTC, datetime

import numpy as np
import polars as pl

from social_energy.eda.features import (
    ScrConfig,
    WearConfig,
    artifact_mask,
    detect_scr,
    wear_bouts,
)

T0 = int(datetime(2030, 1, 1, tzinfo=UTC).timestamp())


def _scr_wave(t, onset, amp, rise=2.0, decay=5.0):
    """Linear rise of ``amp`` uS over ``rise`` s from ``onset``, then exponential decay."""
    x = np.zeros_like(t)
    up = (t >= onset) & (t < onset + rise)
    x[up] = amp * (t[up] - onset) / rise
    down = t >= onset + rise
    x[down] = amp * np.exp(-(t[down] - onset - rise) / decay)
    return x


def test_scr_onsets_and_amplitudes_above_threshold():
    """128 Hz, 70 s at 2.0 uS. SCRs at 10 s (+0.30 uS, 2 s rise), 30 s (+0.02, below the
    0.05 uS threshold) and 45 s (+0.10, 1.5 s rise). A NaN gap 60-62 s (no contact) is
    skipped. Expected: two SCRs, onsets near 10 and 45 s (within 0.6 s: the 1 s smoothing
    blurs edges), amplitudes within 15% of 0.30 and 0.10."""
    t = np.arange(0, 70, 1 / 128)
    us = 2.0 + _scr_wave(t, 10, 0.30) + _scr_wave(t, 30, 0.02) + _scr_wave(t, 45, 0.10, 1.5)
    us[(t >= 60) & (t < 62)] = np.nan
    scr = detect_scr(T0 + t, us, ScrConfig())
    assert scr.height == 2
    onsets = scr["onset_s"].to_numpy() - T0
    assert np.allclose(onsets, [10, 45], rtol=0, atol=0.6)
    assert np.allclose(scr["amplitude_us"].to_numpy(), [0.30, 0.10], rtol=0.15, atol=0)
    assert ((scr["rise_s"] >= 0.5) & (scr["rise_s"] <= 5)).all()


def test_flat_and_noisy_signal_has_no_scr():
    """Quantisation-sized noise (+-0.003 uS) on a flat 1 uS signal: nothing reaches 0.05 uS."""
    rng = np.random.default_rng(0)
    t = np.arange(0, 120, 1 / 128)
    us = 1.0 + rng.uniform(-0.003, 0.003, len(t))
    assert detect_scr(T0 + t, us, ScrConfig()).height == 0


def _seconds(device, contact_mask):
    n = len(contact_mask)
    return pl.DataFrame(
        {
            "device": [device] * n,
            "t": [datetime.fromtimestamp(T0 + i, UTC) for i in range(n)],
            "conductance_us": np.where(contact_mask, 2.0, 0.01),
        }
    )


def test_wear_bouts_bridge_short_gaps_and_drop_short_bouts():
    """Device A: contact 0-399 s, off 400-429 (30 s, bridged: <= 60 s), contact 430-699, off
    700-999. One bout [0, 700). Device B: contact 0-199 only, shorter than the 300 s minimum:
    no bout. ``worn`` marks seconds inside a bout; ``contact`` the raw per-second test."""
    a = np.zeros(1000, bool)
    a[:400] = True
    a[430:700] = True
    b = np.zeros(1000, bool)
    b[:200] = True
    seconds = pl.concat([_seconds("SH01", a), _seconds("SH02", b)])
    bouts, flagged = wear_bouts(seconds, WearConfig())
    assert bouts.height == 1
    row = bouts.row(0, named=True)
    assert row["device"] == "SH01"
    assert row["start"] == datetime.fromtimestamp(T0, UTC)
    assert row["end"] == datetime.fromtimestamp(T0 + 700, UTC)
    a_flags = flagged.filter(device="SH01")
    assert a_flags["worn"].to_list() == [i < 700 for i in range(1000)]
    assert a_flags["contact"].to_list() == a.tolist()
    assert not flagged.filter(device="SH02")["worn"].any()


def test_a_sudden_drop_is_an_artifact_and_its_recovery_is_not_an_scr():
    """Flat 2.5 uS for 60 s. At 20 s a pressure artifact: the signal drops 0.4 uS within
    0.25 s (64 %/s of the level, beyond the 25 %/s limit; a recovery falls ~10 %/s), climbs to
    2.7 uS (overshooting) and settles back. At 45 s a real SCR (+0.3 uS). The overshoot looks
    like an SCR but rises inside the artifact window (+-5 s around the drop): flagged. The
    real one is not."""
    t = np.arange(0, 60, 1 / 128)
    us = 2.5 + _scr_wave(t, 45, 0.30)
    drop = (t >= 20) & (t < 20.25)
    us[drop] = 2.5 - 0.4 * (t[drop] - 20) / 0.25
    climb = (t >= 20.25) & (t < 22.25)
    us[climb] = 2.1 + 0.6 * (t[climb] - 20.25) / 2.0
    settle = (t >= 22.25) & (t < 40)
    us[settle] = 2.5 + 0.2 * np.exp(-(t[settle] - 22.25) / 3.0)
    scr = detect_scr(T0 + t, us, ScrConfig())
    clean = scr.filter(~pl.col("artifact"))
    assert clean.height == 1 and abs(clean["onset_s"][0] - T0 - 45) <= 0.6
    assert scr.filter("artifact").height >= 1


def test_artifact_mask_marks_out_of_range_and_fast_changes():
    """4 Hz bins: 1 uS throughout except bin 40 (0.01 uS, out of range) and a +3 uS jump at
    bin 120 (12 uS/s, beyond 10). Each bad bin and 5 s (20 bins) either side are artifact."""
    x = np.full(200, 1.0)
    x[40] = 0.01
    x[120:] = 4.0
    mask = artifact_mask(x, ScrConfig())
    assert mask[20:61].all() and not mask[:20].any() and not mask[61:99].any()
    assert mask[100:141].all() and not mask[141:].any()


def test_a_rise_out_of_a_notch_is_flagged():
    """Flat 5 uS. At 20 s a notch: -0.9 uS over 1 s (18 %/s: under the 25 %/s artifact rule,
    over the 10 %/s a baseline can fall before a real response), then a climb back with an
    overshoot to 5.3 uS. The 'SCR' rising out of the notch is flagged; a real SCR at 45 s
    rising from the flat baseline is not."""
    t = np.arange(0, 60, 1 / 128)
    us = 5.0 + _scr_wave(t, 45, 0.30)
    fall = (t >= 20) & (t < 21)
    us[fall] = 5.0 - 0.9 * (t[fall] - 20)
    climb = (t >= 21) & (t < 23)
    us[climb] = 4.1 + 1.2 * (t[climb] - 21) / 2.0
    settle = (t >= 23) & (t < 40)
    us[settle] = 5.0 + 0.3 * np.exp(-(t[settle] - 23) / 3.0)
    scr = detect_scr(T0 + t, us, ScrConfig())
    clean = scr.filter(~pl.col("artifact"))
    assert clean.height == 1 and abs(clean["onset_s"][0] - T0 - 45) <= 0.6
    assert scr.filter("artifact").height >= 1
