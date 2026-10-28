"""Exploratory: the gradient theory. Do people whose membranes differ meet and press together more?

**Everything here is exploratory, and outside the frozen plan** (``research/analysis-plan.md``,
frozen 2026-10-19). The question came from the research team after the plan was frozen (a note of
25 Oct 2026), so nothing here confirms or refutes anything: no error control, effects beside
their null distributions, and a fresh field phase to test whatever looks promising. The mapping
of the theory to these measures is our own `[inferred]`.

The theory, in our words: each person's *membrane* is described by the survey's trust-in-life and
lust-for-life dimensions and the scales that make them up; a difference between two membranes is
a *gradient*, and gradients make a reaction between people possible. Two leads follow, each set
against the plain alternative that similar people attract (homophily):

* **(H-a) Opposites attract.** Pairs whose membranes differ more spend more time close together.
  Beside it, **repulsion**: are the pairs who rarely meet more alike, or more different?
* **(H-b) Gradients make flow more probable.** When a person presses the self-report button with
  someone close by, the partner is more likely to press too (a co-located press pair, as in
  ``exploratory_cascades.py``) when their membranes differ more.

**Unit.** The confirmatory unit (``exploratory_survey.unit_frame``: participants with ``beacons``
and ``survey`` consent and a linked kept submission). Press analyses also need ``self_report``
consent and exposure (``exploratory_presses.load``).

**Membrane distance** per pair (``MEASURES``), on the confirmatory standardisation (each scale
z-scored across the unit; composites as in ``confirmatory.py``):

* ``trust``, ``lust``: absolute difference of the composites;
* ``trust_scales``, ``lust_scales``: Euclidean distance over the six z-scored scales of each
  dimension; ``all_scales``: over all twelve;
* per scale (secondary, ``scales.csv``): absolute difference of each z-scored scale.

**(H-a) Pair contact.** All unordered pairs of unit people, from ``copresence_by_phase.py build``
on the main settings of ``outcomes.py``: camp days 13-28 Aug, close at ``CLOSE_RSSI`` or
stronger. Outcomes: ``log_close`` = log(1 + close minutes over the camp) (primary), ``log_tie_days``
= log(1 + days tied, close for ``TIE_MIN`` minutes or more) and ``tied`` (ever tied; a linear
probability model). Controls: log of the bins in which both tags were heard (the pair's joint
exposure; pairs never heard together are left out), same course, and one dummy per person, so
each person's own sociability, wear time and membrane *level* are absorbed and only what is
specific to the pair remains. Variant without the person dummies. Effect: the partial
correlation of distance with the outcome given the controls (and the slope per SD of distance).
Samples: all pairs, within-course pairs, between-course pairs (courses dominate contact).
**Sign:** a negative effect means similar people meet more (homophily), a positive one means
different people do (the theory's "opposites attract").

**Null (QAP).** Pairs share people, so pair-level p-values would be far too optimistic. The
membranes are permuted among people of the same course (``N_PERM`` times), which keeps the
network, the controls and each course's membrane mix, and moves only who carries which membrane.
Reported: the observed effect, the null mean and 95% band, the observed effect's percentile in the
null, and the share of null draws at least as far from the null mean (two-sided).

**Repulsion.** Within each sample, pairs in the bottom ``RARE_Q`` of the residual contact (contact
given the controls above) are pairs who "rarely meet" for who they are and how long they were
heard together; their mean distance (in SDs of the sample's distance) minus that of all pairs,
against the same null; the top ``RARE_Q`` likewise.

**(H-b) Presses.** Every press episode of a unit person, and every *partner*: a unit person with
``self_report`` consent at close range in the press's 5-minute bin who was exposed in that bin
(``partner_coevents``). The partner co-pressed when they had a press episode within ``WINDOW`` s
either side. Statistic: mean distance (in SDs of the distance over all unit pairs) of partners who
co-pressed minus of those who did not; and the co-press share by distance tercile (terciles over all
unit pairs). Two nulls: (1) *node permutation* within course, which keeps every press and every
partner and moves only the membranes; (2) *time shuffle*, every press moved to a random exposure bin
of the same person, camp day and phase of day (``shuffle_events``, ``N_SHUFFLE`` times; the
cascades null), which keeps who carries which membrane and each person's press rate, so a link
between membrane and press rate cannot make the effect. Also split into within- and
between-course partners.

**Caveats** for any reading: about 75 people (a few thousand pairs that are far from independent);
composite reliability is modest (alpha about 0.7 for trust); many distances x samples x outcomes are
reported with no correction; contact is co-presence, not interaction; and exposure is controlled
only as well as the joint heard bins capture it.

    uv run --extra analysis python studies/dsa-2026/analyses/exploratory_gradients.py

Run after ``confirmatory.py`` and ``copresence_by_phase.py build`` (and ``beacon_diagnostics.py``
for the press exposure). Writes CSVs, ``qa_gradients.json`` and two figures to
``$SOCIAL_ENERGY_DATA/dsa-2026/derived/analyses/exploratory/gradients/``. Nothing per person or
per pair is written.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import polars as pl

sys.path.insert(0, str(Path(__file__).parent))
import confirmatory as conf
import copresence_by_phase as cp
import exploratory_presses as xp
import exploratory_survey as xs
import outcomes as oc

from social_energy import paths
from social_energy.confirmatory import composite, permute_within
from social_energy.dyads import (
    Residualiser,
    attribute_distance,
    node_dummies,
    node_permutation_null,
    null_position,
    pair_index,
    partial_fit,
    partner_coevents,
)
from social_energy.exploratory import shuffle_events
from social_energy.spine import Spine
from social_energy.study import StudyConfig

SLUG = "exploratory/gradients"
MIN_GROUP = 5
CLOSE_RSSI = cp.CLOSE_RSSI
BIN_S = xp.BIN_S
BIN_MIN = BIN_S // 60
TIE_MIN = cp.TIE_MIN_BINS * BIN_MIN
DAYS = oc.DAYS
WINDOW = 300
RARE_Q = 0.2
N_PERM = 2000
N_SHUFFLE = 1000
SEED = 20261028
TRUST = [f"z_{s}" for s in conf.SCALES["trust"]]
LUST = [f"z_{s}" for s in conf.SCALES["lust"]]
#: Membrane distances: name -> (label, columns of the person table).
MEASURES = {
    "trust": ("trust in life (composite)", ["trust"]),
    "lust": ("lust for life (composite)", ["lust"]),
    "trust_scales": ("trust scales (Euclidean, 6)", TRUST),
    "lust_scales": ("lust scales (Euclidean, 6)", LUST),
    "all_scales": ("all 12 scales (Euclidean)", TRUST + LUST),
}
OUTCOMES = {
    "log_close": "log(1 + close minutes)",
    "log_tie_days": "log(1 + days tied)",
    "tied": "ever tied (0/1)",
}
SAMPLES = ("all", "within course", "between course")
BLUE, ORANGE, GRAY = cp.BLUE, cp.ORANGE, cp.GRAY


# --- inputs ---------------------------------------------------------------------------------------


def membranes(layout: paths.StudyLayout, spine: Spine) -> pl.DataFrame:
    """One row per unit person, sorted: entity, course, composites and the twelve scale z-scores
    (standardised across the unit, as ``confirmatory.py`` does)."""
    unit, linked = xs.unit_frame(layout, spine)
    config = StudyConfig.load(conf.STUDY_YAML)
    long = conf.scale_scores(layout, config.survey_scoring_config().codebook, linked).filter(
        pl.col("entity").is_in(unit["entity"].implode())
    )
    out = unit.select("entity", "course", "trust", "lust")
    for block, scales in conf.SCALES.items():
        c = composite(long, scales, min_valid=conf.MIN_VALID)
        out = out.join(
            c.select("entity", *[f"z_{s}" for s in scales],
                     pl.col("composite").alias(f"{block}_check")),
            on="entity", how="left",
        )  # fmt: skip
    return out.sort("entity")


def pair_contact(people: list[str], spine_days: list) -> pl.DataFrame:
    """Per unordered pair of ``people`` (positions ``i < j``): close minutes, days tied and joint
    heard bins over ``spine_days``. Pairs never close have zero minutes."""
    pos = {e: k for k, e in enumerate(people)}
    in_days = pl.col("day").is_in(spine_days)
    pairs = cp.load_all("pairs").filter(
        pl.col("a").is_in(people) & pl.col("b").is_in(people) & in_days
    )
    close = (
        pairs.filter(pl.col("max_rssi") >= CLOSE_RSSI)
        .with_columns(
            pl.col("a").replace_strict(pos).alias("pa"), pl.col("b").replace_strict(pos).alias("pb")
        )
        .with_columns(
            pl.min_horizontal("pa", "pb").alias("i"), pl.max_horizontal("pa", "pb").alias("j")
        )
        .group_by("i", "j", "day")
        .agg((pl.col("bin").n_unique() * BIN_MIN).alias("minutes"))
        .group_by("i", "j")
        .agg(
            pl.col("minutes").sum().alias("close_minutes"),
            (pl.col("minutes") >= TIE_MIN).sum().alias("tie_days"),
        )
    )
    seen = cp.load_all("seen").filter(pl.col("entity").is_in(people) & in_days)
    bins = {b: k for k, b in enumerate(seen["bin"].unique().sort())}
    M = np.zeros((len(people), len(bins)), dtype=np.float32)
    M[
        seen["entity"].replace_strict(pos).to_numpy(),
        seen["bin"].replace_strict(bins, return_dtype=pl.Int64).to_numpy(),
    ] = 1
    joint = M @ M.T
    i, j = pair_index(len(people))
    base = pl.DataFrame({"i": i, "j": j, "joint_bins": joint[i, j].astype(np.int64)})
    return (
        base.join(close.with_columns(pl.col("i", "j").cast(pl.Int64)), on=["i", "j"], how="left")
        .with_columns(pl.col("close_minutes", "tie_days").fill_null(0))
        .sort("i", "j")
    )


# --- (H-a) pair contact against membrane distance -------------------------------------------------


def two_partial(y: np.ndarray, x: np.ndarray, other: np.ndarray) -> float:
    """Partial correlation of ``y`` and ``x`` given ``other``, all already residualised on the
    same controls (Frisch-Waugh-Lovell once more)."""
    oo = other @ other
    if oo <= 0:
        return float("nan")
    return partial_fit(y - other * (other @ y) / oo, x - other * (other @ x) / oo).partial_r


class PairSample:
    """The pairs of one sample with their outcomes residualised on the controls, ready for
    distances recomputed under any permutation of the people."""

    def __init__(self, contact: pl.DataFrame, course: np.ndarray, sample: str, fe: bool):
        f = contact.filter(pl.col("joint_bins") > 0)
        i, j = f["i"].to_numpy(), f["j"].to_numpy()
        same = course[i] == course[j]
        keep = {"all": np.ones(len(i), bool), "within course": same,
                "between course": ~same}[sample]  # fmt: skip
        f, i, j, same = f.filter(pl.Series(keep)), i[keep], j[keep], same[keep]
        cols = [np.ones(len(i)), np.log(f["joint_bins"].to_numpy().astype(float))]
        if sample == "all":
            cols.append(same.astype(float))
        Z = np.column_stack(cols)
        n = len(course)
        if fe:
            Z = np.column_stack([Z, node_dummies(i, j, n)])
        self.sample, self.fe, self.i, self.j = sample, fe, i, j
        self.pairs = len(i)
        self.people = len(set(i.tolist()) | set(j.tolist()))
        self.r = Residualiser(Z)
        minutes = f["close_minutes"].to_numpy().astype(float)
        days = f["tie_days"].to_numpy().astype(float)
        self.raw = {"log_close": np.log1p(minutes), "log_tie_days": np.log1p(days),
                    "tied": (days > 0).astype(float)}  # fmt: skip
        self.y = {k: self.r(v) for k, v in self.raw.items()}

    def distance(self, X: np.ndarray, perm: np.ndarray) -> np.ndarray:
        return attribute_distance(X[perm], self.i, self.j)

    def effect(self, X: np.ndarray, outcome: str):
        def stat(perm: np.ndarray) -> float:
            return partial_fit(self.y[outcome], self.r(self.distance(X, perm))).partial_r

        return stat


def qap_row(stat, groups) -> dict:
    identity = np.arange(len(groups))
    obs = stat(identity)
    pos = null_position(obs, node_permutation_null(stat, groups, n_perm=N_PERM, seed=SEED))
    return {"partial_r": pos.observed, "null_mean": pos.null_mean, "null_lo": pos.null_lo,
            "null_hi": pos.null_hi, "percentile": pos.percentile,
            "share_as_extreme": pos.share_as_extreme,
            "reading": "different attract" if obs > 0 else "similar attract"}  # fmt: skip


def pair_effects(samples: dict, X: dict, groups: np.ndarray) -> pl.DataFrame:
    rows = []
    identity = np.arange(len(groups))
    for (sample, fe), s in samples.items():
        outcomes = OUTCOMES if fe else ["log_close"]
        for o in outcomes:
            for m, (label, _) in MEASURES.items():
                d = s.distance(X[m], identity)
                fit = partial_fit(s.y[o], s.r(d))
                slope_sd = fit.slope * float(np.std(d, ddof=1))
                r = {"sample": sample, "person_fe": fe, "outcome": o, "measure": m,
                     "label": label, "pairs": s.pairs, "people": s.people,
                     **qap_row(s.effect(X[m], o), groups), "slope_per_sd": slope_sd,
                     "pct_change_per_sd": float(np.expm1(slope_sd)) if o == "log_close"
                     else None}  # fmt: skip
                if s.people < MIN_GROUP:
                    r = {k: v for k, v in r.items() if k in ("sample", "person_fe", "outcome",
                                                             "measure", "people")}  # fmt: skip
                rows.append(r)
    return pl.DataFrame(rows, infer_schema_length=None)


def joint_effects(samples: dict, X: dict, groups: np.ndarray) -> pl.DataFrame:
    """Trust and lust distances in one model: each one's partial correlation given the other."""
    rows = []
    for sample in SAMPLES:
        s = samples[(sample, True)]
        y = s.y["log_close"]
        for m, other in (("trust", "lust"), ("lust", "trust")):

            def stat(p, s=s, y=y, m=m, other=other):
                return two_partial(y, s.r(s.distance(X[m], p)), s.r(s.distance(X[other], p)))

            rows.append({"sample": sample, "measure": m, "given": other, "pairs": s.pairs,
                         "people": s.people, **qap_row(stat, groups)})  # fmt: skip
    return pl.DataFrame(rows)


