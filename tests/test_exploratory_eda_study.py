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
           excluded=False, entity="person:1", hr=None, hrq=None, uncertain=False,
           hr_uncertain=None):  # fmt: skip
    return {"entity": entity, "minute": minute, "device": device, "worn_s": worn,
            "artifact_s": artifact, "conductance_us": cond, "motion_sd_g": motion, "scr_n": n,
            "scr_amp_us": amp, "excluded": excluded, "clock_uncertain": uncertain,
            "hr_ppg_bpm": hr, "hr_quality": hrq, "hr_clock_uncertain": hr_uncertain}  # fmt: skip


PM_SCHEMA = {"worn_s": pl.UInt32, "artifact_s": pl.UInt32, "conductance_us": pl.Float32,
             "motion_sd_g": pl.Float32, "hr_ppg_bpm": pl.Float32, "hr_quality": pl.Float32,
             "hr_clock_uncertain": pl.Boolean}  # fmt: skip


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
    # No PPG in these rows: no HR minute.
    assert not m["hr_ok"].any() and m["hr"].null_count() == 3


def test_build_minutes_heart_rate_and_clock_sensitivity(ee):
    m0, m1, m2, m3, m4 = (utc(20, 8, i) for i in range(5))
    one = 1 / 6
    pm = pl.DataFrame(
        [
            pm_row("D1", m0, motion=math.exp(-2), hr=80.0, hrq=one, hr_uncertain=False),
            pm_row("D1", m1, hr=None, hrq=0.0, hr_uncertain=False),  # no good window
            # Artifacts make the minute unusable for EDA; its heart rate still counts.
            pm_row("D1", m2, worn=60, artifact=50, hr=90.0, hrq=0.5, hr_uncertain=False),
            pm_row("D1", m3, uncertain=True, hr=70.0, hrq=1.0, hr_uncertain=True),
            pm_row("D1", m4, hr=75.0, hrq=1.0, hr_uncertain=True),  # only the PPG clock guessed
        ],
        schema_overrides=PM_SCHEMA,
    )
    counts = {r: pl.DataFrame({"device": ["D1"], "minute": [m0], "n": [1], "amp": [0.3]})
              for r in ("main", "amp02")}  # fmt: skip
    m = ee.build_minutes(pm, counts)
    assert m["usable"].to_list() == [True, True, False, True, True]
    assert m["hr_ok"].to_list() == [True, False, True, True, True]
    assert m["hr"].to_list() == [80.0, None, 90.0, 70.0, 75.0]
    assert m["hr_motion"][0] == pytest.approx(-2.0, abs=1e-5)
    c = ee.build_minutes(pm, counts, clock="certain")
    assert c["usable"].to_list() == [True, True, False, False, True]
    assert c["hr_ok"].to_list() == [True, False, True, False, False]
    assert c["tonic"][3] is None and c["hr"][3] is None and c["hr"][4] is None
    with pytest.raises(ValueError):
        ee.build_minutes(pm, counts, clock="sync")


def test_build_minutes_heart_rate_quality_threshold(ee, monkeypatch):
    m0, m1 = utc(20, 8, 0), utc(20, 8, 1)
    pm = pl.DataFrame([pm_row("D1", m0, hr=80.0, hrq=1 / 6), pm_row("D1", m1, hr=82.0, hrq=0.5)],
                      schema_overrides=PM_SCHEMA)  # fmt: skip
    counts = {r: pl.DataFrame(schema={"device": pl.String, "minute": pm["minute"].dtype,
                                      "n": pl.Int64, "amp": pl.Float64})
              for r in ("main", "amp02")}  # fmt: skip
    assert ee.build_minutes(pm, counts)["hr_ok"].to_list() == [True, True]
    monkeypatch.setattr(ee, "HR_MIN_QUALITY", 0.5)
    assert ee.build_minutes(pm, counts)["hr_ok"].to_list() == [False, True]


# --- oracle: an SCR burst after presses -----------------------------------------------------------


