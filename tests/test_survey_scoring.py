"""Survey scoring: codebook, recoding, scale scores, reliability, submissions and QA.

Golden fixtures (all codes and values invented):
``fixtures/survey/codebook.yaml`` and ``fixtures/survey/scoring_responses.jsonl``.

Codebook: ``belong`` (block B, 1-4, printed reversed, Q2 reverse-keyed [inferred], min 3 items);
``agency`` (block C, 1-5, "6"/"DK" non-substantive, Q3 reverse-keyed, min ceil(0.5 * 3) = 2);
``agency_grad`` (gradient C_G, 1-4, parent agency; old code OLD_G renames to C_G);
``degrees`` (items D1, "3" non-substantive); ``frequency`` (items F1, codes F1_1..3 -> 1..3,
printed reversed, F1_9 non-substantive); unscored AGE, SCHOOL.

Recoding: printed-reversed x -> min + max - x, then reverse-keyed x -> min + max - x.

s-1 (ID "7")  belong Q1 1->4, Q2 1->4->1, Q3 2->3, Q4 empty      -> 8/3 from 3 items
              agency Q1 5, Q2 DK (non-substantive), Q3 2->4        -> 4.5 from 2 items
              C_G 3 and OLD_G 1 both present: the current code wins -> grad 3 (1 conflict)
              F1 F1_1 -> 1 -> 3 (printed reversed)                   13 rows, 12 answered
s-2 (ID " 7 " -> "7")  belong Q1 only -> below min, null           2 rows: duplicate of s-1
s-3 (ID "x9" -> "X9", version 16)  belong 4,4,4,4 -> 1,4,1,1     -> 7/4
              agency Q1 9 (out of range), Q2 3, Q3 "6" (non-subst.) -> 1 item, null
              OLD_G 2 -> C_G -> grad 2; ZZZ is not in the codebook   10 rows, 10 answered
s-4 (ID "X9")  belong 2,3,3,2 -> 3,(2->)3,2,3                     -> 11/4
              agency 1, 2, 5->1                                     -> 4/3;  grad 4
              10 rows, 10 answered: ties with s-3, later submitted_at -> s-4 kept, s-3 duplicate
s-5 (no ID)   belong Q1 3 -> 2, below min; agency 4, 4 -> 4.0; F1 F1_9 non-substantive

Scores: 5 respondents x 3 scored groups (2 scales + 1 gradient) = 15 rows; null means:
s-2 x 3, s-3 agency, s-5 belong and grad -> 6.
"""

from __future__ import annotations

import json
import math
from fractions import Fraction
from pathlib import Path

import numpy as np
import polars as pl
import pytest
from pydantic import ValidationError

from social_energy import cli
from social_energy.survey import (
    SurveyConfig,
    cronbach_alpha,
    ingest_zeitgeist,
    load_codebook,
    load_corrections,
    mcdonald_omega,
    normalise_study_id,
    recode,
    reliability,
    resolve_submissions,
    score,
    score_survey,
    validate_against,
)
from social_energy.synth.survey import generate_scored_survey

FIXTURES = Path(__file__).parent / "fixtures" / "survey"
EXPORT = FIXTURES / "scoring_responses.jsonl"
CODEBOOK = FIXTURES / "codebook.yaml"
REPO = Path(__file__).resolve().parents[1]


@pytest.fixture
def tables():
    return ingest_zeitgeist([EXPORT], SurveyConfig(study_id_item="q_pre"))


@pytest.fixture
def codebook():
    return load_codebook(CODEBOOK)


def _scores(frame: pl.DataFrame) -> dict[tuple[str, str], float | None]:
    return {(r["respondent"], r["group"]): r["mean"] for r in frame.iter_rows(named=True)}


# --- codebook --------------------------------------------------------------------------------


