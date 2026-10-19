"""The confirmatory tier of ``research/analysis-plan.md`` (frozen 2026-10-19 at 109bc50).

Everything here is the plan's, transcribed; nothing was chosen after seeing a result. Where the
plan leaves a choice open, the choice is named below and was fixed before the first run.

**Unit.** One row per participant with ``beacons`` and ``survey`` consent and a kept survey
submission linked to them through the spine; C4 also needs ``self_report`` consent.

**Survey side.** Kept submissions only (``duplicate_submission`` false). A submission reaches a
person through its platform account (``Spine.account_entities("zeitgeist")``), never through the
typed study ID, which is only cross-checked (agreement counted in ``qa.json``). An account the
spine does not link is left out and counted.

**Composites.** Trust in life: B1, B8, B11, B14, B16 positive affect, B17. Lust for life: C1a, C3,
C6, C8, C12, C21. Each scale is standardised across the unit, the composite is the mean of a
person's valid standardised scales, and needs at least four of the six. B17 is a single item in
the codebook (``kind: items``), so its "scale score" is the recoded item. Rows the scoring marks
``provisional`` are used and counted in ``qa.json``.

**Tests** (``TESTS``), the predictor standardised over each test's complete cases:

* C1: ``strength_min_per_day`` ~ trust, OLS with course fixed effects, age and female, HC3.
* C2: ``cross_share`` ~ lust, the same model. The plan's hypothesis names the share; its
  difference from the expected share (``cross_share_excess``) is fitted as well, outside the
  family (``EXTRA``). The expected share is constant within a course, so under course fixed
  effects both give the same coefficient.
* C4: press episodes ~ trust, and ~ lust: negative binomial (NB2) with log exposure hours as
  offset, the same covariates and fixed effects.

**Direction.** The plan gives every hypothesis a direction (positive) and no sidedness. The primary
p-value is one-sided in the stated direction; two-sided p-values are reported beside it. Intervals
are two-sided 95%. Holm over the four tests at alpha 0.05, on the one-sided p (and, for reference,
on the two-sided p).

**Permutation check.** On the main variant: the predictor (the survey row) shuffled among people
of the same course, ``N_PERM`` times with seed ``SEED``; the statistic is the model's coefficient.

**Sensitivity.** Every test is refitted on every variant in ``outcomes.parquet`` and, for C4, on
worn-time exposure (``worn_exposure``, sensitivity 6). Within each variant the family is
Holm-adjusted again; a test is fragile if any variant changes its sign or its significance.

**Reporting.** Aggregates only; a test on fewer than ``MIN_GROUP`` people is withheld.

Run after ``outcomes.py`` and ``social-energy score-survey``:

    uv run --extra analysis python studies/dsa-2026/analyses/confirmatory.py

Writes ``results.csv``, ``sensitivity.csv``, ``reliability.csv`` and ``qa.json`` (aggregates) and
``composites.parquet`` (per person, private) to
``$SOCIAL_ENERGY_DATA/dsa-2026/derived/analyses/confirmatory/``.
"""

from __future__ import annotations

import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np
import polars as pl

from social_energy import paths
from social_energy.confirmatory import (
    Design,
    Fit,
    composite,
    design,
    flips,
    holm,
    negbin,
    negbin_params,
    ols_hc3,
    permutation_test,
    suppress,
)
from social_energy.spine import Spine
from social_energy.study import StudyConfig
from social_energy.survey import load_codebook
from social_energy.survey.score import cronbach_alpha, recode

STUDY = "dsa-2026"
SLUG = "confirmatory"
REPO = Path(__file__).resolve().parents[3]
STUDY_YAML = REPO / "studies" / STUDY / "study.yaml"

#: Core sets (analysis plan, "Composites", Álvaro 2026-10-18), codebook group keys.
SCALES = {
    "trust": [
        "b1_belonging",
        "b8_trust",
        "b11_teacher_relationship",
        "b14_family_support",
        "b16_positive_affect",
        "b17_life_satisfaction",
    ],
    "lust": [
        "c1a_self_efficacy",
        "c3_creative_self_efficacy",
        "c6_proactive_learning",
        "c8_assertiveness",
        "c12_perseverance",
        "c21_openness",
    ],
}
#: Codebook groups of ``kind: items`` with one item, used as a score.
SINGLE_ITEMS = ["b17_life_satisfaction"]
MIN_VALID = 4
COVARIATES = ["age", "female"]
#: The spine's gender code that the "female" indicator marks; every other value is 0.
FEMALE = "f"
FIXED_EFFECT = "course"
ALPHA = 0.05
DIRECTION = 1  # every confirmatory hypothesis is "positive"
N_PERM = 10_000
SEED = 20261019
MIN_GROUP = 5
BASE_CONSENT = ("beacons", "survey")


