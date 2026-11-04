"""What could the gradient analysis have seen? Effects of known size, put in on purpose.

``docs/plans/ongoing/moments-and-networks.md``, section D, fixed before this ran. It says what the
results of ``exploratory_gradients.py`` are worth; it is **not new evidence about the camp**.

Each run permutes the membranes within course, which leaves the real contact and co-presses with no
real link to them. True scores are drawn around the permuted scores at each column's reliability
(``true_scores``), or equal to them with ``perfect``. The effect follows the true distance; the test
sees the measured one, against the analysis's node-permutation null.

**(H-a)** log(1 + close minutes) rises by log(1 + g) per SD of true distance, ``GAINS``. **(H-b)** A
close partner's odds of co-pressing move by ``ODDS`` per SD of true distance (``flip_towards``).
Detected: positive, and at most ``ALPHA`` of the null as extreme, two-sided.

One test per run and uniform plants are the easiest case: the analysis itself scanned many.

    OPENBLAS_NUM_THREADS=1 POLARS_MAX_THREADS=1 uv run --extra analysis python \
        studies/dsa-2026/analyses/gradient_sensitivity.py

Run after ``confirmatory.py``, ``copresence_by_phase.py build`` and ``beacon_diagnostics.py``.
Writes ``detection_contact.csv``, ``detection_copress.csv``, ``reliability_used.csv``, ``qa.json``
and a
figure to ``$SOCIAL_ENERGY_DATA/dsa-2026/derived/analyses/exploratory/gradient-sensitivity/``. Only
rates over runs are written.
"""

from __future__ import annotations

import json
import multiprocessing as mp
import sys
from pathlib import Path

import numpy as np
import polars as pl

sys.path.insert(0, str(Path(__file__).parent))
import confirmatory as conf
import exploratory_gradients as g
import exploratory_presses as xp

from social_energy import paths
from social_energy.confirmatory import permute_within
from social_energy.dyads import (
    attribute_distance,
    flip_towards,
    node_permutation_null,
    null_position,
    pair_index,
    partial_fit,
    true_scores,
)
from social_energy.spine import Spine

SLUG = "exploratory/gradient-sensitivity"
MEASURES = ("trust", "lust", "trust_scales", "all_scales")
SAMPLES = ("all", "within course")
SURVEYS = ("as measured", "perfect")
GAINS = (0.0, 0.05, 0.10, 0.20, 0.40)
ODDS = (1.0, 1.25, 1.5, 2.0, 3.0)
ALPHA = 0.05
N_RUNS = 100
N_PERM = 500
SEED = 20261106
BLUE, ORANGE, GRAY = g.BLUE, g.ORANGE, g.GRAY
#: ``--quick``: a few runs, to catch a crash before the long run. Its output is not a result.
if "--quick" in sys.argv:
    N_RUNS, N_PERM = 2, 20


def column_reliability(columns: list[str], table: pl.DataFrame) -> tuple[list[float], list[str]]:
    """Alpha per measure column, and the columns that had none and took the scales' median.

    ``trust`` and ``lust`` read their composite's row, ``z_<scale>`` the scale's."""
    alpha = dict(table.select("group", "alpha").iter_rows())
    scales = [v for k, v in alpha.items() if not k.endswith("_composite") and v == v]
    fallback = float(np.median(scales))
    out, missing = [], []
    for c in columns:
        key = f"{c}_composite" if c in ("trust", "lust") else c.removeprefix("z_")
        v = alpha.get(key)
        if v is None or v != v:
            missing.append(c)
            v = fallback
        out.append(float(v))
    return out, missing


def detected(obs: float, null: np.ndarray) -> tuple[bool, float]:
    """Positive and rare in the null, two-sided; and the observed value's place in it."""
    pos = null_position(obs, null)
    return bool(obs > 0 and pos.share_as_extreme <= ALPHA), pos.share_as_extreme


def zscore(v: np.ndarray) -> np.ndarray:
    return (v - v.mean()) / v.std(ddof=1)


def rates(runs: list[dict], keys: list[str], value: str) -> pl.DataFrame:
    return (
        pl.DataFrame(runs, infer_schema_length=None)
        .group_by(keys)
        .agg(
            pl.len().alias("runs"),
            pl.col("detected").mean().alias("detected"),
            pl.col(value).median().alias(f"median_{value}"),
        )
        .sort(keys)
    )


# --- worker state: built once per process; polars can hang in a forked child ---------------------

STATE: dict = {}


def load_state() -> None:
    layout = paths.study(conf.STUDY)
    spine = Spine.load(layout.spine)
    mem = g.membranes(layout, spine)
    people = mem["entity"].to_list()
    course = mem["course"].to_numpy()
    contact = g.pair_contact(people, g.DAYS)
    table = pl.read_csv(layout.derived / "analyses" / "confirmatory" / "reliability.csv")
    X, rel, missing = {}, {}, set()
    for m in MEASURES:
        cols = g.MEASURES[m][1]
        X[m] = mem.select(cols).to_numpy().astype(float)
        rel[m], gone = column_reliability(cols, table)
        missing |= set(gone)
    presses = g.Presses(xp.load(layout, spine), people)
    a, b, c = presses.instances(presses.ts)
    STATE.update(
        X=X, rel=rel, missing=sorted(missing), groups=np.array(course.tolist()),
        samples={s: g.PairSample(contact, course, s, True) for s in SAMPLES},
        a=a, b=b, c=c, n=len(people),
    )  # fmt: skip


