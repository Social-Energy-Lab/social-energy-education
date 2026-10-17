"""A synthetic survey export in the zeitgeist-platform format, with known answers.

It reproduces the traps of the real export: unanswered items are absent, a
"don't know" option is a code rather than a number, some values fall outside the
scale, and respondents on an older form version carry an item that exists only
in the flat view. Item codes and answers are invented.
"""

from __future__ import annotations

import json
import random
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

# (item code, type, scale_max); scale_max None = open number
ITEMS: tuple[tuple[str, str, int | None], ...] = (
    ("S1.Q1", "single_choice", 4),
    ("S1.Q2", "single_choice", 4),
    ("S2.Q1", "single_choice", 5),
    ("S3.Q1", "single_choice", 6),  # has a "DK" code option
    ("SL", "number", None),
)
STUDY_ID_ITEM = "q_id"
OLD_ITEM = "OLD_1"  # only in form version 16, only in the flat view
DONT_KNOW = "DK"


@dataclass(frozen=True)
class SurveyTruth:
    numeric: dict[tuple[str, str], int]  # (respondent, item) -> value, incl. study ID item
    study_ids: dict[str, str]
    n_out_of_range: int
    n_flat_only: int


def _label(text: str) -> dict[str, str]:
    return {"de": text, "en": text}


def generate_survey(path: Path, n_respondents: int = 20, seed: int = 1) -> SurveyTruth:
    rng = random.Random(seed)
    numeric: dict[tuple[str, str], int] = {}
    study_ids: dict[str, str] = {}
    out_of_range = flat_only = 0
    start = datetime(2026, 1, 1, 9, 0)
    lines = []
    for i in range(n_respondents):
        respondent = f"r-{i:03d}"
        study_id = 100 + i
        study_ids[respondent] = str(study_id)
        numeric[(respondent, STUDY_ID_ITEM)] = study_id
        version = 16 if i % 5 == 0 else 18
        resolved = [
            {"question_id": STUDY_ID_ITEM, "type": "number", "phase": "pre", "required": True,
             "label": _label("id"), "value_raw": str(study_id), "value_numeric": study_id,
             "value_label": None},
        ]  # fmt: skip
        flat: dict[str, object] = {"__survey_version": version}
        for item, typ, scale_max in ITEMS:
            if rng.random() < 0.1:
                continue  # unanswered: absent from the export
            if item == "S3.Q1" and rng.random() < 0.2:
                raw, value = DONT_KNOW, None
            elif scale_max is not None and rng.random() < 0.05:
                value = scale_max + 1
                raw = str(value)
                out_of_range += 1
            else:
                value = rng.randint(1, scale_max or 10)
                raw = str(value)
            if value is not None:
                numeric[(respondent, item)] = value
            entry = {"question_id": item, "type": typ, "phase": "post", "required": True,
                     "label": _label(item), "value_raw": raw, "value_numeric": value,
                     "value_label": _label(raw) if typ == "single_choice" else None}  # fmt: skip
            if scale_max is not None:
                entry["scale_max"] = scale_max
            resolved.append(entry)
            flat[item] = raw
        if version == 16:
            value = rng.randint(1, 4)
            flat[OLD_ITEM] = str(value)
            numeric[(respondent, OLD_ITEM)] = value
            flat_only += 1
        submitted = (start + timedelta(hours=i)).isoformat(sep=" ") + ".000000+02:00"
        lines.append(
            json.dumps(
                {
                    "user_id": respondent,
                    "surveys_resolved_at": submitted,
                    "responses": flat,
                    "surveys_resolved": resolved,
                }
            )
        )
    Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")
    return SurveyTruth(numeric, study_ids, out_of_range, flat_only)


# --- scoring: a synthetic codebook and an export with known scale scores ----------------------

SCORED_CODEBOOK = """\
# Synthetic codebook written by social_energy.synth.survey. Every code is invented.
title: synthetic
version: 1
roles: {B: trust_in_life, C: lust_for_life}
min_share: 0.5
min_share_status: confirmed
renames:
  OLD_S_GRAD: {to: S_GRAD, status: confirmed}
groups:
  warm:
    {block: B, role: trust_in_life, kind: scale, concept: synthetic warmth, prefix: "W.",
     items: [Q1, Q2, Q3, Q4, Q5], range: [1, 4], printed_reversed: true, reverse: [Q2, Q5],
     reverse_status: confirmed, missing_codes: ["9"]}
  spark:
    {block: C, role: lust_for_life, kind: scale, concept: synthetic spark, prefix: "S.",
     items: [Q1, Q2, Q3, Q4], range: [1, 5], reverse: [Q3], reverse_status: confirmed,
     missing_codes: [DK], min_items: 2}
  levels:
    {block: B, role: trust_in_life, kind: scale, concept: synthetic coded levels,
     items: [L1, L2, L3], range: [1, 4], reverse_status: confirmed,
     code_values: {L_1: 1, L_2: 2, L_3: 3, L_4: 4}, missing_codes: [L_X]}
  spark_grad:
    {block: C, role: lust_for_life, kind: gradient, concept: synthetic spark gradient,
     parent: spark, items: [S_GRAD], range: [1, 4]}
unscored:
  background: [AGE]
"""

