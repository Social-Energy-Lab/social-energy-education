"""Exploratory tier, survey against network: new ties (former C3) and background and embedding.

``research/analysis-plan.md`` (frozen 2026-10-19), section "Exploratory analyses". **Every result
here is exploratory**: no error control, two-sided, effect sizes with 95% intervals and no
p-values, distributions rather than people.

**New ties (former C3).** The lust-for-life composite against new close partners after the first
two camp days, for every threshold variant side by side, since the variants rank people
differently (the stability rule that moved C3 out of the confirmatory family). Three
definitions, all from ``outcomes.parquet``: ``c3_partners`` (distinct partners first tied after
the burn-in, per present day after it; the plan's wording), ``c3_daily`` (the first definition)
and ``c3_partners_all`` (all distinct partners per present day, no burn-in). Model as the
confirmatory C1/C2: OLS on the standardised composite with age, female and course fixed effects,
HC3; reported as the outcome's SDs per SD of the composite. Beside it, the plain Spearman
correlation with a Fisher interval.

**Background and embedding (RQ3, within DSA only).** Family-background items of block A against
network position. Indicators, recoded from ``derived/survey/items.parquet`` (kept submissions,
linked by platform account as in ``confirmatory.py``) `[inferred: our grouping of the items]`:

* ``social_status``: A14, subjective social status of the family now (ST259Q01, 1-10);
* ``books``: A18, books at home (ST255, ordinal levels);
* ``home_resources``: mean of the z-scores of A15 possessions (count of "yes"), A16 family wealth
  items (sum of the levels, none = 0) and books;
* ``parent_tertiary``: A9/A12, either parent with a university degree (doctorate, master or
  equivalent, bachelor or equivalent; ST006/ST008 C01-C03), 1 or 0;
* ``parent_abitur``: A8/A11, either parent with Abitur or Fachhochschulreife (ST005/ST007 = 1);
* ``siblings``: A7 (ST230, 0 to 3 or more).

Network position from the main variant of ``outcomes.parquet``: C1 strength (tie minutes per
present day), C2 cross-course share and its excess over the random-mixing share, and degree
(``partners``: distinct close partners over the camp). For each pair: Spearman with a Fisher
interval, and the same fixed-effects OLS as above. A binary indicator whose smaller group has
fewer than ``MIN_GROUP`` people is withheld. DSA is a selective setting, so this is no answer to
RQ4 (the plan says so).

Unit: the confirmatory unit (participants with ``beacons`` and ``survey`` consent and a linked
kept submission). Run after ``confirmatory.py``:

    uv run --extra analysis python studies/dsa-2026/analyses/exploratory_survey.py

Writes ``new_ties.csv``, ``background.csv``, ``background_items.csv`` (distributions of the
indicators), ``qa.json`` and two figures to
``$SOCIAL_ENERGY_DATA/dsa-2026/derived/analyses/exploratory/``. Nothing per person is written.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import polars as pl

sys.path.insert(0, str(Path(__file__).parent))
import confirmatory as conf

from social_energy import paths
from social_energy.confirmatory import design, ols_hc3, zscore
from social_energy.spine import Spine
from social_energy.stats import correlation

SLUG = "exploratory"
MIN_GROUP = 5
C3 = {
    "c3_partners": "new partners after burn-in / day",
    "c3_daily": "new ties / day (first definition)",
    "c3_partners_all": "all partners / day",
}
NETWORK = {
    "strength_min_per_day": "C1 strength (min/day)",
    "cross_share": "C2 cross-course share",
    "cross_share_excess": "C2 excess over random mixing",
    "partners": "degree (distinct partners)",
}
#: Variant order for the side-by-side table (outcomes.py's names).
VARIANTS = [
    "main", "rssi_-70", "rssi_-75", "min_15", "min_30", "lost_both_sides", "hand_split_fill",
    "no_drift",
]  # fmt: skip
YES = 1  # A9/A12/A15: 1 = yes, 2 = no
TERTIARY = ["C01", "C02", "C03"]
BLUE, GRAY = "#2a78d6", "#8a8984"


# --- background indicators -----------------------------------------------------------------------


def background(items: pl.DataFrame) -> pl.DataFrame:
    """One row per respondent with the background indicators (nulls where unanswered)."""
    v = items.filter(pl.col("ok") & ~pl.col("empty")).select("respondent", "item", "value_numeric")

    def single(code: str, name: str) -> pl.DataFrame:
        return v.filter(pl.col("item") == code).select(
            "respondent", pl.col("value_numeric").cast(pl.Float64).alias(name)
        )

    def prefixed(prefix: str) -> pl.DataFrame:
        return v.filter(pl.col("item").str.starts_with(prefix))

    possessions = (
        prefixed("A15_ST250.")
        .group_by("respondent")
        .agg((pl.col("value_numeric") == YES).sum().cast(pl.Float64).alias("possessions"))
    )
    wealth = (
        prefixed("A16_ST251.")
        .group_by("respondent")
        .agg((pl.col("value_numeric") - 1).sum().cast(pl.Float64).alias("wealth"))
    )
    degree = pl.concat([prefixed("A9_ST006."), prefixed("A12_ST008.")])
    tertiary = (
        degree.filter(pl.col("item").str.extract(r"\.ST00[68](C\d\d)", 1).is_in(TERTIARY))
        .group_by("respondent")
        .agg((pl.col("value_numeric") == YES).any().cast(pl.Float64).alias("parent_tertiary"))
    )
    abitur = (
        v.filter(pl.col("item").is_in(["ST005", "ST007"]))
        .group_by("respondent")
        .agg((pl.col("value_numeric") == 1).any().cast(pl.Float64).alias("parent_abitur"))
    )
    out = pl.DataFrame({"respondent": items["respondent"].unique().sort()})
    for t in [
        single("ST259Q01JA", "social_status"),
        single("ST255", "books"),
        single("ST230", "siblings"),
        possessions,
        wealth,
        tertiary,
        abitur,
    ]:
        out = out.join(t, on="respondent", how="left")
    return out


def add_home_resources(frame: pl.DataFrame) -> pl.DataFrame:
    """``home_resources``: the mean of the available z-scores of possessions, wealth and books
    (z over ``frame``, so pass exactly the analysed sample)."""
    z = np.column_stack([zscore(frame[c].to_list()) for c in ("possessions", "wealth", "books")])
    valid = ~np.isnan(z)
    mean = np.where(valid.any(1), np.nansum(z, 1) / np.maximum(valid.sum(1), 1), np.nan)
    return frame.with_columns(pl.Series("home_resources", mean).fill_nan(None))


INDICATORS = {
    "social_status": "family social status (A14)",
    "books": "books at home (A18)",
    "home_resources": "home resources (A15, A16, A18)",
    "parent_tertiary": "a parent with a university degree (A9/A12)",
    "parent_abitur": "a parent with Abitur (A8/A11)",
    "siblings": "siblings (A7)",
}
BINARY = {"parent_tertiary", "parent_abitur"}


# --- models ---------------------------------------------------------------------------------------


def fe_effect(frame: pl.DataFrame, outcome: str, predictor: str) -> dict:
    """The confirmatory C1/C2 model, two-sided: std effect and its 95% interval."""
    d = design(
        frame,
        outcome=outcome,
        predictor=predictor,
        covariates=conf.COVARIATES,
        fixed_effect=conf.FIXED_EFFECT,
    )
    try:
        f = ols_hc3(d)
    except ValueError:
        return {"n_model": d.X.shape[0], "std": None, "std_lo": None, "std_hi": None}
    return {"n_model": f.n, "std": f.std_estimate, "std_lo": f.std_lo, "std_hi": f.std_hi,
            "b": f.estimate, "b_lo": f.lo, "b_hi": f.hi}  # fmt: skip


def spearman(frame: pl.DataFrame, x: str, y: str) -> dict:
    c = correlation(frame[x].to_list(), frame[y].to_list(), method="spearman")
    return {"n": c.n, "rho": c.r, "rho_lo": c.lo, "rho_hi": c.hi}


def unit_frame(layout: paths.StudyLayout, spine: Spine) -> tuple[pl.DataFrame, pl.DataFrame]:
    """The confirmatory unit with composites, age, female and course; and the linking table."""
    comps = pl.read_parquet(layout.derived / "analyses" / "confirmatory" / "composites.parquet")
    people = spine.people_frame().filter(pl.col("role") == "participant")
    submissions = pl.read_parquet(layout.derived / "survey" / "scoring" / "submissions.parquet")
    linked, _ = conf.linked_submissions(submissions, spine)
    unit = (
        comps.select("entity", "trust", "lust")
        .join(people.select("entity", "age", "gender", "course"), on="entity")
        .join(linked, on="entity")
        .with_columns((pl.col("gender") == conf.FEMALE).cast(pl.Float64).alias("female"))
    )
    return unit, linked


def main() -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    layout = paths.study(conf.STUDY)
    spine = Spine.load(layout.spine)
    out = layout.derived / "analyses" / SLUG
    out.mkdir(parents=True, exist_ok=True)
    unit, _ = unit_frame(layout, spine)
    outcomes = pl.read_parquet(layout.derived / "analyses" / "outcomes" / "outcomes.parquet")
    qa: dict = {"unit": unit.height}

    # -- 1. New ties: lust for life against every C3 definition and variant.
    rows = []
    for v in [v for v in VARIANTS if v in set(outcomes["variant"])]:
        f = unit.join(outcomes.filter(pl.col("variant") == v), on="entity")
        for c in C3:
            r = {"variant": v, "outcome": c, **spearman(f, "lust", c), **fe_effect(f, c, "lust")}
            if r["n"] < MIN_GROUP:
                r = {k: (val if k in ("variant", "outcome", "n") else None) for k, val in r.items()}
            rows.append(r)
    new_ties = pl.DataFrame(rows, infer_schema_length=None)
    new_ties.write_csv(out / "new_ties.csv")

    # -- 2. Background and embedding.
    items = pl.read_parquet(layout.derived / "survey" / "items.parquet")
    bg = unit.join(background(items), on="respondent", how="left")
    bg = add_home_resources(bg)
    main_o = outcomes.filter(pl.col("variant") == "main")
    bg = bg.join(main_o.select("entity", *NETWORK), on="entity", how="left")
    item_rows, rows = [], []
    for ind, label in INDICATORS.items():
        col = bg[ind].drop_nulls()
        small = False
        if ind in BINARY:
            ones = int(col.sum())
            small = min(ones, len(col) - ones) < MIN_GROUP
            item_rows.append({"indicator": ind, "n": len(col),
                              "share_1": None if small else ones / len(col),
                              "withheld": small})  # fmt: skip
        else:
            q = col.quantile
            item_rows.append({"indicator": ind, "n": len(col), "median": col.median(),
                              "q25": q(0.25), "q75": q(0.75), "withheld": False})  # fmt: skip
        for net in NETWORK:
            r = {"indicator": ind, "label": label, "network": net}
            if small:
                rows.append({**r, "withheld": True})
                continue
            r |= spearman(bg, ind, net) | fe_effect(bg, net, ind) | {"withheld": False}
            if ind in BINARY:
                for g in (0, 1):
                    r[f"median_{g}"] = bg.filter(pl.col(ind) == g)[net].median()
            rows.append(r)
    background_t = pl.DataFrame(rows, infer_schema_length=None)
    background_t.write_csv(out / "background.csv")
    pl.DataFrame(item_rows, infer_schema_length=None).write_csv(out / "background_items.csv")
    qa["background_complete_cases"] = {i: int(bg[i].is_not_null().sum()) for i in INDICATORS}
    qa["settings"] = {"min_group": MIN_GROUP, "covariates": conf.COVARIATES,
                      "fixed_effect": conf.FIXED_EFFECT}  # fmt: skip
    (out / "qa_survey.json").write_text(json.dumps(qa, indent=2), encoding="utf-8")

    # -- Figures: forest plots of the standardised effects (aggregates only).
    plt.rcParams.update({"font.size": 10, "axes.spines.top": False, "axes.spines.right": False})
    fig, axes = plt.subplots(1, len(C3), figsize=(12, 4.2), sharey=True)
    for ax, c in zip(axes, C3, strict=True):
        t = new_ties.filter(pl.col("outcome") == c)
        y = np.arange(t.height)[::-1]
        est = t["std"].to_numpy().astype(float)
        ax.errorbar(est, y, xerr=[est - t["std_lo"].to_numpy(), t["std_hi"].to_numpy() - est],
                    fmt="o", color=BLUE, ecolor=BLUE, capsize=2)  # fmt: skip
        ax.axvline(0, color=GRAY, lw=0.8)
        ax.set_yticks(y, t["variant"].to_list())
        ax.set_title(C3[c], loc="left", fontsize=10)
        ax.set_xlabel("SD of outcome per SD of lust for life")
    fig.suptitle("Exploratory: lust for life and new close partners, by threshold variant "
                 "(course FE, age, gender; 95% CI)", fontsize=10, x=0.01, ha="left")  # fmt: skip
    fig.tight_layout()
    fig.savefig(out / "fig_new_ties_variants.png", dpi=160)

    shown = background_t.filter(~pl.col("withheld"))
    fig, axes = plt.subplots(1, len(NETWORK), figsize=(14, 4.2), sharey=True)
    inds = [i for i in INDICATORS if i in set(shown["indicator"])]
    for ax, net in zip(axes, NETWORK, strict=True):
        t = shown.filter(pl.col("network") == net)
        t = t.sort(pl.col("indicator").replace_strict({i: k for k, i in enumerate(inds)}))
        y = np.arange(t.height)[::-1]
        r = t["rho"].to_numpy().astype(float)
        ax.errorbar(r, y, xerr=[r - t["rho_lo"].to_numpy(), t["rho_hi"].to_numpy() - r],
                    fmt="o", color=BLUE, capsize=2)  # fmt: skip
        ax.axvline(0, color=GRAY, lw=0.8)
        ax.set_xlim(-0.7, 0.7)
        ax.set_yticks(y, [INDICATORS[i] for i in t["indicator"]])
        ax.set_title(NETWORK[net], loc="left", fontsize=10)
        ax.set_xlabel("Spearman rho (95% CI)")
    fig.suptitle("Exploratory: family background and network position", fontsize=10, x=0.01,
                 ha="left")  # fmt: skip
    fig.tight_layout()
    fig.savefig(out / "fig_background_network.png", dpi=160)

    with pl.Config(tbl_rows=200, tbl_cols=20, fmt_str_lengths=40):
        print(json.dumps(qa, indent=2))
        print(new_ties.select("variant", "outcome", "n", "rho", "rho_lo", "rho_hi", "std",
                              "std_lo", "std_hi"))  # fmt: skip
        print(pl.DataFrame(item_rows, infer_schema_length=None))
        print(background_t.select("indicator", "network", "n", "rho", "rho_lo", "rho_hi", "std",
                                  "std_lo", "std_hi", "withheld"))  # fmt: skip


if __name__ == "__main__":
    main()
