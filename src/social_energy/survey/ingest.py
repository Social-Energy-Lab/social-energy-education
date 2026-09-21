"""zeitgeist-platform survey export → one row per respondent and answered item.

The export (``responses.jsonl``, one respondent per line) holds two views of the
answers, and neither is complete alone (see docs/context/instruments/survey.md):

* ``surveys_resolved``: a list of items with type, scale and labels. Items that exist
  only in an older form version are missing from it.
* ``responses``: flat ``{item_code: value}`` plus ``__survey_version``. Items asked
  before the interview are missing from it.

Rows come from ``surveys_resolved``, plus one row per item found only in the flat
view (``flat_only``). Nothing is dropped. Suspicious rows are flagged and ``ok`` is
false for ``empty`` and ``out_of_range``. Rows are keyed by the platform user UUID
(``respondent``); the spine resolves it to a person as a ``zeitgeist:<uuid>``
assignment.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import polars as pl

VERSION_KEY = "__survey_version"
_INT = re.compile(r"-?\d+")


@dataclass(frozen=True)
class SurveyConfig:
    # Platform question ID of the item holding the study ID typed before the interview.
    study_id_item: str | None = None


@dataclass(frozen=True)
class SurveyTables:
    items: pl.DataFrame
    respondents: pl.DataFrame
    qa: dict[str, Any]


_ITEM_SCHEMA = {
    "respondent": pl.String,
    "item": pl.String,
    "block": pl.String,
    "type": pl.String,
    "phase": pl.String,
    "required": pl.Boolean,
    "value_raw": pl.String,
    "value_numeric": pl.Int64,
    "value_code": pl.String,
    "value_label_de": pl.String,
    "value_label_en": pl.String,
    "scale_max": pl.Int64,
    "survey_version": pl.Int64,
    "submitted_at": pl.Datetime("us", "UTC"),
    "source": pl.String,
    "line_no": pl.Int64,
    "free_text": pl.Boolean,
    "flat_only": pl.Boolean,
    "mismatch": pl.Boolean,
    "empty": pl.Boolean,
    "out_of_range": pl.Boolean,
    "ok": pl.Boolean,
}
_RESPONDENT_SCHEMA = {
    "respondent": pl.String,
    "survey_version": pl.Int64,
    "submitted_at": pl.Datetime("us", "UTC"),
    "study_id_raw": pl.String,
    "n_items": pl.Int64,
    "n_ok": pl.Int64,
    "source": pl.String,
    "line_no": pl.Int64,
}


def _as_int(value: Any) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value
    text = str(value).strip()
    return int(text) if _INT.fullmatch(text) else None


def _label(value: Any, lang: str) -> str | None:
    return value.get(lang) if isinstance(value, dict) else None


def _row(respondent: str, item: str, meta: dict[str, Any]) -> dict[str, Any]:
    raw = "" if meta.get("value_raw") is None else str(meta["value_raw"])
    typ = meta.get("type")
    numeric = _as_int(meta.get("value_numeric"))
    if numeric is None and typ is None:  # flat-only: no type, so parse the raw value
        numeric = _as_int(raw)
    free_text = typ == "text"
    code = raw if raw and numeric is None and typ not in ("text", "number") else None
    scale_max = _as_int(meta.get("scale_max"))
    return {
        "respondent": respondent,
        "item": item,
        "block": item.split(".", 1)[0] if "." in item else None,
        "type": typ,
        "phase": meta.get("phase"),
        "required": meta.get("required"),
        "value_raw": raw,
        "value_numeric": numeric,
        "value_code": code,
        "value_label_de": _label(meta.get("value_label"), "de"),
        "value_label_en": _label(meta.get("value_label"), "en"),
        "scale_max": scale_max,
        "free_text": free_text,
        "empty": raw.strip() == "",
        "out_of_range": numeric is not None
        and scale_max is not None
        and not 0 <= numeric <= scale_max,
    }


def _submitted_at(value: Any) -> datetime | None:
    if not value:
        return None
    t = datetime.fromisoformat(str(value))
    if t.tzinfo is None:
        raise ValueError(f"survey timestamp without UTC offset: {value!r}")
    return t.astimezone(UTC)


def ingest_zeitgeist(paths: Iterable[Path], config: SurveyConfig) -> SurveyTables:
    items: list[dict[str, Any]] = []
    respondents: list[dict[str, Any]] = []
    versions: Counter[str] = Counter()
    resolved_in = flat_in = files = 0

    for path in paths:
        files += 1
        lines = Path(path).read_text(encoding="utf-8").splitlines()
        for line_no, line in enumerate(lines, start=1):
            if not line.strip():
                continue
            record = json.loads(line)
            respondent = str(record["user_id"])
            flat = dict(record.get("responses") or {})
            version = _as_int(flat.pop(VERSION_KEY, None))
            versions[str(version)] += 1
            resolved = record.get("surveys_resolved") or []
            resolved_in += len(resolved)
            flat_in += len(flat)
            common = {
                "survey_version": version,
                "submitted_at": _submitted_at(record.get("surveys_resolved_at")),
                "source": str(path),
                "line_no": line_no,
            }
            rows = []
            seen = set()
            for meta in resolved:
                item = meta["question_id"]
                seen.add(item)
                row = _row(respondent, item, meta)
                flat_value = flat.get(item)
                row["mismatch"] = flat_value is not None and str(flat_value) != row["value_raw"]
                row["flat_only"] = False
                rows.append(row)
            for item, value in flat.items():
                if item in seen:
                    continue
                row = _row(respondent, item, {"value_raw": value})
                row["mismatch"] = False
                row["flat_only"] = True
                rows.append(row)
            for row in rows:
                row.update(common)
                row["ok"] = not (row["empty"] or row["out_of_range"])
            items.extend(rows)

            study_id = next(
                (r["value_raw"] for r in rows if r["item"] == config.study_id_item), None
            )
            respondents.append(
                {
                    "respondent": respondent,
                    **{k: common[k] for k in ("survey_version", "submitted_at")},
                    "study_id_raw": study_id or None,
                    "n_items": len(rows),
                    "n_ok": sum(r["ok"] for r in rows),
                    **{k: common[k] for k in ("source", "line_no")},
                }
            )

    item_df = pl.DataFrame(items, schema=_ITEM_SCHEMA)
    qa: dict[str, Any] = {
        "files": files,
        "respondents": len(respondents),
        "survey_versions": dict(sorted(versions.items())),
        "resolved_items_in": resolved_in,
        "flat_items_in": flat_in,
        "rows_out": item_df.height,
    }
    for flag in ("flat_only", "mismatch", "empty", "out_of_range", "free_text"):
        qa[flag] = int(item_df[flag].sum())
    qa["not_ok"] = int((~item_df["ok"]).sum())
    return SurveyTables(item_df, pl.DataFrame(respondents, schema=_RESPONDENT_SCHEMA), qa)
