"""Ingested survey items + a codebook → recoded items, scale scores, reliability and QA.

Pure functions on the tables ``ingest_zeitgeist`` returns. Nothing is dropped silently:
repeat submissions are flagged ``duplicate_submission`` and still scored, missing values carry
a reason, and the QA dict accounts for every respondent and every non-substantive or
out-of-range answer.

Repeat submissions: one study ID on several respondent records is the same person submitting
again. Keep the most complete record (most answered items); ties go to the later
``submitted_at``, then to the later line of the export. The others are flagged. Respondents
without a study ID are never duplicates of each other; they are flagged ``no_study_id``.

Reliability is computed on the kept submissions only, so nobody counts twice, and on complete
cases within each scale.
"""

from __future__ import annotations

import csv
import fnmatch
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl

from .. import paths
from .codebook import Codebook

_INT = re.compile(r"-?\d+")
_WILDCARD = re.compile(r"[*?\[]")

_RECODED_SCHEMA = {
    "respondent": pl.String,
    "item": pl.String,
    "group": pl.String,
    "kind": pl.String,
    "value_in": pl.Int64,
    "value": pl.Float64,
    "missing": pl.String,
    "renamed_from": pl.String,
}


# --- study IDs and repeat submissions ----------------------------------------------------------


def normalise_study_id(value: Any) -> str | None:
    """Typed study ID → canonical form: all whitespace removed, upper case; blank → None."""
    if value is None:
        return None
    text = re.sub(r"\s+", "", str(value)).upper()
    return text or None


@dataclass(frozen=True)
class StudyIdCorrections:
    """The team's local correction table. Lives in the private data root, never in the repo.

    A row matches a respondent record (``respondent``, the platform UUID) or a typed value
    (``typed``, compared after normalisation). A respondent match wins over a typed match.
    """

    by_respondent: dict[str, str] = field(default_factory=dict)
    by_typed: dict[str, str] = field(default_factory=dict)


def load_corrections(path: Path) -> StudyIdCorrections:
    """Read a CSV with the columns ``respondent,typed,study_id`` (one of the first two set)."""
    resolved = paths.refuse_inside_repo(Path(path))
    by_respondent: dict[str, str] = {}
    by_typed: dict[str, str] = {}
    with resolved.open(encoding="utf-8", newline="") as handle:
        for line_no, row in enumerate(csv.DictReader(handle), start=2):
            target = normalise_study_id(row.get("study_id"))
            respondent = (row.get("respondent") or "").strip()
            typed = normalise_study_id(row.get("typed"))
            if target is None or bool(respondent) == bool(typed):
                raise ValueError(
                    f"{resolved}:{line_no}: needs a study_id and exactly one of respondent/typed"
                )
            if respondent:
                by_respondent[respondent] = target
            else:
                by_typed[typed] = target
    return StudyIdCorrections(by_respondent, by_typed)


def resolve_submissions(
    respondents: pl.DataFrame,
    items: pl.DataFrame,
    corrections: StudyIdCorrections | None = None,
) -> pl.DataFrame:
    """One row per respondent record with its study ID and the repeat-submission flags."""
    corrections = corrections or StudyIdCorrections()
    answered = dict(items.filter(~pl.col("empty")).group_by("respondent").len().iter_rows())
    rows = []
    for r in respondents.iter_rows(named=True):
        typed = normalise_study_id(r["study_id_raw"])
        if r["respondent"] in corrections.by_respondent:
            study_id, corrected = corrections.by_respondent[r["respondent"]], True
        elif typed is not None and typed in corrections.by_typed:
            study_id, corrected = corrections.by_typed[typed], True
        else:
            study_id, corrected = typed, False
        rows.append(
            {
                "respondent": r["respondent"],
                "study_id_raw": r["study_id_raw"],
                "study_id": study_id,
                "corrected": corrected,
                "n_answered": answered.get(r["respondent"], 0),
                "submitted_at": r["submitted_at"],
                "source": r["source"],
                "line_no": r["line_no"],
            }
        )
    keep: set[str] = set()
    by_id: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        if row["study_id"] is None:
            keep.add(row["respondent"])
        else:
            by_id.setdefault(row["study_id"], []).append(row)
    for claims in by_id.values():
        best = max(
            claims,
            key=lambda c: (
                c["n_answered"],
                c["submitted_at"] is not None,
                c["submitted_at"] or 0,
                c["source"] or "",
                c["line_no"] or 0,
            ),
        )
        keep.add(best["respondent"])
    for row in rows:
        row["no_study_id"] = row["study_id"] is None
        row["duplicate_submission"] = row["respondent"] not in keep
    schema = {
        "respondent": pl.String,
        "study_id_raw": pl.String,
        "study_id": pl.String,
        "corrected": pl.Boolean,
        "n_answered": pl.Int64,
        "submitted_at": pl.Datetime("us", "UTC"),
        "source": pl.String,
        "line_no": pl.Int64,
        "no_study_id": pl.Boolean,
        "duplicate_submission": pl.Boolean,
    }
    return pl.DataFrame(rows, schema=schema)


