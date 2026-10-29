"""The EDA second pass's social-dose script (analysis A), on invented rows.

Hand-derived expectations for ties, exposure bins and per person-day slopes; an oracle on
synthetic minutes with a known dose effect, and the small-cell rule.
"""

import importlib.util
import sys
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import numpy as np
import polars as pl
import pytest

ANALYSES = Path(__file__).resolve().parents[1] / "studies" / "dsa-2026" / "analyses"


@pytest.fixture(scope="module")
def sd():
    sys.path.insert(0, str(ANALYSES))
    spec = importlib.util.spec_from_file_location("eda2_social_dose_script",
                                                  ANALYSES / "eda2_social_dose.py")  # fmt: skip
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


D1, D2 = date(2026, 8, 20), date(2026, 8, 21)


def bin_at(day: date, k: int) -> datetime:
    """The k-th 5-minute bin from 08:00 UTC on ``day``."""
    return datetime(day.year, day.month, day.day, 8, tzinfo=UTC) + timedelta(minutes=5 * k)


def pair_rows(a, b, day, bins, rssi):
    return [{"a": a, "b": b, "bin": bin_at(day, k), "day": day, "max_rssi": rssi} for k in bins]


def test_first_ties_need_twelve_close_bins(sd):
    pairs = pl.DataFrame(
        pair_rows("p:1", "p:2", D1, range(12), -60)  # tied on day 1
        + pair_rows("p:1", "p:3", D1, range(11), -60)  # one bin short
        + pair_rows("p:1", "p:3", D2, range(20), -70)  # heard, never close
        + pair_rows("p:1", "p:2", D2, range(12), -50)  # tied again later
    )
    t = sd.first_ties(pairs).sort("a", "b")
    assert t.to_dicts() == [{"a": "p:1", "b": "p:2", "first_tie": D1}]


def test_dose_level_bands(sd):
    df = pl.DataFrame({"c": [0, 0, 1, 2, 3, 4, 7, 8, 20], "h": [0, 3, 1, 2, 3, 4, 7, 8, 20]})
    got = df.select(sd.dose_level(pl.col("c"), pl.col("h"))).to_series().to_list()
    assert got == ["0", "heard only", "1", "2-3", "2-3", "4-7", "4-7", "8+", "8+"]


def test_exposure_bins_counts_and_shares(sd):
    # P is tied with Q on day 1 (familiar on day 2), not with R or S. Q and P share a course;
    # R is in another course; S has no course. X is not a partner (no beacon consent).
    tie = pair_rows("p:P", "p:Q", D1, range(12), -60)
    b0, b1, b2, b3 = (bin_at(D2, k) for k in range(4))
    day2 = [
        {"a": "p:P", "b": "p:Q", "bin": b0, "day": D2, "max_rssi": -60},
        {"a": "p:P", "b": "p:R", "bin": b0, "day": D2, "max_rssi": -64},
        {"a": "p:P", "b": "p:S", "bin": b0, "day": D2, "max_rssi": -65},
        {"a": "p:P", "b": "p:X", "bin": b0, "day": D2, "max_rssi": -50},
        {"a": "p:P", "b": "p:R", "bin": b1, "day": D2, "max_rssi": -75},  # heard only
        {"a": "p:P", "b": "p:R", "bin": b3, "day": D2, "max_rssi": -55},  # removed bin
    ]
    # P and R are tied on day 2 itself (later bins): not yet familiar on day 2.
    same_day = pair_rows("p:P", "p:R", D2, range(10, 22), -60)
    pairs = pl.DataFrame(tie + day2 + same_day)
    seen = pl.DataFrame({"entity": ["p:P"] * 4, "bin": [b0, b1, b2, b3], "day": [D2] * 4,
                         "phase": ["morning"] * 4})  # fmt: skip
    removed = pl.DataFrame({"entity": ["p:P"], "bin": [b3]})
    e = sd.exposure_bins(seen, pairs, removed, people={"p:P"}, partners={"p:P", "p:Q", "p:R",
                         "p:S"}, course={"p:P": "c1", "p:Q": "c1", "p:R": "c2"})  # fmt: skip
    assert e["bin"].to_list() == [b0, b1, b2]
    r0, r1, r2 = e.to_dicts()
    assert (r0["n_heard"], r0["n_close"], r0["n_familiar"]) == (3, 3, 1)
    assert (r0["n_course_known"], r0["n_other_course"]) == (2, 1)
    assert r0["dose_level"] == "2-3" and r0["log_dose"] == pytest.approx(np.log(4))
    assert r0["familiar_share"] == pytest.approx(1 / 3)
    assert r0["other_course_share"] == pytest.approx(1 / 2)
    assert r1["dose_level"] == "heard only" and r1["heard_only"] == 1.0
    assert r1["familiar_share"] is None and r1["other_course_share"] is None
    assert r2["dose_level"] == "0" and r2["n_heard"] == 0 and r2["heard_only"] == 0.0


