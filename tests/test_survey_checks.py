"""Survey checks that run before any scale is scored: the min-items rule, reverse-keying and
old form-version codes. Every code and value here is invented and written by hand.

Min items: max(floor, ceil(share x k)), capped at k. With floor 3 and share 0.5:
k = 1 -> 1 (cap), 2 -> 2 (cap), 3 -> 3, 4 -> 3, 6 -> 3, 7 -> 4, 10 -> 5, 11 -> 6.

Reverse-key check, scale S (range 1-5, items A B C D, C marked reversed, D behaves reversed
but is not marked). Complete cases r1-r4; r5 lacks C and is left out.

        A  B  C  D    C keyed (6 - C)
  r1    1  1  5  5    1
  r2    2  3  4  4    2
  r3    3  2  3  3    3
  r4    5  5  1  1    5

Item on its own raw values vs the rest of the scale keyed as the codebook says:
  A vs B + C' + D = 7, 9, 8, 11:  dA = -1.75 -.75 .25 2.25, dR = -1.75 .25 -.75 2.25,
      Σ dA dR = 7.75, Σ dA² = 8.75, Σ dR² = 8.75  -> r = +7.75 / 8.75 = +0.885714
  C vs A + B + D = 7, 9, 8, 11:  dC = -dA                 -> r = -0.885714 (reversed: agrees)
  D vs A + B + C' = 3, 7, 8, 15: dD = 1.75 .75 -.25 -2.25, dR = -5.25 -1.25 -.25 6.75,
      Σ dD dR = -25.25, Σ dD² = 8.75, Σ dR² = 74.75   -> r = -25.25 / √654.0625 = -0.987304
      (negative, yet not marked: flagged)
Against the raw rest instead (every item unreversed), A vs B + C + D = 11, 11, 8, 7:
      dR = 1.75 1.75 -1.25 -2.25, Σ dA dR = -9.75, Σ dR² = 12.75
      -> r = -9.75 / √(8.75 x 12.75) = -0.923077: the raw rest is contaminated by C and D.

Version check: OLD -> NEW (range 1-4). OLD answers 1, 1, 1, 2; NEW answers 1, 2, 2, 2.
  Chi-square (no continuity correction) on [[3, 1], [1, 3]]: expected 2 everywhere,
      chi2 = 4 x 1/2 = 2.0, df 1, p = erfc(1) = 0.157299.
  Mann-Whitney U for OLD: a 1 beats no NEW and ties one (0.5) -> 0.5 each, x3 = 1.5;
      the 2 beats one 1 and ties three 2s -> 2.5; U = 4.0, E[U] = 16 / 2 = 8.
      Ties (4 ones, 4 twos): var = 16/12 x (9 - 120/56) = 9.142857, z = -4 / 3.023716
      = -1.322876, p = erfc(1.322876 / √2) = 0.185877.
  Both p >= 0.05 -> equivalent (with min_n 4). OLD2 -> NEW2: ten 1s vs ten 4s -> chi2 = 20,
  not equivalent. Under the default min_n of 5, four OLD answers are too few for a verdict.
"""

from __future__ import annotations

import math
from typing import Any

import polars as pl
import pytest

from social_energy import cli
from social_energy.survey import (
    Codebook,
    chi_square_sf,
    chi_square_test,
    load_codebook,
    mann_whitney,
    reverse_key_check,
    version_equivalence,
)


def _items(rows: list[tuple[str, str, int | None]]) -> pl.DataFrame:
    return pl.DataFrame(
        [
            {
                "respondent": r,
                "item": i,
                "value_raw": "" if v is None else str(v),
                "value_numeric": v,
                "empty": v is None,
            }
            for r, i, v in rows
        ],
        schema={
            "respondent": pl.String, "item": pl.String, "value_raw": pl.String,
            "value_numeric": pl.Int64, "empty": pl.Boolean,
        },
    )  # fmt: skip


def _codebook(**overrides: Any) -> Codebook:
    raw: dict[str, Any] = {
        "title": "checks fixture",
        "version": 1,
        "roles": {"B": "trust_in_life"},
        "min_share": 0.5,
        "min_share_status": "decided",
        "min_items_floor": 3,
        "renames": {
            "OLD": {"to": "NEW", "status": "inferred"},
            "OLD2": {"to": "NEW2", "status": "inferred"},
        },
        "groups": {
            "s": {
                "block": "B", "role": "trust_in_life", "kind": "scale", "concept": "invented",
                "prefix": "S.", "items": ["A", "B", "C", "D"], "range": [1, 5],
                "reverse": ["C"], "reverse_status": "inferred",
            },
            "flat": {
                "block": "B", "role": "trust_in_life", "kind": "scale", "concept": "constant",
                "items": ["F1", "F2", "F3"], "range": [1, 5], "reverse_status": "inferred",
            },
            "single": {
                "block": "B", "role": "trust_in_life", "kind": "items", "concept": "renamed",
                "items": ["NEW", "NEW2"], "range": [1, 4],
            },
        },
    }  # fmt: skip
    for key, value in overrides.items():
        if key.startswith("s_"):
            raw["groups"]["s"][key[2:]] = value
        else:
            raw[key] = value
    return Codebook.model_validate(raw)


