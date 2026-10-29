"""The deck's share of the DSA 2026 site export, on invented rows: small cells never surface."""

import importlib.util
import sys
from pathlib import Path

import polars as pl
import pytest

from social_energy.site.aggregates import NUMBER_KEYS, check_aggregates

SCRIPT = (
    Path(__file__).resolve().parents[1] / "studies" / "dsa-2026" / "analyses" / "deck_export.py"
)


@pytest.fixture(scope="module")
def deck():
    spec = importlib.util.spec_from_file_location("deck_export_script", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    yield module
    sys.modules.pop(spec.name, None)


def pair_effects():
    return pl.DataFrame(
        {
            "sample": ["all", "within course", "all", "all", "between course"],
            "person_fe": [True, True, False, True, True],
            "outcome": ["log_close", "log_close", "log_close", "days_tied", "log_close"],
            "measure": ["trust", "trust_scales", "trust", "trust", "B1"],
            "people": [40, 40, 40, 40, 40],
            "partial_r": [-0.01, -0.1, -0.2, -0.3, -0.06],
            "null_lo": [-0.03, -0.09, -0.05, -0.05, -0.04],
            "null_hi": [0.04, 0.1, 0.02, 0.02, 0.04],
            "pct_change_per_sd": [-0.009, -0.08, -0.12, -0.2, -0.05],
        }
    )


def test_gradient_pairs_keep_the_main_model_only(deck):
    log = []
    rows = deck.gradient_pair_rows(pair_effects(), log)
    assert [(r["measure"], r["sample"], r["r"]) for r in rows] == [
        ("trust", "all", -0.01),
        ("trust_scales", "within", -0.1),
    ]
    assert any("B1" in line for line in log)


def terciles(people_far=10, withheld_far=False):
    return pl.DataFrame(
        {
            "measure": ["trust", "trust", "trust", "trust_scales", "trust"],
            "partners": ["all", "all", "all", "all", "within course"],
            "tercile": ["near", "middle", "far", "near", "near"],
            "people_copressing": [20, 20, people_far, 20, 20],
            "copress_share": [0.07, 0.06, 0.09, 0.07, 0.5],
            "time_null_mean": [0.04, 0.04, 0.036, 0.04, 0.1],
            "excess_over_time_null": [1.8, 1.7, 2.5, 1.8, 5.0],
            "withheld": [False, False, withheld_far, False, False],
        }
    )


def test_gradient_presses_are_percent_and_small_cells_drop(deck):
    rows = deck.gradient_press_rows(terciles(people_far=4), [])
    assert [(r["tercile"], r["share"], r["time_null"]) for r in rows] == [
        ("near", 7.0, 4.0),
        ("middle", 6.0, 4.0),
        ("far", 9.0, 3.6),
    ]
    checked = check_aggregates({"gradient_presses": rows})
    assert [r["tercile"] for r in checked["gradient_presses"]] == ["near", "middle"]


def test_withheld_tercile_is_not_exported(deck):
    rows = deck.gradient_press_rows(terciles(withheld_far=True), [])
    assert [r["tercile"] for r in rows] == ["near", "middle"]


def test_eda_profile_is_one_series_in_offset_order(deck):
    base = dict(deck.EDA_PROFILE)
    df = pl.DataFrame(
        [
            {**base, "offset": 1, "people": 30, "observed": 0.1, "null_lo": -0.2,
             "null_hi": 0.2, "suppressed": False},
            {**base, "offset": -1, "people": 30, "observed": -0.1, "null_lo": -0.2,
             "null_hi": 0.2, "suppressed": False},
            {**base, "clock": "certain", "offset": 0, "people": 30, "observed": 9.0,
             "null_lo": -0.2, "null_hi": 0.2, "suppressed": False},
        ]
    )  # fmt: skip
    rows = deck.eda_profile_rows(df, [])
    assert [(r["offset"], r["observed"]) for r in rows] == [(-1, -0.1), (1, 0.1)]


def test_reasons_drop_other_and_withheld_cells(deck):
    df = pl.DataFrame(
        {
            "group": ["openers", "openers", "openers", "closers", "direction"],
            "level": ["people", "other", "nature", "fatigue", "opened"],
            "n": [70, 12, None, 16, 49],
            "share": [0.93, 0.16, None, 0.21, 0.65],
            "withheld": [False, False, True, False, False],
        }
    )
    log = []
    rows = check_aggregates({"membrane_reasons": deck.reason_rows(df, log)})["membrane_reasons"]
    assert [(r["reason"], r["direction"], r["share"]) for r in rows] == [
        ("people", "opens", 93.0),
        ("fatigue", "closes", 21.0),
    ]
    assert any("other" in line for line in log)


def test_data_state_counts_kept_records_per_source(deck):
    survey = pl.DataFrame(
        {
            "duplicate_submission": [False] * 9 + [True],
            "study_id": ["a"] * 8 + [None, "a"],
        }
    )
    qa = {
        "beacons": {"contacts": 1000, "contacts_not_ok": 100},
        "presses": {"press": {"rows": 50, "episodes": 30, "pressers": 12}},
        "survey": survey,
        "eda": {"all": {"minutes": {"person_minutes": 900, "usable_minutes": 800,
                                    "usable_people": 3, "hr_minutes": 500, "hr_people": 8}}},
        "interviews": {"coded": 20, "main_people": 19},
    }  # fmt: skip
    rows = deck.data_state_rows(qa, n_nodes=25, log=[])
    got = {r["source"]: (r["people"], r["raw"], r["clean"]) for r in rows}
    assert got == {
        "beacons": (25, 1000, 900),
        "presses": (12, 50, 30),
        "survey": (8, 10, 9),
        "eda": (3, 900, 800),
        "heart_rate": (8, 900, 500),
        "interviews": (19, 20, 19),
    }
    kept = check_aggregates({"data_state": rows})["data_state"]
    assert "eda" not in {r["source"] for r in kept}  # 3 wearers: under the small-cell rule


def test_numbers_need_enough_people_and_are_known_keys(deck):
    eda = {
        "all": {
            "minutes": {
                "usable_people": 40, "hr_people": 4, "usable_minutes": 900,
                "person_minutes": 1000, "clock_uncertain_minutes": 370,
                "clock_source_minutes": {"sync": 600, "rate": 300, "box": 100},
            },
            "presses_eda": {"presses_eligible": 9, "pressers_eligible": 3},
        },
        "certain": {"minutes": {"usable_people": 30}},
    }  # fmt: skip
    src = {
        "eda": eda,
        "gradient_pairs": pair_effects(),
        "gradient_presses": terciles(people_far=4),
    }
    log = []
    n = deck.deck_numbers(src, min_group=5, log=log)
    assert set(n) <= set(NUMBER_KEYS)
    assert n["eda_wearers"] == 40
    assert "hr_wearers" not in n  # 4 people
    assert "eda_presses" not in n and "eda_pressers" not in n  # 3 pressers
    clock = [n[f"eda_clock_{k}_pct"] for k in ("sync", "rate", "box")]
    assert clock == [60, 30, 10]
    assert n["eda_clock_uncertain_pct"] == 37
    assert n["gradient_trust_scales_within_pct"] == -8
    assert n["gradient_excess_near"] == 1.8
    assert "gradient_excess_far" not in n  # 4 people co-pressed in the far tercile


def test_a_missing_source_leaves_its_numbers_out(deck, tmp_path):
    log = []
    sections, src = deck.read_deck(tmp_path, 10, log)
    assert all(rows == [] for rows in sections.values())
    assert deck.deck_numbers(src, min_group=5, log=log) == {}
    assert any("missing" in line for line in log)
