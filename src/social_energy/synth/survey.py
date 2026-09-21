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
