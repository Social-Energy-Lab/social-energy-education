"""The person view's part of the explorer bundle: consent per module, codes only, no IDs.

Golden: the four-person world of ``test_explorer_bundle`` with hand-written person data and
hand-derived contents. Oracle: a synthetic camp with made-up person data. Public: the public
bundle and the site's checks never carry any of it.
"""

import json
from dataclasses import replace
from datetime import timedelta

import numpy as np
import polars as pl
import pytest
from test_explorer_bundle import CONFIG, T0, _bin, _golden

from social_energy.explorer import read_bundle, write_bundle
from social_energy.explorer.person import (
    EDA_SCHEMA,
    NONE_U16,
    PersonData,
    PersonDataError,
    check_codes,
)
from social_energy.explorer.synthetic import demo_bundle, synthetic_inputs
from social_energy.site.public import write_public_bundle
from social_energy.site.validate import SiteDataError, validate_site_data
from social_energy.study import ExplorerConfig
from social_energy.synth import CampSpec, generate

SCALES = [
    {"key": "t1", "label": "belonging", "block": "trust", "kind": "scale", "core": True,
     "items": ["T1_01", "T1_02"], "range": [1, 4]},
]  # fmt: skip


def _persons(**over) -> PersonData:
    everyone = frozenset({"person:1", "person:2", "person:3", "person:4"})
    eda = pl.DataFrame(
        [
            ("person:1", T0 + timedelta(minutes=1), 2.5, 1.0, 71.0, True, True, False),
            ("person:1", T0 + timedelta(minutes=2), None, None, None, False, False, True),
            ("person:2", T0 + timedelta(minutes=1), 1.0, 0.0, 80.0, True, True, False),
        ],
        schema=EDA_SCHEMA,
        orient="row",
    )
    base = dict(
        consent={
            "survey": frozenset({"person:1", "person:2", "person:3"}),
            "interview_in_person": frozenset({"person:1"}),
            "eda": frozenset({"person:1"}),  # person:2's EDA row must be dropped
            "self_report": everyone,
        },
        attributes={"person:1": {"age": 16, "gender": "f"}},
        scales=SCALES,
        composites=pl.DataFrame(
            {
                "entity": ["person:1", "person:2", "person:3", "person:4"],
                "wave": ["pre"] * 4,
                "trust": [1.0, 0.0, -1.0, 9.0],
                "lust": [0.5, 0.5, -0.5, 9.0],
            }
        ),
        scale_scores=pl.DataFrame(
            {
                "entity": ["person:1", "person:2"],
                "wave": ["pre", "pre"],
                "group": ["t1", "t1"],
                "mean": [3.0, 2.0],
            }
        ),
        items=pl.DataFrame(
            {
                "entity": ["person:1", "person:1", "person:2"],
                "wave": ["pre"] * 3,
                "group": ["t1"] * 3,
                "item": ["T1_01", "T1_02", "T1_01"],
                "value": [3.0, 3.0, 1.0],
            }
        ),
        membrane={
            "person:1": {
                "M_arrival": {"value": 3, "confidence": "high"},
                "openers": ["people"],
                "D_academy_lenient": 1.0,
                "episodes": [{"day": "2026-01-01"}],
            },
            "person:2": {"M_arrival": {"value": 2}},  # no interview consent: dropped
        },
        interviews={"person:1": T0 + timedelta(minutes=20), "person:2": T0},
        eda=eda,
        events=pl.DataFrame(
            {
                "label": ["plenary", "late"],
                "kind": ["plenum", "kuea"],
                "start": [_bin(1), _bin(5)],
                "end": [_bin(3), _bin(9)],
                "end_known": [True, False],
                "all_camp": [True, False],
                "locations": [[], ["location:9", "location:77"]],
            },
            schema_overrides={"start": pl.Datetime("us", "UTC"), "end": pl.Datetime("us", "UTC")},
        ),
    )
    return PersonData(**(base | over))


@pytest.fixture
def world(tmp_path):
    inp = replace(_golden(), persons=_persons())
    meta = write_bundle(inp, tmp_path / "b", CONFIG, timezone="UTC", seed=3)
    _, cols = read_bundle(tmp_path / "b")
    doc = json.loads((tmp_path / "b" / "person.json").read_text())
    # The shuffled index of each entity, recovered from the one course-free attribute we set.
    return meta, cols, doc, tmp_path / "b"


