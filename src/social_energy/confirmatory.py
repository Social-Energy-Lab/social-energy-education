"""Confirmatory tests: composites, fixed-effects models, Holm, within-group permutation.

The pieces a pre-registered person-level test needs, with every choice passed in:

* **Composites** (:func:`zscore`, :func:`composite`): each scale standardised across the rows
  given, the composite the mean of a person's valid standardised scales, null when fewer than
  ``min_valid`` are valid.
* **Design** (:func:`design`): outcome, the predictor standardised over the complete cases (so its
  coefficient is per standard deviation), covariates, and group fixed effects as indicators with
  the first level (sorted) as reference. Rows with a missing value in any column used are left
  out, and the count is returned.
* **Models**: :func:`ols_hc3`, linear regression with HC3 standard errors and t inference on the
  residual degrees of freedom; :func:`negbin`, a negative binomial (NB2, dispersion estimated by
  maximum likelihood) of a count with ``log(exposure)`` as offset, Wald inference. Each returns a
  :class:`Fit` for the predictor's coefficient, with a standardised effect: the coefficient over
  the outcome's standard deviation for OLS, the rate ratio per standard deviation for NB.
* **Error control** (:func:`holm`): Holm's step-down adjustment.
* **Permutation** (:func:`permute_within`, :func:`permutation_test`): the predictor shuffled among
  rows of the same group, everything else kept with its row; p-values count the observed
  statistic as one of the permutations, so they are never zero.
* **Fragility** (:func:`flips`): whether a rerun changed the sign or the significance.

Statsmodels comes with the ``analysis`` extra and the dev group; it is imported where a model is
fitted, so the rest of the toolkit loads without it.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Hashable, Sequence
from dataclasses import dataclass

import numpy as np
import polars as pl

NAN = float("nan")


# --- composites -----------------------------------------------------------------------------------


def zscore(values: Sequence[float | None]) -> np.ndarray:
    """Standardise: (x - mean) / sd over the valid values (sample sd); missing stays NaN."""
    x = np.array([NAN if v is None else float(v) for v in values], dtype=float)
    valid = ~np.isnan(x)
    if valid.sum() < 2:
        return np.full_like(x, NAN)
    sd = x[valid].std(ddof=1)
    if sd == 0:
        return np.full_like(x, NAN)
    return (x - x[valid].mean()) / sd


def composite(
    scores: pl.DataFrame,
    scales: Sequence[str],
    *,
    min_valid: int,
    id_col: str = "entity",
    scale_col: str = "group",
    value_col: str = "mean",
) -> pl.DataFrame:
    """One row per id: each scale's z-score, ``n_valid`` and ``composite``.

    ``scores`` is long (``id_col``, ``scale_col``, ``value_col``); every id in it gets a row. Each
    scale is standardised across all those ids, so pass exactly the analysed sample. A scale
    missing from ``scores`` altogether counts as invalid for everyone.
    """
    if len(set(scales)) != len(scales):
        raise ValueError("scales must be distinct")
    if not 1 <= min_valid <= len(scales):
        raise ValueError(f"min_valid must be between 1 and {len(scales)}")
    dup = scores.filter(pl.struct(id_col, scale_col).is_duplicated())
    if dup.height:
        raise ValueError(f"{dup.height} rows repeat an ({id_col}, {scale_col}) pair")
    ids = scores[id_col].unique().sort().to_list()
    lookup = {(i, s): v for i, s, v in scores.select(id_col, scale_col, value_col).iter_rows()}
    z = {s: zscore([lookup.get((i, s)) for i in ids]) for s in scales}
    matrix = np.column_stack([z[s] for s in scales]) if ids else np.empty((0, len(scales)))
    n_valid = (~np.isnan(matrix)).sum(axis=1)
    sums = np.where(np.isnan(matrix), 0.0, matrix).sum(axis=1)
    means = np.where(n_valid >= min_valid, sums / np.maximum(n_valid, 1), NAN)
    columns = {f"z_{s}": z[s] for s in scales} | {"composite": means}
    return pl.DataFrame({id_col: ids, **columns, "n_valid": n_valid.astype(np.int64)}).with_columns(
        pl.col(c).fill_nan(None) for c in columns
    )


# --- design ---------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Design:
    y: np.ndarray
    X: np.ndarray
    names: list[str]
    groups: np.ndarray
    ids: list[Hashable]
    offset: np.ndarray | None
    n_dropped: int


def design(
    frame: pl.DataFrame,
    *,
    outcome: str,
    predictor: str,
    covariates: Sequence[str] = (),
    fixed_effect: str | None = None,
    exposure: str | None = None,
    id_col: str = "entity",
) -> Design:
    """Complete cases of the columns used, the predictor standardised over them.

    Columns: intercept, predictor (index 1), covariates, then one indicator per group level but
    the first (sorted). ``exposure`` (hours, must be positive) becomes ``log(exposure)``.
    """
    used = [outcome, predictor, *covariates]
    used += [c for c in (fixed_effect, exposure) if c is not None]
    complete = frame.drop_nulls(used)
    for c in [outcome, predictor, *covariates, *([exposure] if exposure else [])]:
        complete = complete.filter(pl.col(c).is_not_nan())
    if exposure is not None:
        complete = complete.filter(pl.col(exposure) > 0)
    n = complete.height
    y = complete[outcome].cast(pl.Float64).to_numpy()
    x = zscore(complete[predictor].cast(pl.Float64).to_list())
    columns = [np.ones(n), x]
    names = ["intercept", predictor]
    for c in covariates:
        columns.append(complete[c].cast(pl.Float64).to_numpy())
        names.append(c)
    groups = (
        complete[fixed_effect].cast(pl.String).to_numpy()
        if fixed_effect is not None
        else np.zeros(n, dtype=object)
    )
    if fixed_effect is not None:
        for level in sorted(set(groups))[1:]:
            columns.append((groups == level).astype(float))
            names.append(f"{fixed_effect}[{level}]")
    X = np.column_stack(columns) if n else np.empty((0, len(names)))
    offset = None
    if exposure is not None:
        offset = np.log(complete[exposure].cast(pl.Float64).to_numpy())
    return Design(y, X, names, groups, complete[id_col].to_list(), offset, frame.height - n)


# --- models ---------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Fit:
    """The predictor's coefficient (column 1 of the design) from one model."""

    model: str
    n: int
    k: int
    estimate: float
    se: float
    lo: float
    hi: float
    p_two: float
    p_one: float
    std_estimate: float
    std_lo: float
    std_hi: float
    converged: bool = True
    dispersion: float | None = None