def test_codebook_expands_prefixes_and_indexes_items(codebook):
    assert codebook.group_of("B.Q2") == "belong"
    assert codebook.group_of("C_G") == "agency_grad"
    assert codebook.group_of("OLD_G") is None  # an old code is known only through its rename
    assert codebook.groups["belong"].codes == ["B.Q1", "B.Q2", "B.Q3", "B.Q4"]
    assert codebook.groups["belong"].min_items_required(codebook.min_share) == 3
    assert codebook.groups["agency"].min_items_required(codebook.min_share) == 2
    assert codebook.knows("AGE") and codebook.knows("OLD_G") and not codebook.knows("ZZZ")


def test_codebook_lists_what_is_not_confirmed(codebook):
    assert codebook.pending() == ["groups.belong.reverse_status: inferred"]


def test_codebook_rejects_unknown_keys_and_inconsistent_entries(tmp_path):
    def load(text: str):
        path = tmp_path / "cb.yaml"
        path.write_text(text)
        return load_codebook(path)

    base = CODEBOOK.read_text()
    with pytest.raises(ValidationError):
        load(base.replace("concept: invented agency\n", "concept: invented agency\n    x: 1\n"))
    with pytest.raises(ValueError, match="role"):  # block C is lust for life
        load(
            base.replace(
                "role: lust_for_life\n    kind: scale", "role: trust_in_life\n    kind: scale"
            )
        )
    with pytest.raises(ValueError, match="reverse"):  # reverse-keyed item not in the group
        load(base.replace("reverse: [Q3]", "reverse: [Q9]"))
    with pytest.raises(ValueError, match="parent"):
        load(base.replace("parent: agency", "parent: nowhere"))
    with pytest.raises(ValueError, match="more than one group"):
        load(base.replace("items: [D1]", "items: [C_G]"))
    with pytest.raises(ValueError, match="range"):
        load(base.replace("range: [1, 5]", "range: [5, 1]"))


def test_codebook_needs_a_status_for_scale_reverse_lists(tmp_path):
    path = tmp_path / "cb.yaml"
    path.write_text(CODEBOOK.read_text().replace("    reverse_status: confirmed\n", ""))
    with pytest.raises(ValueError, match="reverse_status"):
        load_codebook(path)


# --- validation against an export ------------------------------------------------------------


def test_validate_against_reports_unknown_and_unseen_codes(tables, codebook):
    report = validate_against(tables.items, codebook, ignore=("q_pre",))
    assert report == {"not_in_codebook": ["ZZZ"], "not_in_export": ["SCHOOL"]}


# --- recoding --------------------------------------------------------------------------------


def test_recode_harmonises_reverse_keys_and_maps_codes(tables, codebook):
    rec = recode(tables.items, codebook)
    got = {
        (r["respondent"], r["item"]): (r["value"], r["missing"]) for r in rec.iter_rows(named=True)
    }
    assert got[("s-1", "B.Q1")] == (4.0, None)  # printed reversed only
    assert got[("s-1", "B.Q2")] == (1.0, None)  # printed reversed, then reverse-keyed
    assert got[("s-1", "B.Q4")] == (None, "empty")
    assert got[("s-1", "C.Q2")] == (None, "non_substantive")
    assert got[("s-1", "C.Q3")] == (4.0, None)  # reverse-keyed
    assert got[("s-1", "F1")] == (3.0, None)  # code F1_1 -> 1, printed reversed -> 3
    assert got[("s-5", "F1")] == (None, "non_substantive")
    assert got[("s-1", "D1")] == (None, "non_substantive")
    assert got[("s-3", "C.Q1")] == (None, "out_of_range")
    assert got[("s-3", "C_G")] == (2.0, None)  # renamed from OLD_G
    assert ("s-1", "OLD_G") not in got and ("s-3", "OLD_G") not in got
    assert ("s-1", "AGE") not in got and ("s-3", "ZZZ") not in got  # unscored / unknown
    renamed = rec.filter(pl.col("renamed_from").is_not_null())
    assert renamed.select("respondent", "item", "renamed_from").rows() == [("s-3", "C_G", "OLD_G")]