# --- codebook vs export ------------------------------------------------------------------------


def _matches(entry: str, seen: set[str]) -> bool:
    if _WILDCARD.search(entry):
        return any(fnmatch.fnmatchcase(code, entry) for code in seen)
    return entry in seen


def validate_against(
    items: pl.DataFrame, codebook: Codebook, ignore: tuple[str, ...] = ()
) -> dict[str, list[str]]:
    """Codes in the export the codebook does not know, and codebook entries never seen."""
    seen = set(items["item"].unique().to_list())
    return {
        "not_in_codebook": sorted(c for c in seen if c not in ignore and not codebook.knows(c)),
        "not_in_export": sorted(e for e in codebook.entries() if not _matches(e, seen)),
    }


# --- recoding ----------------------------------------------------------------------------------


def _apply_renames(items: pl.DataFrame, codebook: Codebook) -> tuple[pl.DataFrame, int, int]:
    """Old-version codes → current codes. If a record has both, the current code wins."""
    if not codebook.renames:
        return items.with_columns(pl.lit(None, pl.String).alias("renamed_from")), 0, 0
    mapping = {old: rename.to for old, rename in codebook.renames.items()}
    is_old = pl.col("item").is_in(list(mapping))
    present = set(items.filter(~is_old).select("respondent", "item").iter_rows())
    old = items.filter(is_old).with_columns(
        pl.col("item").alias("renamed_from"), pl.col("item").replace_strict(mapping)
    )
    clash = pl.Series(
        [(r, i) in present for r, i in old.select("respondent", "item").iter_rows()],
        dtype=pl.Boolean,
    )
    renamed = old.filter(~clash)
    current = items.filter(~is_old).with_columns(pl.lit(None, pl.String).alias("renamed_from"))
    out = pl.concat([current, renamed.select(current.columns)], how="vertical")
    return out, renamed.height, int(clash.sum())


def _value(
    row: dict[str, Any], codebook: Codebook, key: str
) -> tuple[int | None, float | None, str | None]:
    group = codebook.groups[key]
    raw = (row["value_raw"] or "").strip()
    if row["empty"] or raw == "":
        return None, None, "empty"
    if raw in group.missing_codes:
        return None, None, "non_substantive"
    x = row["value_numeric"]
    if x is None:
        x = group.code_values.get(raw)
    if x is None and _INT.fullmatch(raw):
        x = int(raw)
    if x is None:
        return None, None, "not_numeric"
    lo, hi = group.range
    if not lo <= x <= hi:
        return x, None, "out_of_range"
    v = x
    if group.printed_reversed:
        v = lo + hi - v
    if row["item"] in group.reverse_codes:
        v = lo + hi - v
    return x, float(v), None


def _recode(items: pl.DataFrame, codebook: Codebook) -> tuple[pl.DataFrame, int, int]:
    items, renamed, conflicts = _apply_renames(items, codebook)
    index = codebook.item_index()
    rows = []
    for row in items.filter(pl.col("item").is_in(list(index))).iter_rows(named=True):
        key = index[row["item"]]
        value_in, value, missing = _value(row, codebook, key)
        rows.append(
            {
                "respondent": row["respondent"],
                "item": row["item"],
                "group": key,
                "kind": codebook.groups[key].kind,
                "value_in": value_in,
                "value": value,
                "missing": missing,
                "renamed_from": row["renamed_from"],
            }
        )
    return pl.DataFrame(rows, schema=_RECODED_SCHEMA), renamed, conflicts


def recode(items: pl.DataFrame, codebook: Codebook) -> pl.DataFrame:
    """One row per respondent and codebook item: the recoded ``value`` or a ``missing`` reason.

    Reasons: ``empty``, ``non_substantive``, ``not_numeric``, ``out_of_range``. Items outside
    the codebook's groups (unscored, unknown) are left out; ``validate_against`` reports them.
    """
    return _recode(items, codebook)[0]


# --- scores ------------------------------------------------------------------------------------