SCALE = {"A": [1, 2, 3, 5], "B": [1, 3, 2, 5], "C": [5, 4, 3, 1], "D": [5, 4, 3, 1]}


def _scale_items() -> pl.DataFrame:
    rows = [
        (f"r{n + 1}", f"S.{item}", values[n]) for item, values in SCALE.items() for n in range(4)
    ]
    rows += [("r5", "S.A", 3), ("r5", "S.B", 3), ("r5", "S.C", None), ("r5", "S.D", 2)]
    rows += [(f"r{n}", f"F{k}", 3) for n in range(1, 5) for k in (1, 2, 3)]
    return _items(rows)


# --- min items -----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("k", "want"), [(1, 1), (2, 2), (3, 3), (4, 3), (6, 3), (7, 4), (10, 5), (11, 6)]
)
def test_min_items_is_max_of_floor_and_share_capped_at_k(k, want):
    cb = _codebook(s_items=[f"I{n}" for n in range(k)], s_reverse=[])
    assert cb.min_items_for("s") == want


def test_min_items_floor_defaults_to_one_and_group_min_items_wins():
    raw = _codebook().model_dump(by_alias=True)
    raw.pop("min_items_floor")
    assert Codebook.model_validate(raw).min_items_for("s") == 2  # ceil(0.5 x 4)
    assert _codebook(s_min_items=4).min_items_for("s") == 4


def test_settled_statuses_are_not_pending():
    cb = _codebook(s_reverse_status="confirmed_by_check")
    assert "groups.s.reverse_status: confirmed_by_check" not in cb.pending()
    assert "min_share_status: decided" not in cb.pending()
    assert "groups.flat.reverse_status: inferred" in cb.pending()
    assert not cb.is_provisional("s")
    assert cb.is_provisional("flat")


# --- reverse keys ----------------------------------------------------------------------------


def _rows(frame: pl.DataFrame) -> dict[str, dict[str, Any]]:
    return {r["item"]: r for r in frame.iter_rows(named=True)}


def test_reverse_key_check_hand_computed():
    got = _rows(reverse_key_check(_scale_items(), _codebook()).filter(pl.col("group") == "s"))
    assert set(got) == {"S.A", "S.B", "S.C", "S.D"}
    assert {r["n"] for r in got.values()} == {4}  # r5 lacks C
    assert got["S.A"]["r_rest_keyed"] == pytest.approx(7.75 / 8.75)
    assert got["S.C"]["r_rest_keyed"] == pytest.approx(-7.75 / 8.75)
    assert got["S.D"]["r_rest_keyed"] == pytest.approx(-25.25 / math.sqrt(654.0625))
    assert got["S.A"]["r_rest_raw"] == pytest.approx(-9.75 / math.sqrt(8.75 * 12.75))
    assert got["S.C"]["marked_reverse"] and not got["S.D"]["marked_reverse"]
    assert got["S.A"]["agrees"] and got["S.C"]["agrees"]
    assert got["S.D"]["agrees"] is False
    assert got["S.D"]["finding"] == "negative but not marked reversed"
    assert got["S.C"]["finding"] is None


def test_reverse_key_check_flags_a_marked_item_that_runs_with_the_scale():
    got = _rows(reverse_key_check(_scale_items(), _codebook(s_reverse=["A", "C"])))
    assert got["S.A"]["agrees"] is False
    assert got["S.A"]["finding"] == "marked reversed but not negative"


def test_reverse_key_check_ignores_the_printed_direction():
    plain = reverse_key_check(_scale_items(), _codebook())
    printed = reverse_key_check(_scale_items(), _codebook(s_printed_reversed=True))
    assert plain["r_rest_keyed"].to_list() == pytest.approx(printed["r_rest_keyed"].to_list())


def test_reverse_key_check_undefined_correlation_is_null_not_a_verdict():
    got = _rows(reverse_key_check(_scale_items(), _codebook()).filter(pl.col("group") == "flat"))
    assert all(r["r_rest_keyed"] is None and r["agrees"] is None for r in got.values())