def _one_sided(p_two: float, stat: float, direction: int) -> float:
    """One-sided p in ``direction`` (+1: coefficient above zero) from a symmetric two-sided p."""
    if math.isnan(p_two) or math.isnan(stat):
        return NAN
    return p_two / 2 if stat * direction > 0 else 1 - p_two / 2


def _check(d: Design) -> None:
    n, k = d.X.shape
    if n <= k:
        raise ValueError(f"{n} complete rows for {k} parameters")
    if np.linalg.matrix_rank(d.X) < k:
        raise ValueError(f"design is rank deficient: {d.names}")


def hc3_cov(X: np.ndarray, resid: np.ndarray) -> np.ndarray:
    """HC3 covariance: (X'X)^-1 X' diag(e_i^2 / (1 - h_ii)^2) X (X'X)^-1."""
    bread = np.linalg.inv(X.T @ X)
    h = np.einsum("ij,jk,ik->i", X, bread, X)
    meat = (X * (resid**2 / (1 - h) ** 2)[:, None]).T @ X
    return bread @ meat @ bread


def ols_hc3(d: Design, *, direction: int = 1, level: float = 0.95) -> Fit:
    """OLS of ``d.y`` on ``d.X``, HC3 standard errors, t on n - k degrees of freedom."""
    import statsmodels.api as sm

    _check(d)
    res = sm.OLS(d.y, d.X).fit(cov_type="HC3", use_t=True)
    b, se, p = float(res.params[1]), float(res.bse[1]), float(res.pvalues[1])
    lo, hi = (float(v) for v in res.conf_int(alpha=1 - level)[1])
    sd_y = float(np.std(d.y, ddof=1))
    n, k = d.X.shape
    return Fit(
        "ols_hc3", n, k, b, se, lo, hi, p, _one_sided(p, b, direction),
        b / sd_y, lo / sd_y, hi / sd_y,
    )  # fmt: skip


def _nb_fit(d: Design, start: np.ndarray | None):
    """NB2 maximum likelihood that does not stop at a diverged Newton run.

    Starts from a Poisson GLM (IRLS, which does not diverge) and dispersion 0.5 unless ``start``
    is given; Newton first, then BFGS from the same start when Newton ends non-finite or
    unconverged. Statsmodels' own default start can send Newton to NaN on small samples while
    still reporting convergence.
    """
    import warnings

    import statsmodels.api as sm
    from statsmodels.discrete.discrete_model import NegativeBinomial

    if d.offset is None:
        raise ValueError("negbin needs an exposure offset")
    _check(d)
    model = NegativeBinomial(d.y, d.X, loglike_method="nb2", offset=d.offset)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        if start is None:
            poisson = sm.GLM(d.y, d.X, family=sm.families.Poisson(), offset=d.offset).fit()
            start = np.append(poisson.params, 0.5)
        res = None
        for method, maxiter in (("newton", 200), ("bfgs", 5000)):
            res = model.fit(start_params=start, method=method, maxiter=maxiter, disp=0)
            if _good(res):
                break
    return res


