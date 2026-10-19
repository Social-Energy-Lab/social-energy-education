"""Synthetic people for confirmatory tests: survey scales, covariates and outcomes with planted
effects. Invented numbers only, never real data.

Each person has a latent trait per block, standard normal. Each of a block's scales is the latent
trait plus a little noise, put on its own arbitrary mean and spread, so a composite has to
standardise before averaging to recover the trait. Groups shift the latent trait (``group_shift``)
and the outcomes (``group_effect``), so a model without group fixed effects is confounded.

Outcomes, ``z_trust`` and ``z_lust`` being the latent traits:

* ``linear = group_effect[g] + beta * z_trust + 0.1 * age + noise`` (sd ``noise_sd``);
* ``count ~ NB2(mean = exposure * exp(-1 + group_effect[g] / 4 + log(rate_ratio) * z_lust),
  dispersion)``, with exposure hours that grow with ``z_lust`` (``exposure_on_lust``), so a model
  without the offset is biased.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import polars as pl


@dataclass(frozen=True)
class ConfirmatorySpec:
    n: int = 600
    groups: int = 4
    beta: float = 2.0
    rate_ratio: float = 1.5
    dispersion: float = 0.3
    noise_sd: float = 1.0
    scale_noise: float = 0.1
    group_shift: float = 1.0
    group_effect: float = 5.0
    exposure_on_lust: float = 0.5
    missing_share: float = 0.05
    scales: tuple[str, ...] = ("s1", "s2", "s3", "s4", "s5", "s6")
    seed: int = 11


@dataclass(frozen=True)
class SyntheticPeople:
    spec: ConfirmatorySpec
    people: pl.DataFrame  # entity, group, age, female, z_trust, z_lust, linear, count, exposure
    scores: pl.DataFrame  # long: entity, block ("trust" / "lust"), group (scale), mean


def generate_people(spec: ConfirmatorySpec | None = None) -> SyntheticPeople:
    spec = spec or ConfirmatorySpec()
    rng = np.random.default_rng(spec.seed)
    n = spec.n
    group = rng.integers(0, spec.groups, n)
    level = np.linspace(-1, 1, spec.groups)
    trust = rng.standard_normal(n) + spec.group_shift * level[group]
    lust = rng.standard_normal(n) + spec.group_shift * level[group]
    age = rng.integers(15, 19, n).astype(float)
    female = rng.integers(0, 2, n).astype(float)
    effect = spec.group_effect * level[group]
    linear = effect + spec.beta * trust + 0.1 * age + spec.noise_sd * rng.standard_normal(n)
    exposure = 50 * np.exp(spec.exposure_on_lust * lust + 0.2 * rng.standard_normal(n))
    mu = exposure * np.exp(-1 + effect / 4 + np.log(spec.rate_ratio) * lust)
    # NB2 as a gamma-Poisson mixture: var = mu + dispersion * mu^2.
    shape = 1 / spec.dispersion
    count = rng.poisson(rng.gamma(shape, mu / shape))
    entity = [f"person:{i:04d}" for i in range(n)]
    people = pl.DataFrame(
        {
            "entity": entity,
            "group": [f"g{g}" for g in group],
            "age": age,
            "female": female,
            "z_trust": trust,
            "z_lust": lust,
            "linear": linear,
            "count": count.astype(np.int64),
            "exposure": exposure,
        }
    )
    rows = []
    for block, latent in (("trust", trust), ("lust", lust)):
        for j, scale in enumerate(spec.scales):
            centre, spread = 2 + j, 0.5 + 0.3 * j
            values = centre + spread * (latent + spec.scale_noise * rng.standard_normal(n))
            gone = rng.random(n) < spec.missing_share
            rows += [
                {"entity": e, "block": block, "group": f"{block}_{scale}", "mean": None if g
                 else float(v)}
                for e, v, g in zip(entity, values, gone, strict=True)
            ]  # fmt: skip
    scores = pl.DataFrame(
        rows,
        schema={"entity": pl.String, "block": pl.String, "group": pl.String, "mean": pl.Float64},
    )
    return SyntheticPeople(spec, people, scores)