# --- submissions -----------------------------------------------------------------------------


def test_normalise_study_id():
    assert normalise_study_id(" x9 ") == "X9"
    assert normalise_study_id("1 2") == "12"
    assert normalise_study_id("   ") is None
    assert normalise_study_id(None) is None


def test_most_complete_submission_wins_and_ties_go_to_the_later_one(tables):
    subs = resolve_submissions(tables.respondents, tables.items).sort("respondent")
    assert subs.select("respondent", "study_id", "n_answered", "duplicate_submission").rows() == [
        ("s-1", "7", 12, False),
        ("s-2", "7", 2, True),
        ("s-3", "X9", 10, True),
        ("s-4", "X9", 10, False),
        ("s-5", None, 4, False),
    ]
    assert subs["no_study_id"].to_list() == [False, False, False, False, True]


def test_local_correction_table_by_respondent_and_by_typed_value(tables, tmp_path):
    table = tmp_path / "corrections.csv"
    table.write_text("respondent,typed,study_id\ns-5,,7\n,x9,9\n")
    corrections = load_corrections(table)
    subs = resolve_submissions(tables.respondents, tables.items, corrections).sort("respondent")
    assert subs["study_id"].to_list() == ["7", "7", "9", "9", "7"]
    assert subs["duplicate_submission"].to_list() == [False, True, True, False, True]
    assert subs["corrected"].to_list() == [False, False, True, True, True]


def test_correction_table_inside_the_repo_is_refused(tables):
    with pytest.raises(Exception, match="inside the repository"):
        load_corrections(REPO / "corrections.csv")


# --- scores ----------------------------------------------------------------------------------


def test_scores_golden(tables, codebook):
    subs = resolve_submissions(tables.respondents, tables.items)
    scores = score(tables.items, codebook, subs)
    assert scores.height == 15
    got = _scores(scores)
    expected = {
        ("s-1", "belong"): Fraction(8, 3), ("s-1", "agency"): Fraction(9, 2),
        ("s-1", "agency_grad"): 3,
        ("s-2", "belong"): None, ("s-2", "agency"): None, ("s-2", "agency_grad"): None,
        ("s-3", "belong"): Fraction(7, 4), ("s-3", "agency"): None, ("s-3", "agency_grad"): 2,
        ("s-4", "belong"): Fraction(11, 4), ("s-4", "agency"): Fraction(4, 3),
        ("s-4", "agency_grad"): 4,
        ("s-5", "belong"): None, ("s-5", "agency"): 4, ("s-5", "agency_grad"): None,
    }  # fmt: skip
    for key, want in expected.items():
        if want is None:
            assert got[key] is None, key
        else:
            assert got[key] == pytest.approx(float(want)), key
    row = scores.filter((pl.col("respondent") == "s-1") & (pl.col("group") == "belong")).row(
        0, named=True
    )
    assert (row["n_items"], row["n_expected"], row["min_items"]) == (3, 4, 3)
    assert (row["block"], row["role"], row["kind"]) == ("B", "trust_in_life", "scale")
    assert row["provisional"] and row["study_id"] == "7" and not row["duplicate_submission"]
    grad = scores.filter(pl.col("group") == "agency_grad")
    assert set(grad["kind"]) == {"gradient"} and not any(grad["provisional"])
    assert scores.filter(pl.col("respondent") == "s-2")["duplicate_submission"].all()


def test_gradient_items_never_enter_the_parent_scale(tables, codebook):
    """If C_G were averaged into agency, s-1 would score (5 + 4 + 3) / 3 = 4, not 4.5."""
    scores = score(tables.items, codebook)
    assert _scores(scores)[("s-1", "agency")] == pytest.approx(4.5)


# --- reliability -----------------------------------------------------------------------------