def test_exposure_bins_unknown_own_course(sd):
    b0 = bin_at(D2, 0)
    pairs = pl.DataFrame([{"a": "p:P", "b": "p:Q", "bin": b0, "day": D2, "max_rssi": -60}])
    seen = pl.DataFrame({"entity": ["p:P"], "bin": [b0], "day": [D2], "phase": ["morning"]})
    removed = pl.DataFrame(schema={"entity": pl.String, "bin": pairs["bin"].dtype})
    e = sd.exposure_bins(seen, pairs, removed, people={"p:P"}, partners={"p:P", "p:Q"},
                         course={"p:Q": "c1"})  # fmt: skip
    assert e["n_course_known"][0] is None and e["other_course_share"][0] is None
    assert e["n_close"][0] == 1 and e["familiar_share"][0] == 0.0


def test_person_day_slopes(sd):
    x = [0.0, 1.0, 2.0, 3.0]
    d = pl.DataFrame({
        "entity": ["a"] * 4 + ["b"] * 4 + ["c"] * 2,
        "day": [D1] * 10,
        "log_dose": x + [1.0] * 4 + [0.0, 1.0],
        "y": [1 + 2 * v for v in x] + [0.5, 0.1, 0.2, 0.3] + [0.0, 1.0],
    })  # fmt: skip
    s = sd.person_day_slopes(d, "y").sort("entity")
    a, b, c = s.to_dicts()
    assert a["slope"] == pytest.approx(2.0) and a["se"] == pytest.approx(0.0, abs=1e-9)
    assert a["minutes"] == 4 and a["x_sd"] == pytest.approx(np.std(x, ddof=1))
    assert b["slope"] is None  # no variation in the exposure
    assert c["slope"] is None  # too few minutes


def test_with_verdicts(sd):
    key = {"clock": "all", "exposure": "dose slope", "term": "log_dose",
           "model": "movement + time"}  # fmt: skip
    rows = []
    for outcome, disc, rep in (("scr_main", (0.3, 0.1, 0.5), (0.2, 0.05, 0.35)),
                               ("tonic", (0.3, 0.1, 0.5), (-0.1, -0.3, 0.1)),
                               ("hr", (0.1, -0.1, 0.3), (0.2, 0.1, 0.3))):  # fmt: skip
        for half, (e, lo, hi) in (("discovery", disc), ("replication", rep), ("all", rep)):
            rows.append({**key, "outcome": outcome, "half": half, "estimate_sd": e, "lo": lo,
                         "hi": hi, "people": 10})  # fmt: skip
    est, wide = sd.with_verdicts(pl.DataFrame(rows))
    v = dict(wide.select("outcome", "verdict").iter_rows())
    assert v == {"scr_main": "replicates", "tonic": "does not replicate", "hr": "no lead"}
    assert est.filter(pl.col("outcome") == "tonic")["verdict"].unique().to_list() == [
        "does not replicate"
    ]


