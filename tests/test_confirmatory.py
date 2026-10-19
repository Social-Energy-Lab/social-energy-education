"""Confirmatory toolkit: hand-derived expectations plus synthetic people with planted effects."""

import math

import numpy as np
import polars as pl
import pytest

from social_energy.confirmatory import (
    composite,
    design,
    flips,
    hc3_cov,
    holm,
    negbin,
    ols_hc3,
    permutation_test,
    permute_within,
    suppress,
    zscore,
)
from social_energy.synth.confirmatory import ConfirmatorySpec, generate_people

# --- composites ---------------------------------------------------------------------------------


def test_zscore_uses_the_sample_sd_and_keeps_missing():
    z = zscore([1.0, 2.0, 3.0, None])
    assert z[:3] == pytest.approx([-1.0, 0.0, 1.0])
    assert math.isnan(z[3])


def _long(rows):
    return pl.DataFrame(rows, schema=["entity", "group", "mean"], orient="row")


def test_composite_standardises_each_scale_then_averages_with_a_minimum():
    # s1 and s2 rank people alike on different units; s3 has two valid values.
    scores = _long([
        ("a", "s1", 1.0), ("b", "s1", 2.0), ("c", "s1", 3.0),
        ("a", "s2", 10.0), ("b", "s2", 20.0), ("c", "s2", 30.0),
        ("a", "s3", 5.0), ("b", "s3", None), ("c", "s3", 3.0),
    ])  # fmt: skip
    out = composite(scores, ["s1", "s2", "s3"], min_valid=3).sort("entity")
    # s3: mean 4, sd sqrt(2) -> a = +1/sqrt(2), c = -1/sqrt(2).
    r = 1 / math.sqrt(2)
    assert out["n_valid"].to_list() == [3, 2, 3]
    assert out["composite"][0] == pytest.approx((-1 - 1 + r) / 3)
    assert out["composite"][1] is None  # two of three valid, below the minimum
    assert out["composite"][2] == pytest.approx((1 + 1 - r) / 3)
    assert out["z_s3"].to_list()[1] is None


def test_composite_counts_a_scale_absent_from_the_table_as_invalid():
    scores = _long([("a", "s1", 1.0), ("b", "s1", 3.0)])
    out = composite(scores, ["s1", "s2"], min_valid=1).sort("entity")
    assert out["n_valid"].to_list() == [1, 1]
    assert out["composite"].to_list() == pytest.approx([-1 / math.sqrt(2), 1 / math.sqrt(2)])
    assert composite(scores, ["s1", "s2"], min_valid=2)["composite"].null_count() == 2


def test_composite_refuses_repeated_rows():
    scores = _long([("a", "s1", 1.0), ("a", "s1", 2.0)])
    with pytest.raises(ValueError, match="repeat"):
        composite(scores, ["s1"], min_valid=1)


# --- OLS with HC3 -------------------------------------------------------------------------------


def test_hc3_covariance_by_hand():
    # Two groups of two: means 2 and 4, residuals -1, 1, -2, 2, every leverage 1/2.
    # HC3 weights e^2 / (1 - h)^2 = 4 e^2 -> slope variance 8/4 + 32/4 = 10.
    X = np.array([[1, 0], [1, 0], [1, 1], [1, 1]], dtype=float)
    y = np.array([1, 3, 2, 6], dtype=float)
    beta = np.linalg.lstsq(X, y, rcond=None)[0]
    assert beta == pytest.approx([2, 2])
    cov = hc3_cov(X, y - X @ beta)
    assert cov == pytest.approx(np.array([[2, -2], [-2, 10]]))


def test_ols_hc3_reports_the_coefficient_per_sd_of_the_predictor():
    frame = pl.DataFrame({"entity": list("abcd"), "x": [0.0, 0, 1, 1], "y": [1.0, 3, 2, 6]})
    fit = ols_hc3(design(frame, outcome="y", predictor="x"))
    sd_x = math.sqrt(1 / 3)  # sample sd of 0, 0, 1, 1
    assert fit.n == 4 and fit.k == 2
    assert fit.estimate == pytest.approx(2 * sd_x)
    assert fit.se == pytest.approx(math.sqrt(10) * sd_x)
    # t inference on n - k = 2 degrees of freedom: t = 2/sqrt(10), two-sided p by hand
    # from the t(2) cdf, 1 - |t| / sqrt(2 + t^2).
    t = 2 / math.sqrt(10)
    assert fit.p_two == pytest.approx(1 - t / math.sqrt(2 + t**2))
    assert fit.p_one == pytest.approx(fit.p_two / 2)
    assert fit.std_estimate == pytest.approx(fit.estimate / np.std([1, 3, 2, 6], ddof=1))


