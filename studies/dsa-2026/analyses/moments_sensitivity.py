"""What could the moments analyses have seen? Effects of known size, put in on purpose.

``docs/plans/ongoing/moments-and-networks.md``, section C, fixed before this ran. It says what the
"no lead" of ``moments_networks.py`` is worth; it is **not new evidence about the camp**. Every run
uses a background without the real signal and the analysis's own verdict rule.

**A.** Pseudo-presses are one draw of the day x clock-hour shuffle. For each, ``close`` or
``unfamiliar`` rises by ``DELTAS`` people in the person's exposure bins from +10 to +60 minutes
(``plant_after``). Detected: the window is positive and "replicates" under both nulls.

**B.** The real shared pair-days are dropped and comparison pair-days become pseudo-shared, as many
per half as the real ones, in the real ones' mix of same course x tied earlier x tercile of that
day's minutes (``pseudo_shared``). Later minutes are multiplied by ``FACTORS``, or tied later rises
by ``POINTS`` percentage points (``plant_rows``). Detected: positive and "replicates".

Planted effects are uniform over people and moments, which is the easiest case.

    OPENBLAS_NUM_THREADS=1 uv run --extra analysis python \
        studies/dsa-2026/analyses/moments_sensitivity.py

Run after ``copresence_by_phase.py build`` and ``beacon_diagnostics.py``. Writes
``detection_lags.csv``, ``detection_come_back.csv``, ``qa.json`` and a figure to
``$SOCIAL_ENERGY_DATA/dsa-2026/derived/analyses/exploratory/moments-sensitivity/``. Only rates over
runs are written.
"""

from __future__ import annotations

import json
import multiprocessing as mp
import sys
from pathlib import Path

import numpy as np
import polars as pl

sys.path.insert(0, str(Path(__file__).parent))
import copresence_by_phase as cp
import moments_networks as mn
import outcomes as oc

from social_energy import paths
from social_energy.moments import plant_after
from social_energy.spine import Spine

SLUG = "exploratory/moments-sensitivity"
FEATURES = ("close", "unfamiliar")
DELTAS = (0.0, 0.1, 0.25, 0.5, 1.0)
FACTORS = (1.0, 1.25, 1.5, 2.0, 3.0)
POINTS = (0.0, 0.1, 0.2, 0.3)
AFTER = mn.WINDOWS["after"]
N_RUNS = 100
N_SHUFFLE = 100
N_BOOT = 200
SEED = 20261105
BLUE, ORANGE, GRAY = cp.BLUE, cp.ORANGE, cp.GRAY


def strata(rows: pl.DataFrame) -> pl.DataFrame:
    """Rows with a ``stratum``: same course x tied earlier x tercile of that day's minutes, the
    terciles taken over the comparison rows."""
    cuts = np.quantile(rows.filter(~pl.col("shared"))["today"].to_numpy(), [1 / 3, 2 / 3])
    band = np.digitize(rows["today"].to_numpy(), cuts)
    return rows.with_columns(
        pl.concat_str(
            [pl.col("same_course").cast(pl.String), pl.col("tied_earlier").cast(pl.String),
             pl.Series(band).cast(pl.String)], separator="|",
        ).alias("stratum")
    )  # fmt: skip


def pseudo_shared(rows: pl.DataFrame, rng: np.random.Generator) -> pl.DataFrame:
    """The comparison rows only, ``shared`` now marking a draw matching the real shared rows' count
    per half and stratum (fewer where a stratum runs out)."""
    rows = strata(rows).with_columns(pl.Series("half", half_labels(rows["day"].to_list())))
    pool = rows.filter(~pl.col("shared")).drop("shared")
    want = rows.filter(pl.col("shared")).group_by("half", "stratum").len()
    keys = pool.select("half", "stratum").rows()
    where: dict = {}
    for k, key in enumerate(keys):
        where.setdefault(key, []).append(k)
    flag = np.zeros(pool.height, dtype=bool)
    for half, stratum, n in want.sort("half", "stratum").iter_rows():
        have = where.get((half, stratum), [])
        if have:
            flag[rng.choice(have, size=min(n, len(have)), replace=False)] = True
    return pool.with_columns(pl.Series("shared", flag)).drop("half", "stratum")


def half_labels(days: list) -> list:
    d, r = set(mn.DISCOVERY), set(mn.REPLICATION)
    return ["discovery" if x in d else "replication" if x in r else "neither" for x in days]