def synthetic_camp(ee, *, burst: float, seed: int = 7, n_people: int = 8, hr_burst: float = 0.0,
                   motion_burst: float = 0.0, no_ppg: int | None = None):  # fmt: skip
    """People x 2 days x 300 minutes of SCR counts; ``burst`` extra SCRs per minute at presses
    (minutes 0 to +2). Heart rate follows log movement (8 bpm per unit) plus noise, with
    ``hr_burst`` extra bpm at presses; ``motion_burst`` raises log movement there (so heart rate
    rises with it, through movement only). A fifth of the minutes have no good PPG, and none
    of person ``no_ppg``'s. Returns
    minutes (standardised) and presses."""
    rng = np.random.default_rng(seed)
    pm, cm, c2, presses = [], [], [], []
    for i in range(n_people):
        dev, ent = f"D{i}", f"person:{i}"
        for d in (20, 21):
            start = utc(d, 7, 0)
            t_press = sorted(rng.choice(np.arange(30, 270), 4, replace=False).tolist())
            boost, at = np.zeros(300), np.zeros(300, dtype=bool)
            for tp in t_press:
                boost[tp : tp + 3] = burst
                at[tp : tp + 3] = True
                presses.append({"entity": ent, "t": start + timedelta(minutes=tp, seconds=20)})
            lam = 5 + boost
            n = rng.poisson(lam)
            n2 = rng.binomial(n, 0.5)
            log_motion = rng.normal(-3, 0.5, 300) + motion_burst * at
            hr = 70 + 4 * i + 8 * (log_motion + 3) + rng.normal(0, 3, 300) + hr_burst * at
            good = (rng.uniform(size=300) > 0.2) & (i != no_ppg)
            for k in range(300):
                mt = start + timedelta(minutes=k)
                pm.append(pm_row(dev, mt, entity=ent, cond=float(np.exp(rng.normal(1 + i, 0.1))),
                                 motion=float(np.exp(log_motion[k])), n=int(n[k]),
                                 amp=0.3 * int(n[k]) * float(rng.uniform(0.5, 1.5)),
                                 hr=float(hr[k]) if good[k] else None,
                                 hrq=1.0 if good[k] else 0.0, hr_uncertain=False))  # fmt: skip
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


def _inside(r, slack=0.05):
    return r["null_lo"] - slack <= r["observed"] <= r["null_hi"] + slack


def test_press_heart_rate_finds_a_rise_and_separates_movement(ee, monkeypatch):
    monkeypatch.setattr(ee, "N_SHUFFLE", 150)
    monkeypatch.setattr(ee, "N_BOOT", 300)
    # A heart-rate rise of its own at presses: seen with and without the movement adjustment.
    m, p = synthetic_camp(ee, burst=0.0, hr_burst=10.0, no_ppg=0)
    res = ee.press_analysis(m, p, ee.HR_PRESS_COLUMNS, "hr_ok")
    # Person 0 has no good PPG: their 8 presses are eligible for EDA but not for heart rate.
    assert res["qa"]["presses_eligible"] == 56
    assert ee.press_analysis(m, p)["qa"]["presses_eligible"] == 64
    for col in ("r_pd_hr", "z_pd_hr"):
        r = _row(res, col, "at_minus_before")
        assert r["observed"] > r["null_hi"] and r["person_lo"] > 0, col
    # Two of the three "at" minutes carry the 10 bpm: about 6.7 bpm over the null.
    assert _row(res, "raw_hr", "at")["excess"] == pytest.approx(20 / 3, abs=2.0)
    assert _inside(_row(res, "z_pd_hr_motion", "at_minus_before"))
    # A rise that is only movement: raw heart rate up, adjusted heart rate flat.
    m, p = synthetic_camp(ee, burst=0.0, motion_burst=1.5)
    res = ee.press_analysis(m, p, ee.HR_PRESS_COLUMNS, "hr_ok")
    r = _row(res, "z_pd_hr", "at_minus_before")
    assert r["observed"] > r["null_hi"]
    assert _row(res, "z_pd_hr_motion", "at_minus_before")["observed"] > r["null_hi"]
    assert _inside(_row(res, "r_pd_hr", "at_minus_before"))


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


