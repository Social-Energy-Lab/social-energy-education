"""The EDA second pass's onset-synchrony script (analysis D), on invented onset trains.

Hand-derived counts on tiny trains; oracle tests on synthetic trains: planted co-onsets give an
excess above 1 peaking at lag 0, independent trains give about 1.
"""

import importlib.util
import sys
from datetime import date
from pathlib import Path

import numpy as np
import pytest

ANALYSES = Path(__file__).resolve().parents[1] / "studies" / "dsa-2026" / "analyses"


@pytest.fixture(scope="module")
def osync():
    sys.path.insert(0, str(ANALYSES))
    spec = importlib.util.spec_from_file_location("eda2_onset_sync_script",
                                                  ANALYSES / "eda2_onset_sync.py")  # fmt: skip
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    yield module
    sys.modules.pop(spec.name, None)


def ones(n: int) -> np.ndarray:
    return np.ones(n, dtype=bool)


def test_counts_by_hand(osync):
    a = np.array([10, 50, 90])
    b = np.array([12, 70])
    lab = np.zeros(3, dtype=np.int64)
    c = osync.shift_counts(a, lab, b, ones(100), ones(100), 0, 100, [0, 40], n_lab=1)
    # Observed: 10 has 12 (lag +2) within 3 s; 50 and 90 have none within 3 s.
    assert c["onsets"][0, 0] == 3 and c["hits"][0, 0] == 1
    lags = c["lags"][0, 0]
    # Lags within 20 s: 10->12 (+2); 50->70 (+20); 90->70 (-20).
    assert lags[osync.MAX_LAG + 2] == 1 and lags[osync.MAX_LAG + 20] == 1
    assert lags[0] == 1 and lags.sum() == 3
    # Shift +40 moves B to 52 and 10 (70 + 40 wraps to 10): 10 and 50 are hits.
    assert c["hits"][1, 0] == 2


def test_validity_follows_the_shift(osync):
    a = np.array([10, 60])
    b = np.array([11, 61])
    va = ones(100)
    vb = ones(100)
    vb[50:] = False  # B invalid in the second half: its onset at 61 cannot exist
    b = b[vb[b]]
    c = osync.shift_counts(a, np.zeros(2, np.int64), b, va, vb, 0, 100, [0, 50], n_lab=1)
    # Observed: A's onset at 60 falls where B is invalid, so only one A onset counts.
    assert c["onsets"][0, 0] == 1 and c["hits"][0, 0] == 1
    # Shift 50: B valid on 50..99 now, so only A's 60 counts; B's 11 moved to 61: a hit.
    assert c["onsets"][1, 0] == 1 and c["hits"][1, 0] == 1


def test_labels_split_the_counts(osync):
    a = np.array([10, 50])
    b = np.array([11, 51])
    lab = np.array([0, 2])
    c = osync.shift_counts(a, lab, b, ones(100), ones(100), 0, 100, [0], n_lab=3)
    assert c["onsets"][0].tolist() == [1, 0, 1] and c["hits"][0].tolist() == [1, 0, 1]


def _trains(rng, n=20000, rate=0.05, shared=0.0, jitter=1):
    a = np.flatnonzero(rng.random(n) < rate)
    b = np.flatnonzero(rng.random(n) < rate)
    if shared:
        pick = a[rng.random(a.size) < shared]
        b = np.union1d(b, np.clip(pick + rng.integers(-jitter, jitter + 1, pick.size), 0, n - 1))
    return a, b


def _excess(osync, a, b, n):
    c = osync.shift_counts(a, np.zeros(a.size, np.int64), b, ones(n), ones(n), 0, n,
                           (0, *osync.SHIFTS), n_lab=1)  # fmt: skip
    share = c["hits"][0, 0] / c["onsets"][0, 0]
    null = c["hits"][1:, 0].sum() / c["onsets"][1:, 0].sum()
    prof = (c["lags"][0, 0] / c["onsets"][0, 0]) / (
        c["lags"][1:, 0].sum(0) / c["onsets"][1:, 0].sum()
    )
    return share / null, prof


def test_planted_co_onsets_give_excess_at_lag_zero(osync):
    rng = np.random.default_rng(1)
    a, b = _trains(rng, shared=0.3)
    ratio, prof = _excess(osync, a, b, 20000)
    assert ratio > 1.3
    zero = osync.MAX_LAG
    assert prof[zero] == prof.max() and prof[zero] > 2
    assert np.all(np.abs(prof[np.abs(osync.LAGS) > 3] - 1) < 0.35)