@dataclass(frozen=True)
class Test:
    name: str
    predictor: str  # "trust" or "lust"
    outcome: str
    model: str  # "ols" or "negbin"
    exposure: str | None = None
    consent: tuple[str, ...] = BASE_CONSENT


#: The confirmatory family (four tests).
TESTS = [
    Test("C1", "trust", "strength_min_per_day", "ols"),
    Test("C2", "lust", "cross_share", "ols"),
    Test("C4_trust", "trust", "press_episodes", "negbin", "exposure_hours",
         (*BASE_CONSENT, "self_report")),
    Test("C4_lust", "lust", "press_episodes", "negbin", "exposure_hours",
         (*BASE_CONSENT, "self_report")),
]  # fmt: skip
#: Fitted beside the family, never Holm-adjusted with it.
EXTRA = [Test("C2_excess", "lust", "cross_share_excess", "ols")]
#: Sensitivity number in the plan, per variant (outcomes.py's names, plus worn_exposure).
SENSITIVITY = {
    "hand_split_fill": 2,
    "no_drift": 3,
    "rssi_-70": 4,
    "rssi_-75": 4,
    "min_15": 4,
    "min_30": 4,
    "lost_both_sides": 5,
    "worn_exposure": 6,
    "accidental_7min": 7,
}
#: Sensitivity 6: C4 on worn time, from the main rows' worn columns.
WORN = {"press_episodes": "press_episodes_worn", "exposure_hours": "exposure_hours_worn"}


# --- survey side ---------------------------------------------------------------------------------


def linked_submissions(submissions: pl.DataFrame, spine: Spine) -> tuple[pl.DataFrame, dict]:
    """Kept submissions with the entity the spine gives their account."""
    accounts = spine.account_entities("zeitgeist")
    kept = submissions.filter(~pl.col("duplicate_submission"))
    linked = kept.join(accounts, left_on="respondent", right_on="account", how="left")
    resolved = linked.filter(pl.col("entity").is_not_null())
    repeated = resolved.filter(pl.col("entity").is_duplicated())
    if repeated.height:
        raise SystemExit(f"{repeated.height} kept submissions share a person; fix the spine first")
    typed = ("person:" + resolved["study_id"]).to_list()
    qa = {
        "submissions": submissions.height,
        "kept": kept.height,
        "kept_unlinked": linked.height - resolved.height,
        "kept_linked": resolved.height,
        "typed_id_agrees_with_spine": sum(
            t == e for t, e in zip(typed, resolved["entity"], strict=True)
        ),
    }
    return resolved.select("respondent", "entity"), qa


def scale_scores(layout: paths.StudyLayout, codebook_path: Path, linked: pl.DataFrame):
    """Long table (entity, group, mean, provisional) of the core scales, kept submissions only."""
    scoring = layout.derived / "survey" / "scoring"
    wanted = [s for block in SCALES.values() for s in block]
    scores = (
        pl.read_parquet(scoring / "scores.parquet")
        .filter(~pl.col("duplicate_submission") & pl.col("group").is_in(wanted))
        .join(linked, on="respondent")
        .select("entity", "group", "mean", "provisional")
    )
    codebook = load_codebook(codebook_path)
    items = pl.read_parquet(layout.derived / "survey" / "items.parquet")
    single = (
        recode(items, codebook)
        .filter(pl.col("group").is_in(SINGLE_ITEMS))
        .join(linked, on="respondent")
        .select(
            "entity",
            "group",
            pl.col("value").alias("mean"),
            pl.col("group")
            .map_elements(codebook.is_provisional, return_dtype=pl.Boolean)
            .alias("provisional"),
        )
    )
    long = pl.concat([scores, single])
    missing = sorted(set(wanted) - set(long["group"]))
    if missing:
        raise SystemExit(f"no scores for {missing}")
    return long


# --- fitting -------------------------------------------------------------------------------------


def frame_for(test: Test, unit: pl.DataFrame, outcomes: pl.DataFrame, spine: Spine):
    allowed = set.intersection(*(spine.consented(m) for m in test.consent))
    allowed = {f"person:{p}" for p in allowed}
    return unit.filter(pl.col("entity").is_in(list(allowed))).join(outcomes, on="entity")