def _good(res) -> bool:
    return bool(res.mle_retvals.get("converged", False)) and bool(
        np.isfinite(res.params).all() and np.isfinite(res.bse).all()
    )


def negbin(
    d: Design,
    *,
    direction: int = 1,
    level: float = 0.95,
    start: np.ndarray | None = None,
) -> Fit:
    """Negative binomial (NB2) of the count ``d.y`` with offset ``d.offset``; Wald inference.

    ``start`` (coefficients then dispersion) speeds up repeated fits such as permutations. A fit
    that does not converge to finite values is returned with ``converged`` false.
    """
    res = _nb_fit(d, start)
    b, se, p = float(res.params[1]), float(res.bse[1]), float(res.pvalues[1])
    lo, hi = (float(v) for v in res.conf_int(alpha=1 - level)[1])
    n, k = d.X.shape
    return Fit(
        "negbin", n, k, b, se, lo, hi, p, _one_sided(p, b, direction),
        math.exp(b), math.exp(lo), math.exp(hi), _good(res), float(res.params[-1]),
    )  # fmt: skip


def negbin_params(d: Design) -> np.ndarray:
    """Fitted coefficients and dispersion, as ``start`` for further fits on the same design."""
    return np.asarray(_nb_fit(d, None).params)


# --- error control --------------------------------------------------------------------------------


def holm(pvalues: Sequence[float]) -> list[float]:
    """Holm step-down adjusted p-values, in the input order (capped at 1, monotone)."""
    p = np.asarray(pvalues, dtype=float)
    m = len(p)
    order = np.argsort(p, kind="mergesort")
    adjusted = np.empty(m)
    running = 0.0
    for rank, i in enumerate(order):
        running = max(running, min(1.0, (m - rank) * p[i]))
        adjusted[i] = running
    return adjusted.tolist()


# --- permutation ----------------------------------------------------------------------------------


def permute_within(groups: Sequence[Hashable], rng: np.random.Generator) -> np.ndarray:
    """An index permutation that only moves rows among rows of the same group."""
    groups = list(groups)
    out = np.arange(len(groups))
    members: dict[Hashable, list[int]] = {}
    for i, g in enumerate(groups):
        members.setdefault(g, []).append(i)
    for idx in members.values():
        idx = np.asarray(idx)
        out[idx] = idx[rng.permutation(len(idx))]
    return out


@dataclass(frozen=True)
class Permutation:
    observed: float
    p_one: float
    p_two: float
    n_perm: int
    n_failed: int


def permutation_test(
    statistic: Callable[[np.ndarray], float],
    x: np.ndarray,
    groups: Sequence[Hashable],
    *,
    n_perm: int,
    seed: int,
    direction: int = 1,
) -> Permutation:
    """Shuffle ``x`` within ``groups`` ``n_perm`` times and recompute ``statistic``.

    ``p_one``: share of statistics at least as far as the observed one in ``direction``;
    ``p_two``: at least as large in absolute value. Both count the observed statistic, so
    ``p = (1 + hits) / (1 + valid permutations)``. A statistic that fails (NaN or an error) is
    left out and counted in ``n_failed``.
    """
    x = np.asarray(x)
    observed = float(statistic(x))
    rng = np.random.default_rng(seed)
    one = two = valid = failed = 0
    for _ in range(n_perm):
        idx = permute_within(groups, rng)
        try:
            s = float(statistic(x[idx]))
        except (ValueError, np.linalg.LinAlgError):
            s = NAN
        if math.isnan(s):
            failed += 1
            continue
        valid += 1
        one += s * direction >= observed * direction - 1e-12
        two += abs(s) >= abs(observed) - 1e-12
    return Permutation(observed, (1 + one) / (1 + valid), (1 + two) / (1 + valid), n_perm, failed)


# --- fragility ------------------------------------------------------------------------------------


def flips(
    main_estimate: float, main_significant: bool, estimate: float, significant: bool
) -> list[str]:
    """What a rerun changed against the main result: ``sign``, ``significance``, both or none."""
    out = []
    if math.isnan(estimate) or np.sign(estimate) != np.sign(main_estimate):
        out.append("sign")
    if significant != main_significant:
        out.append("significance")
    return out


def suppress(n: int, min_n: int) -> bool:
    """Whether a result on ``n`` people must be withheld (fewer than ``min_n``)."""
    return n < min_n
