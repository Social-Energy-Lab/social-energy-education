"""Checks on the survey's items that come before any scale is scored.

Neither check computes or writes a scale score, and neither joins the survey to anything else.

* ``reverse_key_check``: does each item run with or against the rest of its scale? For every
  item of every ``scale`` group, the Pearson correlation of the item, on its own values before
  reverse-keying, with the sum of the scale's other items keyed as the codebook says
  (``r_rest_keyed``). An item marked reversed should correlate negatively; an item not marked
  should correlate positively. The same correlation against the rest left unreversed
  (``r_rest_raw``) is reported alongside: it mixes both directions, so it is the weaker check.
  Both use complete cases of the scale. A printed-reversed scale is flipped as a whole, which
  changes no correlation among its items.
* ``version_equivalence``: does an old form-version code collect the same answers as the
  current code it is renamed to? Per pair: counts over the response range, means, a
  chi-square test of homogeneity (no continuity correction) and a two-sided Mann-Whitney U
  test (normal approximation with tie correction). ``equivalent`` is true when neither test
  rejects at ``alpha``, and null (no verdict) when either code has fewer than ``min_n``
  answers: a handful of answers is not a distribution. A test that does not reject is weak
  evidence with few old-version answers; read the counts too.

Both take the kept submissions only when ``submissions`` is given, so nobody counts twice.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

import numpy as np
import polars as pl

from .codebook import Codebook
from .score import recode

# --- statistics ------------------------------------------------------------------------------


def _gamma_q(a: float, x: float) -> float:
    """Regularised upper incomplete gamma Q(a, x) (series below a + 1, continued fraction above)."""
    if x <= 0:
        return 1.0
    log_front = -x + a * math.log(x) - math.lgamma(a)
    if x < a + 1:
        term = total = 1.0 / a
        n = a
        for _ in range(10_000):
            n += 1
            term *= x / n
            total += term
            if abs(term) < abs(total) * 1e-15:
                break
        return max(0.0, 1.0 - total * math.exp(log_front))
    tiny = 1e-300
    b = x + 1 - a
    c = 1 / tiny
    d = 1 / b
    h = d
    for i in range(1, 10_000):
        an = -i * (i - a)
        b += 2
        d = an * d + b
        d = tiny if abs(d) < tiny else d
        c = b + an / c
        c = tiny if abs(c) < tiny else c
        d = 1 / d
        delta = d * c
        h *= delta
        if abs(delta - 1) < 1e-15:
            break
    return math.exp(log_front) * h


def chi_square_sf(x: float, df: int) -> float:
    """P(X >= x) for X ~ chi-square with ``df`` degrees of freedom."""
    return _gamma_q(df / 2, x / 2)


def chi_square_test(table: Sequence[Sequence[float]]) -> tuple[float, int, float]:
    """Chi-square test of homogeneity on a contingency table, without continuity correction.

    Columns that are empty in every row are dropped first. Returns (statistic, df, p)."""
    t = np.asarray(table, dtype=float)
    t = t[:, t.sum(axis=0) > 0]
    t = t[t.sum(axis=1) > 0]
    rows, cols = t.shape
    df = (rows - 1) * (cols - 1)
    if df == 0:
        return 0.0, 0, 1.0
    expected = np.outer(t.sum(axis=1), t.sum(axis=0)) / t.sum()
    stat = float(((t - expected) ** 2 / expected).sum())
    return stat, df, chi_square_sf(stat, df)


def mann_whitney(a: Sequence[float], b: Sequence[float]) -> tuple[float, float]:
    """Two-sided Mann-Whitney U test. Returns (U of ``a``, p) from the normal approximation
    with tie correction and no continuity correction; p is 1 when every value is tied."""
    x, y = np.asarray(a, dtype=float), np.asarray(b, dtype=float)
    n1, n2 = len(x), len(y)
    u = float((x[:, None] > y[None, :]).sum() + 0.5 * (x[:, None] == y[None, :]).sum())
    n = n1 + n2
    _, ties = np.unique(np.concatenate([x, y]), return_counts=True)
    var = n1 * n2 / 12 * ((n + 1) - float((ties**3 - ties).sum()) / (n * (n - 1)))
    if var <= 0:
        return u, 1.0
    z = (u - n1 * n2 / 2) / math.sqrt(var)
    return u, math.erfc(abs(z) / math.sqrt(2))


def _pearson(x: np.ndarray, y: np.ndarray) -> float | None:
    if len(x) < 3:
        return None
    dx, dy = x - x.mean(), y - y.mean()
    denominator = math.sqrt(float((dx**2).sum() * (dy**2).sum()))
    if denominator == 0:
        return None
    return float((dx * dy).sum()) / denominator


# --- reverse keys ----------------------------------------------------------------------------


def _kept_only(recoded: pl.DataFrame, submissions: pl.DataFrame | None) -> pl.DataFrame:
    if submissions is None:
        return recoded
    kept = submissions.filter(~pl.col("duplicate_submission"))["respondent"]
    return recoded.filter(pl.col("respondent").is_in(kept.to_list()))


_REVERSE_SCHEMA = {
    "group": pl.String,
    "item": pl.String,
    "marked_reverse": pl.Boolean,
    "n": pl.Int64,
    "r_rest_keyed": pl.Float64,
    "r_rest_raw": pl.Float64,
    "agrees": pl.Boolean,
    "finding": pl.String,
}


def reverse_key_check(
    items: pl.DataFrame, codebook: Codebook, submissions: pl.DataFrame | None = None
) -> pl.DataFrame:
    """Per item of every scale: item-rest correlations before reverse-keying (module docstring).

    ``agrees`` is null when the correlation is undefined (fewer than three complete cases, or
    no variance); ``finding`` names a disagreement between the codebook and the data."""
    recoded = _kept_only(recode(items, codebook), submissions)
    rows = []
    for key, group in codebook.groups.items():
        if group.kind != "scale":
            continue
        lo, hi = group.range
        codes = group.codes
        values = recoded.filter((pl.col("group") == key) & pl.col("value").is_not_null())
        wide = values.pivot(on="item", index="respondent", values="value")
        present = set(codes) <= set(wide.columns)
        keyed = wide.select(codes).drop_nulls().to_numpy() if present else np.empty((0, 0))
        flip = np.array([code in group.reverse_codes for code in codes])
        raw = np.where(flip, lo + hi - keyed, keyed) if keyed.size else keyed
        for j, code in enumerate(codes):
            r_keyed = r_raw = None
            if keyed.size:
                rest = np.delete(np.arange(len(codes)), j)
                r_keyed = _pearson(raw[:, j], keyed[:, rest].sum(axis=1))
                r_raw = _pearson(raw[:, j], raw[:, rest].sum(axis=1))
            marked = bool(flip[j])
            agrees = finding = None
            if r_keyed is not None:
                agrees = (r_keyed < 0) if marked else (r_keyed >= 0)
                if not agrees:
                    finding = (
                        "marked reversed but not negative"
                        if marked
                        else "negative but not marked reversed"
                    )
            rows.append(
                {
                    "group": key, "item": code, "marked_reverse": marked,
                    "n": int(keyed.shape[0]) if keyed.size else 0,
                    "r_rest_keyed": r_keyed, "r_rest_raw": r_raw,
                    "agrees": agrees, "finding": finding,
                }
            )  # fmt: skip
    return pl.DataFrame(rows, schema=_REVERSE_SCHEMA)


# --- old form-version codes ------------------------------------------------------------------

_VERSION_SCHEMA = {
    "old": pl.String,
    "new": pl.String,
    "n_old": pl.Int64,
    "n_new": pl.Int64,
    "counts_old": pl.List(pl.Int64),
    "counts_new": pl.List(pl.Int64),
    "mean_old": pl.Float64,
    "mean_new": pl.Float64,
    "chi2": pl.Float64,
    "chi2_df": pl.Int64,
    "chi2_p": pl.Float64,
    "mwu_u": pl.Float64,
    "mwu_p": pl.Float64,
    "equivalent": pl.Boolean,
}


def version_equivalence(
    items: pl.DataFrame,
    codebook: Codebook,
    submissions: pl.DataFrame | None = None,
    alpha: float = 0.05,
    min_n: int = 5,
) -> pl.DataFrame:
    """Per rename (old code -> current code): answer distributions and two tests (docstring).

    Values are the answers as given (non-substantive and out-of-range answers left out),
    before any reversal. ``equivalent`` is null when either side has fewer than ``min_n``."""
    recoded = _kept_only(recode(items, codebook), submissions).filter(pl.col("missing").is_null())
    index = codebook.item_index()
    rows = []
    for old, rename in codebook.renames.items():
        lo, hi = codebook.groups[index[rename.to]].range
        a = recoded.filter(pl.col("renamed_from") == old)["value_in"].to_list()
        b = recoded.filter((pl.col("item") == rename.to) & pl.col("renamed_from").is_null())[
            "value_in"
        ].to_list()
        counts_a = [a.count(v) for v in range(lo, hi + 1)]
        counts_b = [b.count(v) for v in range(lo, hi + 1)]
        row = {
            "old": old, "new": rename.to, "n_old": len(a), "n_new": len(b),
            "counts_old": counts_a, "counts_new": counts_b,
            "mean_old": float(np.mean(a)) if a else None,
            "mean_new": float(np.mean(b)) if b else None,
            "chi2": None, "chi2_df": None, "chi2_p": None, "mwu_u": None, "mwu_p": None,
            "equivalent": None,
        }  # fmt: skip
        if a and b:
            chi2, df, p_chi = chi_square_test([counts_a, counts_b])
            u, p_u = mann_whitney(a, b)
            row.update(
                chi2=chi2, chi2_df=df, chi2_p=p_chi, mwu_u=u, mwu_p=p_u,
                equivalent=(p_chi >= alpha and p_u >= alpha) if min(len(a), len(b)) >= min_n
                else None,
            )  # fmt: skip
        rows.append(row)
    return pl.DataFrame(rows, schema=_VERSION_SCHEMA)