def test_fe_contrasts_adjust_heart_rate_for_its_own_movement(ee):
    """Heart rate is adjusted for movement over the HR minutes (``z_pd_hr_motion``), not for the
    EDA minutes' movement (here pure noise): the setting raises movement, heart rate follows
    movement, and the setting itself adds 0.3."""
    rng = np.random.default_rng(5)
    rows = []
    for i in range(10):
        for d in range(2):
            for k in range(150):
                setting = "meal time" if k < 50 else "course block"
                hm = rng.normal() + (1.0 if setting == "meal time" else 0.0)
                y = 0.3 * (setting == "meal time") + 0.8 * hm + rng.normal(0, 0.5)
                em = rng.normal()
                rows.append({"entity": f"p{i}", "day": date(2026, 8, 20 + d), "setting": setting,
                             "z_pd_hr": y, "z_pd_hr_motion": hm, "z_pd_hr_motion2": hm**2,
                             "z_pd_motion": em, "z_pd_motion2": em**2})  # fmt: skip
    df = pl.DataFrame(rows)
    out = ee.fe_contrasts(df, category="setting", reference="course block", measures=["hr"],
                          label="setting")  # fmt: skip
    by = {r["adjustment"]: r for r in out}
    assert by["none"]["estimate_sd"] == pytest.approx(1.1, abs=0.1)
    assert by["movement"]["lo"] < 0.3 < by["movement"]["hi"]
    assert by["movement"]["estimate_sd"] == pytest.approx(0.3, abs=0.1)


def test_fe_contrasts_use_each_measures_own_minutes(ee):
    """A measure missing in some minutes is fitted on the rest: people and minutes count only
    the minutes where it exists, and a level it never reaches is withheld for it alone."""
    rng = np.random.default_rng(9)
    rows = []
    for i in range(6):
        for k in range(60):
            setting = "plenum" if k < 20 else "course block"
            y = rng.normal() + (0.5 if setting == "plenum" else 0.0)
            hr = None if setting == "plenum" or k % 2 else rng.normal()
            rows.append({"entity": f"p{i}", "day": date(2026, 8, 20), "setting": setting,
                         "z_pd_scr_main": y, "z_pd_hr": hr, "z_pd_motion": 0.0,
                         "z_pd_motion2": 0.0, "z_pd_hr_motion": 0.0,
                         "z_pd_hr_motion2": 0.0})  # fmt: skip
    df = pl.DataFrame(rows)
    out = ee.fe_contrasts(df, category="setting", reference="course block",
                          measures=["scr_main", "hr"], label="setting")  # fmt: skip
    eda = next(r for r in out if r["measure"] == "scr_main" and r["adjustment"] == "none")
    hr = next(r for r in out if r["measure"] == "hr" and r["adjustment"] == "none")
    assert eda["minutes"] == 6 * 20 and not eda["suppressed"]
    assert hr["suppressed"] and hr["estimate_sd"] is None


def test_level_means_withhold_heart_rate_on_its_own_people(ee):
    rows = []
    for i in range(6):
        for setting in ("plenum", "course block"):
            hr_ok = setting == "course block" or i < 3  # plenum: heart rate from 3 people only
            rows.append({"entity": f"p{i}", "setting": setting, "usable": True, "hr_ok": hr_ok,
                         "scr_main": 6.0 + i, "scr_amp02": 3.0, "motion": -3.0,
                         "hr": 80.0 + i if hr_ok else None})  # fmt: skip
    lv = ee.level_means(pl.DataFrame(rows), "setting")
    course = lv.filter(pl.col("level") == "course block").row(0, named=True)
    plenum = lv.filter(pl.col("level") == "plenum").row(0, named=True)
    assert course["people"] == 6 and course["scr_main"] == pytest.approx(8.5)
    assert course["hr_bpm"] == pytest.approx(82.5) and course["hr_people"] == 6
    assert not plenum["suppressed"] and plenum["scr_main"] == pytest.approx(8.5)
    assert plenum["hr_suppressed"] and plenum["hr_bpm"] is None and plenum["hr_people"] is None


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


