"""Box co-motion anchors (eda.box) on hand-made clocks and motion, with known truth.

Times are small epoch seconds. Reference units REF, K and K2 keep time; their records say so
(the master keeps time too, so every offset is 0). U has no records; it truly loses 0.5 %
from its start at 1000 (true time T, device time tau = T - 0.005 (T - 1000)), while its
configured fallback rate is -20 s/h. From T = 7000 to 8200 every unit lies in the box and
sees the same bumps.
"""

import math
from dataclasses import replace

import numpy as np
import polars as pl

from social_energy.eda.box import (
    BoxConfig,
    BoxStretch,
    box_edges,
    find_stretches,
    leave_one_out,
    solve,
    solve_offsets,
)
from social_energy.eda.clock import RECORDS_SCHEMA, RUNS_SCHEMA, ClockConfig, ClockModel

HZ = 64.0
RATE_U = -0.005
# U's rate is truly constant here, so a box anchor is trusted up to 30 s/h of drift (by
# default only 1 s/h: real drifting clocks change rate within a day).
CFG = ClockConfig(
    reference_devices=("REF", "K", "K2"),
    fallback_rates_s_per_h={"U": -20.0},
    min_span_s=600,
    box_drift_limit_s_per_h=30.0,
)
BOX = BoxConfig(window_s=120.0, max_lag_s=40.0, min_stretch_s=300.0)
RUNS = [
    ("REF", "r", 900.0, 8300.0, False),
    ("K", "k", 900.0, 8300.0, False),
    ("K2", "k2", 900.0, 8300.0, False),
    ("U", "u", 1000.0, 8200.0, False),
]
BURSTS = np.sort(np.random.default_rng(5).uniform(7000, 8200, 1200))


def records(devices=("REF", "K", "K2")):
    run = {"REF": "r", "K": "k", "K2": "k2"}
    return [(d, run[d], t, 0.0) for d in devices for t in (1000.0, 4600.0, 8200.0)]


def frame(rows, schema):
    return pl.DataFrame(rows, schema=schema, orient="row")


def u_error(true_t):
    return RATE_U * (np.asarray(true_t, float) - 1000.0)


def stretch(device, run, error=lambda T: 0.0 * T, late_s=0.0):
    """Jerk spikes at the bursts, on the device's own clock (device = true + error); its
    motion shows ``late_s`` later than its clock says, as if it had been bumped late."""
    T = BURSTS + late_s
    tau = T + error(T)
    t0 = 6990.0 + float(error(np.array([6990.0]))[0])
    n = int((8200 - 6990) * HZ)
    g = np.zeros(n, np.float32)
    i = np.rint((tau - t0) * HZ).astype(int)
    g[i[(i >= 0) & (i < n)]] = 1.0
    return BoxStretch(device, run, "tail", t0, HZ, g)


def u_tau(T):
    return T + u_error(T)


def setup(devices=("REF", "K", "K2"), late=None):
    late = late or {}
    run = {"REF": "r", "K": "k", "K2": "k2"}
    model = ClockModel(frame(records(), RECORDS_SCHEMA), frame(RUNS, RUNS_SCHEMA), CFG)
    st = [stretch(d, run[d], late_s=late.get(d, 0.0)) for d in devices]
    st.append(stretch("U", "u", u_error))
    return model, st


def test_find_stretches_takes_the_off_skin_ends_of_a_run():
    """A run of 3000 s at 128 Hz, on skin 1000-2000 s, with a 30-s touch at 500 s (handling,
    not wear): the head stretch is 0-1000 s and the tail 2000-3000 s, on 64-Hz grids."""
    t = np.arange(0, 3000, 1 / 128)
    us = np.where((t >= 1000) & (t < 2000), 2.0, 0.01)
    us[(t >= 500) & (t < 530)] = 2.0
    acc = np.zeros((len(t), 3))
    got = find_stretches("A", "a", t, us, acc, np.zeros(len(t), bool), BOX)
    assert [(s.position, s.t0, len(s.jerk)) for s in got] == [
        ("head", 0.0, 1000 * 64),
        ("tail", 2000.0, 1000 * 64),
    ]


def test_solve_offsets_drops_a_pair_that_does_not_close():
    """Truth: A 0, B 0.2 (both measured), C 5, D -3. Pairs (lag = r_b - r_a): A-B 0.2,
    A-C 5, B-C 4.8, C-D -8, A-D -3, and a wrong B-D +7 (true -3.2), which is dropped. The
    zero is the mean of A and B (both within 1 s of their median), so A -0.1, B 0.1, C 4.9,
    D -3.1; C and D sit in closed triangles, so both are anchors."""
    pairs = [(0, 1, 0.2), (0, 2, 5.0), (1, 2, 4.8), (2, 3, -8.0), (0, 3, -3.0), (1, 3, 7.0)]
    sol = solve_offsets(4, pairs, [True, True, False, False], 0.25, 1.0)
    assert sol["kept"] == [0, 1, 2, 3, 4]
    assert np.allclose(sol["residual"], [-0.1, 0.1, 4.9, -3.1], atol=1e-9)
    assert sol["status"].tolist() == ["check", "check", "anchor", "anchor"]


