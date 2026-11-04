"""Exploratory: a person's company around self-reports, and whether shared moments last.

``docs/plans/ongoing/moments-and-networks.md``, whose rules were committed before this ran. **Every
result here is exploratory**: no error control over the many estimates, effects with 95% intervals,
distributions rather than people, cells with fewer than ``MIN_GROUP`` people withheld.

Common ground is the exploratory tier's (``exploratory_presses.load``): press episodes of
participants with ``self_report`` and ``beacons`` consent, counted only in exposure bins (5-minute
bins in which the tag was heard, less lost and unsettled windows); staff are left out. The days are
split as in the EDA second pass and extended to the days without wear (``DISCOVERY``,
``REPLICATION``); an estimate gets ``eda_split.verdict`` from its two halves.

**A. The lag profile.** Per press and lag (``LAGS``, positive after the press), the presser's value
of five features (``features``), only in that person's exposure bins. Per person with at least
``MIN_PRESSES`` presses in the half: the mean over presses minus the mean over ``N_SHUFFLE``
shuffles, which move each press to a random exposure bin of the same person within day x phase
(``NULLS["day-phase"]``, the cascades null) or day x clock hour. Both keep the person's rate and the
autocorrelation of their company. Estimates are the means over people in the windows before, near
and after the press, and the asymmetry (after minus before), with intervals over people. Lag curves
also get cluster inference (``moments.cluster_mass``), which describes the shape; verdicts come from
the windows, and a window is a lead only if it replicates under both nulls. By kind of press:
``shared`` (in a co-located pair ``MIN_GAP`` to ``WINDOW`` seconds apart) and ``solo``.
Sensitivities under the main null: ``SENSITIVE_RSSI``; without 24-27 Aug. The one-minute check does
``close`` alone at 1-minute resolution, where a minute needs a record of the person and an exposure
bin around it.

A press may follow the moment it marks, and may be caused by the company: **before and after are not
cleanly before and after, and nothing here is read causally.**

**B. Do pairs who shared a moment come back?** Pair-days of unit participants from ``FIRST_MOMENT``
to ``LAST_MOMENT`` (``pair_days``): shared, or one pressed while the other was close and exposed and
no co-press followed. Outcomes over the next ``FOLLOW_DAYS`` camp days: log(1 + close minutes) and
tied on any of them. Held fixed: that day's minutes, earlier minutes, an earlier tie, same course,
bins in which both were seen in the follow-up, one dummy per person and per day (``fit``); intervals
by node bootstrap. The placebo sets the same contrast on the ``FOLLOW_DAYS`` days before: a result
is a lead only if it replicates and the placebo's all-days interval includes zero.

    uv run --extra analysis python studies/dsa-2026/analyses/moments_networks.py

Run after ``copresence_by_phase.py build`` and ``beacon_diagnostics.py``. Writes CSVs, ``qa.json``
and figures to ``$SOCIAL_ENERGY_DATA/dsa-2026/derived/analyses/exploratory/moments-networks/``, and
a cache of one-minute contacts beside them. Nothing per person or per pair is reported.
"""

from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

import numpy as np
import polars as pl

sys.path.insert(0, str(Path(__file__).parent))
import copresence_by_phase as cp
import eda_split
import exploratory_presses as xp
import outcomes as oc

from social_energy import paths
from social_energy.dyads import node_dummies, partner_coevents
from social_energy.exploratory import CloseIndex, bootstrap_mean, co_event_pairs, shuffle_events
from social_energy.moments import (
    cluster_mass,
    component_sizes,
    eigenvector_centrality,
    lag_sums,
    person_lag_means,
    window_mean,
)
from social_energy.presence import copresence
from social_energy.rhythm import node_bootstrap_weights
from social_energy.spine import Spine

SLUG = "exploratory/moments-networks"
MIN_GROUP = 5
MIN_PRESSES = 3
CLOSE_RSSI = cp.CLOSE_RSSI
SENSITIVE_RSSI = -70
BIN_S = xp.BIN_S
TIE_BINS = cp.TIE_MIN_BINS
BIN_MIN = BIN_S // 60
WINDOW = 300
MIN_GAP = 10
LAGS = np.arange(-12, 13)  # in 5-minute bins
#: Estimates with a verdict, in lags; asymmetry is after minus before.
WINDOWS = {"before": (-12, -2), "near": (-1, 1), "after": (2, 12)}
MINUTE_LAGS = np.arange(-15, 16)
MINUTE_WINDOWS = {"before": (-15, -3), "near": (-2, 2), "after": (3, 15)}
FEATURES = ("close", "gathering", "centrality", "unfamiliar", "cross_course")
DISCOVERY = eda_split.DISCOVERY
REPLICATION = tuple(sorted((*eda_split.REPLICATION, date(2026, 8, 14), date(2026, 8, 18))))
HALVES = ("discovery", "replication", "all")
DROP_DAYS = tuple(date(2026, 8, d) for d in (24, 25, 26, 27))
NULLS = {"day-phase": ["day", "phase"], "day-hour": ["day", "hour"]}
FIRST_MOMENT, LAST_MOMENT = date(2026, 8, 17), date(2026, 8, 27)
FOLLOW_DAYS = 3
NO_DIP_LAST = date(2026, 8, 20)
N_SHUFFLE = 1000
N_BOOT = 4000
N_BOOT_NODE = 1000
N_FLIPS = 10_000
SEED = 20261104
BLUE, ORANGE, GRAY = cp.BLUE, cp.ORANGE, cp.GRAY