def test_one_sided_p_against_the_direction_is_large():
    frame = pl.DataFrame({"entity": list("abcd"), "x": [0.0, 0, 1, 1], "y": [1.0, 3, 2, 6]})
    fit = ols_hc3(design(frame, outcome="y", predictor="x"), direction=-1)
    assert fit.p_one == pytest.approx(1 - fit.p_two / 2)


def test_design_drops_incomplete_rows_and_adds_fixed_effects():
    frame = pl.DataFrame(
        {
            "entity": list("abcde"),
            "x": [1.0, 2, 3, None, 5],
            "y": [1.0, 2, 3, 4, float("nan")],
            "g": ["p", "q", "r", "p", "q"],
        }
    )
    d = design(frame, outcome="y", predictor="x", fixed_effect="g")
    assert d.ids == ["a", "b", "c"]
    assert d.n_dropped == 2
    assert d.names == ["intercept", "x", "g[q]", "g[r]"]
    assert d.X[:, 2].tolist() == [0, 1, 0]
    assert d.X[:, 1] == pytest.approx([-1, 0, 1])


def test_design_refuses_nonpositive_exposure_and_logs_it():
    frame = pl.DataFrame(
        {"entity": list("abc"), "x": [1.0, 2, 3], "n": [1, 2, 3], "h": [2.0, 0.0, math.e]}
    )
    d = design(frame, outcome="n", predictor="x", exposure="h")
    assert d.ids == ["a", "c"]
    assert d.offset == pytest.approx([math.log(2), 1.0])


# --- planted effects ----------------------------------------------------------------------------


@pytest.fixture(scope="module")
def people():
    return generate_people(ConfirmatorySpec())


def test_composite_recovers_the_latent_trait(people):
    trust = people.scores.filter(pl.col("block") == "trust")
    scales = sorted(trust["group"].unique())
    comp = composite(trust, scales, min_valid=4).join(people.people, on="entity")
    assert comp["composite"].null_count() < 0.01 * comp.height
    assert comp.select(pl.corr("composite", "z_trust")).item() > 0.99


def test_fixed_effects_recover_a_planted_slope_that_groups_confound(people):
    spec, frame = people.spec, people.people
    sd = frame["z_trust"].std()
    with_fe = ols_hc3(
        design(frame, outcome="linear", predictor="z_trust", covariates=["age", "female"],
               fixed_effect="group")
    )  # fmt: skip
    assert with_fe.estimate == pytest.approx(spec.beta * sd, rel=0.05)
    assert with_fe.lo < spec.beta * sd < with_fe.hi
    assert with_fe.p_one < 1e-10
    # The same model without fixed effects absorbs the group effect into the slope.
    pooled = ols_hc3(design(frame, outcome="linear", predictor="z_trust", covariates=["age"]))
    assert pooled.estimate > 1.3 * spec.beta * sd


def test_negbin_recovers_a_planted_rate_ratio_with_the_exposure_offset(people):
    spec, frame = people.spec, people.people
    sd = frame["z_lust"].std()
    target = math.exp(math.log(spec.rate_ratio) * sd)
    fit = negbin(
        design(frame, outcome="count", predictor="z_lust", covariates=["age", "female"],
               fixed_effect="group", exposure="exposure")
    )  # fmt: skip
    assert fit.converged
    assert fit.std_estimate == pytest.approx(target, rel=0.06)
    assert fit.std_lo < target < fit.std_hi
    assert fit.dispersion == pytest.approx(spec.dispersion, rel=0.3)
    # Without the offset, exposure (which grows with the trait) inflates the ratio.
    no_offset = design(frame.with_columns(pl.lit(1.0).alias("one")), outcome="count",
                       predictor="z_lust", covariates=["age", "female"], fixed_effect="group",
                       exposure="one")  # fmt: skip
    assert negbin(no_offset).std_estimate > 1.2 * target


def test_negbin_finds_nothing_where_nothing_was_planted():
    null = generate_people(ConfirmatorySpec(n=400, rate_ratio=1.0, seed=5))
    fit = negbin(
        design(null.people, outcome="count", predictor="z_lust", fixed_effect="group",
               exposure="exposure")
    )  # fmt: skip
    assert fit.std_lo < 1 < fit.std_hi