def build(test: Test, frame: pl.DataFrame) -> Design:
    return design(
        frame,
        outcome=test.outcome,
        predictor=test.predictor,
        covariates=COVARIATES,
        fixed_effect=FIXED_EFFECT,
        exposure=test.exposure,
    )


def fit(test: Test, d: Design) -> Fit:
    if test.model == "ols":
        return ols_hc3(d, direction=DIRECTION)
    return negbin(d, direction=DIRECTION)


def coefficient(test: Test, d: Design):
    """The statistic for the permutation check: the predictor's coefficient, x permuted."""
    if test.model == "ols":
        X = d.X.copy()

        def stat(x):
            X[:, 1] = x
            return float(np.linalg.lstsq(X, d.y, rcond=None)[0][1])

        return stat
    start = negbin_params(d)

    def stat_nb(x):
        X = d.X.copy()
        X[:, 1] = x
        r = negbin(Design(d.y, X, d.names, d.groups, d.ids, d.offset, 0), start=start)
        return r.estimate if r.converged else float("nan")

    return stat_nb


def row(test: Test, f: Fit, variant: str, family: bool) -> dict:
    out = {"variant": variant, "test": test.name, "family": family, "outcome": test.outcome,
           "predictor": test.predictor, **asdict(f)}  # fmt: skip
    if suppress(f.n, MIN_GROUP):
        out = {k: (v if k in ("variant", "test", "family", "outcome", "predictor", "n") else None)
               for k, v in out.items()}  # fmt: skip
    return out


def with_holm(rows: list[dict]) -> list[dict]:
    fam = [r for r in rows if r["family"]]
    for key in ("p_one", "p_two"):
        adj = holm([r[key] if r[key] is not None else 1.0 for r in fam])
        for r, a in zip(fam, adj, strict=True):
            r[f"{key}_holm"] = a
    for r in fam:
        r["significant"] = r["p_one_holm"] < ALPHA
    return rows


def variant_outcomes(outcomes: pl.DataFrame, variant: str) -> pl.DataFrame:
    if variant == "worn_exposure":
        main = outcomes.filter(pl.col("variant") == "main")
        return main.drop(list(WORN)).rename({v: k for k, v in WORN.items()})
    return outcomes.filter(pl.col("variant") == variant)


def run_variant(variant, unit, outcomes, spine, tests) -> list[dict]:
    o = variant_outcomes(outcomes, variant)
    return with_holm([row(t, fit(t, build(t, frame_for(t, unit, o, spine))), variant, True)
                      for t in tests])  # fmt: skip


