"""The DSA 2026 EDA second pass, analysis C (pair synchrony), on invented rows.

Hand-derived expectations for the pair-day sums, the tie history and the verdict wiring; oracle
tests for the models on synthetic pair-days with a known effect and without it.
"""

import importlib.util
import math
import sys
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import numpy as np
import polars as pl
import pytest

ANALYSES = Path(__file__).resolve().parents[1] / "studies" / "dsa-2026" / "analyses"


@pytest.fixture(scope="module")
def ps():
    sys.path.insert(0, str(ANALYSES))
    spec = importlib.util.spec_from_file_location("eda2_pair_sync_script",
                                                  ANALYSES / "eda2_pair_sync.py")  # fmt: skip
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    yield module
    sys.modules.pop(spec.name, None)


def minute(k: int) -> datetime:
    """Minutes from 10:00 UTC on 15 Aug (noon local, a discovery day)."""
    return datetime(2026, 8, 15, 10, 0, tzinfo=UTC) + timedelta(minutes=k)


def signals(n: int, va: list[float], vb: list[float]) -> pl.DataFrame:
    rows = []
    for e, v in (("person:a", va), ("person:b", vb)):
        for k in range(n):
            t = minute(k)
            rows.append({"entity": e, "day": date(2026, 8, 15), "minute": t,
                         "bin": t.replace(minute=t.minute - t.minute % 5), "s_key": 1.0,
                         "s_x": v[k]})  # fmt: skip
    return pl.DataFrame(rows)


def test_pair_day_sums_split_close_and_common(ps):
    # 40 common minutes; the first 20 (bins 10:00-10:15) are close, the rest heard.
    n = 40
    va = [1.0] * n
    vb = [2.0] * 20 + [-1.0] * 20
    sig = signals(n, va, vb)
    close_bins = [minute(k) for k in range(0, 20, 5)]
    other_bins = [minute(k) for k in range(20, 40, 5)]
    pairs = pl.DataFrame({"a": "person:a", "b": "person:b", "bin": close_bins + other_bins,
                          "max_rssi": [-60] * 4 + [-80] * 4})  # fmt: skip
    seen = pl.DataFrame({"entity": ["person:a"], "bin": [minute(0)]})
    s = ps.pair_day_sums(sig, pairs, seen, key="s_key", values=["s_x"])
    assert s.height == 1
    r = s.row(0, named=True)
    assert (r["n_close_s_x"], r["n_common_s_x"]) == (20, 40)
    assert r["sum_close_s_x"] == pytest.approx(40.0)
    assert r["sum_common_s_x"] == pytest.approx(20.0)
    d = ps.pair_days(s, "s_x")
    assert d["sync_close"][0] == pytest.approx(2.0)
    assert d["sync_common"][0] == pytest.approx(0.5)
    # One close minute fewer than MIN_CLOSE: the pair-day does not enter.
    short = s.with_columns(pl.col("n_close_s_x") - 1)
    assert ps.pair_days(short, "s_x").height == 0


def test_pair_day_sums_count_only_minutes_with_both_values(ps):
    n = 40
    va = [1.0] * n
    vb = [None] * 5 + [1.0] * 35
    s = ps.pair_day_sums(signals(n, va, vb), pl.DataFrame({"a": ["person:a"], "b": ["person:b"],
                         "bin": [minute(0)], "max_rssi": [-50]}),
                         pl.DataFrame({"entity": ["person:a"], "bin": [minute(0)]}),
                         key="s_key", values=["s_x"])  # fmt: skip
    r = s.row(0, named=True)
    assert r["n_common_s_x"] == 35
    assert r["n_close_s_x"] == 0  # the only close bin's minutes lack b's value


def test_tie_history(ps):
    d = date(2026, 8, 20)
    keys = pl.DataFrame({"a": ["p:1", "p:1", "p:3", "p:1"], "b": ["p:2", "p:2", "p:4", "p:2"],
                         "day": [d, d + timedelta(1), d, date(2026, 8, 26)],
                         "signal": ["x", "x", "x", "x"]})  # fmt: skip
    ties = pl.DataFrame({"a": ["p:1", "p:1", "p:3"], "b": ["p:2", "p:2", "p:4"],
                         "day": [d - timedelta(2), d + timedelta(3), d]})  # fmt: skip
    h = ps.tie_history(keys, ties).sort("a", "day")
    rows = h.select("a", "day", "prior_tie", "tied_later", "has_follow").rows()
    assert rows == [
        ("p:1", d, True, True, True),  # tied 2 days before and 3 days after
        ("p:1", d + timedelta(1), True, True, True),  # tie 2 days later
        ("p:1", date(2026, 8, 26), True, False, False),  # follow-up passes 28 Aug
        ("p:3", d, False, False, True),  # tied that same day only: neither before nor after
    ]