def _respondent_frame(items: pl.DataFrame, submissions: pl.DataFrame | None) -> pl.DataFrame:
    if submissions is not None:
        return submissions.select("respondent", "study_id", "duplicate_submission")
    return (
        items.select("respondent")
        .unique()
        .with_columns(
            pl.lit(None, pl.String).alias("study_id"), pl.lit(False).alias("duplicate_submission")
        )
    )


def _score(recoded: pl.DataFrame, codebook: Codebook, people: pl.DataFrame) -> pl.DataFrame:
    meta = pl.DataFrame(
        [
            {
                "group": key,
                "block": g.block,
                "role": g.role,
                "kind": g.kind,
                "concept": g.concept,
                "n_expected": len(g.items),
                "min_items": g.min_items_required(codebook.min_share),
                "provisional": codebook.is_provisional(key),
            }
            for key, g in codebook.groups.items()
            if g.kind in ("scale", "gradient")
        ],
        schema={
            "group": pl.String, "block": pl.String, "role": pl.String, "kind": pl.String,
            "concept": pl.String, "n_expected": pl.Int64, "min_items": pl.Int64,
            "provisional": pl.Boolean,
        },
    )  # fmt: skip
    agg = (
        recoded.filter(pl.col("value").is_not_null())
        .group_by("respondent", "group")
        .agg(pl.col("value").mean().alias("item_mean"), pl.len().cast(pl.Int64).alias("n_items"))
    )
    return (
        people.join(meta, how="cross")
        .join(agg, on=["respondent", "group"], how="left")
        .with_columns(pl.col("n_items").fill_null(0))
        .with_columns(
            pl.when(pl.col("n_items") >= pl.col("min_items"))
            .then(pl.col("item_mean"))
            .otherwise(None)
            .alias("mean")
        )
        .select(
            "respondent",
            "study_id",
            "duplicate_submission",
            "group",
            "block",
            "role",
            "kind",
            "concept",
            "mean",
            "n_items",
            "n_expected",
            "min_items",
            "provisional",
        )
        .sort("respondent", "group")
    )


def score(
    items: pl.DataFrame, codebook: Codebook, submissions: pl.DataFrame | None = None
) -> pl.DataFrame:
    """One row per respondent per scale or gradient: item ``mean`` (null below ``min_items``)
    and ``n_items`` (valid items used). Repeat submissions are scored and flagged."""
    recoded = recode(items, codebook)
    return _score(recoded, codebook, _respondent_frame(items, submissions))


# --- reliability -------------------------------------------------------------------------------


def cronbach_alpha(matrix: np.ndarray) -> float:
    """Cronbach's alpha for a complete respondents x items matrix (sample variances)."""
    x = np.asarray(matrix, dtype=float)
    n, k = x.shape
    if k < 2 or n < 2:
        return float("nan")
    total = x.sum(axis=1).var(ddof=1)
    if total == 0:
        return float("nan")
    return float(k / (k - 1) * (1 - x.var(axis=0, ddof=1).sum() / total))


def mcdonald_omega(matrix: np.ndarray, max_iter: int = 500, tol: float = 1e-8) -> float:
    """McDonald's omega (total) from a one-factor model of the standardised items.

    Loadings come from iterated principal-axis factoring of the correlation matrix (start:
    squared multiple correlations); omega = (Σλ)² / ((Σλ)² + Σ(1 - λ²)). Not a CFA/ML fit, so
    it can differ slightly from omega reported by SEM software. Needs at least three items.
    """
    x = np.asarray(matrix, dtype=float)
    n, k = x.shape
    if k < 3 or n <= k or np.any(x.std(axis=0) == 0):
        return float("nan")
    r = np.corrcoef(x, rowvar=False)
    try:
        h2 = 1 - 1 / np.diag(np.linalg.inv(r))
    except np.linalg.LinAlgError:
        h2 = np.max(np.abs(r - np.eye(k)), axis=1)
    loadings = np.sqrt(np.clip(h2, 0, 1))
    for _ in range(max_iter):
        reduced = r.copy()
        np.fill_diagonal(reduced, h2)
        values, vectors = np.linalg.eigh(reduced)
        loadings = vectors[:, -1] * np.sqrt(max(values[-1], 0.0))
        new_h2 = np.clip(loadings**2, 0, 0.999)
        if np.max(np.abs(new_h2 - h2)) < tol:
            h2 = new_h2
            break
        h2 = new_h2
    if loadings.sum() < 0:
        loadings = -loadings
    common = loadings.sum() ** 2
    return float(common / (common + np.sum(1 - np.clip(loadings**2, 0, 0.999))))