def test_heart_rate_synchrony_after_its_own_movement(ee, monkeypatch):
    """Heart rate of couples shares a factor in the close half, and everyone's heart rate also
    follows a movement series common to the whole camp. Adjusted for movement on the HR minutes,
    the close couples synchronise and the apart ones do not; unadjusted, apart pairs do too.
    Minutes without good PPG drop out of the HR pairs only."""
    monkeypatch.setattr(ee, "N_BOOT", 200)
    rng = np.random.default_rng(13)
    n_min, people = 240, [f"person:{i}" for i in range(8)]
    start = utc(20, 7, 0)
    minutes = [start + timedelta(minutes=k) for k in range(n_min)]
    bins = [mt - timedelta(minutes=mt.minute % 5) for mt in minutes]
    close_half = np.arange(n_min) < n_min // 2
    shared = {p: rng.normal(size=n_min) for p in people[::2]}
    camp_motion = rng.normal(size=n_min)
    rows = []
    for i, p in enumerate(people):
        f = shared[people[i - i % 2]]
        lm = -3 + 0.5 * camp_motion + 0.2 * rng.normal(size=n_min)
        hr = 80 + 20 * (lm + 3) + 3 * (rng.normal(size=n_min) + np.where(close_half, 1.0, 0) * f)
        good = rng.uniform(size=n_min) > 0.1
        for j, (mt, b) in enumerate(zip(minutes, bins, strict=True)):
            rows.append({"entity": p, "day": date(2026, 8, 20), "minute": mt, "bin": b,
                         "scr_main": float(rng.poisson(5)), "scr_amp02": 2.0, "tonic": 0.0,
                         "motion": float(lm[j]), "hr": float(hr[j]) if good[j] else None,
                         "hr_motion": float(lm[j]) if good[j] else None})  # fmt: skip
    sig = ee.sync_signals(pl.DataFrame(rows))
    couple_bins = sorted(set(b for b, c in zip(bins, close_half, strict=True) if c))
    pairs = pl.DataFrame([{"a": people[i], "b": people[i + 1], "bin": b, "max_rssi": -55}
                          for i in range(0, 8, 2) for b in couple_bins])  # fmt: skip
    seen = pl.DataFrame([{"entity": p, "bin": b} for p in people for b in set(bins)])
    pm_ = ee.pair_minutes(sig, pairs, seen, signal="s_hr")
    eda_pm = ee.pair_minutes(sig, pairs, seen)
    assert 0 < pm_.height < eda_pm.height  # bad PPG minutes leave the HR pairs only
    res = ee.synchrony(sig, pm_, ee.HR_SYNC_SIGNALS)["rows"]

    def get(signal, label):
        return res.filter((pl.col("signal") == signal) & (pl.col("label") == label)).row(
            0, named=True
        )

    assert get("hr", "close")["excess_lo"] > 0.15
    assert abs(get("hr", "apart")["sync"]) < 0.08
    assert get("hr_unadj", "apart")["sync"] > 0.3  # the camp's shared movement
    assert get("hr_motion", "apart")["sync"] > 0.3


def test_per_day_withholds_each_value_on_its_own_people(ee, monkeypatch):
    monkeypatch.setattr(ee, "N_BOOT", 100)
    rows = [{"day": date(2026, 8, 20), "entity": f"p{i}", "r_p_scr_main": 0.5,
             "r_p_scr_amp02": 0.4, "r_p_hr": 0.2 if i < 3 else None} for i in range(6)]  # fmt: skip
    out = ee.per_day(pl.DataFrame(rows)).row(0, named=True)
    assert out["scr_main_people"] == 6 and out["scr_main_mean"] == pytest.approx(0.5)
    assert not out["suppressed"]
    assert out["hr_people"] == 3 and out.get("hr_mean") is None
