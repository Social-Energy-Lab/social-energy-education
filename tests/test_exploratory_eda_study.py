"""The DSA 2026 exploratory EDA script's own wiring, on invented rows.

Hand-derived expectations for the minute measures and the pair-minute labels; oracle tests on
synthetic signals with a known effect (an SCR burst after presses, a setting shift, a shared
component between close pairs) and on the same signals without it.
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
def ee():
    sys.path.insert(0, str(ANALYSES))
    spec = importlib.util.spec_from_file_location("exploratory_eda_script",
                                                  ANALYSES / "exploratory_eda.py")  # fmt: skip
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def utc(d: int, h: int, m: int, s: float = 0) -> datetime:
    return datetime(2026, 8, d, h, m, tzinfo=UTC) + timedelta(seconds=s)


def pm_row(device, minute, *, worn=60, artifact=0, cond=1.0, motion=0.05, n=0, amp=0.0,
           excluded=False, entity="person:1"):  # fmt: skip
    return {"entity": entity, "minute": minute, "device": device, "worn_s": worn,
            "artifact_s": artifact, "conductance_us": cond, "motion_sd_g": motion, "scr_n": n,
            "scr_amp_us": amp, "excluded": excluded}  # fmt: skip


PM_SCHEMA = {"worn_s": pl.UInt32, "artifact_s": pl.UInt32, "conductance_us": pl.Float32,
             "motion_sd_g": pl.Float32}  # fmt: skip


def test_scr_counts_apply_flags_and_amplitude(ee):
    scr = pl.DataFrame(
        {
            "device": ["D1"] * 5,
            "onset": [utc(20, 8, 0, 5), utc(20, 8, 0, 40), utc(20, 8, 0, 50), utc(20, 8, 1, 2),
                      utc(20, 8, 1, 3)],
            "amplitude_us": [0.1, 0.3, 0.5, 0.25, 0.9],
            "artifact": [False, False, True, False, False],
            "ok": [True, True, True, True, False],
            "worn": [True, True, True, True, True],
        }
    )  # fmt: skip
    main = ee.scr_counts(scr.lazy(), 0.0).sort("minute")
    # 08:00: 0.1 and 0.3 (0.5 has an artifact); 08:01: 0.25 (0.9 is not ok).
    assert main["n"].to_list() == [2, 1]
    assert main["amp"].to_list() == pytest.approx([0.4, 0.25])
    big = ee.scr_counts(scr.lazy(), 0.2).sort("minute")
    assert big["n"].to_list() == [1, 1]
    assert big["amp"].to_list() == pytest.approx([0.3, 0.25])


def test_build_minutes_measures(ee):
    m0, m1, m2, m3 = (utc(20, 8, i) for i in range(4))
    pm = pl.DataFrame(
        [
            pm_row("D1", m0, cond=math.e, motion=math.exp(-3), n=6, amp=1.2),
            pm_row("D1", m1, worn=40, artifact=20, n=1, amp=0.1),  # 20 clean s: not usable
            pm_row("D1", m2, worn=60, artifact=30, n=3, amp=0.6),  # 30 clean s: usable
            pm_row("D1", m3, excluded=True),
        ],
        schema_overrides=PM_SCHEMA,
    )
    counts = {
        "main": pl.DataFrame({"device": ["D1", "D1", "D1"], "minute": [m0, m1, m2],
                              "n": [6, 1, 3], "amp": [1.2, 0.1, 0.6]}),
        "amp02": pl.DataFrame({"device": ["D1"], "minute": [m0], "n": [2], "amp": [0.8]}),
    }  # fmt: skip
    m = ee.build_minutes(pm, counts)
    assert m.height == 3  # the excluded minute is gone
    assert m["usable"].to_list() == [True, False, True]
    assert m["scr_main"].to_list() == pytest.approx([6.0, None, 6.0], nan_ok=True)  # 3 in 30 s
    assert m["scr_amp02"].to_list()[0] == 2.0 and m["scr_amp02"].to_list()[2] == 0.0
    assert m["amp_main"][0] == pytest.approx(math.log(0.2))
    assert m["amp_amp02"][0] == pytest.approx(math.log(0.4))
    assert m["amp_amp02"][2] is None  # no SCR of 0.2 µS in that minute
    assert m["tonic"][0] == pytest.approx(1.0)
    assert m["motion"][0] == pytest.approx(-3.0, abs=1e-5)
    assert m["scr_main"][1] is None and m["tonic"][1] is None
    # 08:00 UTC is 10:00 in Berlin: camp day 20 Aug, morning.
    assert m["day"][0] == date(2026, 8, 20) and m["phase"][0] == "morning"
    assert m["wear_min"].to_list() == [0, 1, 2]


# --- oracle: an SCR burst after presses -----------------------------------------------------------


def synthetic_camp(ee, *, burst: float, seed: int = 7, n_people: int = 8):
    """People x 2 days x 300 minutes of SCR counts; ``burst`` extra SCRs per minute at presses
    (minutes 0 to +2). Motion is pure noise. Returns minutes (standardised) and presses."""
    rng = np.random.default_rng(seed)
    pm, cm, c2, presses = [], [], [], []
    for i in range(n_people):
        dev, ent = f"D{i}", f"person:{i}"
        for d in (20, 21):
            start = utc(d, 7, 0)
            t_press = sorted(rng.choice(np.arange(30, 270), 4, replace=False).tolist())
            boost = np.zeros(300)
            for tp in t_press:
                boost[tp : tp + 3] = burst
                presses.append({"entity": ent, "t": start + timedelta(minutes=tp, seconds=20)})
            lam = 5 + boost
            n = rng.poisson(lam)
            n2 = rng.binomial(n, 0.5)
            for k in range(300):
                mt = start + timedelta(minutes=k)
                pm.append(pm_row(dev, mt, entity=ent, cond=float(np.exp(rng.normal(1 + i, 0.1))),
                                 motion=float(np.exp(rng.normal(-3, 0.5))), n=int(n[k]),
                                 amp=0.3 * int(n[k]) * float(rng.uniform(0.5, 1.5))))  # fmt: skip
                cm.append(
                    {"device": dev, "minute": mt, "n": int(n[k]), "amp": pm[-1]["scr_amp_us"]}
                )
                c2.append({"device": dev, "minute": mt, "n": int(n2[k]), "amp": 0.4 * int(n2[k])})
    m = ee.standardise(ee.build_minutes(
        pl.DataFrame(pm, schema_overrides=PM_SCHEMA),
        {"main": pl.DataFrame(cm), "amp02": pl.DataFrame(c2)},
    ))  # fmt: skip
    p = pl.DataFrame(presses).with_columns(
        ee.cp.camp_day_expr(pl.col("t")).alias("day"),
        pl.col("t").alias("minute"),
        pl.lit(False).alias("cascade"),
    )
    return m, p


def _row(res, column, window, null="person-day"):
    rows = [r for r in res["rows"] if r["column"] == column and r.get("window") == window
            and r["null"] == null and r["presses"] == "all"]  # fmt: skip
    assert len(rows) == 1
    return rows[0]


def test_press_profile_finds_a_burst_and_not_a_missing_one(ee, monkeypatch):
    monkeypatch.setattr(ee, "N_SHUFFLE", 150)
    monkeypatch.setattr(ee, "N_BOOT", 300)
    m, p = synthetic_camp(ee, burst=4.0)
    res = ee.press_analysis(m, p)
    assert res["qa"]["presses_eligible"] == p.height == 64
    for col in ("r_pd_scr_main", "r_pd_scr_amp02", "raw_scr_main"):
        r = _row(res, col, "at_minus_before")
        assert r["observed"] > r["null_hi"], col
        assert r["person_lo"] > 0, col
        r = _row(res, col, "at_minus_before", null="person-day-phase")
        assert r["observed"] > r["null_hi"], col
    # Raw rate: about 4 extra SCRs in two of the three "at" minutes -> excess near 2.7.
    assert _row(res, "raw_scr_main", "at")["excess"] == pytest.approx(8 / 3, abs=0.8)
    # Tonic level and movement carry no burst.
    for col in ("r_pd_tonic", "z_pd_motion"):
        r = _row(res, col, "at_minus_before")
        assert r["null_lo"] - 0.05 <= r["observed"] <= r["null_hi"] + 0.05, col
    # The cascade subset is empty, so it is withheld.
    assert all(r["suppressed"] for r in res["rows"] if r["presses"] == "cascade")

    m0, p0 = synthetic_camp(ee, burst=0.0)
    res0 = ee.press_analysis(m0, p0)
    r = _row(res0, "r_pd_scr_main", "at_minus_before")
    assert r["null_lo"] - 0.05 <= r["observed"] <= r["null_hi"] + 0.05


# --- oracle: a setting that raises SCR within person-day -----------------------------------------


def test_fe_contrasts_recover_a_setting_shift(ee):
    rng = np.random.default_rng(3)
    rows = []
    for i in range(10):
        for d in range(3):
            level = rng.normal()
            for k in range(120):
                setting = "plenum" if k < 40 else "course block"
                motion = rng.normal()
                y = level + (0.5 if setting == "plenum" else 0.0) + 0.3 * motion + rng.normal()
                rows.append({"entity": f"p{i}", "day": date(2026, 8, 20 + d), "setting": setting,
                             "z_pd_scr_main": y, "z_pd_motion": motion,
                             "z_pd_motion2": motion**2})  # fmt: skip
    df = pl.DataFrame(rows)
    out = ee.fe_contrasts(df, category="setting", reference="course block",
                          measures=["scr_main"], label="setting")  # fmt: skip
    adj = next(r for r in out if r["adjustment"] == "movement")
    assert adj["level"] == "plenum" and adj["people"] == 10
    assert adj["lo"] < 0.5 < adj["hi"]
    assert adj["estimate_sd"] == pytest.approx(0.5, abs=0.12)
    few = ee.fe_contrasts(
        df.filter(pl.col("entity").is_in(["p0", "p1"])),
        category="setting",
        reference="course block",
        measures=["scr_main"],
        label="setting",
    )
    assert all(r["suppressed"] and r["estimate_sd"] is None for r in few)


# --- pair-minute labels and the synchrony oracle -------------------------------------------------


def test_pair_minutes_labels(ee, monkeypatch):
    monkeypatch.setattr(ee, "SYNC_MIN_OVERLAP", 3)
    minutes = [utc(20, 8, 0), utc(20, 8, 5), utc(20, 8, 10), utc(20, 8, 15)]
    sig = pl.DataFrame(
        {
            "entity": ["person:a"] * 4 + ["person:b"] * 4 + ["person:c"] * 2,
            "day": [date(2026, 8, 20)] * 10,
            "minute": minutes * 2 + minutes[:2],
            "bin": minutes * 2 + minutes[:2],
            **{f"s_{k}": [0.0] * 10 for k in ee.SYNC_SIGNALS},
        }
    )
    pairs = pl.DataFrame({"a": ["person:a", "person:a"], "b": ["person:b", "person:b"],
                          "bin": [minutes[0], minutes[1]], "max_rssi": [-60, -75]})  # fmt: skip
    seen = pl.DataFrame({"entity": ["person:a", "person:b", "person:a"],
                         "bin": [minutes[2], minutes[2], minutes[3]]})  # fmt: skip
    pm_ = ee.pair_minutes(sig, pairs, seen).sort("minute")
    # a-c and b-c share only two minutes: below the overlap minimum.
    assert set(zip(pm_["a"], pm_["b"], strict=True)) == {("person:a", "person:b")}
    assert pm_["label"].to_list() == ["close", "heard", "apart", "unknown"]


def test_synchrony_finds_shared_signal_only_when_close(ee, monkeypatch):
    monkeypatch.setattr(ee, "N_BOOT", 200)
    rng = np.random.default_rng(11)
    n_min, people = 240, [f"person:{i}" for i in range(8)]
    start = utc(20, 7, 0)
    minutes = [start + timedelta(minutes=k) for k in range(n_min)]
    bins = [mt - timedelta(minutes=mt.minute % 5) for mt in minutes]
    close_half = np.arange(n_min) < n_min // 2
    shared = {p: rng.normal(size=n_min) for p in people[::2]}  # one factor per couple
    rows = []
    for i, p in enumerate(people):
        f = shared[people[i - i % 2]]
        x = rng.normal(size=n_min) + np.where(close_half, 1.0, 0.0) * f
        x = (x - x.mean()) / x.std()
        rows += [{"entity": p, "day": date(2026, 8, 20), "minute": mt, "bin": b,
                  **{f"s_{k}": float(x[j]) for k in ee.SYNC_SIGNALS}}
                 for j, (mt, b) in enumerate(zip(minutes, bins, strict=True))]  # fmt: skip
    sig = pl.DataFrame(rows)
    couple_bins = sorted(set(b for b, c in zip(bins, close_half, strict=True) if c))
    pairs = pl.DataFrame([{"a": people[i], "b": people[i + 1], "bin": b, "max_rssi": -55}
                          for i in range(0, 8, 2) for b in couple_bins])  # fmt: skip
    seen = pl.DataFrame([{"entity": p, "bin": b} for p in people for b in set(bins)])
    pm_ = ee.pair_minutes(sig, pairs, seen)
    res = ee.synchrony(sig, pm_)["rows"]
    close = res.filter((pl.col("signal") == "scr_main") & (pl.col("label") == "close")).row(
        0, named=True
    )
    apart = res.filter((pl.col("signal") == "scr_main") & (pl.col("label") == "apart")).row(
        0, named=True
    )
    # A shared factor of weight 1 next to unit noise in the close half: the product's mean
    # there is cov / var = 1 / 1.5, since each series is standardised over the whole day
    # (variance 2 in the close half, 1 in the other).
    assert close["sync"] == pytest.approx(2 / 3, abs=0.1)
    assert close["excess_lo"] > 0.25
    assert abs(apart["sync"]) < 0.06
    diff = res.filter((pl.col("signal") == "scr_main") & (pl.col("label") == "close minus apart"))
    assert diff["sync_lo"][0] > 0.25