def contact_run(task: tuple) -> dict:
    measure, sample, survey, gain, run = task
    s = STATE
    rng = np.random.default_rng([SEED, run])
    groups = s["groups"]
    X = s["X"][measure][permute_within(groups, rng)]
    rel = [1.0] * X.shape[1] if survey == "perfect" else s["rel"][measure]
    pair = s["samples"][sample]
    true_d = attribute_distance(true_scores(X, rel, rng), pair.i, pair.j)
    y = pair.r(pair.raw["log_close"] + np.log1p(gain) * zscore(true_d))
    identity = np.arange(len(groups))

    def stat(p: np.ndarray) -> float:
        return partial_fit(y, pair.r(attribute_distance(X[p], pair.i, pair.j))).partial_r

    d = attribute_distance(X, pair.i, pair.j)
    fit = partial_fit(y, pair.r(d))
    hit, _ = detected(stat(identity), node_permutation_null(stat, groups, n_perm=N_PERM, seed=run))
    return {
        "measure": measure, "sample": sample, "survey": survey, "gain": gain, "run": run,
        "detected": hit, "pct_per_sd": float(np.expm1(fit.slope * d.std(ddof=1))),
    }  # fmt: skip


def copress_run(task: tuple) -> dict:
    measure, survey, odds, run = task
    s = STATE
    rng = np.random.default_rng([SEED, run, 1])
    groups = s["groups"]
    X = s["X"][measure][permute_within(groups, rng)]
    rel = [1.0] * X.shape[1] if survey == "perfect" else s["rel"][measure]
    a, b = s["a"], s["b"]
    i, j = pair_index(s["n"])
    D_true = g.distance_matrix(true_scores(X, rel, rng))
    z = (D_true[a, b] - D_true[i, j].mean()) / D_true[i, j].std(ddof=1)
    c = flip_towards(s["c"], z, odds, rng)
    D = g.distance_matrix(X)
    sd = float(D[i, j].std(ddof=1))

    def stat(p: np.ndarray) -> float:
        d = D[p[a], p[b]]
        return float((d[c].mean() - d[~c].mean()) / sd)

    obs = stat(np.arange(len(groups)))
    hit, _ = detected(obs, node_permutation_null(stat, groups, n_perm=N_PERM, seed=run))
    return {
        "measure": measure, "survey": survey, "odds": odds, "run": run, "detected": hit,
        "diff_sd": obs, "share": float(c.mean()),
    }  # fmt: skip


def main() -> None:
    out = paths.study(conf.STUDY).derived / "analyses" / SLUG
    out.mkdir(parents=True, exist_ok=True)
    load_state()
    contact_tasks = [
        (m, s, v, x, r)
        for m in MEASURES for s in SAMPLES for v in SURVEYS for x in GAINS for r in range(N_RUNS)
    ]  # fmt: skip
    copress_tasks = [(m, v, x, r) for m in MEASURES for v in SURVEYS for x in ODDS
                     for r in range(N_RUNS)]  # fmt: skip
    with mp.get_context("spawn").Pool(14, initializer=load_state) as pool:
        contact = list(pool.imap_unordered(contact_run, contact_tasks, 8))
        print("contact done", flush=True)
        copress = list(pool.imap_unordered(copress_run, copress_tasks, 8))
    cont = rates(contact, ["measure", "sample", "survey", "gain"], "pct_per_sd")
    pres = rates(copress, ["measure", "survey", "odds"], "diff_sd")
    cont.write_csv(out / "detection_contact.csv")
    pres.write_csv(out / "detection_copress.csv")
    pl.DataFrame(
        [{"measure": m, "mean_reliability": float(np.mean(STATE["rel"][m]))} for m in MEASURES]
    ).write_csv(out / "reliability_used.csv")
    qa = {
        "runs_per_level": N_RUNS, "n_perm": N_PERM, "seed": SEED, "people": STATE["n"],
        "pairs": {s: STATE["samples"][s].pairs for s in SAMPLES},
        "partner_moments": len(STATE["c"]), "copress_share": float(STATE["c"].mean()),
        "columns_without_alpha": len(STATE["missing"]),
    }  # fmt: skip
    (out / "qa.json").write_text(json.dumps(qa, indent=2), encoding="utf-8")
    figure(cont, pres, out)
    print(json.dumps(qa, indent=2))


def figure(cont: pl.DataFrame, pres: pl.DataFrame, out: Path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    plt.rcParams.update({"font.size": 10, "axes.spines.top": False, "axes.spines.right": False})
    fig, axes = plt.subplots(2, len(MEASURES), figsize=(13, 5.6), sharey=True)
    for k, m in enumerate(MEASURES):
        for survey, color in zip(SURVEYS, (BLUE, ORANGE), strict=True):
            part = cont.filter(
                (pl.col("measure") == m)
                & (pl.col("sample") == "all")
                & (pl.col("survey") == survey)
            )
            axes[0, k].plot(part["gain"] * 100, part["detected"], color=color, lw=2, marker="o",
                            ms=6, label=f"survey {survey}")  # fmt: skip
            part = pres.filter((pl.col("measure") == m) & (pl.col("survey") == survey))
            axes[1, k].plot(part["odds"], part["detected"], color=color, lw=2, marker="o", ms=6)
        axes[0, k].set_title(m.replace("_", " "))
        axes[0, k].set_xlabel("% more close minutes per SD")
        axes[1, k].set_xlabel("odds of co-pressing per SD")
        for ax in axes[:, k]:
            ax.axhline(0.8, color=GRAY, lw=1, ls="--")
            ax.set_ylim(0, 1.02)
    axes[0, 0].set_ylabel("opposites attract:\nshare of runs detected")
    axes[1, 0].set_ylabel("gradients and flow:\nshare of runs detected")
    axes[0, 0].legend(frameon=False)
    fig.tight_layout()
    fig.savefig(out / "fig_detection.png", dpi=180)
    plt.close(fig)


if __name__ == "__main__":
    main()