def test_independent_trains_give_about_one(osync):
    rng = np.random.default_rng(2)
    a, b = _trains(rng, n=100000)
    ratio, prof = _excess(osync, a, b, 100000)
    assert abs(ratio - 1) < 0.05
    assert np.all(np.abs(prof - 1) < 0.25)


def test_a_lead_shows_off_zero(osync):
    rng = np.random.default_rng(3)
    a = np.flatnonzero(rng.random(20000) < 0.03)
    b = np.union1d(np.flatnonzero(rng.random(20000) < 0.03), np.clip(a + 8, 0, 19999))
    _, prof = _excess(osync, a, b, 20000)
    assert int(osync.LAGS[np.argmax(prof)]) == 8


def test_movement_peaks_first_second_of_each_run(osync):
    sd = np.full(200, 0.01)
    sd[50:53] = [0.5, 1.0, 1.5]  # one run of big changes from 50 to 53
    sd[120] = 0.9  # up at 120, down at 121: one run 120-121
    sd[150] = np.nan  # invalid seconds break the change
    peaks = osync.movement_peaks(sd, percentile=95)
    assert peaks.tolist() == [50, 120]


def test_near(osync):
    assert osync.near(np.array([0, 10, 20]), np.array([13]), 3).tolist() == [False, True, False]
    assert osync.near(np.array([5]), np.array([], dtype=np.int64), 3).tolist() == [False]


def test_comovement_counts(osync):
    a = np.array([10, 40, 80])
    b = np.array([11, 81])
    cm = np.array([12])
    out = osync.comovement_counts(a, np.zeros(3, np.int64), b, cm, ones(100), n_lab=1)
    # co-onsets 10 and 80; 10 near the co-movement peak at 12; other onset 40 not.
    assert out[0].tolist() == [1, 2, 0, 1]


def _recs(osync, people, shared):
    """Pair records for a small invented camp: every pair of ``people`` on one day."""
    rng = np.random.default_rng(4)
    n = 6000
    base = {p: np.flatnonzero(rng.random(n) < 0.04) for p in people}
    common = np.flatnonzero(rng.random(n) < 0.02)
    trains = {p: np.union1d(base[p], common) if shared else base[p] for p in people}
    recs, band = [], {s: np.zeros((len(osync.SHIFTS), len(osync.LABELS), 2))
                      for s in osync.SIGNALS}  # fmt: skip
    offsets = (0, *osync.SHIFTS)
    for i, x in enumerate(people):
        for y in people[i + 1 :]:
            for a, b in ((x, y), (y, x)):
                lab = np.zeros(trains[a].size, np.int64)  # all "close"
                c = osync.shift_counts(trains[a], lab, trains[b], ones(n), ones(n), 0, n,
                                       offsets)  # fmt: skip
                band["scr_amp02"][:, :, 0] += c["onsets"][1:]
                band["scr_amp02"][:, :, 1] += c["hits"][1:]
                recs.append({
                    "day": date(2026, 8, 15), "a": a, "b": b, "signal": "scr_amp02",
                    "obs_on": c["onsets"][0], "obs_hit": c["hits"][0],
                    "null_on": c["onsets"][1:].sum(0), "null_hit": c["hits"][1:].sum(0),
                    "lag_obs": c["lags"][0], "lag_null": c["lags"][1:].sum(0),
                })  # fmt: skip
    return recs, band


def test_summarise_excess_and_withholding(osync):
    people = [f"person:{i}" for i in range(6)]
    recs, band = _recs(osync, people, shared=True)
    rows = osync.summarise(recs, band, "discovery", n_boot=200)
    ex = {r["label"]: r for r in rows["excess"] if r["signal"] == "scr_amp02"}
    assert ex["close"]["excess"] > 1.2 and ex["close"]["excess_lo"] > 1
    assert ex["close"]["null_band_hi"] < ex["close"]["share"]
    assert ex["all"]["onsets"] == ex["close"]["onsets"]
    assert ex["heard"]["suppressed"]
    lag0 = next(r for r in rows["lags"] if r["label"] == "close" and r["lag"] == 0)
    assert lag0["ratio"] > 1.5
    # Four people: every cell withheld.
    small, sband = _recs(osync, people[:4], shared=True)
    srows = osync.summarise(small, sband, "discovery", n_boot=50)
    assert all(r["suppressed"] for r in srows["excess"]) and not srows["lags"]


def test_summarise_independent_is_no_lead(osync):
    people = [f"person:{i}" for i in range(6)]
    recs, band = _recs(osync, people, shared=False)
    rows = osync.summarise(recs, band, "discovery", n_boot=200)
    close = next(r for r in rows["excess"] if r["label"] == "close")
    assert close["log_lo"] < 0 < close["log_hi"]