def plant_rows(
    rows: pl.DataFrame, rng: np.random.Generator, *, factor: float = 1.0, points: float = 0.0
) -> pl.DataFrame:
    """Rows with the effect put on the shared ones: later close minutes times ``factor``, and tied
    later up by ``points``, by turning untied shared rows into tied ones at random."""
    shared = rows["shared"].to_numpy()
    later = rows["later"].to_numpy()
    planted = np.where(shared, np.log1p(np.expm1(later) * factor), later)
    tied = rows["tied_later"].to_numpy().copy()
    if points > 0 and shared.any():
        untied = shared & ~tied
        base = tied[shared].mean()
        flip = rng.random(len(tied)) < points / max(1 - base, 1e-9)
        tied = tied | (untied & flip)
    return rows.with_columns(pl.Series("later", planted), pl.Series("tied_later", tied))


def detection(runs: list[dict], keys: list[str]) -> pl.DataFrame:
    """Per level: the share of runs detected, the all-days interval excluding zero and the median
    estimate."""
    return (
        pl.DataFrame(runs, infer_schema_length=None)
        .group_by(keys)
        .agg(
            pl.len().alias("runs"),
            pl.col("detected").mean().alias("detected"),
            pl.col("all_excludes_zero").mean().alias("all_excludes_zero"),
            pl.col("all_est").median().alias("median_all_estimate"),
            (pl.col("all_hi") - pl.col("all_lo")).median().alias("median_all_width"),
        )
        .sort(keys)
    )


def positive_lead(row: dict) -> bool:
    """Positive on both halves and "replicates"."""
    return row["verdict"] == "replicates" and row["discovery"] > 0


# --- worker state: filled before the pool forks ---------------------------------------------------

STATE: dict = {}


def lag_run(task: tuple) -> list[dict]:
    feature, delta, run = task
    s = STATE
    rng = np.random.default_rng([SEED, run])
    t = mn.shuffle_events(s["entity"], s["stratum_hour"], s["pools_hour"], rng, bin_size=mn.BIN_S)
    at = (t - t % mn.BIN_S - s["lo"]) // mn.BIN_S
    grid = plant_after(s["grids"][feature], s["person"], at, AFTER[0], AFTER[1], delta)
    verdicts: dict = {}
    allv: dict = {}
    for null, shuffled in s["shuffles"].items():
        eff = mn.lag_effects(grid, s["person"], at, shuffled, s["masks"], mn.LAGS)
        vals = {h: mn.window_values(eff[h], mn.LAGS, mn.WINDOWS) for h in mn.HALVES}
        for window in ("after", "asymmetry"):
            row = mn.window_row({h: vals[h][window] for h in mn.HALVES})
            verdicts.setdefault(window, []).append(positive_lead(row))
            if null == "day-hour":
                allv[window] = row
    return [
        {
            "feature": feature, "delta": delta, "window": w, "run": run,
            "detected": all(verdicts[w]), "all_est": allv[w]["all"],
            "all_lo": allv[w]["all_lo"], "all_hi": allv[w]["all_hi"],
            "all_excludes_zero": allv[w]["all_lo"] > 0 or allv[w]["all_hi"] < 0,
        }
        for w in ("after", "asymmetry")
    ]  # fmt: skip


def back_run(task: tuple) -> dict:
    outcome, level, run = task
    s = STATE
    rng = np.random.default_rng([SEED, run, 1])
    rows = pseudo_shared(s["rows"], rng)
    plant = {"factor": level} if outcome == "later" else {"points": level}
    rows = plant_rows(rows, rng, **plant)
    c = mn.contrast(rows, outcome, mn.LATER_CONTROLS, s["n_people"], s["n_days"], n_boot=N_BOOT)
    return {
        "outcome": outcome, "level": level, "run": run,
        "detected": c["verdict"] == "replicates" and c["discovery_est"] > 0,
        "all_est": c["all_est"], "all_lo": c["all_lo"], "all_hi": c["all_hi"],
        "all_excludes_zero": c["all_lo"] is not None and (c["all_lo"] > 0 or c["all_hi"] < 0),
    }  # fmt: skip


