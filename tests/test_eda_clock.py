"""Clock model (eda.clock) on hand-made sync records, with hand-derived expectations.

Times are small epoch seconds (one UTC day). A reference unit REF keeps time; its records
give the master's curve R = reference - master: 0, 20, 40 s at 1000, 4600, 8200 (the
master loses 20 s per hour). Offsets are device - master.
"""

import math

import numpy as np
import polars as pl

from social_energy.eda.clock import (
    RECORDS_SCHEMA,
    RUNS_SCHEMA,
    ClockConfig,
    ClockModel,
    comotion,
    robust_line,
)

CFG = ClockConfig(reference_devices=("REF",), fallback_rates_s_per_h={"U": -36.0})
REF = [("REF", "r", 1000.0, 0.0), ("REF", "r", 4600.0, 20.0), ("REF", "r", 8200.0, 40.0)]


def model(records, runs, config=CFG):
    return ClockModel(
        pl.DataFrame(records, schema=RECORDS_SCHEMA, orient="row"),
        pl.DataFrame(runs, schema=RUNS_SCHEMA, orient="row"),
        config,
    )


def r_curve(tau):
    return np.interp(tau, [1000, 4600, 8200], [0, 20, 40])


def test_robust_line_ignores_outliers():
    t = np.array([0, 1000, 2000, 3000, 1500.0])
    v = np.array([1, 2, 3, 4, 90.0])
    ok, slope, icpt = robust_line(t, v, 1.0, 0.05)
    assert ok.tolist() == [True, True, True, True, False]
    assert math.isclose(slope, 0.001) and math.isclose(icpt, 1.0)


def test_a_slow_slave_is_corrected_through_the_master_curve():
    """Slave S loses 1 % (e = -0.01 (t - 1000) on its own clock). At device 2000, e = -10, so
    reference time 2010 and offset = e + R(2010) = -10 + 1010/180 = -4.3889. At 6000, e = -50,
    reference 6050, offset -50 + 20 + 1450/180 = -21.9444. A record of 500 s at 4000 is
    noise. Corrected: 2000 -> 2010, 6000 -> 6050, and 7000 (past the last record, the fitted
    rate: e = -60) -> 7060."""
    s = [("S", "s", 2000.0, -10 + r_curve(2010)), ("S", "s", 6000.0, -50 + r_curve(6050))]
    s.append(("S", "s", 4000.0, 500.0))
    runs = [("REF", "r", 900.0, 8300.0, False), ("S", "s", 1000.0, 7000.0, False)]
    m = model(REF + s, runs)
    t, unc = m.correct("S", "s", np.array([2000.0, 6000.0, 7000.0]))
    assert np.allclose(t, [2010, 6050, 7060], atol=0.05)
    assert not unc.any()
    rc = m.runs[("S", "s")]
    assert rc.kind == "sync" and rc.records == 3 and rc.inliers == 2
    assert math.isclose(rc.slope, -0.01, rel_tol=1e-3)
    # The reference unit itself needs no correction.
    t, _ = m.correct("REF", "r", np.array([1000.0, 5000.0]))
    assert np.allclose(t, [1000, 5000], atol=1e-6)


def test_the_master_is_corrected_by_minus_its_curve():
    """The master M reads 4580 when the reference reads 4600 (R = 20 there): e = -R."""
    runs = [("REF", "r", 900.0, 8300.0, False), ("M", "m", 1000.0, 8100.0, True)]
    m = model(REF, runs)
    t, unc = m.correct("M", "m", np.array([4580.0, 1000.0]))
    assert np.allclose(t, [4600, 1000], atol=0.01) and not unc.any()
    assert m.runs[("M", "m")].kind == "master"


def test_a_run_without_records_gets_its_units_rate_and_is_flagged():
    """U has no records; its configured rate is -36 s/h, counted from the run's start (1000):
    at 1360, e = -3.6, so 1363.6, flagged uncertain."""
    runs = [("REF", "r", 900.0, 8300.0, False), ("U", "u", 1000.0, 5000.0, False)]
    m = model(REF, runs)
    t, unc = m.correct("U", "u", np.array([1360.0]))
    assert math.isclose(t[0], 1363.6) and unc.all()
    assert m.runs[("U", "u")].kind == "rate"


def test_reference_to_utc_shifts_every_corrected_time():
    runs = [("REF", "r", 900.0, 8300.0, False)]
    m = model(REF, runs, ClockConfig(reference_devices=("REF",), reference_to_utc_s=-2.5))
    t, _ = m.correct("REF", "r", np.array([5000.0]))
    assert math.isclose(t[0], 4997.5)


