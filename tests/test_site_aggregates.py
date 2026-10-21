"""Aggregates schema, small-cell rule and the pre-deploy validator. Synthetic data only."""

import json

import pytest
from test_site_public import CONFIG, TZ, _world

from social_energy.explorer import write_bundle
from social_energy.site import (
    AGGREGATE_SECTIONS,
    NUMBER_KEYS,
    SiteDataError,
    check_aggregates,
    synthetic_aggregates,
    validate_site_data,
    write_public_bundle,
)


def _site(tmp_path, agg=None):
    out = tmp_path / "site"
    write_public_bundle(_world(), out, CONFIG, timezone=TZ, seed=1)
    (out / "aggregates.json").write_text(json.dumps(agg or synthetic_aggregates(), allow_nan=False))
    return out


def _edit_meta(out, fn):
    p = out / "meta.json"
    meta = json.loads(p.read_text())
    fn(meta)
    p.write_text(json.dumps(meta))


def test_check_drops_small_and_missing_people():
    agg = {
        "places": [
            {"setting": "plenum", "people": 4},
            {"setting": "night"},
            {"setting": "meal_time", "people": 5},
        ]
    }
    assert check_aggregates(agg)["places"] == [{"setting": "meal_time", "people": 5}]


def test_check_strips_unknown_keys():
    agg = {"places": [{"setting": "plenum", "people": 9, "course": "X"}]}
    assert check_aggregates(agg)["places"] == [{"setting": "plenum", "people": 9}]
    out = check_aggregates({"numbers": {"n_presses": 3, "bogus": 1, "company_gain": "x"}})
    assert out["numbers"] == {"n_presses": 3}


def test_synthetic_fills_everything():
    agg = synthetic_aggregates(seed=2)
    assert set(agg) == set(AGGREGATE_SECTIONS) | {"numbers"}
    assert set(agg["numbers"]) == set(NUMBER_KEYS)
    assert all(r["people"] >= 5 for s, rows in agg.items() if s != "numbers" for r in rows)
    assert check_aggregates(agg) == agg


def test_validator_accepts_public_bundle_with_synthetic_aggregates(tmp_path):
    meta = validate_site_data(_site(tmp_path))
    assert meta["mode"] == "public"


def test_validator_refuses_team_bundle(tmp_path):
    out = tmp_path / "team"
    write_bundle(_world(), out, CONFIG, timezone=TZ, mode="team", seed=1)
    (out / "aggregates.json").write_text(json.dumps(synthetic_aggregates(), allow_nan=False))
    with pytest.raises(SiteDataError, match="mode"):
        validate_site_data(out)


def test_validator_refuses_extra_meta_key(tmp_path):
    out = _site(tmp_path)
    _edit_meta(out, lambda m: m.update(courses=["A"]))
    with pytest.raises(SiteDataError, match="courses"):
        validate_site_data(out)


def test_validator_refuses_seconds_presses(tmp_path):
    out = _site(tmp_path)
    _edit_meta(
        out, lambda m: m["files"]["presses"].update(columns=[["sec", "u32"], ["node", "u16"]])
    )
    with pytest.raises(SiteDataError, match="presses"):
        validate_site_data(out)


def test_validator_refuses_node_names(tmp_path):
    out = _site(tmp_path)
    _edit_meta(out, lambda m: m["nodes"][0].update(name="x"))
    with pytest.raises(SiteDataError, match="nodes"):
        validate_site_data(out)


def test_validator_refuses_small_row(tmp_path):
    agg = synthetic_aggregates()
    agg["places"][0]["people"] = 3
    with pytest.raises(SiteDataError, match="places"):
        validate_site_data(_site(tmp_path, agg))