def test_cronbach_alpha_hand_computed():
    """Items (1,2,3) and (2,3,3): variances 1 and 1/3; totals 3,5,6 have variance 7/3.
    alpha = 2/1 * (1 - (4/3) / (7/3)) = 6/7."""
    matrix = np.array([[1, 2], [2, 3], [3, 3]], dtype=float)
    assert cronbach_alpha(matrix) == pytest.approx(6 / 7)
    assert math.isnan(cronbach_alpha(matrix[:, :1]))  # one item: undefined
    assert math.isnan(cronbach_alpha(np.ones((4, 3))))  # no variance: undefined


def test_omega_matches_theory_on_congeneric_items():
    """One factor, loadings l on standardised items: omega = (sum l)^2 / ((sum l)^2 + sum(1-l^2)).
    For l = (0.8, 0.7, 0.6, 0.5): sum l = 2.6, sum(1 - l^2) = 0.36 + 0.51 + 0.64 + 0.75 = 2.26,
    so omega = 6.76 / 9.02 = 0.7494."""
    rng = np.random.default_rng(0)
    loadings = np.array([0.8, 0.7, 0.6, 0.5])
    factor = rng.standard_normal(40_000)
    noise = rng.standard_normal((40_000, 4)) * np.sqrt(1 - loadings**2)
    items = factor[:, None] * loadings + noise
    assert mcdonald_omega(items) == pytest.approx(6.76 / 9.02, abs=0.01)
    # Parallel items: alpha and omega agree.
    parallel = factor[:, None] * 0.7 + rng.standard_normal((40_000, 4)) * np.sqrt(0.51)
    assert mcdonald_omega(parallel) == pytest.approx(cronbach_alpha(parallel), abs=0.01)


def test_reliability_uses_complete_cases_of_kept_submissions(tables, codebook):
    subs = resolve_submissions(tables.respondents, tables.items)
    rel = {r["group"]: r for r in reliability(tables.items, codebook, subs).iter_rows(named=True)}
    assert set(rel) == {"belong", "agency"}  # scales only: no gradients, no item groups
    # belong: kept s-1 lacks Q4 and s-5 has Q1 only, so s-4 is the one complete case.
    assert (rel["belong"]["n_complete"], rel["belong"]["k"]) == (1, 4)
    assert rel["belong"]["alpha"] is None and rel["belong"]["omega"] is None


# --- QA and the orchestrator -----------------------------------------------------------------


def test_score_survey_qa_accounts_for_everything(tables, codebook):
    out = score_survey(tables.items, tables.respondents, codebook, ignore=("q_pre",))
    qa = out.qa
    assert qa["validation"] == {"not_in_codebook": ["ZZZ"], "not_in_export": ["SCHOOL"]}
    assert qa["out_of_range"] == {"C.Q1": 1}
    assert qa["non_substantive"] == {"C.Q2": 1, "C.Q3": 1, "D1": 1, "F1": 1}
    assert (qa["renamed"], qa["rename_conflicts"]) == (1, 1)  # s-3 renamed; s-1 conflict
    assert qa["submissions"] == {
        "respondents": 5, "with_study_id": 4, "no_study_id": 1, "distinct_study_ids": 2,
        "duplicate_submission": 2, "kept": 3, "corrected": 0,
    }  # fmt: skip
    s = qa["submissions"]
    assert s["kept"] + s["duplicate_submission"] == s["respondents"]
    assert qa["scores"] == {"rows": 15, "null_mean": 6}
    assert qa["pending"] == ["groups.belong.reverse_status: inferred"]
    # Missingness over the 3 kept submissions: B.Q4 answered by s-4 only.
    assert qa["missing"]["kept_respondents"] == 3
    assert qa["missing"]["items"]["B.Q4"] == 2
    assert qa["missing"]["items"]["B.Q1"] == 0
    json.dumps(qa)  # serialisable as qa.json


# --- synthetic oracle ------------------------------------------------------------------------


