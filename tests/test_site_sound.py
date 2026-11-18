"""The site's sound sections: rows describe rooms, so an hours rule replaces the people rule.

Synthetic, hand-written rows only. ``sound_day`` keeps a day with at least one recorded hour,
``sound_kind`` a programme kind with at least half an hour; ``room`` and ``programme`` come from
fixed sets, every other value is a finite number.
"""

import pytest
from test_site_aggregates import _refused, _site

from social_energy.site import SiteDataError, check_aggregates, synthetic_aggregates
from social_energy.site.aggregates import ROOMS, SOUND_KINDS, SOUND_MIN_HOURS
from social_energy.site.validate import validate_site_data


def test_the_hours_rule_is_one_hour_a_day_and_half_an_hour_a_kind():
    assert SOUND_MIN_HOURS == {"sound_day": 1.0, "sound_kind": 0.5}
    assert ROOMS == ("dining_hall", "main_hall")
    assert "no_item" in SOUND_KINDS


def test_check_keeps_sound_days_from_one_hour_and_drops_the_rest():
    rows = [
        {"day": "2026-08-14", "room": "main_hall", "hours": 1.0, "leq": -41.5, "leq_p90": -33.0},
        {"day": "2026-08-15", "room": "main_hall", "hours": 0.92, "leq": -50.0},
        {"day": "2026-08-16", "room": "dining_hall", "leq": -40.0},  # no hours stated
        {"day": "2026-08-17", "room": "dining_hall", "hours": "6", "leq": -40.0},
    ]
    out = check_aggregates({"sound_day": rows})["sound_day"]
    assert out == [rows[0]]


def test_check_keeps_sound_kinds_from_half_an_hour():
    rows = [
        {"room": "dining_hall", "programme": "meal", "hours": 0.5, "leq": -38.0, "lo": -41.0,
         "hi": -35.0},
        {"room": "dining_hall", "programme": "party", "hours": 0.42, "leq": -30.0},
    ]  # fmt: skip
    assert check_aggregates({"sound_kind": rows})["sound_kind"] == [rows[0]]


def test_sound_rows_need_no_people_and_lose_any_people_or_label_key():
    row = {"room": "main_hall", "programme": "concert", "hours": 2.0, "leq": -30.0,
           "people": 2, "label": "Konzert am Freitag"}  # fmt: skip
    out = check_aggregates({"sound_kind": [row]})["sound_kind"]
    assert out == [{"room": "main_hall", "programme": "concert", "hours": 2.0, "leq": -30.0}]


def test_check_drops_free_text_rooms_and_programme_kinds():
    rows = [
        {"room": "Mensa", "programme": "meal", "hours": 3.0, "leq": -40.0},
        {"room": "main_hall", "programme": "Konzert von X", "hours": 3.0, "leq": -40.0},
        {"room": "main_hall", "programme": "excursion", "hours": 3.0, "leq": -40.0},
    ]
    assert check_aggregates({"sound_kind": rows})["sound_kind"] == [rows[2]]
    day = {"day": "Freitag", "room": "main_hall", "hours": 3.0, "leq": -40.0}
    assert check_aggregates({"sound_day": [day]})["sound_day"] == []


def test_synthetic_sound_sections_survive_the_check_and_show_both_halls():
    for seed in range(20):
        agg = synthetic_aggregates(seed)
        for section, minimum in SOUND_MIN_HOURS.items():
            rows = agg[section]
            assert {r["room"] for r in rows} == set(ROOMS), (seed, section)
            assert all(r["hours"] >= minimum for r in rows), (seed, section)
            assert check_aggregates({section: rows})[section] == rows
        for r in agg["sound_kind"]:
            assert r["lo"] <= r["leq"] <= r["hi"], (seed, r)
        for r in agg["sound_day"]:
            assert r["leq"] <= r["leq_p90"], (seed, r)


def test_validator_accepts_the_synthetic_sound_sections(tmp_path):
    validate_site_data(_site(tmp_path, synthetic_aggregates(4)))


@pytest.mark.parametrize(
    ("section", "change", "match"),
    [
        ("sound_day", {"hours": 0.5}, "sound_day"),
        ("sound_day", {"hours": None}, "sound_day"),
        ("sound_kind", {"hours": 0.25}, "sound_kind"),
        ("sound_kind", {"room": "Mensa"}, "room"),
        ("sound_kind", {"programme": "Konzert von X"}, "programme"),
        ("sound_kind", {"label": "Konzert"}, "label"),
        ("sound_kind", {"people": 30}, "people"),
        ("sound_day", {"leq": "loud"}, "leq"),
        ("sound_day", {"day": "Freitag"}, "day"),
    ],
)
def test_validator_refuses_sound_rows_outside_the_rule(tmp_path, section, change, match):
    _refused(tmp_path, agg_fn=lambda a: a[section][0].update(change), match=match)


def test_validator_refuses_a_sound_row_without_hours(tmp_path):
    with pytest.raises(SiteDataError, match="hours"):
        agg = synthetic_aggregates()
        agg["sound_kind"][0].pop("hours")
        validate_site_data(_site(tmp_path, agg))
