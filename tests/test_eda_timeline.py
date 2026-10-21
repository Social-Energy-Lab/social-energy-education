"""SD timeline: tick cleaning, segmenting and anchoring to file modification times.

Hand-built tick sequences (128 Hz: +256 ticks per sample, 32768 ticks per second).
"""

import math

import numpy as np

from social_energy.eda.timeline import ChunkInfo, TimelineConfig, pick_inliers, place_run

WRAP = 1 << 24
CFG = TimelineConfig(anchor_from_s=0.0, anchor_to_s=1e7)


def ticks(start: int, n: int) -> list[int]:
    return [(start + 256 * i) % WRAP for i in range(n)]


def run(chunks, infos, config=CFG):
    t = [np.asarray(c, dtype=np.int64) for c, _ in chunks]
    z = [np.asarray(zz, dtype=bool) for _, zz in chunks]
    return place_run(t, z, infos, config)


def test_wrap_glitches_and_pause_on_one_anchor():
    """200 samples across the 2^24 wrap, a 28.703125 s pause (940544 ticks), 200 more.

    Inserted: an all-zero record after sample 4 and an out-of-sequence tick (5000000) after
    sample 6. Both are bad and get no time. Elapsed time of the good samples: i/128 before
    the pause; 199/128 + 28.703125 + j/128 after it. The last one, at 398/128 + 28.703125 =
    31.8125 s, sits at the chunk's mtime (1000 s) plus the 7200 s offset: 8200 s. So sample 0
    sits at 8200 - 31.8125 = 8168.1875."""
    before = ticks(WRAP - 512, 200)
    after = ticks((before[-1] + 940544) % WRAP, 200)
    seq = [*before[:5], 0, *before[5:7], 5_000_000, *before[7:], *after]
    zero = [False] * len(seq)
    zero[5] = True
    tl = run([(seq, zero)], [ChunkInfo(mtime_s=1000.0)], TimelineConfig(mtime_to_utc_s=7200.0))
    assert tl.bad.tolist() == [i in (5, 8) for i in range(len(seq))]
    expected = [8168.1875 + i / 128 for i in range(200)]
    expected += [8168.1875 + 199 / 128 + 28.703125 + j / 128 for j in range(200)]
    assert np.allclose(tl.t[~tl.bad], expected)
    assert np.isnan(tl.t[tl.bad]).all()
    assert tl.qa["segments"] == 1 and tl.qa["records_bad"] == 2


def test_truncated_chunk_is_not_an_anchor_and_a_long_gap_starts_an_unanchored_segment():
    """Chunk 0: 1280 samples (last at 1279/128 = 9.9921875 s), mtime 100 -> offset 90.0078125.
    Chunk 1: 640 samples, truncated, its mtime claims an hour later: ignored.
    Chunk 2: starts 20 s (655360 ticks) after chunk 1's last sample, a pause the counter
    bridges; 1280 samples, last at 14.9921875 + 20 + 9.9921875 = 44.984375 s; its mtime
    134.9921875 agrees with chunk 0.
    Chunk 3: 100 s later (> 60 s: new segment), mtime outside the anchor window: unanchored."""
    c0 = ticks(0, 1280)
    c1 = ticks(c0[-1] + 256, 640)
    c2 = ticks(c1[-1] + 655360, 1280)
    c3 = ticks(c2[-1] + 100 * 32768, 256)
    f = [False]
    tl = run(
        [(c0, f * 1280), (c1, f * 640), (c2, f * 1280), (c3, f * 256)],
        [
            ChunkInfo(mtime_s=100.0),
            ChunkInfo(mtime_s=3700.0, truncated=True),
            ChunkInfo(mtime_s=134.9921875),
            ChunkInfo(mtime_s=2e9),
        ],
    )
    assert tl.qa["segments"] == 2 and tl.qa["segments_unanchored"] == 1
    assert math.isclose(tl.t[0], 90.0078125)
    assert math.isclose(tl.t[1280 + 640], 90.0078125 + 34.9921875)  # chunk 2's first sample
    assert np.isnan(tl.t[-256:]).all() and tl.unanchored[-256:].all()
    assert not tl.unanchored[:-256].any()
    ends = tl.anchors.filter(kind="end")
    assert ends["used"].to_list() == [True, False, True, False]


def test_drift_is_fitted_when_anchors_span_long_enough():
    """Three 10 s chunks whose mtimes run 1000 ppm fast: mtime = 50 + 1.001 * tau_last.
    With drift_min_span_s = 5 the fit recovers t = 50 + 1.001 * tau."""
    chunks, infos = [], []
    start = 0
    for _ in range(3):
        c = ticks(start, 1280)
        start = c[-1] + 256
        chunks.append((c, [False] * 1280))
    taus_last = [(1280 * (k + 1) - 1) / 128 for k in range(3)]
    infos = [ChunkInfo(mtime_s=50 + 1.001 * tau) for tau in taus_last]
    tl = run(chunks, infos, TimelineConfig(anchor_from_s=0, anchor_to_s=1e7, drift_min_span_s=5))
    tau = np.arange(3840) / 128
    assert np.allclose(tl.t, 50 + 1.001 * tau, atol=1e-6)
    assert math.isclose(tl.qa["segment_rates_ppm"][0], 1000.0, rel_tol=1e-6)