def out_dir() -> Path:
    d = paths.study(cp.STUDY).derived / "analyses" / SLUG
    d.mkdir(parents=True, exist_ok=True)
    return d


def half_mask(days: list[date], half: str) -> np.ndarray:
    """Which of ``days`` belong to the half; ``all`` is both halves, so the handover is outside."""
    keep = {"discovery": DISCOVERY, "replication": REPLICATION}.get(half, DISCOVERY + REPLICATION)
    return np.array([d in keep for d in days], dtype=bool)


# --- A. features per person and bin ---------------------------------------------------------------


def features(
    exposure: pl.DataFrame,
    close: pl.DataFrame,
    course: dict,
    people: list,
    lo: int,
    n_bins: int,
) -> dict[str, np.ndarray]:
    """The five features as people x bins, NaN outside each person's exposure bins.

    ``exposure`` has ``entity`` and ``bs`` (bin start, seconds); ``close`` has one row per direction
    of each close pair and bin: ``entity``, ``other``, ``bs``, ``day``. Company may include people
    outside ``people``, who are in the graph but get no row.
    """
    pos = {e: i for i, e in enumerate(people)}
    seen = np.zeros((len(people), n_bins), dtype=bool)
    for e, b in exposure.select("entity", "bs").iter_rows():
        if e in pos and 0 <= (b - lo) // BIN_S < n_bins:
            seen[pos[e], (b - lo) // BIN_S] = True

    def as_grid(rows: pl.DataFrame, value: str, base: float | None) -> np.ndarray:
        g = np.full(seen.shape, np.nan if base is None else base)
        for e, b, v in rows.select("entity", "bs", value).iter_rows():
            if e in pos and 0 <= (b - lo) // BIN_S < n_bins:
                g[pos[e], (b - lo) // BIN_S] = v
        g[~seen] = np.nan
        return g

    n_close = close.group_by("entity", "bs").agg(pl.col("other").n_unique().alias("n"))
    first_tie = (
        close.group_by("entity", "other", "day")
        .agg(pl.col("bs").n_unique().alias("bins"))
        .filter(pl.col("bins") >= TIE_BINS)
        .group_by("entity", "other")
        .agg(pl.col("day").min().alias("first_tie"))
    )
    unfamiliar = (
        close.join(first_tie, on=["entity", "other"], how="left")
        .filter(pl.col("first_tie").is_null() | (pl.col("first_tie") >= pl.col("day")))
        .group_by("entity", "bs")
        .agg(pl.col("other").n_unique().alias("n"))
    )
    cross = (
        close.with_columns(
            pl.col("entity").replace_strict(course, default=None).alias("c1"),
            pl.col("other").replace_strict(course, default=None).alias("c2"),
        )
        .filter(pl.col("c1").is_not_null() & pl.col("c2").is_not_null())
        .group_by("entity", "bs")
        .agg((pl.col("c1") != pl.col("c2")).mean().alias("share"))
    )
    gathering, centrality = graph_features(close, seen, pos, lo, n_bins)
    return {
        "close": as_grid(n_close, "n", 0.0),
        "gathering": gathering,
        "centrality": centrality,
        "unfamiliar": as_grid(unfamiliar, "n", 0.0),
        "cross_course": as_grid(cross, "share", None),
    }


def graph_features(close, seen, pos, lo, n_bins) -> tuple[np.ndarray, np.ndarray]:
    """Component size in the bin's close graph; eigenvector centrality over the three bins centred
    on it. Alone: size 1, centrality 0. NaN outside exposure."""
    gathering = np.ones(seen.shape)
    centrality = np.zeros(seen.shape)
    nodes = sorted(set(close["entity"].unique()) | set(close["other"].unique()) | set(pos))
    code = {e: i for i, e in enumerate(nodes)}
    edges: dict[int, list[tuple[int, int]]] = {}
    for e, o, b in (
        close.filter(pl.col("entity") < pl.col("other")).select("entity", "other", "bs").iter_rows()
    ):
        edges.setdefault((b - lo) // BIN_S, []).append((code[e], code[o]))
    rows = np.array([pos.get(e, -1) for e in nodes])
    mine = rows >= 0
    for k in range(n_bins):
        near = [edges.get(j, []) for j in (k - 1, k, k + 1)]
        if not any(near):
            continue
        if near[1]:
            a, b = np.array(near[1]).T
            gathering[rows[mine], k] = component_sizes(len(nodes), a, b)[mine]
        W = np.zeros((len(nodes), len(nodes)))
        for part in near:
            for i, j in part:
                W[i, j] += 1.0
                W[j, i] += 1.0
        centrality[rows[mine], k] = eigenvector_centrality(W)[mine]
    gathering[~seen] = np.nan
    centrality[~seen] = np.nan
    return gathering, centrality


# --- A. observed against shuffled, per mask of presses --------------------------------------------


def lag_effects(
    grid: np.ndarray,
    person: np.ndarray,
    at: np.ndarray,
    shuffled: np.ndarray,
    masks: dict,
    lags: np.ndarray,
) -> dict:
    """Per mask, people x lags: the observed mean minus the mean over shuffles (a row of
    ``shuffled`` holds every press's bin in one shuffle)."""
    n = grid.shape[0]
    out = {}
    for key, mask in masks.items():
        events = np.bincount(person[mask], minlength=n)
        obs = person_lag_means(
            *lag_sums(grid, person[mask], at[mask], lags, n), events, min_events=MIN_PRESSES
        )
        total, count = np.zeros(obs.shape), np.zeros(obs.shape)
        for draw in shuffled:
            m = person_lag_means(
                *lag_sums(grid, person[mask], draw[mask], lags, n), events, min_events=MIN_PRESSES
            )
            ok = ~np.isnan(m)
            total[ok] += m[ok]
            count[ok] += 1
        with np.errstate(invalid="ignore", divide="ignore"):
            out[key] = obs - total / count
    return out


def window_values(d: np.ndarray, lags: np.ndarray, windows: dict) -> dict[str, np.ndarray]:
    """Per person, each window's mean and the asymmetry (after minus before)."""
    w = {name: window_mean(d, lags, lo, hi) for name, (lo, hi) in windows.items()}
    w["asymmetry"] = w["after"] - w["before"]
    return w


def window_row(by_half: dict[str, np.ndarray]) -> dict:
    """Estimate and interval per half, and the verdict, from one window's per-person values."""
    row: dict = {}
    for half, v in by_half.items():
        m = bootstrap_mean(v.tolist(), n_boot=N_BOOT, seed=SEED)
        people = m.n
        row |= dict.fromkeys((half, f"{half}_lo", f"{half}_hi"), None) | {f"{half}_people": people}
        if people >= MIN_GROUP:
            row |= {half: m.mean, f"{half}_lo": m.lo, f"{half}_hi": m.hi}
    vals = [row[k] for h in ("discovery", "replication") for k in (h, f"{h}_lo", f"{h}_hi")]
    row["verdict"] = "withheld" if any(v is None for v in vals) else eda_split.verdict(*vals)
    return row


def run_lags(grids, person, at, days, shuffles, kinds, lags, windows, labels) -> tuple[list, dict]:
    """Rows for every feature x kind x window, and the effects (for curves)."""
    masks = {
        (kind, half): kmask & half_mask(days, half)
        for kind, kmask in kinds.items()
        for half in HALVES
    }
    rows, effects = [], {}
    for name, grid in grids.items():
        eff = lag_effects(grid, person, at, shuffles, masks, lags)
        effects[name] = eff
        for kind in kinds:
            vals = {h: window_values(eff[(kind, h)], lags, windows) for h in HALVES}
            for window in (*windows, "asymmetry"):
                rows.append(
                    labels
                    | {"feature": name, "kind": kind, "window": window}
                    | window_row({h: vals[h][window] for h in HALVES})
                )
    return rows, effects


def curve_rows(effects: dict, kind: str, lags: np.ndarray, step_min: int, labels: dict) -> list:
    rows = []
    for name, eff in effects.items():
        for half in HALVES:
            d = eff[(kind, half)]
            people = (~np.isnan(d)).sum(axis=0)
            with np.errstate(invalid="ignore"):
                se = np.nanstd(d, axis=0, ddof=1) / np.sqrt(people)
            mean = np.nanmean(d, axis=0)
            for k, lag in enumerate(lags.tolist()):
                ok = int(people[k]) >= MIN_GROUP
                rows.append(labels | {
                    "feature": name, "half": half, "lag_min": lag * step_min,
                    "effect": float(mean[k]) if ok else None,
                    "se": float(se[k]) if ok else None, "people": int(people[k]),
                })  # fmt: skip
    return rows


def cluster_rows(effects: dict, kind: str, lags: np.ndarray, step_min: int, labels: dict) -> list:
    rows = []
    for name, eff in effects.items():
        for half in HALVES:
            for c in cluster_mass(eff[(kind, half)], n_perm=N_FLIPS, seed=SEED):
                rows.append(labels | {
                    "feature": name, "half": half, "from_min": int(lags[c.start]) * step_min,
                    "to_min": int(lags[c.stop]) * step_min, "sign": c.sign, "mass": c.mass,
                    "p": c.p,
                })  # fmt: skip
    return rows


def draw_shuffles(entity, stratum, pools, *, offset: int, n: int, seed: int) -> np.ndarray:
    """``n`` x presses: each press's new second, at a random exposure bin of its stratum."""
    rng = np.random.default_rng(seed)
    t = np.empty((n, len(entity)), dtype=np.int64)
    for k in range(n):
        t[k] = shuffle_events(entity, stratum, pools, rng, bin_size=BIN_S)
    return t - offset


# --- B. shared moments and later contact ----------------------------------------------------------


def pair_days(
    entity: list,
    ts: np.ndarray,
    day: list,
    close: CloseIndex,
    partners: dict,
    *,
    include_near: bool = False,
) -> tuple[set, set]:
    """``(shared, comparison)`` as sets of ``(person, person, day)`` with the people sorted.

    Shared: a co-located press pair at least ``MIN_GAP`` s apart (any gap with ``include_near``) and
    at most ``WINDOW`` s, on the day of its earlier press. Comparison: one pressed while the other
    was among its ``partners`` in the bin and no press of theirs lay within ``WINDOW`` s, on a day
    the pair has no co-press at all; a day whose only co-press is under ``MIN_GAP`` s is neither.
    """
    p = co_event_pairs(entity, ts, close, window=WINDOW, bin_size=BIN_S)
    shared, near = set(), set()
    for a, b, gap, is_close in zip(p.first, p.second, p.gap, p.close, strict=True):
        if not is_close:
            continue
        key = (*sorted((entity[a], entity[b])), day[a])
        (shared if include_near or gap >= MIN_GAP else near).add(key)
    q = partner_coevents(entity, ts, partners, window=WINDOW, bin_size=BIN_S)
    other = set()
    for k, o, hit in zip(q.event.tolist(), q.partner, q.coevent.tolist(), strict=True):
        key = (*sorted((entity[k], o)), day[k])
        (near if hit else other).add(key)
    return shared, other - shared - near


def fit(y: np.ndarray, X: np.ndarray, w: np.ndarray | None = None) -> float:
    """The first column's coefficient in weighted least squares; dummies may be collinear."""
    Xw = X if w is None else X * w[:, None]
    return float((np.linalg.pinv(Xw.T @ X, rcond=1e-10) @ (Xw.T @ y))[0])


def design(rows: pl.DataFrame, controls: list[str], n_people: int, n_days: int) -> np.ndarray:
    i, j, d = (rows[c].to_numpy() for c in ("i", "j", "d"))
    day = np.zeros((rows.height, n_days))
    day[np.arange(rows.height), d] = 1.0
    return np.column_stack(
        [rows["shared"].to_numpy().astype(float)]
        + [rows[c].to_numpy().astype(float) for c in controls]
        + [node_dummies(i, j, n_people), day]
    )


def contrast(rows: pl.DataFrame, outcome: str, controls: list, n_people: int, n_days: int) -> dict:
    """Estimate, interval and verdict of ``shared`` per half, by the day of the moment."""
    out: dict = {}
    for half in HALVES:
        part = rows.filter(pl.Series(half_mask(rows["day"].to_list(), half)))
        people = len(set(part["i"].to_list()) | set(part["j"].to_list()))
        treated = int(part["shared"].sum()) if part.height else 0
        out |= {f"{half}_{k}": None for k in ("est", "lo", "hi")}
        out |= {f"{half}_people": people, f"{half}_shared": treated,
                f"{half}_comparison": part.height - treated}  # fmt: skip
        if people < MIN_GROUP or treated < MIN_GROUP or part.height == treated:
            continue
        y = part[outcome].to_numpy().astype(float)
        X = design(part, controls, n_people, n_days)
        a, b = part["i"].to_numpy(), part["j"].to_numpy()
        draws = [
            fit(y, X, (w[a] * w[b]).astype(float))
            for w in node_bootstrap_weights(n_people, n_boot=N_BOOT_NODE, seed=SEED)
        ]
        lo, hi = np.quantile(draws, [0.025, 0.975])
        out |= {f"{half}_est": fit(y, X), f"{half}_lo": float(lo), f"{half}_hi": float(hi)}
    vals = [out[f"{h}_{k}"] for h in ("discovery", "replication") for k in ("est", "lo", "hi")]
    out["verdict"] = "withheld" if any(v is None for v in vals) else eda_split.verdict(*vals)
    return out


def pair_table(
    shared: set,
    comparison: set,
    minutes: np.ndarray,
    seen: np.ndarray,
    pos: dict,
    course: dict,
    days: list,
) -> pl.DataFrame:
    """One row per pair-day with its outcomes and controls. ``minutes`` and ``seen`` are people x
    people x days: close minutes, and bins in which both were exposed."""  # fmt: skip
    idx = {d: k for k, d in enumerate(days)}
    rows = []
    for key_set, flag in ((shared, True), (comparison, False)):
        for a, b, day in key_set:
            if not (FIRST_MOMENT <= day <= LAST_MOMENT) or a not in pos or b not in pos:
                continue
            i, j, d = pos[a], pos[b], idx[day]
            m, s = minutes[i, j], seen[i, j]
            tied = m >= TIE_BINS * BIN_MIN
            after = slice(d + 1, d + 1 + FOLLOW_DAYS)
            pre = slice(d - FOLLOW_DAYS, d)
            ca, cb = course.get(a), course.get(b)
            rows.append({
                "i": i, "j": j, "d": d, "day": day, "shared": flag,
                "same_course": ca is not None and ca == cb,
                "today": np.log1p(m[d]),
                "earlier": np.log1p(m[:d].sum()), "tied_earlier": bool(tied[:d].any()),
                "later": np.log1p(m[after].sum()), "tied_later": bool(tied[after].any()),
                "seen_later": np.log1p(s[after].sum()),
                "previous": np.log1p(m[pre].sum()),
                "prior": np.log1p(m[: d - FOLLOW_DAYS].sum()),
                "tied_prior": bool(tied[: d - FOLLOW_DAYS].any()),
                "seen_previous": np.log1p(s[pre].sum()),
            })  # fmt: skip
    return pl.DataFrame(rows, infer_schema_length=None)


LATER_CONTROLS = ["today", "earlier", "tied_earlier", "same_course", "seen_later"]
PLACEBO_CONTROLS = ["today", "prior", "tied_prior", "same_course", "seen_previous"]


def come_back(rows: pl.DataFrame, variant: str, n_people: int, n_days: int) -> list[dict]:
    out = []
    for outcome, y, controls in (
        ("close minutes later (log)", "later", LATER_CONTROLS),
        ("tied later", "tied_later", LATER_CONTROLS),
        ("placebo: close minutes before (log)", "previous", PLACEBO_CONTROLS),
    ):
        out.append(
            {"variant": variant, "outcome": outcome} | contrast(rows, y, controls, n_people, n_days)
        )
    return out


# --- run ------------------------------------------------------------------------------------------


def minute_tables(layout, spine, participants: set, out: Path) -> tuple[pl.DataFrame, pl.DataFrame]:
    """One-minute close rows and seen minutes, cached under ``out``."""
    f_close, f_seen = out / "cache_minute_close.parquet", out / "cache_minute_seen.parquet"
    if f_close.exists() and f_seen.exists():
        return pl.read_parquet(f_close), pl.read_parquet(f_seen)
    who = list(participants)
    closes, seens = [], []
    for day, raw, qa in cp.contact_days(layout, False):
        df = cp.resolve_contacts(raw, spine, qa)
        persons = df.filter(
            pl.col("observer_entity").is_in(who) & pl.col("observed_entity").is_in(who)
            & (pl.col("rssi") >= CLOSE_RSSI)
        )  # fmt: skip
        if persons.height:
            closes.append(
                copresence(persons, every="1m").filter(pl.col("max_rssi") >= CLOSE_RSSI)
                .with_columns(pl.col("bin").dt.epoch("s").alias("ms"))
                .select("a", "b", "ms")
            )  # fmt: skip
        seens.append(
            pl.concat([
                df.select(pl.col("observer_entity").alias("entity"), "t"),
                df.select(pl.col("observed_entity").alias("entity"), "t"),
            ]).filter(pl.col("entity").is_in(who))
            .with_columns(pl.col("t").dt.truncate("1m").dt.epoch("s").alias("ms"))
            .select("entity", "ms").unique()
        )  # fmt: skip
        print("minutes", day, flush=True)
    close, seen = pl.concat(closes), pl.concat(seens)
    close.write_parquet(f_close)
    seen.write_parquet(f_seen)
    return close, seen


def minute_grid(close: pl.DataFrame, seen: pl.DataFrame, exposure, people: list, lo: int, n: int):
    """``close`` per minute, people x minutes; NaN unless seen in that minute and in exposure."""
    pos = {e: i for i, e in enumerate(people)}
    usable = np.zeros((len(people), n), dtype=bool)
    in_bin = {(e, b) for e, b in exposure.select("entity", "bs").iter_rows()}
    for e, m in seen.filter(pl.col("entity").is_in(people)).iter_rows():
        k = (m - lo) // 60
        if 0 <= k < n and (e, m - m % BIN_S) in in_bin:
            usable[pos[e], k] = True
    g = np.zeros(usable.shape)
    both = pl.concat([close.select(pl.col("a").alias("e"), "ms"),
                      close.select(pl.col("b").alias("e"), "ms")])  # fmt: skip
    for e, m, c in both.filter(pl.col("e").is_in(people)).group_by("e", "ms").len().iter_rows():
        k = (m - lo) // 60
        if 0 <= k < n:
            g[pos[e], k] = c
    g[~usable] = np.nan
    return g


def main() -> None:
    layout = paths.study(cp.STUDY)
    spine = Spine.load(layout.spine)
    out = out_dir()
    data = xp.load(layout, spine)
    course = cp.course_of(spine)
    participants = {p.ref for p in spine.people if p.role == "participant"}
    exposure = data["exposure"].with_columns(
        pl.col("bin").dt.epoch("s").alias("bs"),
        pl.col("bin").dt.convert_time_zone(cp.TZ).dt.hour().alias("hour"),
    )
    presses = data["presses"].with_columns(
        pl.col("t").dt.epoch("s").alias("ts"),
        pl.col("bin").dt.convert_time_zone(cp.TZ).dt.hour().alias("hour"),
    ).sort("entity", "t")  # fmt: skip
    entity = presses["entity"].to_list()
    ts = presses["ts"].to_numpy()
    day = presses["day"].to_list()
    people = sorted(set(exposure["entity"]))
    pos = {e: i for i, e in enumerate(people)}
    person = np.array([pos[e] for e in entity])
    lo = int(exposure["bs"].min())
    n_bins = (int(exposure["bs"].max()) - lo) // BIN_S + 1
    at = (ts - ts % BIN_S - lo) // BIN_S
    ends = data["ends"].with_columns(pl.col("bin").dt.epoch("s").alias("bs"),
                                     cp.camp_day_expr(pl.col("bin")).alias("day"))  # fmt: skip

    def close_at(rssi: int) -> pl.DataFrame:
        return ends.filter(pl.col("max_rssi") >= rssi)

    close = close_at(CLOSE_RSSI)
    grids = features(exposure, close, course, people, lo, n_bins)
    index = CloseIndex(close.select("entity", "bs", "other").iter_rows(), bin_size=BIN_S)
    p = co_event_pairs(entity, ts, index, window=WINDOW, bin_size=BIN_S)
    keep = p.close & (p.gap >= MIN_GAP)
    is_shared = np.zeros(len(entity), dtype=bool)
    is_shared[p.first[keep]] = True
    is_shared[p.second[keep]] = True
    no_dip = np.array([d not in DROP_DAYS for d in day], dtype=bool)
    every = np.ones(len(entity), dtype=bool)

    qa = {
        "presses": len(entity), "people": len(people), "shared_presses": int(is_shared.sum()),
        "discovery_presses": int(half_mask(day, "discovery").sum()),
        "replication_presses": int(half_mask(day, "replication").sum()),
        "feature_sd": {k: float(np.nanstd(v)) for k, v in grids.items()},
        "feature_mean": {k: float(np.nanmean(v)) for k, v in grids.items()},
        "settings": {"close_rssi": CLOSE_RSSI, "n_shuffle": N_SHUFFLE, "seed": SEED,
                     "min_presses": MIN_PRESSES, "min_group": MIN_GROUP},
    }  # fmt: skip

    # A, both nulls.
    rows, curves, clusters = [], [], []
    draws = {}
    for null, keys in NULLS.items():
        s = pl.concat_str([pl.col(k).cast(pl.String) for k in keys], separator="|")
        stratum = presses.select(s).to_series().to_list()
        pools = {
            (e, k): np.asarray(b)
            for e, k, b in exposure.with_columns(s.alias("s")).group_by("entity", "s")
            .agg(pl.col("bs")).iter_rows()
        }  # fmt: skip
        t = draw_shuffles(entity, stratum, pools, offset=0, n=N_SHUFFLE, seed=SEED)
        draws[null] = t
        shuffled = (t - t % BIN_S - lo) // BIN_S
        kinds = {"all": every, "shared": is_shared, "solo": ~is_shared}
        if null == "day-phase":
            kinds["no_dip"] = no_dip
        r, eff = run_lags(grids, person, at, day, shuffled, kinds, LAGS, WINDOWS,
                          {"null": null, "rssi": CLOSE_RSSI, "resolution": "5 min"})  # fmt: skip
        rows += r
        labels = {"null": null}
        curves += curve_rows(eff, "all", LAGS, BIN_MIN, labels)
        clusters += cluster_rows(eff, "all", LAGS, BIN_MIN, labels)
        print("lags", null, flush=True)
        if null == "day-phase":
            main_eff = eff

    # A, -70 dBm, main null.
    grids70 = features(exposure, close_at(SENSITIVE_RSSI), course, people, lo, n_bins)
    t = draws["day-phase"]
    r, _ = run_lags(grids70, person, at, day, (t - t % BIN_S - lo) // BIN_S, {"all": every}, LAGS,
                    WINDOWS,
                    {"null": "day-phase", "rssi": SENSITIVE_RSSI, "resolution": "5 min"})  # fmt: skip
    rows += r
    print("lags -70", flush=True)

    # A, one-minute check.
    mclose, mseen = minute_tables(layout, spine, participants, out)
    n_min = n_bins * BIN_MIN
    mgrid = minute_grid(mclose, mseen, exposure, people, lo, n_min)
    qa["minute_share_usable_in_exposure"] = float((~np.isnan(mgrid)).sum()) / (
        exposure.height * BIN_MIN
    )
    for null, t in draws.items():
        r, eff = run_lags({"close": mgrid}, person, (ts - lo) // 60, day, (t - lo) // 60,
                          {"all": every}, MINUTE_LAGS, MINUTE_WINDOWS,
                          {"null": null, "rssi": CLOSE_RSSI, "resolution": "1 min"})  # fmt: skip
        rows += r
        curves += [c | {"resolution": "1 min"} for c in
                   curve_rows(eff, "all", MINUTE_LAGS, 1, {"null": null})]  # fmt: skip
    print("minutes done", flush=True)

    table = pl.DataFrame(rows, infer_schema_length=None)
    both = (
        table.filter((pl.col("kind") == "all") & (pl.col("rssi") == CLOSE_RSSI))
        .group_by("resolution", "feature", "window")
        .agg((pl.col("verdict") == "replicates").all().alias("lead"))
    )
    table = table.join(both, on=["resolution", "feature", "window"], how="left")
    table.write_csv(out / "lag_windows.csv")
    pl.DataFrame(curves, infer_schema_length=None).write_csv(out / "lag_curves.csv")
    (pl.DataFrame(clusters, infer_schema_length=None) if clusters else pl.DataFrame()).write_csv(
        out / "lag_clusters.csv"
    )

    # B.
    unit = set(people)
    days = oc.DAYS
    n_days = len(days)
    day_pos = {d: k for k, d in enumerate(days)}
    expo = exposure.filter(pl.col("day").is_in(days))
    seen = np.zeros((len(people), len(people), n_days))
    for d, g in expo.group_by("day"):
        m = np.zeros((len(people), n_bins), dtype=np.float32)
        m[[pos[e] for e in g["entity"]], (g["bs"].to_numpy() - lo) // BIN_S] = 1.0
        seen[:, :, day_pos[d[0]]] = m @ m.T
    in_bin = set(exposure.select("entity", "bs").iter_rows())

    def minutes_at(rssi: int) -> np.ndarray:
        m = np.zeros((len(people), len(people), n_days))
        rows_ = close_at(rssi).filter(pl.col("entity").is_in(people) & pl.col("other").is_in(people)
                                      & pl.col("day").is_in(days))  # fmt: skip
        for (e, o, d), g in rows_.group_by("entity", "other", "day"):
            m[pos[e], pos[o], day_pos[d]] = g["bs"].n_unique() * BIN_MIN
        return m

    def partners_at(rssi: int) -> dict:
        out_: dict = {}
        for e, b, o in close_at(rssi).select("entity", "bs", "other").iter_rows():
            if e in unit and o in unit and (o, b) in in_bin:
                out_.setdefault((e, b), []).append(o)
        return out_

    results = []
    minutes = minutes_at(CLOSE_RSSI)
    partners = partners_at(CLOSE_RSSI)
    shared, comparison = pair_days(entity, ts, day, index, partners)
    main_rows = pair_table(shared, comparison, minutes, seen, pos, course, days)
    results += come_back(main_rows, "main", len(people), n_days)
    print("come back main", flush=True)
    desc = (
        main_rows.group_by("shared").agg(
            pl.len().alias("pair_days"),
            pl.col("tied_later").mean().alias("share_tied_later"),
            pl.col("tied_earlier").mean().alias("share_tied_earlier"),
            pl.col("same_course").mean().alias("share_same_course"),
            pl.col("today").expm1().median().alias("median_minutes_that_day"),
            pl.col("later").expm1().median().alias("median_minutes_later"),
            pl.col("previous").expm1().median().alias("median_minutes_before"),
        ).sort("shared")
    )  # fmt: skip
    desc.write_csv(out / "come_back_descriptives.csv")
    results += come_back(main_rows.filter(pl.col("day") <= NO_DIP_LAST),
                         "follow-up misses 24-27 Aug", len(people), n_days)  # fmt: skip
    results += come_back(main_rows.filter(~pl.col("same_course")), "cross-course pairs",
                         len(people), n_days)  # fmt: skip
    near_shared, near_comparison = pair_days(entity, ts, day, index, partners, include_near=True)
    results += come_back(
        pair_table(near_shared, near_comparison, minutes, seen, pos, course, days),
        "with co-presses under 10 s", len(people), n_days,
    )  # fmt: skip
    idx70 = CloseIndex(close_at(SENSITIVE_RSSI).select("entity", "bs", "other").iter_rows(),
                       bin_size=BIN_S)  # fmt: skip
    s70, c70 = pair_days(entity, ts, day, idx70, partners_at(SENSITIVE_RSSI))
    results += come_back(
        pair_table(s70, c70, minutes_at(SENSITIVE_RSSI), seen, pos, course, days),
        f"{SENSITIVE_RSSI} dBm", len(people), n_days,
    )  # fmt: skip
    res = pl.DataFrame(results, infer_schema_length=None)
    placebo = res.filter(pl.col("outcome").str.starts_with("placebo")).select(
        "variant", pl.col("all_lo").alias("placebo_lo"), pl.col("all_hi").alias("placebo_hi")
    )
    res = res.join(placebo, on="variant", how="left").with_columns(
        (
            (pl.col("verdict") == "replicates")
            & (pl.col("placebo_lo") <= 0)
            & (pl.col("placebo_hi") >= 0)
            & ~pl.col("outcome").str.starts_with("placebo")
        ).alias("lead")
    )
    res.write_csv(out / "come_back.csv")
    (out / "qa.json").write_text(json.dumps(qa, indent=2, default=str), encoding="utf-8")
    figures(main_eff, res, out)
    print(json.dumps(qa, indent=2, default=str))


def figures(eff: dict, res: pl.DataFrame, out: Path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    plt.rcParams.update({"font.size": 10, "axes.spines.top": False, "axes.spines.right": False})
    x = LAGS * BIN_MIN
    fig, axes = plt.subplots(1, len(FEATURES), figsize=(15, 3.2))
    for ax, name in zip(axes, FEATURES, strict=True):
        for half, color in (("discovery", BLUE), ("replication", ORANGE)):
            d = eff[name][("all", half)]
            mean = np.nanmean(d, axis=0)
            se = np.nanstd(d, axis=0, ddof=1) / np.sqrt((~np.isnan(d)).sum(axis=0))
            ax.fill_between(x, mean - 1.96 * se, mean + 1.96 * se, color=color, alpha=0.15, lw=0)
            ax.plot(x, mean, color=color, lw=2, label=f"{half} days")
        ax.axhline(0, color=GRAY, lw=1)
        ax.axvline(0, color=GRAY, lw=1, ls=":")
        ax.set_title(name.replace("_", " "))
        ax.set_xlabel("minutes from the press")
    axes[0].set_ylabel("observed minus shuffled")
    axes[0].legend(frameon=False)
    fig.tight_layout()
    fig.savefig(out / "fig_lag_profiles.png", dpi=180)
    plt.close(fig)

    main = res.filter(pl.col("variant") == "main")
    fig, ax = plt.subplots(figsize=(8, 3))
    ypos = 0
    labels = []
    for row in main.iter_rows(named=True):
        for half, color in (("discovery", BLUE), ("replication", ORANGE)):
            if row[f"{half}_est"] is None:
                continue
            ax.plot([row[f"{half}_lo"], row[f"{half}_hi"]], [ypos, ypos], color=color, lw=2)
            ax.plot(row[f"{half}_est"], ypos, "o", color=color, ms=8,
                    label=f"{half} days" if ypos < 2 else None)  # fmt: skip
            labels.append((ypos, f"{row['outcome']}"))
            ypos += 1
        ypos += 1
    ax.axvline(0, color=GRAY, lw=1)
    ax.set_yticks([p for p, _ in labels], [t for _, t in labels])
    ax.invert_yaxis()
    ax.set_xlabel("shared moment minus comparison, given the controls")
    ax.legend(frameon=False)
    fig.tight_layout()
    fig.savefig(out / "fig_come_back.png", dpi=180)
    plt.close(fig)


if __name__ == "__main__":
    main()