def test_with_two_masters_each_record_is_read_against_its_own_curve():
    """Two masters: references see curve A (0, 20, 40 at 1000, 4600, 8200) and curve B
    (50, 75, 100 at 1200, 4800, 8400). Slave S2 loses 1 % from 1000: its record at 3000
    (e = -20, reference 3020) was taken against A: -20 + 2020/180 = -8.7778; at 7000
    (e = -60, reference 7060) against B: -60 + 75 + 2260 x 25/3600 = 30.6944; at 5000
    (e = -40, reference 5040) against A: -40 + 20 + 440/180 = -17.5556. With both curves all
    three records agree on -1 %; against A alone the one at 7000 would read as e = -3 and be
    rejected."""
    ref = [
        *REF,
        ("REF2", "r2", 1200.0, 50.0),
        ("REF2", "r2", 4800.0, 75.0),
        ("REF2", "r2", 8400.0, 100.0),
    ]
    s2 = [
        ("S2", "s2", 3000.0, -20 + 2020 / 180),
        ("S2", "s2", 5000.0, -40 + 20 + 440 / 180),
        ("S2", "s2", 7000.0, -60 + 75 + 2260 * 25 / 3600),
    ]
    runs = [
        ("REF", "r", 900.0, 8300.0, False),
        ("REF2", "r2", 900.0, 8500.0, False),
        ("M1", "m1", 900.0, 8300.0, True),
        ("M2", "m2", 900.0, 8500.0, True),
        ("S2", "s2", 1000.0, 7500.0, False),
    ]
    m = model(ref + s2, runs, ClockConfig(reference_devices=("REF", "REF2")))
    assert len(m.curves["1970-01-01"]) == 2
    rc = m.runs[("S2", "s2")]
    assert rc.inliers == 3 and math.isclose(rc.slope, -0.01, rel_tol=1e-3)
    t, _ = m.correct("S2", "s2", np.array([3000.0, 7000.0]))
    assert np.allclose(t, [3020, 7060], atol=0.05)


def test_comotion_finds_the_lag_between_devices_lying_together():
    """Three devices share random motion bursts; B's clock reads 0.25 s late, C's 0.5 s
    early (64 Hz grid, 900 s). Per device, the median lag against the others:
    A (-0.25 + 0.5) / 2 = 0.125 ... computed as medians of pair lags: A: median(-0.25, +0.5)
    = 0.125, B: median(0.25, 0.75) = 0.5, C: median(-0.5, -0.75) = -0.625."""
    rng = np.random.default_rng(1)
    hz, n = 64.0, 900 * 64
    base = np.zeros(n + 200)
    base[rng.choice(n, 600, replace=False) + 100] = 1.0
    a = base[100 : 100 + n]
    b = base[100 - 16 : 100 - 16 + n]  # B shows each event 16 samples (0.25 s) later
    c = base[100 + 32 : 100 + 32 + n]  # C 0.5 s earlier
    res = comotion({"A": a, "B": b, "C": c}, 0.0, hz, window_s=120.0)
    got = dict(zip(res["device"], res["residual_s"], strict=True))
    assert math.isclose(got["A"], 0.125) and math.isclose(got["B"], 0.5)
    assert math.isclose(got["C"], -0.625)


def test_a_reference_unit_record_far_off_the_curve_is_not_obeyed():
    """A reference unit's second run (restarted after a master restart) has one record 257 s
    off the day's curve. A reference unit keeps time by definition, so the record is not
    used: the run gets the fallback (rate 0, flagged), not a 257-s correction."""
    late = [("REF", "r2", 8500.0, r_curve(8500) - 257.0)]
    runs = [("REF", "r", 900.0, 8300.0, False), ("REF", "r2", 8400.0, 9000.0, False)]
    m = model(REF + late, runs)
    t, unc = m.correct("REF", "r2", np.array([8600.0]))
    assert math.isclose(t[0], 8600.0) and unc.all()


def anchors(rows):
    """Box anchors: (device, run, device time, error, status[, position]); evening boxes
    (``tail``) unless given."""
    rows = [(*r, "tail") if len(r) == 5 else r for r in rows]
    return pl.DataFrame(
        rows,
        schema={
            "device": pl.String,
            "run": pl.String,
            "tau": pl.Float64,
            "error_s": pl.Float64,
            "status": pl.String,
            "position": pl.String,
        },
        orient="row",
    )


def anchored(m, rows, config=CFG):
    return ClockModel(m.records, m.runs_table, config, anchors=anchors(rows))


U_RUNS = [("REF", "r", 900.0, 8300.0, False), ("U", "u", 1000.0, 8000.0, False)]


def test_an_evening_anchor_and_the_reset_replace_the_units_rate():
    """U (no records, run 1000-8000) has a box anchor e = -30 at 7000: with the re-set at
    1000, a line of -30 / 6000 = -0.005. At 4000, e = -15: 4015, set by the box. A unit
    drifting 18 s/h stays flagged (one anchor cannot follow a drifting rate); one drifting
    0.3 s/h (e = -0.5 at 7000) does not."""
    m = anchored(model(REF, U_RUNS), [("U", "u", 7000.0, -30.0, "anchor")])
    t, unc, src = m.correct_full("U", "u", np.array([4000.0]))
    assert math.isclose(t[0], 4015.0) and unc.all() and src.tolist() == [1]
    rc = m.runs[("U", "u")]
    assert rc.kind == "box" and math.isclose(rc.slope, -0.005)
    m = anchored(model(REF, U_RUNS), [("U", "u", 7000.0, -0.5, "anchor")])
    t, unc, src = m.correct_full("U", "u", np.array([4000.0]))
    assert math.isclose(t[0], 4000.25) and not unc.any() and src.tolist() == [1]


