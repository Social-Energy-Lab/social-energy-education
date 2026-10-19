"""The DSA 2026 confirmatory script's own wiring, on invented rows."""

import importlib.util
import sys
from pathlib import Path

import polars as pl
import pytest

SCRIPT = (
    Path(__file__).resolve().parents[1] / "studies" / "dsa-2026" / "analyses" / "confirmatory.py"
)


@pytest.fixture(scope="module")
def script():
    spec = importlib.util.spec_from_file_location("confirmatory_script", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclasses look their module up there
    spec.loader.exec_module(module)
    yield module
    sys.modules.pop(spec.name, None)


def test_the_family_is_four_tests_and_the_core_sets_are_six_scales(script):
    assert [t.name for t in script.TESTS] == ["C1", "C2", "C4_trust", "C4_lust"]
    assert all(len(s) == 6 for s in script.SCALES.values())
    assert all("self_report" in t.consent for t in script.TESTS if t.model == "negbin")


def test_worn_exposure_takes_the_worn_columns_of_the_main_rows(script):
    outcomes = pl.DataFrame(
        {
            "variant": ["main", "rssi_-70"],
            "entity": ["person:1", "person:1"],
            "press_episodes": [3, 9],
            "exposure_hours": [10.0, 90.0],
            "press_episodes_worn": [4, 8],
            "exposure_hours_worn": [20.0, 80.0],
        }
    )
    worn = script.variant_outcomes(outcomes, "worn_exposure")
    assert worn.select("press_episodes", "exposure_hours").row(0) == (4, 20.0)
    assert script.variant_outcomes(outcomes, "rssi_-70")["press_episodes"].to_list() == [9]


def test_holm_runs_over_the_family_only(script):
    rows = [
        {"test": "a", "family": True, "p_one": 0.01, "p_two": 0.02},
        {"test": "b", "family": True, "p_one": 0.02, "p_two": 0.04},
        {"test": "x", "family": False, "p_one": 0.001, "p_two": 0.002},
    ]
    out = script.with_holm(rows)
    assert [r.get("p_one_holm") for r in out] == pytest.approx([0.02, 0.02, None])
    assert [r.get("significant") for r in out] == [True, True, None]


def test_a_result_on_fewer_than_five_people_is_withheld(script):
    from social_energy.confirmatory import Fit

    fit = Fit("ols_hc3", 4, 2, 1.0, 0.1, 0.8, 1.2, 0.01, 0.005, 0.5, 0.4, 0.6)
    r = script.row(script.TESTS[0], fit, "main", True)
    assert r["n"] == 4 and r["estimate"] is None and r["p_one"] is None