def test_survey_distances_in_sds(ps):
    mem = pl.DataFrame({"entity": ["p:1", "p:2", "p:3"], "trust": [0.0, 1.0, 3.0],
                        "lust": [0.0, 0.0, 2.0]})  # fmt: skip
    d, sds = ps.survey_distances(mem)
    raw = np.array([1.0, 3.0, 2.0])  # 1-2, 1-3, 2-3
    assert sds["trust"] == pytest.approx(np.std(raw, ddof=1))
    assert d["d_trust"].to_list() == pytest.approx((raw / np.std(raw, ddof=1)).tolist())
    assert d.select("a", "b").rows() == [("p:1", "p:2"), ("p:1", "p:3"), ("p:2", "p:3")]


def test_wls_and_logit_recover_known_coefficients(ps):
    rng = np.random.default_rng(0)
    x = rng.normal(size=4000)
    X = np.column_stack([np.ones_like(x), x])
    assert ps.wls(2 + 0.5 * x, X) == pytest.approx([2, 0.5])
    y = (rng.random(4000) < 1 / (1 + np.exp(-(-0.5 + 1.2 * x)))).astype(float)
    assert ps.logit(y, X) == pytest.approx([-0.5, 1.2], abs=0.15)
    # Weights equal to repeated rows.
    w = rng.integers(0, 3, 4000).astype(float)
    rep = np.repeat(np.arange(4000), w.astype(int))
    assert ps.logit(y, X, w) == pytest.approx(ps.logit(y[rep], X[rep]), abs=1e-6)
    # Complete separation and a rank-deficient design give NaN, not a number.
    assert np.isnan(ps.logit((x > 0).astype(float), X)).all()
    assert np.isnan(ps.wls(x, np.column_stack([x, 2 * x]))).all()


def synthetic_pair_days(n_people=24, per_pair=1, effect=0.0, tie_effect=0.0, seed=1):
    """Pair-days among invented people: synchrony rises by ``effect`` with same course; tied
    later depends on synchrony with log-odds ``tie_effect`` per SD."""
    rng = np.random.default_rng(seed)
    people = [f"person:{k:02d}" for k in range(n_people)]
    course = {p: k % 2 for k, p in enumerate(people)}
    rows = []
    for i in range(n_people):
        for j in range(i + 1, n_people):
            if rng.random() > 0.35:
                continue
            for _ in range(per_pair):
                same = course[people[i]] == course[people[j]]
                sync = 0.05 + effect * same + rng.normal(0, 0.1)
                z = (sync - 0.05) / 0.1
                p = 1 / (1 + math.exp(-(0.3 + tie_effect * z)))
                rows.append({"a": people[i], "b": people[j], "day": date(2026, 8, 15),
                             "sync_close": sync, "sync_common": sync / 2,
                             "same_course": same, "prior_tie": bool(rng.random() < 0.5),
                             "d_trust": abs(rng.normal()), "d_lust": abs(rng.normal()),
                             "log_close_minutes": math.log(20 + rng.integers(0, 200)),
                             "tied_later": bool(rng.random() < p), "has_follow": True})  # fmt: skip
    return pl.DataFrame(rows)


def _row(rows, model, term):
    return next(r for r in rows if r["model"] == model and r["term"] == term)


def test_determinants_find_a_planted_same_course_effect(ps):
    with_effect = ps.determinants(synthetic_pair_days(effect=0.2), "close", n_boot=200)
    r = _row(with_effect, "course + prior tie", "same_course")
    assert r["estimate"] == pytest.approx(0.2, abs=0.05) and r["lo"] > 0
    without = ps.determinants(synthetic_pair_days(effect=0.0), "close", n_boot=200)
    r = _row(without, "course + prior tie", "same_course")
    assert r["lo"] < 0 < r["hi"]
    assert _row(without, "mean", "const")["estimate"] == pytest.approx(0.05, abs=0.03)
    # The reference level's mean of the other models is not reported as a determinant.
    assert not any(r["term"] == "const" and r["model"] != "mean" for r in without)