# group -> (export codes, (min, max), printed reversed, reverse-keyed codes, missing code,
#           min items, coded as "L_<n>")
_SCORED = {
    "warm": ([f"W.Q{i}" for i in range(1, 6)], (1, 4), True, {"W.Q2", "W.Q5"}, "9", 3, False),
    "spark": ([f"S.Q{i}" for i in range(1, 5)], (1, 5), False, {"S.Q3"}, "DK", 2, False),
    "levels": (["L1", "L2", "L3"], (1, 4), False, set(), "L_X", 2, True),
    "spark_grad": (["S_GRAD"], (1, 4), False, set(), None, 1, False),
}
SCORED_STUDY_ID_ITEM = "q_sid"


@dataclass(frozen=True)
class ScoredSurveyTruth:
    export: Path
    codebook: Path
    study_id_item: str
    scores: dict[tuple[str, str], float | None]  # (respondent, group) -> mean, None below min
    duplicates: set[str]
    n_renamed: int


def _answers(rng: random.Random, sparse: bool) -> tuple[dict[str, str], dict[str, float | None]]:
    """Printed answers and the true score per group, from construct-direction values."""
    printed: dict[str, str] = {}
    truth: dict[str, float | None] = {}
    for group, (codes, (lo, hi), flipped, reverse, missing, min_items, coded) in _SCORED.items():
        valid = []
        for code in codes:
            if rng.random() < (0.75 if sparse else 0.1):
                continue  # unanswered
            roll = rng.random()
            if missing is not None and roll < 0.08:
                printed[code] = missing
                continue
            if not coded and roll < 0.12:
                printed[code] = str(hi + 1)  # out of range: never valid
                continue
            true = rng.randint(lo, hi)  # high = more of the construct
            shown = lo + hi - true if code in reverse else true
            shown = lo + hi - shown if flipped else shown
            printed[code] = f"L_{shown}" if coded else str(shown)
            valid.append(true)
        truth[group] = sum(valid) / len(valid) if len(valid) >= min_items else None
    return printed, truth


def generate_scored_survey(
    directory: Path, n_respondents: int = 40, seed: int = 1
) -> ScoredSurveyTruth:
    """Write ``codebook.yaml`` and ``responses.jsonl`` under ``directory``.

    Every 5th respondent is on form version 16, where the gradient carries its old code
    (flat view only). Every 7th study ID is submitted a second time, earlier and sparser:
    that second record is the duplicate. Values are invented."""
    rng = random.Random(seed)
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    codebook = directory / "codebook.yaml"
    codebook.write_text(SCORED_CODEBOOK, encoding="utf-8")
    start = datetime(2026, 1, 1, 9, 0)
    scores: dict[tuple[str, str], float | None] = {}
    duplicates: set[str] = set()
    n_renamed = 0
    lines = []

    def record(respondent: str, typed: str, version: int, when: datetime, sparse: bool) -> None:
        nonlocal n_renamed
        printed, truth = _answers(rng, sparse)
        for group, value in truth.items():
            scores[(respondent, group)] = value
        printed["AGE"] = str(rng.randint(12, 19))
        resolved = [
            {"question_id": SCORED_STUDY_ID_ITEM, "type": "number", "phase": "pre",
             "required": True, "label": _label("id"), "value_raw": typed,
             "value_numeric": None, "value_label": None},
        ]  # fmt: skip
        flat: dict[str, object] = {"__survey_version": version}
        for code, raw in printed.items():
            if code == "S_GRAD" and version == 16:
                flat["OLD_S_GRAD"] = raw  # older form: old code, flat view only
                n_renamed += 1
                continue
            numeric = int(raw) if raw.isdigit() else None
            resolved.append(
                {"question_id": code, "type": "single_choice", "phase": "post",
                 "required": False, "label": _label(code), "value_raw": raw,
                 "value_numeric": numeric, "value_label": _label(raw)}
            )  # fmt: skip
            flat[code] = raw
        lines.append(
            json.dumps(
                {
                    "user_id": respondent,
                    "surveys_resolved_at": when.isoformat(sep=" ") + "+00:00",
                    "responses": flat,
                    "surveys_resolved": resolved,
                }
            )
        )

    for i in range(n_respondents):
        version = 16 if i % 5 == 0 else 18
        when = start + timedelta(hours=i)
        record(f"p-{i:03d}", str(500 + i), version, when, sparse=False)
        if i % 7 == 3:
            repeat = f"p-{i:03d}-again"
            # Same ID typed with stray whitespace; earlier and sparser, so it loses either way.
            record(repeat, f" {500 + i} ", version, when - timedelta(days=1), sparse=True)
            duplicates.add(repeat)
    export = directory / "responses.jsonl"
    export.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return ScoredSurveyTruth(export, codebook, SCORED_STUDY_ID_ITEM, scores, duplicates, n_renamed)