def synthetic_minutes(n_people: int, effect: float, seed: int = 0) -> pl.DataFrame:
    """Minutes of ``n_people`` over two days with a dose effect of ``effect`` SD per log(1+n)
    on the SCR rate (amp >= 0.2) and none on the others; movement is pure noise."""
    rng = np.random.default_rng(seed)
    rows = []
    levels = {0: "0", 1: "1", 2: "2-3", 3: "2-3", 5: "4-7", 9: "8+"}
    for p in range(n_people):
        for day in (D1, D2):
            start = datetime(day.year, day.month, day.day, 8, tzinfo=UTC)
            n = rng.choice(list(levels), size=240)
            for k in range(240):
                rows.append({"entity": f"person:{p}", "day": day,
                             "minute": start + timedelta(minutes=k), "wear_min": k,
                             "n_close": int(n[k]), "dose_level": levels[int(n[k])]})  # fmt: skip
    d = pl.DataFrame(rows)
    m = d.height
    log_dose = np.log1p(d["n_close"].to_numpy().astype(float))
    noise = {c: rng.normal(size=m) for c in ("a", "b", "t", "h", "mv", "hmv")}
    return d.with_columns(
        pl.lit(True).alias("usable"),
        pl.lit(True).alias("hr_ok"),
        pl.Series("log_dose", log_dose),
        pl.lit(0.0).alias("heard_only"),
        pl.when(pl.col("n_close") > 0).then(pl.lit(0.5)).alias("familiar_share"),
        pl.when(pl.col("n_close") > 0)
        .then(pl.Series(rng.uniform(size=m)))
        .alias("other_course_share"),
        pl.Series("z_pd_scr_amp02", effect * log_dose + noise["a"]),
        pl.Series("z_pd_scr_main", noise["b"]),
        pl.Series("z_pd_tonic", noise["t"]),
        pl.Series("z_pd_hr", noise["h"]),
        pl.Series("z_pd_motion", noise["mv"]),
        pl.Series("z_pd_motion2", noise["mv"] ** 2),
        pl.Series("z_pd_hr_motion", noise["hmv"]),
        pl.Series("z_pd_hr_motion2", noise["hmv"] ** 2),
        pl.lit("course block").alias("setting"),
    )


def test_dose_models_recover_a_known_slope(sd):
    rows = sd.dose_models(synthetic_minutes(8, effect=0.5))
    est = pl.DataFrame(rows)
    slope = est.filter((pl.col("exposure") == "dose slope") & (pl.col("model") == sd.MODELS[0]))
    got = dict(slope.select("outcome", "estimate_sd").iter_rows())
    lo = dict(slope.select("outcome", "lo").iter_rows())
    hi = dict(slope.select("outcome", "hi").iter_rows())
    assert got["scr_amp02"] == pytest.approx(0.5, abs=0.1)
    assert lo["scr_amp02"] < 0.5 < hi["scr_amp02"]
    for x in ("scr_main", "tonic", "hr"):
        assert abs(got[x]) < 0.1
    # A constant familiar share identifies nothing: withheld (no person-day where it varies).
    fam = est.filter(pl.col("exposure") == "familiar share")
    assert fam["suppressed"].all() and fam["estimate_sd"].is_null().all()
    # Every level against nobody heard, rising with the dose on the affected outcome.
    lv = est.filter((pl.col("exposure") == "dose level") & (pl.col("outcome") == "scr_amp02")
                    & (pl.col("model") == sd.MODELS[0]))  # fmt: skip
    by = dict(lv.select("term", "estimate_sd").iter_rows())
    assert by["1"] < by["2-3"] < by["4-7"] < by["8+"]
    assert by["heard only"] is None  # no heard-only minutes: nobody has it


def test_dose_models_withhold_small_groups(sd):
    est = pl.DataFrame(sd.dose_models(synthetic_minutes(4, effect=0.5)))
    assert est["suppressed"].all()
    assert est["estimate_sd"].is_null().all() and est["people"].is_null().all()