def test_validator_refuses_missing_people_unknown_section_key_and_number(tmp_path):
    for mutate, name in (
        (lambda a: a["places"][0].pop("people"), "places"),
        (lambda a: a.update(rooms=[]), "rooms"),
        (lambda a: a["places"][0].update(course="X"), "course"),
        (lambda a: a["numbers"].update(bogus=1), "bogus"),
        (lambda a: a["numbers"].update(n_presses="many"), "n_presses"),
        (lambda a: a["confirmatory"][0].update(scale="z"), "confirmatory"),
    ):
        agg = synthetic_aggregates()
        mutate(agg)
        with pytest.raises(SiteDataError, match=name):
            validate_site_data(_site(tmp_path / name, agg))


def test_check_drops_suppressed_rows_and_unknown_sections():
    agg = {
        "places": [
            {"setting": "plenum", "people": 9, "suppressed": True},
            {"setting": "night", "people": 9, "suppressed": False},
        ],
        "rooms": [{"people": 20}],
    }
    out = check_aggregates(agg)
    assert out == {"places": [{"setting": "night", "people": 9}]}


def test_non_finite_values_are_refused_and_dropped(tmp_path):
    nan = float("nan")
    assert check_aggregates({"places": [{"setting": "a", "people": nan}]})["places"] == []
    assert check_aggregates({"numbers": {"n_presses": nan, "company_gain": float("inf")}}) == {
        "numbers": {}
    }
    agg = synthetic_aggregates()
    agg["places"][0]["people"] = nan
    out = _site(tmp_path / "p", None)
    (out / "aggregates.json").write_text(json.dumps(agg))  # NaN literal
    with pytest.raises(SiteDataError, match="places"):
        validate_site_data(out)
    agg = synthetic_aggregates()
    agg["numbers"]["n_presses"] = nan
    (out / "aggregates.json").write_text(json.dumps(agg))
    with pytest.raises(SiteDataError, match="n_presses"):
        validate_site_data(out)


def test_synthetic_counts_are_whole_numbers():
    numbers = synthetic_aggregates(3)["numbers"]
    counts = {k: v for k, v in numbers.items() if k.startswith("n_")}
    assert set(counts) == {"n_participants", "n_presses", "n_confirmatory"}
    assert all(type(v) is int for v in counts.values()), counts


def test_synthetic_ratios_sit_inside_their_intervals_and_numbers_match_rows():
    for seed in range(50):
        agg = synthetic_aggregates(seed)
        for section in ("moments_latency", "moments_size"):
            for row in agg[section]:
                assert row["ratio_lo"] <= row["ratio"] <= row["ratio_hi"], (seed, section, row)
        for section, (est, lo, hi) in {
            "moments_headline": ("ratio", "lo", "hi"),
            "persistence": ("share", "lo", "hi"),
            "places": ("rate", "lo", "hi"),
            "confirmatory": ("estimate", "lo", "hi"),
        }.items():
            for row in agg[section]:
                assert row[lo] <= row[est] <= row[hi], (seed, section, row)
        n = agg["numbers"]
        head = agg["moments_headline"][0]
        assert (n["cascade_excess"], n["cascade_excess_lo"], n["cascade_excess_hi"]) == (
            head["ratio"],
            head["lo"],
            head["hi"],
        )
        first = next(r for r in agg["moments_latency"] if r["band"] == "0-10")
        assert n["latency_0_10_ratio"] == first["ratio"]
        ordinary = [r["cross_share"] for r in agg["daily_mixing"] if r["kind"] == "ordinary"]
        assert (n["mixing_ordinary_lo"], n["mixing_ordinary_hi"]) == (min(ordinary), max(ordinary))
        share = {r["origin"]: r["share"] for r in agg["persistence"]}
        assert n["persistence_ordinary"] == share["ordinary"]
        assert n["persistence_excursion"] == share["excursion"]


# --- values, not only keys: each probe is something a careless export could publish ----------


def _refused(tmp_path, *, agg_fn=None, meta_fn=None, match):
    agg = synthetic_aggregates()
    if agg_fn:
        agg_fn(agg)
    out = _site(tmp_path, agg)
    if meta_fn:
        _edit_meta(out, meta_fn)
    with pytest.raises(SiteDataError, match=match):
        validate_site_data(out)