def main() -> None:
    layout = paths.study(STUDY)
    config = StudyConfig.load(STUDY_YAML)
    spine = Spine.load(layout.spine)
    out = layout.derived / "analyses" / SLUG
    out.mkdir(parents=True, exist_ok=True)

    people = spine.people_frame().filter(pl.col("role") == "participant")
    base = set.intersection(*(spine.consented(m) for m in BASE_CONSENT))
    submissions = pl.read_parquet(layout.derived / "survey" / "scoring" / "submissions.parquet")
    linked, qa_link = linked_submissions(submissions, spine)
    unit = people.filter(pl.col("id").is_in(list(base))).join(linked, on="entity")
    qa: dict = {
        "participants": people.height,
        "participants_with_base_consent": people.filter(pl.col("id").is_in(list(base))).height,
        "survey_link": qa_link,
        "unit": unit.height,
    }

    # Composites, each scale standardised across the unit.
    long = scale_scores(layout, config.survey_scoring_config().codebook, linked).filter(
        pl.col("entity").is_in(unit["entity"].implode())
    )
    qa["provisional_score_rows"] = int(long["provisional"].sum())
    comps, rel_rows = [], []
    for block, scales in SCALES.items():
        c = composite(long, scales, min_valid=MIN_VALID)
        comps.append(c.select("entity", pl.col("composite").alias(block),
                              pl.col("n_valid").alias(f"{block}_n_valid")))  # fmt: skip
        matrix = c.select([f"z_{s}" for s in scales]).drop_nulls().to_numpy()
        rel_rows.append({"group": f"{block}_composite", "k": len(scales),
                         "n_complete": len(matrix), "alpha": cronbach_alpha(matrix)})  # fmt: skip
        qa[f"{block}_composite"] = {
            "valid": int(c["composite"].is_not_null().sum()),
            "below_min_valid": int(c["composite"].is_null().sum()),
        }
    unit = unit.join(comps[0], on="entity", how="left").join(comps[1], on="entity", how="left")
    unit = unit.with_columns((pl.col("gender") == FEMALE).cast(pl.Float64).alias("female"))
    unit.select("entity", "course", "trust", "lust", "trust_n_valid", "lust_n_valid").write_parquet(
        out / "composites.parquet"
    )

    scored = pl.read_parquet(layout.derived / "survey" / "scoring" / "reliability.parquet")
    wanted = [s for block in SCALES.values() for s in block]
    reliability = pl.concat(
        [
            scored.filter(pl.col("group").is_in(wanted)).select(
                "group", "k", "n_complete", "alpha", "omega"
            ),
            pl.DataFrame(rel_rows).with_columns(pl.lit(None, pl.Float64).alias("omega")),
        ],
        how="vertical_relaxed",
    )
    reliability.write_csv(out / "reliability.csv")

    # Main results, permutation check.
    outcomes = pl.read_parquet(layout.derived / "analyses" / "outcomes" / "outcomes.parquet")
    main_o = variant_outcomes(outcomes, "main")
    results = with_holm(
        [row(t, fit(t, build(t, frame_for(t, unit, main_o, spine))), "main", True) for t in TESTS]
        + [row(t, fit(t, build(t, frame_for(t, unit, main_o, spine))), "main", False)
           for t in EXTRA]
    )  # fmt: skip
    perm_p = {}
    for t in TESTS + EXTRA:
        d = build(t, frame_for(t, unit, main_o, spine))
        p = permutation_test(coefficient(t, d), d.X[:, 1].copy(), d.groups, n_perm=N_PERM,
                             seed=SEED, direction=DIRECTION)  # fmt: skip
        perm_p[t.name] = p
        print(f"permutation {t.name}: {p}", flush=True)
    fam = [r for r in results if r["family"]]
    perm_holm = holm([perm_p[r["test"]].p_one for r in fam])
    for r in results:
        p = perm_p[r["test"]]
        r |= {"perm_p_one": p.p_one, "perm_p_two": p.p_two, "perm_failed": p.n_failed}
    for r, a in zip(fam, perm_holm, strict=True):
        r["perm_p_one_holm"] = a

    # Sensitivity variants.
    variants = [v for v in SENSITIVITY if v == "worn_exposure" or v in set(outcomes["variant"])]
    qa["variants_missing"] = [v for v in SENSITIVITY if v not in variants]
    main_by_test = {r["test"]: r for r in fam}
    sens = []
    for v in variants:
        for r in run_variant(v, unit, outcomes, spine, TESTS):
            m = main_by_test[r["test"]]
            r["sensitivity"] = SENSITIVITY[v]
            r["flips"] = ",".join(
                flips(m["estimate"], m["significant"], r["estimate"] or float("nan"),
                      r["significant"])
            )  # fmt: skip
            sens.append(r)
    sens_df = pl.DataFrame(sens, infer_schema_length=None)
    sens_df.write_csv(out / "sensitivity.csv")
    for r in results:
        if r["family"]:
            fl = sens_df.filter((pl.col("test") == r["test"]) & (pl.col("flips") != ""))
            r["fragile"] = fl.height > 0
            r["fragile_under"] = ",".join(f"{v}:{f}" for v, f in fl.select("variant", "flips")
                                          .iter_rows())  # fmt: skip
    res_df = pl.DataFrame(results, infer_schema_length=None)
    res_df.write_csv(out / "results.csv")
    qa["settings"] = {
        "min_valid": MIN_VALID, "alpha": ALPHA, "direction": DIRECTION, "n_perm": N_PERM,
        "seed": SEED, "min_group": MIN_GROUP, "covariates": COVARIATES,
        "fixed_effect": FIXED_EFFECT,
    }  # fmt: skip
    (out / "qa.json").write_text(json.dumps(qa, indent=2, default=str), encoding="utf-8")
    with pl.Config(tbl_rows=200, tbl_cols=30, fmt_str_lengths=60):
        print(json.dumps(qa, indent=2, default=str))
        print(reliability)
        print(res_df)
        print(sens_df.select("variant", "test", "n", "estimate", "std_estimate", "p_one",
                             "p_one_holm", "significant", "flips"))  # fmt: skip


if __name__ == "__main__":
    sys.exit(main())
