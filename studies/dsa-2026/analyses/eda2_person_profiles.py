"""Exploratory tier, EDA second pass, analysis G: person profiles, their reliability, and what the
reliable ones go with.

``docs/plans/ongoing/eda-second-pass.md``, section G, under the frozen analysis plan
(``research/analysis-plan.md``, "Exploratory analyses"). **Every result here is exploratory**: no
error control, two-sided, correlations with 95% intervals and no p-values, nothing reported for
fewer than ``MIN_GROUP`` people. With some tens of people per correlation, these are weak: an
interval of about +-0.3 around a Spearman coefficient is the normal case. Construct: a stable
personal physiological "style" in company `[inferred: our reading, not signed off by the research
team]`.

**Profiles** (``PROFILES``), one value per person and half (``discovery``, ``replication`` and
``all`` days of ``eda_split``), read from the second-pass outputs (their CSVs, not their code):

* ``scr_dose_amp02`` / ``scr_dose_main`` (analysis A, ``social_dose/person_day_dose.csv``): the
  person-day slope of the movement-adjusted SCR rate (>= 0.2 µS / main rule) on
  ``log(1 + n close)``, averaged over the person's days in the half with **inverse-variance
  weights** (1 / SE^2; person-days without a finite slope and positive SE leave).
* ``sync_dtonic`` / ``sync_scr_amp02`` (analysis C, ``pair_sync/person_sync.csv``, clock
  ``all``): the person's mean lag-0 synchrony with close partners over their pair-days, tonic
  change and SCR >= 0.2 µS.
* ``hrv_level`` / ``hrv_dose`` (analysis E, ``hrv/person_hrv.csv``): mean log RMSSD over still
  HRV minutes, and the person's slope of adjusted log RMSSD on ``log(1 + n close)``.
* ``scr_var_amp02`` / ``scr_var_main``, computed here from the first pass's minutes
  (``exploratory_eda.load_person_minutes`` and ``minutes_for``, clock ``all``): the SD over a
  person-day's usable minutes of the movement-adjusted SCR rate, in SCR per minute. The first
  pass's adjustment works on the within-person-day z (``r_pd_*``), whose SD is near 1 by
  construction, so it is put back on the raw scale: SD of the raw rate x SD of ``r_pd_*``
  (the residual times the person-day's SD is the residual in SCR/min). Person-days need
  ``MIN_PD_MINUTES`` usable minutes; days are ``eda_split.camp_day``; the person value is the
  **minute-weighted** mean of their person-days. It moves with the person's mean rate.

**Reliability gate.** For each profile, over people with a value in both halves: Spearman
between the discovery and replication values, Spearman-Brown corrected to the whole camp
(``2r / (1 + r)``), with a percentile interval from resampling people (``cluster_bootstrap``; the
correction is monotone, so it maps the interval of r). Only profiles whose corrected point
estimate is at least ``GATE`` (0.5) are related to anything. Every profile's reliability and n is
reported. Here the split is the reliability check, not the plan's verdict rule, so no verdict.

**Relations** of each profile that passes, on its all-days value (Spearman, bootstrap over people):

* ``trust``, ``lust``: the survey composites of the confirmatory unit
  (``exploratory_survey.unit_frame``: ``beacons`` and ``survey`` consent, a linked kept
  submission);
* ``D_academy_lenient``: the primary membrane change from the interview codes
  (``exploratory_membrane.code_frame``, variant ``main``; ``interview_in_person`` consent);
* ``degree``: close-contact degree, ``c3_partners_all`` of ``outcomes.py`` (variant ``main``):
  distinct close partners over the camp per present day (``beacons`` consent). Per present day,
  so wear time does not make degree.

**Consent.** Every relation keeps only participants with every module its two sides need: the
profile's (``eda``, and ``beacons`` for those built on close contact) and the target's.

Run after analyses A, C and E (``eda2_social_dose.py``, ``eda2_pair_sync.py``, ``eda2_hrv.py``),
``confirmatory.py``, ``outcomes.py`` and the interview coding:

    uv run --extra analysis python studies/dsa-2026/analyses/eda2_person_profiles.py

Writes ``reliability.csv``, ``relations.csv``, ``qa.json`` and one aggregate figure to
``$SOCIAL_ENERGY_DATA/dsa-2026/derived/analyses/exploratory/eda2/person_profiles/``;
``profiles.csv`` there is per person and stays in the private data root.
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import numpy as np
import polars as pl

sys.path.insert(0, str(Path(__file__).parent))
import eda_split as es

from social_energy.stats import cluster_bootstrap

STUDY = "dsa-2026"
SLUG = "exploratory/eda2/person_profiles"
EDA2 = "exploratory/eda2"
MIN_GROUP = 5
GATE = 0.5
MIN_PD_MINUTES = 30
N_BOOT = 2000
SEED = 20261029
HALVES = ("discovery", "replication")
#: Profile -> (label, source, consent modules it needs).
PROFILES = {
    "scr_dose_amp02": ("SCR dose slope, >= 0.2 µS (A)", "A", ("eda", "beacons")),
    "scr_dose_main": ("SCR dose slope, main (A)", "A", ("eda", "beacons")),
    "sync_dtonic": ("pair synchrony, tonic change (C)", "C", ("eda", "beacons")),
    "sync_scr_amp02": ("pair synchrony, SCR >= 0.2 µS (C)", "C", ("eda", "beacons")),
    "hrv_level": ("HRV level, mean log RMSSD (E)", "E", ("eda",)),
    "hrv_dose": ("HRV dose slope (E)", "E", ("eda", "beacons")),
    "scr_var_amp02": ("SCR rate variability, >= 0.2 µS", "G", ("eda",)),
    "scr_var_main": ("SCR rate variability, main", "G", ("eda",)),
}
#: Target -> (label, consent modules it needs).
TARGETS = {
    "trust": ("trust in life (survey)", ("beacons", "survey")),
    "lust": ("lust for life (survey)", ("beacons", "survey")),
    "D_academy_lenient": ("membrane change (interview)", ("interview_in_person",)),
    "degree": ("close-contact degree per day", ("beacons",)),
}
BLUE, ORANGE, GRAY = "#2a78d6", "#eb6834", "#8a8984"


# --- reliability ---------------------------------------------------------------------------------


def spearman_brown(r: float) -> float:
    """Reliability of the doubled test from the split-half correlation ``r``: ``2r / (1 + r)``.
    NaN for NaN; minus infinity at ``r = -1``."""
    if r is None or math.isnan(r):
        return math.nan
    if r <= -1:
        return -math.inf
    return 2 * r / (1 + r)


def split_half(profiles: pl.DataFrame, profile: str, *, n_boot: int = N_BOOT, seed: int = SEED):
    """Split-half reliability of one profile from a long table (``entity``, ``half``, ``profile``,
    ``value``): people with a finite value in both halves, Spearman between the halves, its
    Spearman-Brown correction and a bootstrap interval over people. Values withheld (NaN) for
    fewer than ``MIN_GROUP`` people."""
    wide = (
        profiles.filter((pl.col("profile") == profile) & pl.col("value").is_finite())
        .filter(pl.col("half").is_in(HALVES))
        .pivot(on="half", index="entity", values="value")
        .sort("entity")
    )
    both = wide.drop_nulls([h for h in HALVES if h in wide.columns]) if wide.height else wide
    n = both.height if all(h in both.columns for h in HALVES) else 0
    row = {"profile": profile, "n_both": n, "r_split": math.nan, "r_lo": math.nan,
           "r_hi": math.nan, "reliability": math.nan, "rel_lo": math.nan,
           "rel_hi": math.nan}  # fmt: skip
    if n < MIN_GROUP:
        return row
    c = cluster_bootstrap(
        both["discovery"].to_list(), both["replication"].to_list(), both["entity"].to_list(),
        method="spearman", n_boot=n_boot, seed=seed,
    )  # fmt: skip
    row |= {"r_split": c.r, "r_lo": c.lo, "r_hi": c.hi, "reliability": spearman_brown(c.r),
            "rel_lo": spearman_brown(c.lo), "rel_hi": spearman_brown(c.hi)}  # fmt: skip
    return row


def passes(reliability: float, gate: float = GATE) -> bool:
    """The gate: a finite corrected reliability of at least ``gate``."""
    return reliability is not None and math.isfinite(reliability) and reliability >= gate


def reliability_table(profiles: pl.DataFrame, **kw) -> pl.DataFrame:
    rows = []
    for p, (label, source, _) in PROFILES.items():
        counts = {
            f"n_{h}": profiles.filter(
                (pl.col("profile") == p) & (pl.col("half") == h) & pl.col("value").is_finite()
            ).height
            for h in (*HALVES, "all")
        }
        r = split_half(profiles, p, **kw)
        rows.append({"profile": p, "label": label, "source": source, **counts, **r,
                     "passes_gate": passes(r["reliability"])})  # fmt: skip
    return pl.DataFrame(rows, infer_schema_length=None)


# --- relations -----------------------------------------------------------------------------------


def consented_for(consents: dict[str, set[str]], modules) -> set[str]:
    """Entities with every module in ``modules``."""
    sets = [consents.get(m, set()) for m in modules]
    return set.intersection(*sets) if sets else set()


def relations(
    profiles: pl.DataFrame,
    targets: pl.DataFrame,
    gated: list[str],
    consents: dict[str, set[str]],
    *,
    n_boot: int = N_BOOT,
    seed: int = SEED,
) -> pl.DataFrame:
    """Spearman of each gated profile's all-days value with each target (``entity`` + one column
    per target), over people with every needed consent; withheld under ``MIN_GROUP``."""
    rows = []
    for p in gated:
        x = profiles.filter(
            (pl.col("profile") == p) & (pl.col("half") == "all") & pl.col("value").is_finite()
        ).select("entity", "value")
        for t, (label, t_mods) in TARGETS.items():
            ok = consented_for(consents, (*PROFILES[p][2], *t_mods))
            f = (
                x.join(targets.select("entity", t), on="entity")
                .filter(pl.col("entity").is_in(list(ok)) & pl.col(t).is_not_null())
                .filter(pl.col(t).is_finite())
                .sort("entity")
            )
            row = {"profile": p, "target": t, "target_label": label, "n": f.height,
                   "rho": None, "lo": None, "hi": None}  # fmt: skip
            if f.height >= MIN_GROUP:
                c = cluster_bootstrap(f["value"].to_list(), f[t].to_list(), f["entity"].to_list(),
                                      method="spearman", n_boot=n_boot, seed=seed)  # fmt: skip
                row |= {"rho": c.r, "lo": c.lo, "hi": c.hi}
            rows.append(row)
    schema = {"profile": pl.String, "target": pl.String, "target_label": pl.String,
              "n": pl.Int64, "rho": pl.Float64, "lo": pl.Float64, "hi": pl.Float64}  # fmt: skip
    return pl.DataFrame(rows, schema=schema)


# --- profiles ------------------------------------------------------------------------------------


def _long(df: pl.DataFrame, cols: dict[str, str]) -> pl.DataFrame:
    """``entity``, ``half``, ``profile``, ``value`` from a person x half table."""
    return pl.concat(
        [df.select("entity", "half", pl.lit(p).alias("profile"),
                   pl.col(c).cast(pl.Float64).alias("value")) for p, c in cols.items()]
    )  # fmt: skip


def with_all(df: pl.DataFrame) -> pl.DataFrame:
    """A person-day table (``half`` set) plus every row again under ``half = "all"``."""
    return pl.concat([df, df.with_columns(pl.lit("all").alias("half"))])


def dose_profiles(dose: pl.DataFrame) -> pl.DataFrame:
    """Inverse-variance mean of the person-day SCR dose slopes per person and half."""
    out = []
    for rule in ("amp02", "main"):
        s, se = f"slope_scr_{rule}", f"se_scr_{rule}"
        d = with_all(
            dose.select("entity", "half", pl.col(s).alias("b"), pl.col(se).alias("se"))
            .filter(pl.col("b").is_finite() & pl.col("se").is_finite() & (pl.col("se") > 0))
            .with_columns((1 / pl.col("se") ** 2).alias("w"))
        )
        agg = d.group_by("entity", "half").agg(
            ((pl.col("b") * pl.col("w")).sum() / pl.col("w").sum()).alias("value")
        )
        out.append(agg.select("entity", "half", pl.lit(f"scr_dose_{rule}").alias("profile"),
                              "value"))  # fmt: skip
    return pl.concat(out)


def variability_profiles(m: pl.DataFrame) -> pl.DataFrame:
    """SCR rate variability per person and half from standardised first-pass minutes (``entity``,
    ``minute``, ``usable``, ``scr_<rule>``, ``r_pd_scr_<rule>``)."""
    m = m.filter(pl.col("usable")).with_columns(es.camp_day(pl.col("minute")).alias("sday"))
    m = m.with_columns(es.half_of(pl.col("sday")).alias("half")).filter(
        pl.col("half").is_not_null()
    )
    out = []
    for rule in ("amp02", "main"):
        pd_ = (
            m.filter(pl.col(f"r_pd_scr_{rule}").is_not_null())
            .group_by("entity", "sday", "half")
            .agg(
                pl.len().alias("n"),
                (pl.col(f"scr_{rule}").std() * pl.col(f"r_pd_scr_{rule}").std()).alias("v"),
            )
            .filter((pl.col("n") >= MIN_PD_MINUTES) & pl.col("v").is_finite())
        )
        agg = (
            with_all(pd_)
            .group_by("entity", "half")
            .agg(((pl.col("v") * pl.col("n")).sum() / pl.col("n").sum()).alias("value"))
        )
        out.append(agg.select("entity", "half", pl.lit(f"scr_var_{rule}").alias("profile"),
                              "value"))  # fmt: skip
    return pl.concat(out)


def load_profiles(layout, spine) -> tuple[pl.DataFrame, dict]:
    import exploratory_eda as xe

    root = layout.derived / "analyses" / EDA2
    dose = pl.read_csv(root / "social_dose" / "person_day_dose.csv", try_parse_dates=True)
    sync = pl.read_csv(root / "pair_sync" / "person_sync.csv").filter(pl.col("clock") == "all")
    hrv = pl.read_csv(root / "hrv" / "person_hrv.csv")
    pm, counts = xe.load_person_minutes(layout, spine)
    m, _ = xe.minutes_for(pm, counts, "all")
    m = m.select("entity", "minute", "usable", "scr_amp02", "scr_main", "r_pd_scr_amp02",
                 "r_pd_scr_main")  # fmt: skip
    del pm, counts
    long = pl.concat(
        [
            dose_profiles(dose),
            _long(
                sync, {"sync_dtonic": "sync_dtonic_close", "sync_scr_amp02": "sync_scr_amp02_close"}
            ),
            _long(hrv, {"hrv_level": "mean_log_rmssd", "hrv_dose": "dose_slope"}),
            variability_profiles(m),
        ]
    ).filter(pl.col("value").is_not_null())
    qa = {
        "dose_person_days": dose.height,
        "sync_rows_clock_all": sync.height,
        "hrv_rows": hrv.height,
        "variability_people": long.filter(pl.col("profile") == "scr_var_amp02")[
            "entity"
        ].n_unique(),
    }
    return long.sort("profile", "half", "entity"), qa


# --- targets -------------------------------------------------------------------------------------


def load_targets(layout, spine) -> tuple[pl.DataFrame, dict]:
    import exploratory_membrane as xm
    import exploratory_survey as xs

    unit, _ = xs.unit_frame(layout, spine)
    survey = unit.select("entity", "trust", "lust")
    root = layout.derived / "interview-membrane"
    participants = {p.ref for p in spine.people if p.role == "participant"}
    interview_ok = {f"person:{p}" for p in spine.consented("interview_in_person")}
    accounts = spine.account_entities("interview")
    people = {k: e for k, e in accounts.select("account", "entity").iter_rows()
              if e in participants and e in interview_ok}  # fmt: skip
    codes = xm.code_frame(xm.read_codes(root / "codes"), people, "main")
    membrane = codes.select("entity", pl.col("D_academy_lenient").cast(pl.Float64))
    outcomes = pl.read_parquet(layout.derived / "analyses" / "outcomes" / "outcomes.parquet")
    degree = outcomes.filter(pl.col("variant") == "main").select(
        "entity", pl.col("c3_partners_all").cast(pl.Float64).alias("degree")
    )
    every = pl.concat([survey["entity"], membrane["entity"], degree["entity"]]).unique()
    t = (
        pl.DataFrame({"entity": every})
        .join(survey, on="entity", how="left")
        .join(membrane, on="entity", how="left")
        .join(degree, on="entity", how="left")
        .filter(pl.col("entity").is_in(list(participants)))
    )
    qa = {c: int(t[c].is_not_null().sum()) for c in TARGETS}
    return t, qa


# --- figure --------------------------------------------------------------------------------------


def figure(out: Path, rel: pl.DataFrame) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    r = rel.filter(pl.col("reliability").is_not_null() & pl.col("reliability").is_not_nan())
    fig, ax = plt.subplots(figsize=(7.5, 0.45 * max(len(PROFILES), 4) + 1.2))
    y = np.arange(r.height)[::-1]
    for yi, row in zip(y, r.iter_rows(named=True), strict=True):
        lo = max(row["rel_lo"], -1.0) if math.isfinite(row["rel_lo"]) else -1.0
        hi = row["rel_hi"]
        color = BLUE if row["passes_gate"] else GRAY
        ax.plot([lo, hi], [yi, yi], color=color, lw=2)
        ax.plot(row["reliability"], yi, "o", color=color, ms=6)
    ax.axvline(GATE, color=ORANGE, lw=1.5, ls="--", label=f"gate ({GATE})")
    ax.axvline(0, color=GRAY, lw=1, ls=":")
    ax.set_yticks(y, r["label"].to_list())
    ax.set_xlim(-1.05, 1.05)
    ax.set_xlabel("split-half reliability, Spearman-Brown corrected (95% bootstrap over people)")
    ax.set_title("Person profiles: which are stable across halves of the camp", loc="left")
    ax.legend(loc="lower right", frameon=False)
    ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout()
    fig.savefig(out / "fig_person_profiles.png", dpi=150)
    plt.close(fig)


# --- main ----------------------------------------------------------------------------------------


def main() -> None:
    from social_energy import paths
    from social_energy.spine import Spine

    layout = paths.study(STUDY)
    spine = Spine.load(layout.spine)
    out = layout.derived / "analyses" / SLUG
    out.mkdir(parents=True, exist_ok=True)
    modules = {m for _, _, ms in PROFILES.values() for m in ms} | {
        m for _, ms in TARGETS.values() for m in ms
    }
    consents = {m: {f"person:{p}" for p in spine.consented(m)} for m in modules}

    profiles, qa_p = load_profiles(layout, spine)
    profiles.write_csv(out / "profiles.csv")
    rel = reliability_table(profiles)
    rel.write_csv(out / "reliability.csv")
    gated = rel.filter(pl.col("passes_gate"))["profile"].to_list()
    targets, qa_t = load_targets(layout, spine)
    links = relations(profiles, targets, gated, consents)
    links.write_csv(out / "relations.csv")
    figure(out, rel)

    qa = {"profiles": qa_p, "targets": qa_t, "gated": gated,
          "consent_counts": {m: len(s) for m, s in sorted(consents.items())},
          "settings": {"min_group": MIN_GROUP, "gate": GATE, "min_pd_minutes": MIN_PD_MINUTES,
                       "n_boot": N_BOOT, "seed": SEED, "dose_weights": "inverse variance",
                       "variability_weights": "usable minutes", "sync_clock": "all",
                       "degree": "c3_partners_all (outcomes main)",
                       "discovery": [str(d) for d in es.DISCOVERY],
                       "replication": [str(d) for d in es.REPLICATION]}}  # fmt: skip
    (out / "qa.json").write_text(json.dumps(qa, indent=2, default=str), encoding="utf-8")
    with pl.Config(tbl_rows=100, tbl_cols=20, tbl_width_chars=250, fmt_str_lengths=40):
        print(json.dumps(qa, indent=2, default=str))
        print(rel.drop("label"))
        print(links.drop("target_label"))


if __name__ == "__main__":
    main()