def _node(doc, **want):
    hits = [i for i, p in enumerate(doc["people"]) if all(p.get(k) == v for k, v in want.items())]
    assert len(hits) == 1, hits
    return hits[0]


def test_person_files_are_listed_and_cover_every_node(world):
    meta, _cols, doc, _ = world
    assert meta["person"] == {"file": "person.json"}
    assert "eda" in meta["files"]
    assert len(doc["people"]) == len(meta["nodes"]) == 4
    assert doc["waves"] == ["pre"]


def test_consent_gates_each_module(world):
    meta, cols, doc, _ = world
    p1 = _node(doc, age=16)
    people = doc["people"]
    assert [p["survey"] is not None for p in people].count(True) == 3  # person:4 has no consent
    assert [p["membrane"] is not None for p in people] == [i == p1 for i in range(4)]
    assert [p["interview_sec"] for p in people if p["interview_sec"] is not None] == [1200]
    assert [p["eda"] for p in people] == [i == p1 for i in range(4)]
    assert set(cols["eda"]["node"].tolist()) == {p1}
    qa = meta["qa"]
    assert qa["membrane_without_consent"] == 1
    assert qa["eda_minutes_without_consent"] == 1
    assert qa["survey_rows_without_consent"] == 1  # person:4's composite


def test_survey_z_against_the_camp_and_types(world):
    _, _, doc, _ = world
    p1 = doc["people"][_node(doc, age=16)]
    # Trust 1, 0, -1 among the consenting: mean 0, sd 1.
    assert p1["survey"]["pre"]["trust"] == [1.0, 1.0]
    assert p1["survey"]["pre"]["scales"]["t1"] == [3.0, pytest.approx(0.707, abs=1e-3)]
    assert p1["survey"]["pre"]["items"]["t1"] == [3.0, 3.0]
    assert doc["item_means"]["pre"]["t1"] == [2.0, 3.0]
    # Median trust 0, lust 0.5: at the median counts as high.
    assert p1["type"] == {"trust": "high", "lust": "high"}
    assert sorted(json.dumps(p["type"]) for p in doc["people"]) == sorted(
        ["null", '{"trust": "high", "lust": "high"}', '{"trust": "high", "lust": "high"}',
         '{"trust": "low", "lust": "low"}']
    )  # fmt: skip


def test_eda_rows_encode_rates_heart_rate_and_flags(world):
    _, cols, _, _ = world
    e = cols["eda"]
    assert e["min"].tolist() == [1, 2]
    assert e["scr"].tolist() == [250, NONE_U16]
    assert e["scr_strict"].tolist() == [100, NONE_U16]
    assert e["hr"].tolist() == [71, 0]
    assert e["flags"].tolist() == [3, 4]


def test_events_become_bins_and_location_indices(world):
    _, _, doc, _ = world
    plenary, late = doc["events"]
    assert (plenary["start_bin"], plenary["end_bin"], plenary["all_camp"]) == (1, 3, True)
    # Clipped to the six bins; the unknown location is dropped.
    assert (late["start_bin"], late["end_bin"], late["locs"], late["end_known"]) == (
        5,
        6,
        [0],
        False,
    )


def test_presses_follow_self_report_consent(tmp_path):
    persons = _persons(consent=_persons().consent | {"self_report": frozenset({"person:2"})})
    meta = write_bundle(replace(_golden(), persons=persons), tmp_path / "b", CONFIG, timezone="UTC")
    assert meta["qa"]["presses_without_consent"] == 1
    assert meta["files"]["presses"]["count"] == 0


def test_bundle_carries_no_entity_strings_or_free_text(world):
    *_, bundle = world
    for f in bundle.iterdir():
        data = f.read_bytes()
        assert b"person:" not in data and b"location:" not in data, f.name