def test_consequence_finds_a_planted_sync_effect(ps):
    with_effect = ps.consequence(synthetic_pair_days(tie_effect=1.5, per_pair=3), "close",
                                 n_boot=100)  # fmt: skip
    r = _row(with_effect, "logit tied later", "sync_z")
    assert r["estimate"] > 0.8 and r["lo"] > 0
    without = ps.consequence(synthetic_pair_days(tie_effect=0.0, per_pair=3), "close", n_boot=100)
    r = _row(without, "logit tied later", "sync_z")
    assert r["lo"] < 0 < r["hi"]


def test_consequence_withholds_and_holds_fixed(ps):
    d = synthetic_pair_days(per_pair=2)
    # Pair-days without a follow-up window never enter.
    gone = ps.consequence(d.with_columns(pl.lit(False).alias("has_follow")), "close", n_boot=20)
    assert all(r["withheld"] for r in gone) and gone[0]["pair_days"] == 0
    # A control level resting on one pair is held fixed by restriction.
    first = (pl.col("a") == d["a"][0]) & (pl.col("b") == d["b"][0])
    one = d.with_columns(first.alias("prior_tie"))
    rows = ps.consequence(one, "close", n_boot=20)
    r = _row(rows, "logit tied later", "sync_z")
    assert r["held_by_restriction"] == "prior_tie=true"
    assert r["pair_days"] == d.height - 2
    assert not any(x["term"] == "prior_tie" for x in rows)
    # Fewer than MIN_GROUP people not tied later: withheld.
    tied = d.with_columns(pl.lit(True).alias("tied_later"))
    assert _row(ps.consequence(tied, "close", n_boot=20), "logit tied later", "sync_z")["withheld"]


def test_verdicts_come_from_the_halves(ps):
    base = {"analysis": "consequence", "signal": "dtonic", "minutes": "close",
            "model": "m", "term": "sync_z"}  # fmt: skip
    rows = []
    for clock, rep in (("all", (0.4, 0.1, 0.7)), ("certain", (-0.2, -0.5, 0.1))):
        for half, (e, lo, hi) in (("discovery", (0.5, 0.2, 0.8)), ("replication", rep),
                                  ("all", (0.45, 0.2, 0.7))):  # fmt: skip
            rows.append(base | {"clock": clock, "half": half, "estimate": e, "lo": lo, "hi": hi})
    v = ps.with_verdicts(pl.DataFrame(rows))
    assert set(v["verdict"]) == {"replicates"}
    assert set(v["verdict_certain"]) == {"does not replicate"}
    assert v.height == len(rows)


def test_person_sync_means_over_each_persons_pair_days(ps):
    pd_ = pl.DataFrame({
        "signal": ["dtonic", "dtonic", "scr_amp02", "hr"],
        "half": ["discovery", "replication", "discovery", "discovery"],
        "a": ["p:1", "p:1", "p:1", "p:1"], "b": ["p:2", "p:3", "p:2", "p:2"],
        "sync_close": [0.2, 0.4, 0.1, 9.0],
    })  # fmt: skip
    out = ps.person_sync(pd_)
    p1 = {r["half"]: r for r in out.filter(pl.col("entity") == "p:1").iter_rows(named=True)}
    assert p1["all"]["sync_dtonic_close"] == pytest.approx(0.3)
    assert p1["all"]["n_pair_days_dtonic"] == 2
    assert p1["discovery"]["sync_scr_amp02_close"] == pytest.approx(0.1)
    assert p1["replication"]["n_pair_days_scr_amp02"] == 0
    p3 = out.filter(pl.col("entity") == "p:3").row(0, named=True)
    assert (p3["half"], p3["sync_dtonic_close"]) == ("all", pytest.approx(0.4))
    assert out.filter(pl.col("entity") == "p:3").height == 2  # all and replication


def test_determinants_hold_a_sparse_level_fixed(ps):
    d = synthetic_pair_days(per_pair=2)
    first = (pl.col("a") == d["a"][0]) & (pl.col("b") == d["b"][0])
    # Prior tie and same course identical on all but one pair: collinear unless held fixed.
    rare = d.with_columns(first.alias("prior_tie"), first.alias("same_course"))
    rows = ps.determinants(rare, "close", n_boot=50)
    r = _row(rows, "survey", "d_trust")
    assert r["held_by_restriction"] == "same_course=true"  # which also removes prior_tie=true
    assert r["pair_days"] == d.height - 2 and math.isfinite(r["estimate"])
    assert _row(rows, "survey", "prior_tie")["withheld"]
    assert not any(x["term"] == "prior_tie" and not x["withheld"] for x in rows)
