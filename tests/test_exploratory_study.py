"""The DSA 2026 exploratory scripts' own wiring, on invented rows."""

import importlib.util
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

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