def main() -> None:
    layout = paths.study(cp.STUDY)
    spine = Spine.load(layout.spine)
    out = paths.study(cp.STUDY).derived / "analyses" / SLUG
    out.mkdir(parents=True, exist_ok=True)
    b = mn.base(layout, spine)
    close = b["ends"].filter(pl.col("max_rssi") >= mn.CLOSE_RSSI)
    grids = mn.features(b["exposure"], close, b["course"], b["people"], b["lo"], b["n_bins"])
    masks = {h: mn.half_mask(b["day"], h) for h in mn.HALVES}
    shuffles = {}
    for null, keys in mn.NULLS.items():
        stratum, pools = mn.null_pools(b["presses"], b["exposure"], keys)
        t = mn.draw_shuffles(b["entity"], stratum, pools, offset=0, n=N_SHUFFLE, seed=SEED)
        shuffles[null] = (t - t % mn.BIN_S - b["lo"]) // mn.BIN_S
        if null == "day-hour":
            stratum_hour, pools_hour = stratum, pools

    days = oc.DAYS
    partners = mn.partners_at(b, mn.CLOSE_RSSI)
    shared, comparison = mn.pair_days(
        b["entity"], b["ts"], b["day"], mn.close_index(b, mn.CLOSE_RSSI), partners
    )
    rows = mn.pair_table(
        shared, comparison, mn.minutes_at(b, mn.CLOSE_RSSI, days), mn.seen_matrix(b, days),
        b["pos"], b["course"], days,
    )  # fmt: skip
    STATE.update(
        entity=b["entity"], person=b["person"], lo=b["lo"], grids=grids, masks=masks,
        shuffles=shuffles, stratum_hour=stratum_hour, pools_hour=pools_hour, rows=rows,
        n_people=len(b["people"]), n_days=len(days),
    )  # fmt: skip

    lag_tasks = [(f, d, r) for f in FEATURES for d in DELTAS for r in range(N_RUNS)]
    back_tasks = [("later", f, r) for f in FACTORS for r in range(N_RUNS)]
    back_tasks += [("tied_later", p, r) for p in POINTS for r in range(N_RUNS)]
    with mp.get_context("fork").Pool(14) as pool:
        lag_runs = [x for part in pool.imap_unordered(lag_run, lag_tasks, 8) for x in part]
        print("lags done", flush=True)
        back_runs = list(pool.imap_unordered(back_run, back_tasks, 4))
    lags = detection(lag_runs, ["feature", "window", "delta"])
    back = detection(back_runs, ["outcome", "level"])
    lags.write_csv(out / "detection_lags.csv")
    back.write_csv(out / "detection_come_back.csv")
    qa = {
        "runs_per_level": N_RUNS, "n_shuffle": N_SHUFFLE, "n_boot": N_BOOT, "seed": SEED,
        "real_shared_rows": int(rows["shared"].sum()),
        "comparison_rows": int((~rows["shared"]).sum()),
        "pseudo_shared_rows_first_run": int(
            pseudo_shared(rows, np.random.default_rng([SEED, 0, 1]))["shared"].sum()
        ),
    }  # fmt: skip
    (out / "qa.json").write_text(json.dumps(qa, indent=2), encoding="utf-8")
    figure(lags, back, out)
    print(json.dumps(qa, indent=2))


def figure(lags: pl.DataFrame, back: pl.DataFrame, out: Path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    plt.rcParams.update({"font.size": 10, "axes.spines.top": False, "axes.spines.right": False})
    fig, axes = plt.subplots(1, 3, figsize=(11, 3.2), sharey=True)
    a = lags.filter(pl.col("window") == "asymmetry")
    for feature, color in zip(FEATURES, (BLUE, ORANGE), strict=True):
        part = a.filter(pl.col("feature") == feature)
        axes[0].plot(part["delta"], part["detected"], color=color, lw=2, marker="o", ms=6,
                     label=feature)  # fmt: skip
    axes[0].set_xlabel("people added after a press")
    axes[0].set_title("contacts widen (A)")
    axes[0].set_ylabel("share of runs detected")
    axes[0].legend(frameon=False)
    part = back.filter(pl.col("outcome") == "later")
    axes[1].plot(part["level"], part["detected"], color=BLUE, lw=2, marker="o", ms=6)
    axes[1].set_xlabel("later close minutes, multiplied by")
    axes[1].set_title("pairs come back: minutes (B)")
    part = back.filter(pl.col("outcome") == "tied_later")
    axes[2].plot(part["level"] * 100, part["detected"], color=BLUE, lw=2, marker="o", ms=6)
    axes[2].set_xlabel("tied later, percentage points added")
    axes[2].set_title("pairs come back: ties (B)")
    for ax in axes:
        ax.axhline(0.8, color=GRAY, lw=1, ls="--")
        ax.set_ylim(0, 1.02)
    fig.tight_layout()
    fig.savefig(out / "fig_detection.png", dpi=180)
    plt.close(fig)


if __name__ == "__main__":
    main()