def test_a_tick_running_ahead_is_dropped_without_splitting_the_run():
    """Garbage 1500000 (45.8 s ahead, inside the 60 s step limit) between ticks 512 and 768:
    removing it leaves a consistent sequence, so it is bad and no segment break follows."""
    seq = [0, 256, 512, 1_500_000, 768, 1024, *ticks(1280, 200)]
    tl = run([(seq, [False] * len(seq))], [ChunkInfo(mtime_s=1000.0)])
    assert tl.bad.tolist() == [i == 3 for i in range(len(seq))]
    assert tl.qa["segments"] == 1


def test_a_short_garbage_segment_is_bad():
    """Two non-zero garbage records with tick 0 sit between real samples 176 s apart in counter
    terms: they form a segment of 2 records (< min_segment_records) and are marked bad."""
    a = ticks(8_000_000, 300)
    b = ticks(a[-1] + 256, 300)
    seq = [*a, 0, 0, *b]
    tl = run([(seq, [False] * len(seq))], [ChunkInfo(mtime_s=1000.0)])
    assert tl.bad[300:302].all() and not tl.bad[:300].any() and not tl.bad[302:].any()
    assert tl.qa["segments"] == 1


def test_a_truncated_chunk_alone_does_not_anchor():
    """Chunk 0's mtime is outside the window; chunk 1 is truncated (its mtime claims a tail it
    lost). Neither is eligible, so the segment is unanchored rather than placed by chunk 1."""
    c0 = ticks(0, 1280)
    c1 = ticks(c0[-1] + 256, 640)
    tl = run(
        [(c0, [False] * 1280), (c1, [False] * 640)],
        [ChunkInfo(mtime_s=2e9), ChunkInfo(mtime_s=3700.0, truncated=True)],
    )
    assert tl.unanchored.all() and np.isnan(tl.t).all()


def test_anchor_clusters_tie_to_the_smaller_residual():
    """Residuals 90, 90.5, 120, 121 with 5 s tolerance: two clusters of two, so the one at 90
    wins (a closing time can lag the last record, never precede it). With a third member
    near 120 that cluster wins instead."""
    assert pick_inliers(np.array([90, 90.5, 120, 121]), 5).tolist() == [True, True, False, False]
    assert pick_inliers(np.array([90, 120, 121, 122]), 5).tolist() == [False, True, True, True]


def test_a_rotated_chunk_that_lost_its_tail_is_placed_by_its_start():
    """Chunks rotate every 100 s of wall time (rotation_s). Chunk 0 began at 900, holds 10 s of
    samples and lost the rest of its hour-equivalent: truncated, closed at 1000 when chunk 1
    opened. Chunk 1 starts at 1000 (90.0078125 s after chunk 0's last sample, beyond the
    60 s step: a new segment) and is the run's last chunk, stopped at 1009.9921875.
    Chunk 0 is placed by its start anchor alone: 900 + k/128. Chunk 1 by both of its own."""
    c0 = ticks(0, 1280)
    c1 = ticks(c0[-1] + int(90.0078125 * 32768), 1280)
    cfg = TimelineConfig(anchor_from_s=0, anchor_to_s=1e7, rotation_s=100.0)
    tl = run(
        [(c0, [False] * 1280), (c1, [False] * 1280)],
        [
            ChunkInfo(mtime_s=1000.0, truncated=True, rotated=True),
            ChunkInfo(mtime_s=1000 + 1279 / 128),
        ],
        cfg,
    )
    assert tl.qa["segments"] == 2 and tl.qa["segments_unanchored"] == 0
    assert np.allclose(tl.t[:1280], 900 + np.arange(1280) / 128)
    assert np.allclose(tl.t[1280:], 1000 + np.arange(1280) / 128)


def test_a_gap_of_whole_wraps_is_found_from_the_anchors():
    """The device stops for 7 x 512 = 3584 s and resumes at a counter value that looks like the
    next sample (step 256). Ticks alone see one segment; the anchors jump by 3584 s and the
    next anchor confirms it. Chunk 0's samples end at 9.9921875 s (mtime 1009.9921875:
    offset 1000). Chunks 1 and 2 follow 3584 s later in reality: offset 4584."""
    c0 = ticks(0, 1280)
    c1 = ticks(c0[-1] + 256, 1280)  # looks continuous
    c2 = ticks(c1[-1] + 256, 1280)
    tl = run(
        [(c0, [False] * 1280), (c1, [False] * 1280), (c2, [False] * 1280)],
        [
            ChunkInfo(mtime_s=1000 + 1279 / 128),
            ChunkInfo(mtime_s=4584 + 2559 / 128),
            ChunkInfo(mtime_s=4584 + 3839 / 128),
        ],
    )
    assert tl.qa["segments"] == 2 and tl.qa["hidden_gaps"] == 1
    assert np.allclose(tl.t[:1280], 1000 + np.arange(1280) / 128)
    assert np.allclose(tl.t[1280:], 4584 + np.arange(1280, 3840) / 128)


def test_one_stray_anchor_does_not_split_a_segment():
    """A single anchor 3584 s off, not confirmed by the next one, is rejected, not obeyed."""
    c = [ticks(256 * 1280 * k, 1280) for k in range(3)]
    tl = run(
        [(x, [False] * 1280) for x in c],
        [
            ChunkInfo(mtime_s=1000 + 1279 / 128),
            ChunkInfo(mtime_s=4584 + 2559 / 128),
            ChunkInfo(mtime_s=1000 + 3839 / 128),
        ],
    )
    assert tl.qa["segments"] == 1 and tl.qa["hidden_gaps"] == 0
    assert np.allclose(tl.t, 1000 + np.arange(3840) / 128)