def _reliability(recoded: pl.DataFrame, codebook: Codebook, kept: set[str] | None) -> pl.DataFrame:
    rows = []
    for key, group in codebook.groups.items():
        if group.kind != "scale":
            continue
        values = recoded.filter((pl.col("group") == key) & pl.col("value").is_not_null())
        if kept is not None:
            values = values.filter(pl.col("respondent").is_in(list(kept)))
        wide = values.pivot(on="item", index="respondent", values="value")
        complete = (
            wide.select(group.codes).drop_nulls() if set(group.codes) <= set(wide.columns) else None
        )
        n = 0 if complete is None else complete.height
        alpha = omega = None
        if complete is not None and n >= 3:
            matrix = complete.to_numpy()
            alpha, omega = cronbach_alpha(matrix), mcdonald_omega(matrix)
            alpha = None if np.isnan(alpha) else alpha
            omega = None if np.isnan(omega) else omega
        rows.append(
            {
                "group": key, "block": group.block, "role": group.role,
                "k": len(group.items), "n_complete": n, "alpha": alpha, "omega": omega,
                "provisional": codebook.is_provisional(key),
            }
        )  # fmt: skip
    schema = {
        "group": pl.String, "block": pl.String, "role": pl.String, "k": pl.Int64,
        "n_complete": pl.Int64, "alpha": pl.Float64, "omega": pl.Float64,
        "provisional": pl.Boolean,
    }  # fmt: skip
    return pl.DataFrame(rows, schema=schema)


def _kept(submissions: pl.DataFrame | None) -> set[str] | None:
    if submissions is None:
        return None
    return set(submissions.filter(~pl.col("duplicate_submission"))["respondent"])


def reliability(
    items: pl.DataFrame, codebook: Codebook, submissions: pl.DataFrame | None = None
) -> pl.DataFrame:
    """Alpha and omega per scale, on complete cases of the kept submissions (needs n ≥ 3)."""
    return _reliability(recode(items, codebook), codebook, _kept(submissions))


# --- everything at once ------------------------------------------------------------------------


@dataclass(frozen=True)
class ScoreTables:
    recoded: pl.DataFrame
    scores: pl.DataFrame
    reliability: pl.DataFrame
    submissions: pl.DataFrame
    qa: dict[str, Any]


def _counts(recoded: pl.DataFrame, reason: str) -> dict[str, int]:
    hits = recoded.filter(pl.col("missing") == reason)
    return dict(sorted(Counter(hits["item"].to_list()).items()))


def score_survey(
    items: pl.DataFrame,
    respondents: pl.DataFrame,
    codebook: Codebook,
    corrections: StudyIdCorrections | None = None,
    ignore: tuple[str, ...] = (),
) -> ScoreTables:
    """Resolve submissions, recode, score, estimate reliability and account for all of it.

    ``ignore`` names export codes that are deliberately outside the codebook (the private
    study-ID question)."""
    submissions = resolve_submissions(respondents, items, corrections)
    recoded, renamed, conflicts = _recode(items, codebook)
    scores = _score(
        recoded, codebook, submissions.select("respondent", "study_id", "duplicate_submission")
    )
    kept = _kept(submissions)
    rel = _reliability(recoded, codebook, kept)

    valid = recoded.filter(pl.col("value").is_not_null() & pl.col("respondent").is_in(list(kept)))
    answered = Counter(valid["item"].to_list())
    codes = [code for g in codebook.groups.values() for code in g.codes]
    qa: dict[str, Any] = {
        "codebook": {"title": codebook.title, "version": codebook.version},
        "validation": validate_against(items, codebook, ignore),
        "out_of_range": _counts(recoded, "out_of_range"),
        "non_substantive": _counts(recoded, "non_substantive"),
        "not_numeric": _counts(recoded, "not_numeric"),
        "renamed": renamed,
        "rename_conflicts": conflicts,
        "submissions": {
            "respondents": submissions.height,
            "with_study_id": int((~submissions["no_study_id"]).sum()),
            "no_study_id": int(submissions["no_study_id"].sum()),
            "distinct_study_ids": submissions["study_id"].drop_nulls().n_unique(),
            "duplicate_submission": int(submissions["duplicate_submission"].sum()),
            "kept": len(kept),
            "corrected": int(submissions["corrected"].sum()),
        },
        "scores": {"rows": scores.height, "null_mean": scores["mean"].null_count()},
        "missing": {
            "kept_respondents": len(kept),
            "items": {code: len(kept) - answered.get(code, 0) for code in codes},
        },
        "pending": codebook.pending(),
    }
    return ScoreTables(recoded, scores, rel, submissions, qa)