def test_a_morning_anchor_replaces_the_reset():
    """Anchors e = -5 at 1500 from the morning box (the unit was not re-set to 0) and
    e = -30 at 7000: at 4250, e = -5 - 25 x 2750 / 5500 = -17.5, so 4267.5; at 1250, before
    the first anchor, the line's rate goes back: e = -5 + 250 x 25 / 5500 = -3.864. Had the
    same anchor come from an evening box, the re-set would count: at 1250, e = -2.5 (half of
    -5 since 1000)."""
    rows = [("U", "u", 1500.0, -5.0, "anchor", "head"), ("U", "u", 7000.0, -30.0, "anchor")]
    m = anchored(model(REF, U_RUNS), rows)
    t, _ = m.correct("U", "u", np.array([4250.0, 1250.0]))
    assert np.allclose(t, [4267.5, 1250 + 5 - 250 * 25 / 5500])
    m = anchored(model(REF, U_RUNS), [(*rows[0][:5], "tail"), rows[1]])
    t, _ = m.correct("U", "u", np.array([1250.0]))
    assert math.isclose(t[0], 1252.5)


def test_anchors_that_disagree_keep_the_flag():
    """Two anchors 300 s apart (one box) that differ by 2 s: more than the 1-s tolerance."""
    rows = [("U", "u", 7000.0, -30.0, "anchor"), ("U", "u", 7300.0, -32.0, "anchor")]
    m = anchored(model(REF, U_RUNS), rows)
    _, unc = m.correct("U", "u", np.array([4000.0]))
    assert unc.all()
    # Only anchors count: a check or an unchecked stretch leaves the fallback alone.
    m = anchored(model(REF, U_RUNS), [("U", "u", 7000.0, -30.0, "unchecked")])
    assert m.runs[("U", "u")].kind == "rate"


def test_a_box_anchor_extends_a_fitted_run_beyond_its_records():
    """S loses 1 % (records at 2000 and 6000, as above), and times more than 1000 s from its
    records are a guess (``max_extrapolation_s``). A box anchor e = -65 at 7500 extends them:
    8000 -> 8070 is then measured (by the box), and 3000 -> 3020 still by the records."""
    s = [("S", "s", 2000.0, -10 + r_curve(2010)), ("S", "s", 6000.0, -50 + r_curve(6050))]
    runs = [("REF", "r", 900.0, 8300.0, False), ("S", "s", 1000.0, 8000.0, False)]
    cfg = ClockConfig(reference_devices=("REF",), max_extrapolation_s=1000.0)
    m = model(REF + s, runs, cfg)
    _, unc = m.correct("S", "s", np.array([8000.0]))
    assert unc.all()
    m = anchored(m, [("S", "s", 7500.0, -65.0, "anchor")], cfg)
    t, unc, src = m.correct_full("S", "s", np.array([3000.0, 8000.0]))
    assert np.allclose(t, [3020, 8070], atol=0.05)
    assert not unc.any() and src.tolist() == [0, 1]


def test_a_measured_run_the_box_contradicts_is_flagged():
    m = anchored(model(REF, U_RUNS), [("REF", "r", 7000.0, 3.0, "disagree")])
    _, unc = m.correct("REF", "r", np.array([5000.0]))
    assert unc.all() and m.runs[("REF", "r")].box_disagrees


def test_the_box_picks_an_ambiguous_masters_curve():
    """Two masters, two curves 50 s apart (the two-master example above): neither master can
    tell which is its own. An anchor e = -R_A(4600) = -20 at 4580 says M1's is curve A: then
    4580 -> 4600, no longer flagged."""
    ref = [
        *REF,
        ("REF2", "r2", 1200.0, 50.0),
        ("REF2", "r2", 4800.0, 75.0),
        ("REF2", "r2", 8400.0, 100.0),
    ]
    runs = [
        ("REF", "r", 900.0, 8300.0, False),
        ("REF2", "r2", 900.0, 8500.0, False),
        ("M1", "m1", 900.0, 8300.0, True),
        ("M2", "m2", 900.0, 8500.0, True),
    ]
    cfg = ClockConfig(reference_devices=("REF", "REF2"))
    m = model(ref, runs, cfg)
    assert m.runs[("M1", "m1")].uncertain
    m = anchored(m, [("M1", "m1", 4580.0, -20.0, "anchor")], cfg)
    t, unc = m.correct("M1", "m1", np.array([4580.0]))
    assert math.isclose(t[0], 4600.0, abs_tol=0.01) and not unc.any()
    assert m.runs[("M1", "m1")].curve == 0 and m.runs[("M2", "m2")].uncertain