def scale_effects(samples: dict, Z: np.ndarray, names: list[str], groups) -> pl.DataFrame:
    rows = []
    for sample in SAMPLES:
        s = samples[(sample, True)]
        for k, name in enumerate(names):
            rows.append({"sample": sample, "scale": name.removeprefix("z_"), "pairs": s.pairs,
                         **qap_row(s.effect(Z[:, k], "log_close"), groups)})  # fmt: skip
    return pl.DataFrame(rows)


def repulsion(samples: dict, X: dict, groups: np.ndarray) -> pl.DataFrame:
    """Mean distance (SDs of the sample's distance) of the pairs who meet least, and most, given
    the controls, minus that of all pairs; against the node-permutation null."""
    rows = []
    for (sample, fe), s in samples.items():
        res = s.y["log_close"]
        lo, hi = np.quantile(res, [RARE_Q, 1 - RARE_Q])
        for group, mask in (("rarely meet", res <= lo), ("often meet", res >= hi)):
            people = len(set(s.i[mask].tolist()) | set(s.j[mask].tolist()))
            for m in ("trust", "lust", "all_scales"):

                def stat(p, s=s, m=m, mask=mask):
                    d = s.distance(X[m], p)
                    return float((d[mask].mean() - d.mean()) / d.std(ddof=1))

                r = {"sample": sample, "person_fe": fe, "group": group, "measure": m,
                     "pairs": int(mask.sum()), "people": people}  # fmt: skip
                q = qap_row(stat, groups)
                q["diff_sd"] = q.pop("partial_r")
                q["reading"] = "more different" if q["diff_sd"] > 0 else "more similar"
                rows.append(r | q if people >= MIN_GROUP else r)
    return pl.DataFrame(rows, infer_schema_length=None)