def test_reverse_key_check_uses_kept_submissions_only():
    subs = pl.DataFrame(
        {"respondent": ["r1", "r2", "r3", "r4", "r5"], "duplicate_submission": [0, 0, 0, 1, 0]}
    ).with_columns(pl.col("duplicate_submission").cast(pl.Boolean))
    got = _rows(reverse_key_check(_scale_items(), _codebook(), subs))
    assert got["S.A"]["n"] == 3


# --- old form-version codes ------------------------------------------------------------------


def test_chi_square_sf_matches_known_critical_values():
    assert chi_square_sf(3.841459, 1) == pytest.approx(0.05, abs=1e-6)
    assert chi_square_sf(5.991465, 2) == pytest.approx(0.05, abs=1e-6)
    assert chi_square_sf(11.070498, 5) == pytest.approx(0.05, abs=1e-6)
    assert chi_square_sf(2.0, 1) == pytest.approx(math.erfc(1.0))
    assert chi_square_sf(0.0, 3) == 1.0


def test_chi_square_and_mann_whitney_hand_computed():
    chi2, df, p = chi_square_test([[3, 1], [1, 3]])
    assert (chi2, df) == (pytest.approx(2.0), 1)
    assert p == pytest.approx(0.157299, abs=1e-6)
    u, p_u = mann_whitney([1, 1, 1, 2], [1, 2, 2, 2])
    assert u == 4.0
    z = -4 / math.sqrt(16 / 12 * (9 - 120 / 56))
    assert p_u == pytest.approx(math.erfc(abs(z) / math.sqrt(2)))
    assert p_u == pytest.approx(0.185877, abs=1e-5)


def test_version_equivalence_hand_computed():
    rows = [(f"o{n}", "OLD", v) for n, v in enumerate([1, 1, 1, 2])]
    rows += [(f"c{n}", "NEW", v) for n, v in enumerate([1, 2, 2, 2])]
    rows += [(f"o{n}", "OLD2", 1) for n in range(10)] + [(f"c{n}", "NEW2", 4) for n in range(10)]
    rows += [("c9", "NEW", None)]  # an empty answer counts nowhere
    frame = version_equivalence(_items(rows), _codebook(), min_n=4)
    got = {r["old"]: r for r in frame.iter_rows(named=True)}
    one = got["OLD"]
    assert (one["new"], one["n_old"], one["n_new"]) == ("NEW", 4, 4)
    assert one["counts_old"] == [3, 1, 0, 0] and one["counts_new"] == [1, 3, 0, 0]
    assert (one["mean_old"], one["mean_new"]) == (1.25, 1.75)
    assert one["chi2"] == pytest.approx(2.0) and one["chi2_df"] == 1
    assert one["chi2_p"] == pytest.approx(0.157299, abs=1e-6)
    assert one["mwu_p"] == pytest.approx(0.185877, abs=1e-5)
    assert one["equivalent"] is True
    two = got["OLD2"]
    assert two["chi2"] == pytest.approx(20.0) and two["equivalent"] is False
    default = version_equivalence(_items(rows), _codebook()).row(0, named=True)
    assert default["chi2"] == pytest.approx(2.0)  # the tests still run
    assert default["equivalent"] is None  # 4 < 5 answers: no verdict


def test_version_equivalence_without_data_gives_no_verdict():
    got = version_equivalence(_items([("o0", "OLD", 2)]), _codebook())
    row = got.filter(pl.col("old") == "OLD").row(0, named=True)
    assert row["n_new"] == 0 and row["equivalent"] is None


# --- CLI -------------------------------------------------------------------------------------


def test_check_survey_cli_writes_checks_and_no_scores(tmp_path, monkeypatch):
    from test_survey_scoring import _study

    monkeypatch.setenv("SOCIAL_ENERGY_DATA", str(tmp_path / "data"))
    study = _study(tmp_path, frozen=False)  # the checks do not need the freeze
    assert cli.main(["ingest-survey", str(study)]) == 0
    assert cli.main(["check-survey", str(study)]) == 0
    survey = tmp_path / "data" / "synthetic-camp" / "derived" / "survey"
    assert set(pl.read_parquet(survey / "checks" / "reverse_keys.parquet")["group"]) == {
        "belong",
        "agency",
    }
    assert pl.read_parquet(survey / "checks" / "versions.parquet")["old"].to_list() == ["OLD_G"]
    assert not (survey / "scoring").exists()


def test_the_study_codebook_states_the_min_items_rule():
    from test_survey_scoring import REPO

    cb = load_codebook(REPO / "studies" / "dsa-2026" / "survey_codebook.yaml")
    assert (cb.min_share, cb.min_items_floor) == (0.5, 3)
    assert cb.groups["b19_fear_drivers"].kind == "items"
    assert cb.groups["b20_joy_sources"].kind == "items"