def test_validator_refuses_a_list_value_in_a_row(tmp_path):
    _refused(tmp_path, agg_fn=lambda a: a["day_phase"][0].update(others=["person:17"]),
             match="day_phase")  # fmt: skip


def test_validator_refuses_a_setting_outside_the_copy_keys(tmp_path):
    _refused(tmp_path, agg_fn=lambda a: a["places"][0].update(setting="Kurs 3 Physik"),
             match="setting")  # fmt: skip


def test_validator_refuses_a_confirmatory_label(tmp_path):
    _refused(tmp_path, agg_fn=lambda a: a["confirmatory"][0].update(label="Anna's course"),
             match="label")  # fmt: skip


def test_validator_refuses_free_text_in_special_days(tmp_path):
    def fn(m):
        m["special_days"] = [{"start_bin": 0, "end_bin": 2, "label": "excursion", "note": "x"}]

    _refused(tmp_path, meta_fn=fn, match="special_days")


def test_validator_refuses_a_special_day_label_outside_the_copy(tmp_path):
    def fn(m):
        m["special_days"] = [{"start_bin": 0, "end_bin": 2, "label": "trip with Mr X"}]

    _refused(tmp_path, meta_fn=fn, match="special_days")


def test_validator_refuses_a_free_text_shade_label(tmp_path):
    _refused(tmp_path, meta_fn=lambda m: m["shade"][0].update(label="private"), match="shade")


def test_validator_refuses_a_course_on_a_day(tmp_path):
    _refused(tmp_path, meta_fn=lambda m: m["days"][0].update(course="Alpha"), match="days")


def test_validator_refuses_free_text_in_phases(tmp_path):
    _refused(tmp_path, meta_fn=lambda m: m["phases"].append("Kurs 3 mit Frau X"), match="phases")


def test_validator_refuses_a_bin_file_longer_than_its_count(tmp_path):
    out = _site(tmp_path)
    with (out / "pairs.bin").open("ab") as f:
        f.write(b"\0" * 6)
    with pytest.raises(SiteDataError, match="pairs"):
        validate_site_data(out)


def test_validator_refuses_a_pair_in_a_hidden_bin(tmp_path):
    import numpy as np

    out = _site(tmp_path)
    meta = json.loads((out / "meta.json").read_text())
    n = meta["n_bins"]
    bins = np.frombuffer((out / "bins.bin").read_bytes(), dtype=np.uint8)
    hidden = int(np.flatnonzero(bins[2 * n :] == 0)[0])
    count = meta["files"]["pairs"]["count"]
    raw = np.frombuffer((out / "pairs.bin").read_bytes(), dtype="<u2").copy()
    raw[0] = hidden  # the first pair's bin column
    assert count >= 1
    (out / "pairs.bin").write_bytes(raw.tobytes())
    with pytest.raises(SiteDataError, match="pairs"):
        validate_site_data(out)


def test_validator_refuses_a_bin_index_past_the_end(tmp_path):
    import numpy as np

    out = _site(tmp_path)
    meta = json.loads((out / "meta.json").read_text())
    raw = np.frombuffer((out / "seen.bin").read_bytes(), dtype="<u2").copy()
    raw[0] = meta["n_bins"]
    (out / "seen.bin").write_bytes(raw.tobytes())
    with pytest.raises(SiteDataError, match="seen"):
        validate_site_data(out)


def test_check_drops_rows_with_values_outside_the_enumerations():
    agg = {
        "places": [
            {"setting": "plenum", "people": 9},
            {"setting": "Kurs 3 Physik", "people": 9},
            {"setting": "night", "people": 9, "rate": [1, 2]},
        ],
        "confirmatory": [{"test": "c1", "label": "c1", "people": 9, "scale": "sd"}],
    }
    out = check_aggregates(agg)
    assert out["places"] == [{"setting": "plenum", "people": 9}]
    assert out["confirmatory"] == [{"test": "c1", "people": 9, "scale": "sd"}]
