"""The DSA 2026 exploratory scripts' own wiring, on invented rows."""

import importlib.util
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import polars as pl
import pytest

ANALYSES = Path(__file__).resolve().parents[1] / "studies" / "dsa-2026" / "analyses"


def _load(name: str):
    sys.path.insert(0, str(ANALYSES))
    spec = importlib.util.spec_from_file_location(f"{name}_script", ANALYSES / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def survey():
    return _load("exploratory_survey")


@pytest.fixture(scope="module")
def presses():
    return _load("exploratory_presses")


def item(respondent: str, code: str, value: int) -> dict:
    return {"respondent": respondent, "item": code, "value_numeric": value, "ok": True,
            "empty": False}  # fmt: skip


def test_background_indicators_from_items(survey):
    rows = [
        # r1: mother has a bachelor (C03 yes), father none; possessions 2 of 3; wealth 1 + 3.
        item("r1", "A9_ST006.ST006C03JA_DE", 1),
        item("r1", "A12_ST008.ST008C07JA_DE", 1),
        item("r1", "A15_ST250.ST250Q01JA", 1),
        item("r1", "A15_ST250.ST250Q03JA", 1),
        item("r1", "A15_ST250.ST250Q05JA", 2),
        item("r1", "A16_ST251.ST251Q01JA", 2),
        item("r1", "A16_ST251.ST251Q02JA", 4),
        item("r1", "ST005", 2),
        item("r1", "ST007", 1),
        item("r1", "ST255", 6),
        # r2: only a vocational degree (C07), no Abitur.
        item("r2", "A9_ST006.ST006C07JA_DE", 1),
        item("r2", "A9_ST006.ST006C01JA_DE", 2),
        item("r2", "ST005", 3),
        item("r2", "ST007", 2),
    ]
    b = survey.background(pl.DataFrame(rows)).sort("respondent")
    assert b["parent_tertiary"].to_list() == [1.0, 0.0]
    assert b["parent_abitur"].to_list() == [1.0, 0.0]
    assert b["possessions"].to_list() == [2.0, None]
    assert b["wealth"].to_list() == [4.0, None]
    assert b["books"].to_list() == [6.0, None]


def test_home_resources_averages_available_z_scores(survey):
    # possessions z = -1, 0, 1; wealth z = -1, 0, 1; books missing for the last -> its mean of 2.
    f = pl.DataFrame(
        {"possessions": [1.0, 2.0, 3.0], "wealth": [0.0, 5.0, 10.0], "books": [3.0, 5.0, None]}
    )
    h = survey.add_home_resources(f)["home_resources"].to_list()
    # books z over two values: -0.7071, 0.7071.
    assert h[0] == pytest.approx((-1 - 1 - 0.70711) / 3, abs=1e-4)
    assert h[1] == pytest.approx((0 + 0 + 0.70711) / 3, abs=1e-4)
    assert h[2] == pytest.approx(1.0)


def test_settings_classify_bins(presses):
    utc = ZoneInfo("UTC")
    # Local summer time is UTC+2: 08:00 UTC = 10:00 morning, 18:00 UTC = 20:00 evening,
    # 21:00 UTC = 23:00 late, 03:00 UTC = 05:00 night, 11:00 UTC = 13:00 midday.
    bins = [datetime(2026, 8, 20, h, 0, tzinfo=utc) for h in (8, 8, 18, 21, 3, 11, 9)]
    placed = pl.DataFrame(
        {
            "bin": bins,
            "zone": ["courses", "mensa", "courses", "aula", "unplaced", "courses", "courses"],
        }
    ).with_columns(presses.cp.phase_expr(pl.col("bin")).alias("phase"))
    plenum = pl.DataFrame({"bin": [bins[6]]})
    s = presses.settings(placed, plenum)["setting"].to_list()
    assert s == ["course block", "other daytime", "KüA evening", "late evening", "night",
                 "meal time", "plenum"]  # fmt: skip


@pytest.fixture(scope="module")
def cascades():
    return _load("exploratory_cascades")


def test_tie_bands_count_days_with_enough_close_minutes(cascades):
    # Pair (a, b): 12 close bins (60 min) on one camp day, 11 on the next -> tied 1 day -> band 1.
    # Pair (a, c): only weak readings -> never close, so not in the table at all.
    utc = ZoneInfo("UTC")
    day1 = [datetime(2026, 8, 20, 10, 5 * k, tzinfo=utc) for k in range(12)]
    day2 = [datetime(2026, 8, 21, 10, 5 * k, tzinfo=utc) for k in range(11)]
    rows = [("a", t, "b", -60) for t in day1 + day2] + [("b", day1[0], "a", -60)]
    rows += [("a", day1[0], "c", -80)]
    ends = pl.DataFrame(rows, schema=["entity", "bin", "other", "max_rssi"], orient="row")
    assert cascades.tie_bands(ends) == {("a", "b"): 1}


def test_statistics_count_one_group_moment(cascades):
    from datetime import date

    from social_energy.exploratory import CloseIndex

    # a, b, c press at 100, 150 and 200 s, all close to each other in bin 0; d presses alone at
    # 1000 s. Co-located pairs: a-b (50 s), a-c (100 s), b-c (50 s); none with d.
    presses = pl.DataFrame({
        "entity": ["a", "b", "c", "d"], "ts": [100, 150, 200, 1000],
        "day": [date(2026, 8, 20)] * 4, "phase": ["evening"] * 4,
        "setting": ["KüA evening"] * 4, "group": ["participant"] * 4,
    })  # fmt: skip
    close = {(x, 0, y) for x in "abc" for y in "abc" if x != y}
    kua = cascades.SETTINGS.index("KüA evening")
    s = cascades.Setup(
        presses=presses,
        exposure=pl.DataFrame({"entity": list("abcd"), "bs": [0, 0, 0, 900]}),
        close=CloseIndex(close, bin_size=300),
        rssi={},
        setting_of={("a", 0): kua, ("b", 0): kua, ("c", 0): kua, ("d", 900): kua},
        band={("a", "b"): 3},
        days=[date(2026, 8, 20)],
    )
    st = cascades.statistics(s, s.ts)
    assert st["close"].tolist() == [[3.0]]
    assert st["any"].tolist() == [[3.0]]  # d is 800 s or more from everyone
    assert st["setting"][0, kua] == 3
    assert st["phase"][0, cascades.PHASES.index("evening")] == 3
    # Gaps 50, 50 (30-60 s band) and 100 (1-2 min band).
    assert st["latency"][0].tolist() == [0, 0, 2, 1, 0, 0, 0]
    assert st["size"][0].tolist() == [0, 1, 0, 0]  # one group of three people
    assert st["triangles"].tolist() == [[1.0]]
    assert st["tie"][0].tolist() == [2, 0, 0, 1]  # a-b in band 3, the others never tied
    # Leaving the pair (a, b) out removes its press pair and breaks the triangle.
    s.drop = {("a", "b")}
    st = cascades.statistics(s, s.ts)
    assert st["close"].tolist() == [[2.0]] and st["triangles"].tolist() == [[0.0]]


def test_random_order_keeps_pairs_sharing_a_press_dependent(cascades, monkeypatch):
    # Pairs (0, 1) and (0, 2) share press 0. Under random order of the three presses, press 0
    # is before both others with probability 1/3, so both pairs keep their orientation 1/3 of
    # the time; flipping pairs independently would give 1/4.
    monkeypatch.setattr(cascades, "N_SHUFFLE", 6000)
    o = pl.DataFrame({"i": [0, 0], "j": [1, 2]})
    draws = list(cascades.random_order(o, np.random.default_rng(0)))
    both_kept = np.mean([not f[0] and not f[1] for f in draws])
    assert both_kept == pytest.approx(1 / 3, abs=0.02)