@pytest.mark.parametrize(
    "codes",
    [
        {"M_now": {"value": 4, "evidence": ["she said it opened up"]}},
        {"notes": "a long note with spaces"},
        {"openers": ["other:a name"]},
        {"bad key": 1},
    ],
)
def test_free_text_in_membrane_codes_is_refused(tmp_path, codes):
    persons = _persons(membrane={"person:1": codes})
    with pytest.raises(PersonDataError):
        write_bundle(replace(_golden(), persons=persons), tmp_path / "b", CONFIG, timezone="UTC")


def test_codes_accept_tokens_numbers_and_dates():
    codes = {"M_now": {"value": None, "confidence": "low", "led": True}, "D": -1.0}
    check_codes(codes | {"episodes": [{"day": "2026-08-20", "category": "being_heard"}]})


def test_unknown_consent_module_is_refused(tmp_path):
    persons = _persons(consent={"acoustics": frozenset()})
    with pytest.raises(PersonDataError):
        write_bundle(replace(_golden(), persons=persons), tmp_path / "b", CONFIG, timezone="UTC")


def test_person_data_is_team_only(tmp_path):
    inp = replace(_golden(), persons=_persons())
    with pytest.raises(ValueError, match="team bundle only"):
        write_bundle(inp, tmp_path / "b", CONFIG, timezone="UTC", mode="public")


def test_rewrite_without_person_data_removes_old_person_files(world):
    *_, bundle = world
    meta = write_bundle(_golden(), bundle, CONFIG, timezone="UTC")
    assert "person" not in meta and "eda" not in meta["files"]
    assert not (bundle / "person.json").exists() and not (bundle / "eda.bin").exists()


def test_public_bundle_never_carries_person_data(tmp_path):
    camp = generate(CampSpec(lost=None, reboot=None, swap=None), tmp_path / "camp")
    inp = synthetic_inputs(camp, persons=True)
    assert inp.persons is not None
    out = tmp_path / "public"
    meta = write_public_bundle(inp, out, ExplorerConfig(), timezone=camp.spec.timezone, seed=0)
    assert "person" not in meta and "eda" not in meta["files"]
    assert sorted(p.name for p in out.iterdir()) == sorted(
        ["meta.json", *(f"{n}.bin" for n in meta["files"])]
    )


def test_site_checks_refuse_a_team_bundle_with_person_data(tmp_path):
    camp = generate(CampSpec(lost=None, reboot=None, swap=None), tmp_path / "camp")
    out = tmp_path / "team"
    write_bundle(synthetic_inputs(camp, persons=True), out, ExplorerConfig(),
                 timezone=camp.spec.timezone)  # fmt: skip
    (out / "aggregates.json").write_text("{}")
    with pytest.raises(SiteDataError):
        validate_site_data(out)


def test_synthetic_camp_person_view_end_to_end(tmp_path):
    spec = CampSpec(hours=36, lost=None, reboot=None, swap=None, id_bug_until_h=None)
    camp = generate(spec, tmp_path / "camp")
    inp = synthetic_inputs(camp, persons=True, seed=1)
    meta = write_bundle(inp, tmp_path / "b", ExplorerConfig(), timezone=spec.timezone)
    _, cols = read_bundle(tmp_path / "b")
    doc = json.loads((tmp_path / "b" / "person.json").read_text())
    eda_people = {i for i, p in enumerate(doc["people"]) if p["eda"]}
    assert eda_people and set(np.unique(cols["eda"]["node"]).tolist()) == eda_people
    # Sorted by node, then minute, as the view's index expects.
    key = cols["eda"]["node"].astype(np.int64) * 10**7 + cols["eda"]["min"]
    assert (np.diff(key) > 0).all()
    assert meta["qa"]["eda_minutes_no_node"] == 0
    assert doc["events"] and all(e["end_bin"] > e["start_bin"] for e in doc["events"])
    assert sum(p["membrane"] is not None for p in doc["people"]) == len(
        inp.persons.consent["interview_in_person"]
    )


def test_demo_bundle_has_the_person_view(tmp_path):
    out = demo_bundle(tmp_path / "demo", ExplorerConfig(courses={"a": "A", "b": "B"}),
                      timezone="Europe/Berlin")  # fmt: skip
    meta = json.loads((out / "meta.json").read_text())
    assert meta["mode"] == "synthetic" and meta["person"]["file"] == "person.json"
    assert {c["key"] for c in meta["courses"]} == {"a", "b"}
