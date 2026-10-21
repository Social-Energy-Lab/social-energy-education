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
    (out / "aggregates.json").write_text(json.dumps(agg or synthetic_aggregates()))
    return out


def _edit_meta(out, fn):
    p = out / "meta.json"
    meta = json.loads(p.read_text())
    fn(meta)
    p.write_text(json.dumps(meta))


def test_check_drops_small_and_missing_people():
    agg = {
        "places": [{"setting": "a", "people": 4}, {"setting": "b"}, {"setting": "c", "people": 5}]
    }
    assert check_aggregates(agg)["places"] == [{"setting": "c", "people": 5}]


def test_check_strips_unknown_keys():
    agg = {"places": [{"setting": "a", "people": 9, "course": "X"}]}
    assert check_aggregates(agg)["places"] == [{"setting": "a", "people": 9}]
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
    (out / "aggregates.json").write_text(json.dumps(synthetic_aggregates()))
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