def test_the_reference_units_set_the_zero():
    """Two reference units (0, 1) at 1.3, two other measured units (2, 3) at 0 and 0.1, an
    unmeasured one (4) at 5.3. The references define time: zero = 1.3, so 2 and 3 are 1.3
    and 1.2 s off (disagree) and 4 is at +4.0. A zero from all four (median 0.7) would pass
    everyone."""
    pairs = [
        (0, 1, 0.0),
        (0, 2, -1.3),
        (1, 2, -1.3),
        (2, 3, 0.1),
        (1, 3, -1.2),
        (0, 4, 4.0),
        (1, 4, 4.0),
    ]
    known = [True, True, True, True, False]
    sol = solve_offsets(5, pairs, known, 0.25, 1.0, [True, True, False, False, False])
    assert np.allclose(sol["residual"], [0, 0, -1.3, -1.2, 4.0], atol=1e-9)
    assert sol["status"].tolist() == ["check", "check", "disagree", "disagree", "anchor"]
    sol = solve_offsets(5, pairs, known, 0.25, 1.0)
    assert set(sol["status"][:4]) == {"check"}


def test_a_unit_on_one_pair_only_gets_no_anchor():
    """U paired with A only: no triangle closes, so the box cannot check it."""
    sol = solve_offsets(2, [(0, 1, 3.0)], [True, False], 0.25, 1.0)
    assert sol["status"].tolist() == ["check", "unchecked"]


def test_the_box_anchors_a_fallback_unit_to_its_true_clock():
    """U's anchor sits near T = 7600 (the middle of the box). There its true error is
    -0.005 x 6600 = -33 s, while the fallback (-20 s/h from 1000) says about -36.5 s. With
    the anchor and the re-set at its start, U's error is a line through (1000, 0) and the
    anchor, the truth exactly: at T = 4000 (tau = 3985) the corrected time is 4000."""
    model, st = setup()
    edges = box_edges(model, st, BOX)
    assert edges.height == 6  # every pair of the four units
    nodes = solve(edges, model, BOX)
    u = nodes.filter(device="U").row(0, named=True)
    assert u["status"] == "anchor" and not u["known"]
    T = 7600.0
    tau = u["tau"]
    true_T = (tau - 5.0) / 0.995  # tau = 0.995 T + 5
    assert abs(true_T - T) < 60
    assert abs(u["error_s"] - u_error(true_T)) < 0.05
    assert set(nodes.filter(pl.col("device") != "U")["status"]) == {"check"}
    anchored = ClockModel(model.records, model.runs_table, CFG, anchors=nodes)
    rc = anchored.runs[("U", "u")]
    assert rc.kind == "box" and rc.anchors == 1 and not rc.uncertain
    t, unc, src = anchored.correct_full("U", "u", np.array([u_tau(4000.0), u_tau(8100.0)]))
    assert np.allclose(t, [4000.0, 8100.0], atol=0.1)
    assert not unc.any() and src.tolist() == [1, 1]
    # Without the box, the fallback is 4 s off by the evening.
    t0, unc0 = model.correct("U", "u", np.array([u_tau(8100.0)]))
    assert abs(t0[0] - 8100.0) > 3.0 and unc0.all()
    # Under the default drift limit, the same correction stays flagged.
    strict = replace(CFG, box_drift_limit_s_per_h=1.0)
    t, unc, src = ClockModel(model.records, model.runs_table, strict, anchors=nodes).correct_full(
        "U", "u", np.array([u_tau(4000.0)])
    )
    assert abs(t[0] - 4000.0) < 0.1 and unc.all() and src.tolist() == [1]


def test_a_measured_clock_the_box_contradicts_is_flagged():
    """K's motion shows 3 s late although its records say its clock is right: against the
    median of REF, K and K2 it is 3 s off, a disagreement, and its run is flagged. U is still
    anchored by the others."""
    model, st = setup(late={"K": 3.0})
    nodes = solve(box_edges(model, st, BOX), model, BOX)
    status = dict(zip(nodes["device"], nodes["status"], strict=True))
    assert status == {"REF": "check", "K": "disagree", "K2": "check", "U": "anchor"}
    k = nodes.filter(device="K")["residual_s"].item()
    assert math.isclose(k, 3.0, abs_tol=0.05)
    anchored = ClockModel(model.records, model.runs_table, CFG, anchors=nodes)
    assert anchored.runs[("K", "k")].uncertain and anchored.runs[("K", "k")].box_disagrees
    assert not anchored.runs[("REF", "r")].uncertain


def test_without_a_triangle_the_fallback_stays():
    """Only REF and U lay together: one pair, no check, U keeps its flagged fallback."""
    model, st = setup(devices=("REF",))
    nodes = solve(box_edges(model, st, BOX), model, BOX)
    assert nodes.filter(device="U")["status"].item() == "unchecked"
    anchored = ClockModel(model.records, model.runs_table, CFG, anchors=nodes)
    assert anchored.runs[("U", "u")].kind == "rate" and anchored.runs[("U", "u")].uncertain


def test_leave_one_out_recovers_a_measured_run_from_the_box():
    """Give U sync records with its true error (offset = error, the master keeps time) at
    T = 2000, 5000, 8000. Leaving them out, the box anchors U to within 0.1 s of the model
    with records over the whole run, where the fallback is ~3.5 s off by the evening."""
    _, st = setup()
    T = np.array([2000.0, 5000.0, 8000.0])
    u_rec = [("U", "u", float(u_tau(x)), float(u_error(x))) for x in T]
    rec = frame(records() + u_rec, RECORDS_SCHEMA)
    runs = frame(RUNS, RUNS_SCHEMA)
    full = ClockModel(rec, runs, CFG)
    assert full.runs[("U", "u")].kind == "sync"
    edges = box_edges(full, st, BOX)
    loo = leave_one_out(rec, runs, edges, CFG, BOX)
    u = loo.filter(device="U").row(0, named=True)
    assert u["anchors"] == 1 and u["kind"] == "box"
    assert u["box_max_abs_s"] < 0.1 and u["fallback_max_abs_s"] > 3.0
    assert u["uncertain_share"] == 0.0
