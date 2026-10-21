"""EDA features: wear bouts from skin contact, and skin-conductance responses (SCRs).

Made-up signals with hand-placed events.
"""

from datetime import UTC, datetime

import numpy as np
import polars as pl

from social_energy.eda.features import ScrConfig, WearConfig, detect_scr, wear_bouts

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