def test_synthetic_oracle_scores_match_the_generators_truth(tmp_path):
    """The generator encodes known construct-direction answers into printed answers (flipping
    reverse-keyed items and printed-reversed scales, adding non-substantive codes, old codes
    and repeat submissions); ingest -> score must decode them exactly."""
    truth = generate_scored_survey(tmp_path, n_respondents=40, seed=5)
    tables = ingest_zeitgeist([truth.export], SurveyConfig(truth.study_id_item))
    out = score_survey(
        tables.items, tables.respondents, load_codebook(truth.codebook),
        ignore=(truth.study_id_item,),
    )  # fmt: skip
    got = _scores(out.scores)
    assert set(got) == set(truth.scores)
    for key, want in truth.scores.items():
        if want is None:
            assert got[key] is None, key
        else:
            assert got[key] == pytest.approx(want), key
    dups = set(out.submissions.filter(pl.col("duplicate_submission"))["respondent"])
    assert dups == truth.duplicates
    assert out.qa["renamed"] == truth.n_renamed
    assert out.qa["validation"] == {"not_in_codebook": [], "not_in_export": []}


# --- CLI -------------------------------------------------------------------------------------


def _study(tmp_path: Path, frozen: bool) -> Path:
    data = tmp_path / "data" / "synthetic-camp"
    raw = data / "raw" / "survey" / "zeitgeist" / "agent_x"
    raw.mkdir(parents=True)
    (raw / "responses.jsonl").write_bytes(EXPORT.read_bytes())
    (data / "local.yaml").write_text("survey:\n  zeitgeist:\n    study_id_item: q_pre\n")
    study = tmp_path / "study" / "study.yaml"
    study.parent.mkdir()
    (study.parent / "codebook.yaml").write_bytes(CODEBOOK.read_bytes())
    frozen_line = '"2026-01-01 abc1234"' if frozen else "null"
    study.write_text(
        "study_id: synthetic-camp\ntimezone: UTC\n"
        f"survey:\n  codebook: codebook.yaml\n  analysis_plan_frozen: {frozen_line}\n"
    )
    return study


def test_score_survey_cli_writes_scores_reliability_and_qa(tmp_path, monkeypatch):
    monkeypatch.setenv("SOCIAL_ENERGY_DATA", str(tmp_path / "data"))
    study = _study(tmp_path, frozen=True)
    assert cli.main(["ingest-survey", str(study)]) == 0
    assert cli.main(["score-survey", str(study)]) == 0
    out = tmp_path / "data" / "synthetic-camp" / "derived" / "survey" / "scoring"
    assert pl.read_parquet(out / "scores.parquet").height == 15
    assert set(pl.read_parquet(out / "reliability.parquet")["group"]) == {"belong", "agency"}
    assert pl.read_parquet(out / "submissions.parquet").height == 5
    qa = json.loads((out / "qa.json").read_text())
    assert qa["validation"]["not_in_codebook"] == ["ZZZ"]  # q_pre is the study-ID item
    # The ingest QA next door is untouched.
    assert "rows_out" in json.loads((out.parent / "qa.json").read_text())


def test_score_survey_cli_refuses_before_the_analysis_plan_is_frozen(tmp_path, monkeypatch):
    monkeypatch.setenv("SOCIAL_ENERGY_DATA", str(tmp_path / "data"))
    study = _study(tmp_path, frozen=False)
    assert cli.main(["ingest-survey", str(study)]) == 0
    assert cli.main(["score-survey", str(study)]) == 3
    assert not (tmp_path / "data" / "synthetic-camp" / "derived" / "survey" / "scoring").exists()


# --- the study codebook ----------------------------------------------------------------------


def test_study_codebooks_load_and_carry_no_own_item_wording():
    for path in (REPO / "studies").glob("*/survey_codebook.yaml"):
        cb = load_codebook(path)
        assert cb.groups, path
        for key in cb.groups.values():
            # Codes and short concept labels only: nothing long enough to be item wording.
            assert len(key.concept) <= 60, (path, key.concept)
