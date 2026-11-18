"""The DSA 2026 site export, on invented rows: numbers come only from rows that survive."""

import importlib.util
import math
import sys
from datetime import date
from pathlib import Path

import polars as pl
import pytest

from social_energy.site import aggregates

SCRIPT = (
    Path(__file__).resolve().parents[1] / "studies" / "dsa-2026" / "analyses" / "site_export.py"
)


@pytest.fixture(scope="module")
def script():
    spec = importlib.util.spec_from_file_location("site_export_script", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    yield module
    sys.modules.pop(spec.name, None)


def places(plenum_people=20, course_people=20):
    return pl.DataFrame(
        {
            "category": ["plenum", "course block", "staff room"],
            "people_exposed": [plenum_people, course_people, 30],
            "rate": [4.0, 1.5, 1.0],
            "lo": [3.0, 1.0, 0.5],
            "hi": [5.0, 2.0, 1.5],
            "suppressed": [False, False, False],
        }
    )


def company(people=20, diff=0.5):
    # Only the -65 dBm, day x phase, close row may be used; the other rows are decoys.
    return pl.DataFrame(
        {
            "variant": ["-65 dBm", "-65 dBm", "-70 dBm"],
            "matched": ["day x phase", "none", "day x phase"],
            "value": ["close", "close", "close"],
            "people": [people, 40, 40],
            "mean_diff": [diff, 9.0, 9.0],
        }
    )


RATIOS = pl.DataFrame(
    {
        "days": ["all days", "from 2026-08-16"],
        "ratio": ["plenum / course block", "plenum / course block"],
        "estimate": [2.5, 9.0],
    }
)


def mixing(people_excursion=20):
    # Arrival (day 1) is dropped; day 4 is outside the bundle; the excursion row may be small.
    return pl.DataFrame(
        {
            "day": ["2026-08-01", "2026-08-02", "2026-08-03", "2026-08-04", "2026-08-02"],
            "people": [20, 20, people_excursion, 20, 20],
            "cross_share": [0.9, 0.30, 0.70, 0.5, 0.99],
            "expected": [0.8, 0.80, 0.84, 0.8, 0.99],
            "variant": ["main", "main", "main", "main", "rssi_-70"],
            "kind": ["ordinary", "ordinary", "excursion", "ordinary", "ordinary"],
        }
    )


DAYS = {"2026-08-01", "2026-08-02", "2026-08-03"}
ARRIVAL = "2026-08-01"


def run(script, sections, *, company_df=None, ratios=RATIOS, min_group=5):
    log = []
    checked, numbers = script.finish(
        sections,
        company_df if company_df is not None else company(),
        ratios,
        min_group=min_group,
        log=log,
    )
    return checked, numbers, log


def test_mixing_rows_keep_main_days_in_the_bundle_as_percent(script):
    rows = script.mixing_rows(mixing(), DAYS, ARRIVAL, [])
    assert [(r["day"], r["kind"], r["cross_share"], r["expected"]) for r in rows] == [
        ("2026-08-02", "ordinary", 30.0, 80.0),
        ("2026-08-03", "excursion", 70.0, 84.0),
    ]


def test_a_small_row_takes_its_number_with_it(script):
    """Excursion row with 4 people: dropped, so mixing_excursion is absent; ordinary stays."""
    sections = {
        "daily_mixing": script.mixing_rows(mixing(people_excursion=4), DAYS, ARRIVAL, []),
        "places": script.place_rows(places(), []),
    }
    checked, numbers, _ = run(script, sections)
    assert [r["day"] for r in checked["daily_mixing"]] == ["2026-08-02"]
    assert "mixing_excursion" not in numbers
    assert numbers["mixing_ordinary_lo"] == 30
    assert numbers["mixing_random"] == 80
    assert numbers["company_gain"] == 0.5
    assert numbers["plenum_vs_course"] == 2.5


def test_plenum_suppressed_drops_plenum_vs_course(script):
    sections = {"places": script.place_rows(places(plenum_people=4), [])}
    checked, numbers, _ = run(script, sections)
    assert [r["setting"] for r in checked["places"]] == ["course_block"]
    assert "plenum_vs_course" not in numbers


def test_unknown_setting_is_dropped_and_logged(script):
    log = []
    rows = script.place_rows(places(), log)
    assert [r["setting"] for r in rows] == ["plenum", "course_block"]
    assert any("staff room" in line for line in log)


def test_small_company_row_drops_company_gain(script):
    _, numbers, _ = run(script, {}, company_df=company(people=4))
    assert "company_gain" not in numbers


def test_none_values_leave_the_key_out_without_a_crash(script):
    headline = pl.DataFrame(
        {
            "variant": ["main"],
            "category": [script.HEADLINE],
            "observed": [10.0],
            "null_mean": [5.0],
            "ratio": [None],
            "ratio_lo": [1.5],
            "ratio_hi": [float("nan")],
        },
        schema_overrides={"ratio": pl.Float64},
    )
    main = pl.DataFrame(
        {
            "null": ["person-day-phase"],
            "window_min": [5.0],
            "excluding_under_s": [0],
            "statistic": ["co-located pairs"],
            "observed": [10.0],
        }
    )
    qa = {"observed_colocated_5min": 10, "people_in_colocated_5min": 9}
    sections = {"moments_headline": script.headline_rows(headline, main, qa)}
    mix = mixing().with_columns(pl.lit(None, dtype=pl.Float64).alias("expected"))
    sections["daily_mixing"] = script.mixing_rows(mix, DAYS, ARRIVAL, [])
    _, numbers, log = run(
        script, sections, company_df=company(diff=None), ratios=RATIOS.with_columns(
            pl.lit(None, dtype=pl.Float64).alias("estimate"))
    )  # fmt: skip
    assert "cascade_excess" not in numbers
    assert "cascade_excess_hi" not in numbers
    assert numbers["cascade_excess_lo"] == 1.5
    assert "mixing_random" not in numbers
    assert "company_gain" not in numbers
    assert "plenum_vs_course" not in numbers
    assert all(isinstance(v, int | float) and math.isfinite(v) for v in numbers.values())
    assert log


def test_confirmatory_count_comes_from_surviving_rows(script):
    df = pl.DataFrame(
        {
            "variant": ["main"] * 4 + ["main"],
            "test": ["C1", "C2", "C4_trust", "C4_lust", "C2_excess"],
            "n": [30, 30, 30, 30, 30],
            "std_estimate": [0.1, -0.1, 1.1, 1.0, 0.0],
            "std_lo": [-0.2, -0.4, 0.9, 0.8, -0.3],
            "std_hi": [0.4, 0.2, 1.3, 1.2, 0.3],
        }
    )
    rows = script.confirmatory_rows(df, [])
    assert [(r["test"], r["scale"]) for r in rows] == [
        ("c1", "sd"), ("c2", "sd"), ("c4_trust", "rr"), ("c4_lust", "rr")
    ]  # fmt: skip
    _, numbers, _ = run(script, {"confirmatory": rows})
    assert numbers["n_confirmatory"] == 30
    _, numbers, _ = run(script, {"confirmatory": rows}, min_group=31)
    assert "n_confirmatory" not in numbers


def test_latency_bands_are_in_seconds(script):
    df = pl.DataFrame(
        {
            "category": ["0-10 s", "1-2 min"],
            "people": [9, 9],
            "ratio": [3.0, 1.2],
            "ratio_lo": [2.0, 1.0],
            "ratio_hi": [4.0, 1.4],
            "suppressed": [False, False],
        }
    )
    rows = script.latency_rows(df, [])
    assert [r["band"] for r in rows] == ["0-10", "60-120"]
    _, numbers, _ = run(script, {"moments_latency": rows})
    assert numbers["latency_0_10_ratio"] == 3.0


def test_copy_keys_are_inside_the_site_enumerations(script):

    assert set(script.SETTINGS.values()) <= set(aggregates.SETTINGS)
    assert {key for key, _ in script.TESTS.values()} <= set(aggregates.TESTS)
    assert {scale for _, scale in script.TESTS.values()} <= set(aggregates.SCALES)
    assert set(script.SPECIAL_DAYS) <= set(aggregates.DAY_KINDS)


def test_confirmatory_count_is_c1_when_the_tests_differ(script):
    df = pl.DataFrame(
        {
            "variant": ["main"] * 4,
            "test": ["C1", "C2", "C4_trust", "C4_lust"],
            "n": [30, 28, 26, 26],
            "std_estimate": [0.1, -0.1, 1.1, 1.0],
            "std_lo": [-0.2, -0.4, 0.9, 0.8],
            "std_hi": [0.4, 0.2, 1.3, 1.2],
        }
    )
    _, numbers, _ = run(script, {"confirmatory": script.confirmatory_rows(df, [])})
    assert numbers["n_confirmatory"] == 30
    # C1 under the small-cell rule: no count, even though the others survive.
    df = df.with_columns(pl.Series("n", [4, 28, 26, 26]))
    _, numbers, _ = run(script, {"confirmatory": script.confirmatory_rows(df, [])})
    assert "n_confirmatory" not in numbers


# --- the halls' sound ---------------------------------------------------------------------------


def sound_bins():
    """Invented bins. Dining hall: two meal bins (-40, -30) and four uncovered bins, two with no
    kind and two labelled by their slot (-50, -48, -46, -20): no_item takes the median of all
    four, -47 (quartiles -48.5 and -39.5), not the mean of per-label medians (-49 and -33 give
    -41). One bin of a kind the site does not know, and one of a recorder it does not know."""
    return pl.DataFrame(
        {
            "recorder": ["mensa"] * 7 + ["office"],
            "day": [date(2026, 8, 2)] * 8,
            "kind": ["meal", "meal", None, None, "no item (12:00-13:45)",
                     "no item (12:00-13:45)", "Lesung mit X", "meal"],
            "leq_dbfs": [-40.0, -30.0, -50.0, -48.0, -46.0, -20.0, -35.0, -10.0],
        }
    )  # fmt: skip


def by_kind(meal_median=-35.0):
    return pl.DataFrame({"recorder": ["mensa"], "kind": ["meal"], "leq_dbfs_median": [meal_median]})


def test_sound_kinds_fold_every_uncovered_bin_into_one_no_item(script):
    log = []
    rows = script.sound_kind_rows(sound_bins(), by_kind(), log)
    got = {r["programme"]: r for r in rows}
    assert set(got) == {"meal", "no_item"}
    assert got["no_item"]["room"] == "dining_hall"
    assert got["no_item"]["leq"] == -47.0
    assert (got["no_item"]["lo"], got["no_item"]["hi"]) == (-48.5, -39.5)
    assert got["no_item"]["hours"] == round(4 * 5 / 60, 2)
    assert got["meal"]["leq"] == -35.0
    assert any("unknown kind" in line for line in log)
    assert any("office" in line for line in log)
    # The log is printed: it names no programme label, only that one was left out.
    assert not any("Lesung" in line for line in log)


def test_sound_kinds_refuse_bins_that_disagree_with_by_kind(script):
    with pytest.raises(SystemExit, match="by_kind"):
        script.sound_kind_rows(sound_bins(), by_kind(meal_median=-36.0), [])


def test_sound_days_keep_the_bundle_days_with_the_hall_names(script):
    df = pl.DataFrame(
        {
            "recorder": ["mensa", "plenum", "plenum"],
            "day": [date(2026, 8, 2), date(2026, 8, 2), date(2026, 8, 9)],
            "recorded_h": [6.5, 0.75, 4.0],
            "leq_dbfs": [-40.04, -55.0, -45.0],
            "leq_p90": [-32.0, -50.0, -38.0],
        }
    )
    log = []
    rows = script.sound_day_rows(df, DAYS, log)
    assert rows == [
        {"day": "2026-08-02", "room": "dining_hall", "hours": 6.5, "leq": -40.0, "leq_p90": -32.0},
        {"day": "2026-08-02", "room": "main_hall", "hours": 0.75, "leq": -55.0, "leq_p90": -50.0},
    ]
    assert any("2026-08-09" in line for line in log)
    # The hours rule then drops the main hall's short day.
    checked, _, _ = run(script, {"sound_day": rows})
    assert [r["room"] for r in checked["sound_day"]] == ["dining_hall"]


def test_missing_sound_folder_leaves_the_sections_empty(script, tmp_path):
    log = []
    assert script.read_sound(tmp_path / "nowhere", DAYS, log) == {"sound_day": [], "sound_kind": []}
    assert any("acoustics" in line for line in log)


def test_sound_rooms_are_inside_the_site_enumeration(script):
    assert set(script.RECORDERS.values()) == set(aggregates.ROOMS)
