"""The team-meeting deck: built with the site, numbers only by placeholder, no result in git."""

import json
import re
from pathlib import Path

import pytest

from social_energy.paths import REPO_ROOT
from social_energy.site.aggregates import (
    AGGREGATE_SECTIONS,
    NUMBER_KEYS,
    check_aggregates,
    synthetic_aggregates,
)
from social_energy.site.build import SITE_STATIC, build_site
from social_energy.study import StudyConfig

DECK = SITE_STATIC / "deck" / "index.html"
STUDY = REPO_ROOT / "studies" / "dsa-2026" / "study.yaml"
DECK_SECTIONS = ("data_state", "gradient_pairs", "gradient_presses", "eda_press_profile",
                 "membrane_reasons")  # fmt: skip


def _text(html: str) -> str:
    """The deck's visible text: comments, tags and attributes removed."""
    html = re.sub(r"<!--.*?-->", " ", html, flags=re.S)
    html = re.sub(r"<(script|style)\b.*?</\1>", " ", html, flags=re.S)
    return re.sub(r"<[^>]+>", " ", html)


@pytest.fixture(scope="module")
def built(tmp_path_factory) -> Path:
    out = tmp_path_factory.mktemp("site")
    return build_site(out, None, config=StudyConfig.load(STUDY).explorer_config(),
                      timezone="Europe/Berlin")  # fmt: skip


def test_deck_is_built_with_the_site(built):
    for name in ("deck/index.html", "deck/deck.js", "deck/viz.js", "deck/deck.css"):
        assert (built / name).is_file(), name


def test_every_placeholder_is_a_public_number():
    names = set(re.findall(r"\{\+?([a-z0-9_]+)\}", _text(DECK.read_text(encoding="utf-8"))))
    assert names, "the deck should take its numbers from the asset"
    assert names <= set(NUMBER_KEYS), sorted(names - set(NUMBER_KEYS))


def test_synthetic_build_fills_every_deck_placeholder(built):
    agg = json.loads((built / "data" / "aggregates.json").read_text())
    names = set(re.findall(r"\{\+?([a-z0-9_]+)\}", _text(DECK.read_text(encoding="utf-8"))))
    assert names <= set(agg["numbers"]), sorted(names - set(agg["numbers"]))
    for section in DECK_SECTIONS:
        assert agg[section], section


def test_deck_text_states_no_result():
    """A decimal, a percentage or a multiplier typed into the slides would be a finding in git."""
    text = _text(DECK.read_text(encoding="utf-8"))
    text = re.sub(r"\{\+?[a-z0-9_]+\}", "", text)
    for pattern in (r"\d+\.\d+", r"\d\s*%", r"\d\s*\u00d7", r"[\u03c1r]\s*=?\s*-?0"):
        assert not re.search(pattern, text), pattern


def test_deck_carries_the_site_content_security_policy():
    html = DECK.read_text(encoding="utf-8")
    for directive in ("default-src 'self'", "script-src 'self'", "style-src 'self'",
                      "base-uri 'none'", "form-action 'none'"):  # fmt: skip
        assert directive in html, directive
    assert "unsafe-" not in html
    assert not re.search(r"(src|href)=\"https?://(?!github\.com/Social-Energy-Lab)", html)


def test_deck_sections_follow_the_small_cell_rule():
    agg = synthetic_aggregates(3)
    agg["data_state"][0]["people"] = 4
    agg["membrane_reasons"][0]["reason"] = "a free-text reason"
    checked = check_aggregates(agg)
    assert len(checked["data_state"]) == len(agg["data_state"]) - 1
    assert len(checked["membrane_reasons"]) == len(agg["membrane_reasons"]) - 1
    assert set(DECK_SECTIONS) <= set(AGGREGATE_SECTIONS)