# --- (H-b) co-presses against membrane distance ---------------------------------------------------


def distance_matrix(X: np.ndarray) -> np.ndarray:
    n = X.shape[0] if X.ndim > 1 else len(X)
    i, j = pair_index(n)
    D = np.zeros((n, n))
    D[i, j] = D[j, i] = attribute_distance(X, i, j)
    return D


class Presses:
    """Press episodes of unit people with ``self_report`` consent, their close and exposed
    partners per bin, and the strata for the time-shuffle null."""

    def __init__(self, data: dict, people: list[str]):
        pos = {e: k for k, e in enumerate(people)}
        exposure = (
            data["exposure"]
            .filter(pl.col("entity").is_in(people))
            .with_columns(xp.epoch("bin").alias("bs"))
        )
        self.raters = sorted(set(exposure["entity"]))
        presses = (
            data["presses"]
            .filter(pl.col("entity").is_in(self.raters))
            .with_columns(xp.epoch("t").alias("ts"))
            .sort("ts", "entity")
        )
        key = pl.concat_str([pl.col("day").cast(pl.String), pl.col("phase")], separator="|")
        self.entity = presses["entity"].to_list()
        self.ts = presses["ts"].to_numpy()
        self.stratum = presses.select(key).to_series().to_list()
        self.pools = {(e, s): np.asarray(b) for e, s, b in exposure.with_columns(key.alias("s"))
                      .group_by("entity", "s").agg(pl.col("bs")).iter_rows()}  # fmt: skip
        ends = (
            data["ends"]
            .filter(
                (pl.col("max_rssi") >= CLOSE_RSSI)
                & pl.col("entity").is_in(self.raters)
                & pl.col("other").is_in(self.raters)
            )
            .with_columns(xp.epoch("bin").alias("bs"))
            .join(
                exposure.select(pl.col("entity").alias("other"), "bs"),
                on=["other", "bs"],
                how="semi",
            )
        )
        self.partners = {(e, b): o for e, b, o in ends.group_by("entity", "bs")
                         .agg(pl.col("other").unique()).iter_rows()}  # fmt: skip
        self.pos = pos

    def instances(self, t: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Anchor person, partner person (positions in the unit) and co-press, per instance."""
        p = partner_coevents(self.entity, t, self.partners, window=WINDOW, bin_size=BIN_S)
        a = np.array([self.pos[self.entity[k]] for k in p.event.tolist()], dtype=np.int64)
        b = np.array([self.pos[o] for o in p.partner], dtype=np.int64)
        return a, b, p.coevent

    def shuffled(self, rng: np.random.Generator) -> np.ndarray:
        return shuffle_events(self.entity, self.stratum, self.pools, rng, bin_size=BIN_S)


def press_stats(D: np.ndarray, sd: float, cuts, a, b, c, subset) -> np.ndarray:
    """[diff in SDs, co-press share near, middle, far] for the instances in ``subset``."""
    d = D[a, b][subset]
    cc = c[subset]
    out = [np.nan] * 4
    if cc.any() and (~cc).any():
        out[0] = (d[cc].mean() - d[~cc].mean()) / sd
    band = np.digitize(d, cuts)
    for k in range(3):
        m = band == k
        out[1 + k] = cc[m].mean() if m.any() else np.nan
    return np.array(out, dtype=float)


def press_analysis(pr: Presses, X: dict, course: np.ndarray, groups: np.ndarray):
    a, b, c = pr.instances(pr.ts)
    same = course[a] == course[b]
    subsets = {"all": np.ones(len(a), bool), "within course": same, "between course": ~same}
    mats = {m: distance_matrix(X[m]) for m in MEASURES}
    n = len(course)
    iu = np.triu_indices(n, 1)
    scale = {m: float(np.std(D[iu], ddof=1)) for m, D in mats.items()}
    cuts = {m: np.quantile(D[iu], [1 / 3, 2 / 3]) for m, D in mats.items()}

    def all_stats(mats_now, a_, b_, c_, same_):
        subs = {"all": np.ones(len(a_), bool), "within course": same_, "between course": ~same_}
        return {(m, s): press_stats(mats_now[m], scale[m], cuts[m], a_, b_, c_, sub)
                for m in MEASURES for s, sub in subs.items()}  # fmt: skip

    observed = all_stats(mats, a, b, c, same)
    rng = np.random.default_rng(SEED)
    node = {k: [] for k in observed}
    for _ in range(N_PERM):
        p = permute_within(groups, rng)
        st = all_stats({m: D[np.ix_(p, p)] for m, D in mats.items()}, a, b, c, same)
        for k, v in st.items():
            node[k].append(v)
    time = {k: [] for k in observed}
    rng = np.random.default_rng(SEED + 1)
    for _ in range(N_SHUFFLE):
        a2, b2, c2 = pr.instances(pr.shuffled(rng))
        st = all_stats(mats, a2, b2, c2, course[a2] == course[b2])
        for k, v in st.items():
            time[k].append(v)
    node = {k: np.array(v) for k, v in node.items()}
    time = {k: np.array(v) for k, v in time.items()}

    rows, bands = [], []
    labels = ["near", "middle", "far"]
    for (m, s), obs in observed.items():
        sub = subsets[s]
        cc = c[sub]
        people_co = len(set(a[sub][cc].tolist()) | set(b[sub][cc].tolist()))
        base = {"measure": m, "partners": s, "instances": int(sub.sum()),
                "people": len(set(a[sub].tolist()) | set(b[sub].tolist())),
                "people_copressing": people_co}  # fmt: skip
        if people_co < MIN_GROUP:
            rows.append(base | {"withheld": True})
        else:
            pn = null_position(obs[0], node[(m, s)][:, 0])
            pt = null_position(obs[0], time[(m, s)][:, 0])
            rows.append(base | {
                "copresses": int(cc.sum()), "copress_share": float(cc.mean()),
                "diff_sd": float(obs[0]),
                "reading": "different press together" if obs[0] > 0 else "similar press together",
                "node_null_mean": pn.null_mean, "node_null_lo": pn.null_lo,
                "node_null_hi": pn.null_hi, "node_percentile": pn.percentile,
                "node_share_as_extreme": pn.share_as_extreme,
                "time_null_mean": pt.null_mean, "time_null_lo": pt.null_lo,
                "time_null_hi": pt.null_hi, "time_percentile": pt.percentile,
                "time_share_as_extreme": pt.share_as_extreme, "withheld": False,
            })  # fmt: skip
        d = mats[m][a, b][sub]
        band = np.digitize(d, cuts[m])
        for k, lab in enumerate(labels):
            mk = band == k
            ppl = len(set(a[sub][mk & cc].tolist()) | set(b[sub][mk & cc].tolist()))
            r = {"measure": m, "partners": s, "tercile": lab, "instances": int(mk.sum()),
                 "people_copressing": ppl}  # fmt: skip
            if ppl < MIN_GROUP:
                bands.append(r | {"withheld": True})
                continue
            tn, nn = time[(m, s)][:, 1 + k], node[(m, s)][:, 1 + k]
            tn, nn = tn[np.isfinite(tn)], nn[np.isfinite(nn)]
            bands.append(r | {
                "copress_share": float(obs[1 + k]),
                "time_null_mean": float(tn.mean()),
                "time_null_lo": float(np.quantile(tn, 0.025)),
                "time_null_hi": float(np.quantile(tn, 0.975)),
                "excess_over_time_null": float(obs[1 + k] / tn.mean()) if tn.mean() > 0 else None,
                "node_null_lo": float(np.quantile(nn, 0.025)),
                "node_null_hi": float(np.quantile(nn, 0.975)),
                "withheld": False,
            })  # fmt: skip
    qa = {"raters_in_unit": len(pr.raters), "presses": len(pr.entity), "instances": len(a),
          "copress_instances": int(c.sum()),
          "within_course_instances": int(same.sum())}  # fmt: skip
    return (pl.DataFrame(rows, infer_schema_length=None),
            pl.DataFrame(bands, infer_schema_length=None), qa)  # fmt: skip


# --- main -----------------------------------------------------------------------------------------


def figures(out: Path, effects: pl.DataFrame, bands: pl.DataFrame) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import Patch

    plt.rcParams.update({"font.size": 11, "axes.spines.top": False, "axes.spines.right": False})
    shown = list(MEASURES)
    t = effects.filter(
        pl.col("person_fe") & (pl.col("outcome") == "log_close") & pl.col("measure").is_in(shown)
    )
    fig, axes = plt.subplots(1, 3, figsize=(14, 4.6), sharex=True, sharey=True)
    for ax, sample in zip(axes, SAMPLES, strict=True):
        u = t.filter(pl.col("sample") == sample)
        u = u.sort(pl.col("measure").replace_strict({m: k for k, m in enumerate(shown)}))
        y = np.arange(u.height)[::-1]
        ax.barh(y, u["null_hi"] - u["null_lo"], left=u["null_lo"], height=0.5, color=GRAY,
                alpha=0.35)  # fmt: skip
        ax.plot(u["partial_r"], y, "o", color=ORANGE, ms=8)
        ax.axvline(0, color=GRAY, lw=0.8)
        ax.set_yticks(y, [MEASURES[m][0] for m in u["measure"]])
        ax.set_title(f"{sample} pairs (n = {u['pairs'][0]})", loc="left", fontsize=11)
        ax.set_xlabel("partial r")
    fig.text(0.5, 0.02, "<- similar membranes spend more time close          different membranes "
             "spend more time close ->", ha="center", fontsize=10, color="#444444")  # fmt: skip
    handles = [
        plt.Line2D([], [], marker="o", color=ORANGE, ls="", ms=8, label="observed"),
        Patch(color=GRAY, alpha=0.35, label="null 95% (membranes permuted within course)"),
    ]
    fig.legend(handles=handles, frameon=False, fontsize=9, loc="upper right", ncol=2)
    fig.suptitle("Exploratory: membrane distance and time spent close (controls: joint exposure, "
                 "same course, each person)", fontsize=11, x=0.01, ha="left")  # fmt: skip
    fig.tight_layout(rect=(0, 0.05, 1, 0.93))
    fig.savefig(out / "fig_gradients_pairs.png", dpi=170)
    plt.close(fig)

    b = bands.filter((pl.col("partners") == "all") & pl.col("measure").is_in(["trust", "lust"]))
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.4), sharey=True)
    top = 0.0
    for ax, m in zip(axes, ["trust", "lust"], strict=True):
        u = b.filter(pl.col("measure") == m)
        x = np.arange(u.height)
        ok = ~u["withheld"].to_numpy()
        share = u["copress_share"].fill_null(0).to_numpy() * 100
        ax.bar(x[ok], share[ok], width=0.6, color=BLUE, label="observed")
        lo = u["time_null_lo"].fill_null(0).to_numpy() * 100
        hi = u["time_null_hi"].fill_null(0).to_numpy() * 100
        ax.errorbar(x[ok] - 0.12, (lo[ok] + hi[ok]) / 2, yerr=(hi[ok] - lo[ok]) / 2, fmt="none",
                    ecolor="black", capsize=4, lw=1.2,
                    label="null 95%, presses shuffled in time")  # fmt: skip
        nlo = u["node_null_lo"].fill_null(0).to_numpy() * 100
        nhi = u["node_null_hi"].fill_null(0).to_numpy() * 100
        ax.errorbar(x[ok] + 0.12, (nlo[ok] + nhi[ok]) / 2, yerr=(nhi[ok] - nlo[ok]) / 2,
                    fmt="none", ecolor=ORANGE, capsize=4, lw=1.2,
                    label="null 95%, membranes permuted")  # fmt: skip
        top = max(top, float(share.max()), float(nhi.max()))
        ax.set_xticks(x, u["tercile"].to_list())
        ax.set_title(MEASURES[m][0], loc="left", fontsize=11)
        ax.set_xlabel("membrane distance to the partner (terciles)")
    axes[0].set_ylim(0, top * 1.4)
    axes[0].set_ylabel("% of close partners also pressing")
    axes[1].legend(frameon=False, fontsize=9, loc="upper right")
    fig.suptitle("Exploratory: does a close partner press too (within 5 min), by membrane distance",
                 fontsize=11, x=0.01, ha="left")  # fmt: skip
    fig.tight_layout()
    fig.savefig(out / "fig_gradients_presses.png", dpi=170)
    plt.close(fig)


def main() -> None:
    layout = paths.study(conf.STUDY)
    spine = Spine.load(layout.spine)
    out = layout.derived / "analyses" / SLUG
    out.mkdir(parents=True, exist_ok=True)

    mem = membranes(layout, spine)
    people = mem["entity"].to_list()
    course = mem["course"].to_numpy()
    groups = course.tolist()
    X = {m: mem.select(cols).to_numpy().astype(float) for m, (_, cols) in MEASURES.items()}
    qa: dict = {
        "unit": len(people),
        "courses": len(set(groups)),
        "composite_recomputation_max_abs_diff": max(
            float((mem["trust"] - mem["trust_check"]).abs().max()),
            float((mem["lust"] - mem["lust_check"]).abs().max()),
        ),
        "membrane_complete": int(mem.select(TRUST + LUST + ["trust", "lust"]).drop_nulls().height),
    }
    if qa["membrane_complete"] < len(people):
        raise SystemExit("some unit people lack a scale; distances need complete membranes")

    contact = pair_contact(people, DAYS)
    samples = {(s, fe): PairSample(contact, course, s, fe) for s in SAMPLES for fe in (True, False)}
    qa["pairs"] = contact.height
    qa["pairs_heard_together"] = int((contact["joint_bins"] > 0).sum())
    qa["pairs_by_sample"] = {s: samples[(s, True)].pairs for s in SAMPLES}
    qa["pairs_ever_close"] = int((contact["close_minutes"] > 0).sum())
    qa["pairs_ever_tied"] = int((contact["tie_days"] > 0).sum())
    print(json.dumps(qa, indent=2), flush=True)

    effects = pair_effects(samples, X, np.array(groups))
    effects.write_csv(out / "pair_effects.csv")
    joint = joint_effects(samples, X, np.array(groups))
    joint.write_csv(out / "pair_joint.csv")
    Z = mem.select(TRUST + LUST).to_numpy().astype(float)
    scales = scale_effects(samples, Z, TRUST + LUST, np.array(groups))
    scales.write_csv(out / "pair_scales.csv")
    rep = repulsion(samples, X, np.array(groups))
    rep.write_csv(out / "repulsion.csv")
    print("pair analyses done", flush=True)

    data = xp.load(layout, spine)
    pr = Presses(data, people)
    press, bands, press_qa = press_analysis(pr, X, course, np.array(groups))
    press.write_csv(out / "press_effects.csv")
    bands.write_csv(out / "press_terciles.csv")
    qa["press"] = press_qa
    qa["settings"] = {"min_group": MIN_GROUP, "close_rssi": CLOSE_RSSI, "tie_min": TIE_MIN,
                      "days": [str(d) for d in DAYS], "window_s": WINDOW, "rare_q": RARE_Q,
                      "n_perm": N_PERM, "n_shuffle": N_SHUFFLE, "seed": SEED}  # fmt: skip
    (out / "qa_gradients.json").write_text(json.dumps(qa, indent=2, default=str), encoding="utf-8")
    figures(out, effects, bands)

    with pl.Config(tbl_rows=200, tbl_cols=30, fmt_str_lengths=40, tbl_width_chars=250):
        print(json.dumps(qa, indent=2, default=str))
        print(effects.select("sample", "person_fe", "outcome", "measure", "pairs", "partial_r",
                             "null_lo", "null_hi", "percentile", "share_as_extreme",
                             "pct_change_per_sd"))  # fmt: skip
        print(joint)
        print(scales)
        print(rep)
        print(press)
        print(bands)


if __name__ == "__main__":
    main()