# --- Holm ---------------------------------------------------------------------------------------


def test_holm_by_hand():
    # Sorted: 0.005 x 4 = 0.02, 0.01 x 3 = 0.03, 0.03 x 2 = 0.06, 0.04 x 1 = 0.04 -> 0.06.
    assert holm([0.01, 0.04, 0.03, 0.005]) == pytest.approx([0.03, 0.06, 0.06, 0.02])
    assert holm([0.5, 0.6]) == pytest.approx([1.0, 1.0])


# --- permutation --------------------------------------------------------------------------------


def test_permute_within_never_moves_a_row_to_another_group():
    groups = ["a", "b", "a", "c", "b", "a", "c", "c"]
    rng = np.random.default_rng(0)
    seen_moves = False
    for _ in range(50):
        idx = permute_within(groups, rng)
        assert sorted(idx) == list(range(len(groups)))
        assert [groups[i] for i in idx] == groups
        seen_moves |= list(idx) != list(range(len(groups)))
    assert seen_moves


def test_permutation_is_reproducible_and_counts_the_observed_statistic():
    x = np.arange(6, dtype=float)
    groups = [0, 0, 0, 1, 1, 1]
    res = permutation_test(lambda v: 1.0, x, groups, n_perm=99, seed=3)
    assert (res.p_one, res.p_two) == (1.0, 1.0)  # every permutation ties the observed
    stat = lambda v: float(v[0])  # noqa: E731
    a = permutation_test(stat, x, groups, n_perm=200, seed=3)
    b = permutation_test(stat, x, groups, n_perm=200, seed=3)
    assert a == b


def _slope(y):
    def stat(x):
        dx = x - x.mean()
        return float((dx * (y - y.mean())).sum() / (dx**2).sum())

    return stat


def test_within_group_permutation_ignores_an_association_made_by_groups():
    # x and y both follow the group and nothing else: a global shuffle sees an effect,
    # a shuffle within groups must not.
    rng = np.random.default_rng(1)
    groups = np.repeat(np.arange(4), 30)
    x = groups + rng.standard_normal(120)
    y = 3 * groups + rng.standard_normal(120)
    within = permutation_test(_slope(y), x, groups, n_perm=999, seed=2)
    pooled = permutation_test(_slope(y), x, np.zeros(120), n_perm=999, seed=2)
    assert pooled.p_two == pytest.approx(1 / 1000)
    assert within.p_two > 0.05


def test_permutation_finds_a_planted_within_group_effect():
    rng = np.random.default_rng(4)
    groups = np.repeat(np.arange(3), 20)
    x = rng.standard_normal(60)
    y = x + 0.3 * rng.standard_normal(60)
    res = permutation_test(_slope(y), x, groups, n_perm=499, seed=0)
    assert res.p_one == pytest.approx(1 / 500)
    against = permutation_test(_slope(y), x, groups, n_perm=499, seed=0, direction=-1)
    assert against.p_one == pytest.approx(1.0)


# --- fragility and suppression ------------------------------------------------------------------


def test_flips():
    assert flips(0.3, True, 0.2, True) == []
    assert flips(0.3, True, -0.1, False) == ["sign", "significance"]
    assert flips(0.3, False, 0.4, True) == ["significance"]
    assert flips(0.3, False, -0.4, False) == ["sign"]
    assert flips(0.3, False, float("nan"), False) == ["sign"]


def test_suppress_below_five():
    assert suppress(4, 5) and not suppress(5, 5)


@pytest.mark.parametrize("seed", [2, 38])
def test_negbin_converges_on_small_samples_where_a_default_newton_run_diverges(seed):
    # Found by search: statsmodels' default Newton run ends in NaN on both while reporting
    # convergence, and Newton from the Poisson start still fails on seed 2.
    small = generate_people(ConfirmatorySpec(n=75, groups=6, seed=seed, dispersion=0.5))
    d = design(small.people, outcome="count", predictor="z_lust", covariates=["age", "female"],
               fixed_effect="group", exposure="exposure")  # fmt: skip
    fit = negbin(d)
    assert fit.converged
    assert all(math.isfinite(v) for v in (fit.estimate, fit.se, fit.p_two, fit.dispersion))
    assert fit.dispersion > 0
