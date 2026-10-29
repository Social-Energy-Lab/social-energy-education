"""Exploratory tier, round 2: a closer look at collective moments (press cascades).

``research/analysis-plan.md`` (frozen 2026-10-19), section "Exploratory analyses", item
"Collective moments". **Every result here is exploratory**: no error control, two-sided, effects
with 95% intervals and no p-values, distributions rather than people, cells with fewer than
``MIN_GROUP`` people withheld.

Common ground is round 1's (``exploratory_presses.load``): press episodes of participants with
``self_report`` and ``beacons`` consent, from the instruction to the handover, counted only in
exposure bins (5-minute bins in which the tag was heard, less lost and unsettled windows). A
**co-located pair** is two press episodes by different participants at most ``WINDOW`` seconds
apart whose people were at close range (pair's strongest reading at least ``CLOSE_RSSI``) in the
bin of either press (``co_event_pairs``). The **null** moves every press to a random exposure bin
of the same person in the same camp day and phase of day (``shuffle_events``), ``N_SHUFFLE``
times; it keeps each person's rate per day and phase and puts presses only where the tag was
heard. Each statistic below is counted per camp day on the observed presses and on every
shuffle. The **excess** is observed over null mean, pooled over days, with a percentile interval
from resampling camp days (``cluster_ratio``): the null is drawn within days, so days are the
natural independent unit. Beside it, the null's own 95% band of the pooled count.

1. **Where and when.** Co-located pairs by setting (round 1's classification, ``[inferred]``:
   plenum, course block, KüA evening, meal time, late evening, other daytime, night; the setting
   of the earlier press's bin), by phase of day and by camp day, each set against the null pairs
   falling in the same cell. A stricter null for settings shuffles within person x day x phase x
   setting, so a setting's own press rate cannot make its excess.
2. **Latency.** Co-located pairs up to ``LATENCY_WINDOW`` apart, by gap (``GAP_EDGES``), against
   the null in each gap band: a peak near zero suggests a shared moment, a peak at a delay one
   press prompting another. Press times are about 3 s after the press began and tag clocks agree
   to seconds, so the first band is coarse.
3. **Size.** Presses joined by co-located pairs form groups (connected components, single
   linkage); a group's size is its number of distinct people. Groups of 2, 3, 4 and 5+ people,
   and co-located triangles (three presses by three people, every pair co-located within
   ``WINDOW``), against the null.
4. **Who goes first.** In co-located pairs at least ``ORDER_MIN_S`` apart (below that, order is
   within clock error), a Bradley-Terry logit of "this one first" on the difference in
   standardised baseline composites (trust, lust: ``confirmatory/composites.parquet``) and in
   log press count (activity), interval from resampling days. Whether "being first" is a trait:
   the spread of people's share of firsts against random order of the presses
   (``random_order``), and its split-half stability (odd vs even camp days). Course: in
   cross-course pairs, each course's share of firsts against random order; courses are
   anonymised. Staff (course and academy
   leaders with ``beacons`` and ``self_report`` consent; the researcher and the musician are
   left out) stay a separate group: their presses and their co-located pairs with participants
   against the same null, and who goes first in mixed pairs.
5. **Network relation.** Each co-located pair's tie strength in the co-presence network: the
   number of camp days on which the two were close for at least ``TIE_MIN`` minutes (the plan's
   tie), in bands ``TIE_BANDS``. Observed against the null per band (does the excess sit among
   close ties?), and the distribution beside that of all participant pairs ever close.
6. **Robustness.** The headline statistics again at -70 and -75 dBm, without 24-27 Aug
   (``DROP_DAYS``, low own-record coverage), without the ``TOP_PAIRS`` person pairs with the
   most co-located pairs (removed from observed and null alike), without pairs under
   ``NEAR_S`` s, and under the looser person x day null and the stricter one with setting.

    uv run --extra analysis python studies/dsa-2026/analyses/exploratory_cascades.py

Writes CSVs, ``qa_cascades.json`` and figures to
``$SOCIAL_ENERGY_DATA/dsa-2026/derived/analyses/exploratory/cascades/``. Nothing per person.
"""

from __future__ import annotations

import itertools
import json
import sys
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import numpy as np
import polars as pl

sys.path.insert(0, str(Path(__file__).parent))
import copresence_by_phase as cp
import exploratory_presses as xp
import outcomes as oc
import self_report_context as srx

from social_energy import paths
from social_energy.exploratory import (
    CloseIndex,
    cluster_ratio,
    co_event_pairs,
    first_mover_logit,
    group_members,
    group_sizes,
    shuffle_events,
)
from social_energy.spine import Spine

SLUG = "exploratory/cascades"
MIN_GROUP = 5
CLOSE_RSSI = cp.CLOSE_RSSI
BIN_S = xp.BIN_S
WINDOW = 300
LATENCY_WINDOW = 900
GAP_EDGES = [0, 10, 30, 60, 120, 300, 600, 900]
GAP_LABELS = ["0-10 s", "10-30 s", "30-60 s", "1-2 min", "2-5 min", "5-10 min", "10-15 min"]
NEAR_S = xp.NEAR_S
ORDER_MIN_S = 30
SIZE_LABELS = ["2", "3", "4", "5+"]
TIE_MIN = cp.TIE_MIN_BINS * 5
TIE_BANDS = [(0, 0, "never tied"), (1, 2, "1-2 days"), (3, 6, "3-6 days"), (7, 99, "7+ days")]
DROP_DAYS = [date(2026, 8, d) for d in (24, 25, 26, 27)]
TOP_PAIRS = 5
STAFF_ROLES = {"course_leader", "academy_leader"}
PHASES = cp.PHASE_ORDER
SETTINGS = xp.SETTING_ORDER
N_SHUFFLE = 1000
N_BOOT = 4000
SEED = 20261021
BLUE, ORANGE, GRAY = cp.BLUE, cp.ORANGE, cp.GRAY
NULLS = {
    "person-day": ["day"],
    "person-day-phase": ["day", "phase"],
    "person-day-phase-setting": ["day", "phase", "setting"],
}


# --- the engine: one set of presses, its null, and every statistic per camp day ------------------


@dataclass
class Setup:
    """Presses (one row each, in a fixed order) and what the statistics need to classify them."""

    presses: pl.DataFrame  # entity, ts, day, phase, setting, group
    exposure: pl.DataFrame  # entity, bs, day, phase, setting
    close: CloseIndex
    rssi: dict  # (entity, bs, other) -> max_rssi, close bins only
    setting_of: dict  # (entity, bs) -> setting index
    band: dict  # sorted person pair -> tie band index
    days: list
    drop: set = field(default_factory=set)  # sorted person pairs left out of every count
    min_gap: int = 0  # pairs closer than this left out of every count

    def __post_init__(self):
        self.entity = self.presses["entity"].to_list()
        self.ts = self.presses["ts"].to_numpy()
        self.day = self.presses["day"].replace_strict({d: i for i, d in enumerate(self.days)})
        self.day = self.day.to_numpy()
        self.phase = self.presses["phase"].replace_strict({p: i for i, p in enumerate(PHASES)})
        self.phase = self.phase.to_numpy()
        self.group = self.presses["group"].to_list()

    def pools(self, null: str) -> tuple[list, dict]:
        keys = NULLS[null]
        s = pl.concat_str([pl.col(k).cast(pl.String) for k in keys], separator="|")
        stratum = self.presses.select(s).to_series().to_list()
        pools = {
            (e, k): np.asarray(b)
            for e, k, b in self.exposure.with_columns(s.alias("s"))
            .group_by("entity", "s")
            .agg(pl.col("bs"))
            .iter_rows()
        }
        return stratum, pools


def pairs_of(s: Setup, t: np.ndarray, window: int):
    p = co_event_pairs(s.entity, t, s.close, window=window, bin_size=BIN_S)
    keep = p.gap >= s.min_gap
    if s.drop:
        ent = s.entity
        keep &= np.array(
            [
                tuple(sorted((ent[a], ent[b]))) not in s.drop
                for a, b in zip(p.first, p.second, strict=True)
            ],
            dtype=bool,
        )
    return p.first[keep], p.second[keep], p.gap[keep], p.close[keep]


def triangles(entity: list, a: np.ndarray, b: np.ndarray, day: np.ndarray, n_days: int):
    """Co-located triangles per day of their earliest press: three presses by three people,
    every pair among the given edges."""
    nb: dict[int, set] = {}
    for u, v in zip(a.tolist(), b.tolist(), strict=True):
        nb.setdefault(u, set()).add(v)
        nb.setdefault(v, set()).add(u)
    out = np.zeros(n_days)
    for u, v in zip(a.tolist(), b.tolist(), strict=True):
        for w in nb[u] & nb[v]:
            if w > max(u, v) and len({entity[u], entity[v], entity[w]}) == 3:
                out[day[min(u, v, w)]] += 1
    return out


def statistics(s: Setup, t: np.ndarray) -> dict[str, np.ndarray]:
    """Every statistic, per camp day (rows), for presses at times ``t``."""
    D = len(s.days)
    a, b, gap, close = pairs_of(s, t, LATENCY_WINDOW)
    day = s.day[a]
    in_w = gap <= WINDOW
    c = close & in_w
    setting = np.array([s.setting_of[(e, x - x % BIN_S)] for e, x in zip(s.entity, t, strict=True)])

    def by(cat, n, mask):
        return np.bincount(day[mask] * n + cat[mask], minlength=D * n).reshape(D, n)

    out = {
        "any": np.bincount(day[in_w], minlength=D)[:, None].astype(float),
        "close": np.bincount(day[c], minlength=D)[:, None].astype(float),
        "phase": by(s.phase[a], len(PHASES), c),
        "setting": by(setting[a], len(SETTINGS), c),
        "day": np.diag(np.bincount(day[c], minlength=D)).astype(float),
        "latency": by(
            np.clip(np.digitize(gap, GAP_EDGES[1:], right=True), 0, len(GAP_LABELS) - 1),
            len(GAP_LABELS),
            close,
        ),
    }
    ent = s.entity
    band = np.array(
        [s.band.get(tuple(sorted((ent[i], ent[j]))), 0) for i, j in zip(a[c], b[c], strict=True)],
        dtype=np.int64,
    )
    out["tie"] = np.zeros((D, len(TIE_BANDS)))
    np.add.at(out["tie"], (day[c], band), 1)
    groups = s.group
    kind = np.array(
        [_kind(groups[i], groups[j]) for i, j in zip(a[c], b[c], strict=True)], dtype=np.int64
    )
    out["kind"] = np.zeros((D, 3))
    np.add.at(out["kind"], (day[c], kind), 1)
    sizes = np.zeros((D, len(SIZE_LABELS)))
    ca, cb = a[c], b[c]
    for d in range(D):
        m = day[c] == d
        if m.any():
            g = group_sizes(ent, ca[m], cb[m])
            sizes[d] += np.bincount(np.clip(g, 2, 5) - 2, minlength=4)
    out["size"] = sizes
    out["size3"] = sizes[:, 1:].sum(1, keepdims=True)
    out["triangles"] = triangles(ent, ca, cb, s.day, D)[:, None]
    lat = out["latency"]
    out["gap_under_60s"] = lat[:, :3].sum(1, keepdims=True)
    out["gap_2_15min"] = lat[:, 4:].sum(1, keepdims=True)
    return out


def _kind(g1: str, g2: str) -> int:
    """0 participant-participant, 1 participant-staff, 2 staff-staff."""
    return (g1 == "staff") + (g2 == "staff")


@dataclass
class Run:
    observed: dict[str, np.ndarray]
    null: dict[str, np.ndarray]  # shuffles x days x categories

    def table(
        self, key: str, labels: list[str], people: list[int | None] | None = None, seed: int = SEED
    ) -> pl.DataFrame:
        obs, null = self.observed[key], self.null[key]
        mean = null.mean(0)
        ratios = cluster_ratio(obs, mean, n_boot=N_BOOT, seed=seed)
        tot = null.sum(1)  # shuffles x categories
        rows = []
        for k, lab in enumerate(labels):
            o = float(obs[:, k].sum())
            lo, hi = np.quantile(tot[:, k], [0.025, 0.975])
            n_people = None if people is None else people[k]
            small = n_people is not None and n_people < MIN_GROUP
            r = ratios[k]
            rows.append(
                {
                    "category": lab,
                    "people": n_people,
                    "observed": None if small else o,
                    "null_mean": float(tot[:, k].mean()),
                    "null_lo": float(lo),
                    "null_hi": float(hi),
                    "ratio": None if small else r.estimate,
                    "ratio_lo": None if small else r.lo,
                    "ratio_hi": None if small else r.hi,
                    "days": r.n,
                    "share_null_at_least_observed": None
                    if small
                    else float((tot[:, k] >= o).mean()),
                    "suppressed": small,
                }
            )
        return pl.DataFrame(rows)


def run(s: Setup, null: str, n: int | None = None, seed: int = SEED) -> Run:
    n = N_SHUFFLE if n is None else n
    observed = statistics(s, s.ts)
    stratum, pools = s.pools(null)
    rng = np.random.default_rng(seed)
    draws = {k: [] for k in observed}
    for _ in range(n):
        t = shuffle_events(s.entity, stratum, pools, rng, bin_size=BIN_S)
        for k, v in statistics(s, t).items():
            draws[k].append(v)
    return Run(observed, {k: np.stack(v) for k, v in draws.items()})


# --- inputs --------------------------------------------------------------------------------------


def tie_bands(ends: pl.DataFrame) -> dict:
    """Sorted participant pair -> band of the number of days tied at the main closeness."""
    e = ends.filter((pl.col("max_rssi") >= CLOSE_RSSI) & (pl.col("entity") < pl.col("other")))
    days = (
        e.with_columns(cp.camp_day_expr(pl.col("bin")).alias("day"))
        .group_by("entity", "other", "day")
        .len()
        .group_by("entity", "other")
        .agg((pl.col("len") * 5 >= TIE_MIN).sum().alias("tied"))
    )
    out = {}
    for a, b, n in days.iter_rows():
        out[(a, b)] = next(i for i, (lo, hi, _) in enumerate(TIE_BANDS) if lo <= n <= hi)
    return out


def staff_data(layout, spine: Spine, data: dict) -> dict:
    """Presses, exposure and close pairs of consenting staff, shaped like round 1's ``load``."""
    role = {p.ref: p.role.value for p in spine.people}
    ok = spine.consented("beacons") & spine.consented("self_report")
    staff = {f"person:{p}" for p in ok if role.get(f"person:{p}") in STAFF_ROLES}
    presses, _ = srx.press_episodes(layout, spine, staff, staff)
    lo, hi = pl.select(srx.local(srx.INSTRUCTION)).item(), pl.select(srx.local(cp.HANDOVER)).item()
    seen = cp.load_all("seen").filter(
        pl.col("entity").is_in(list(staff)) & (pl.col("bin") >= lo) & (pl.col("bin") < hi)
    )
    exposure = seen.join(oc.removed_bins(spine), on=["entity", "bin"], how="anti").select(
        "entity", "bin", "day", "phase"
    )
    counted = presses.join(exposure.select("entity", "bin"), on=["entity", "bin"])
    people = set(data["presses"]["entity"].unique()) | staff
    participants = {p.ref for p in spine.people if p.role.value == "participant"}
    pairs = cp.load_all("pairs").filter(
        pl.col("a").is_in(list(people | participants))
        & pl.col("b").is_in(list(people | participants))
        & (pl.col("a").is_in(list(staff)) | pl.col("b").is_in(list(staff)))
        & (pl.col("bin") >= lo)
        & (pl.col("bin") < hi)
    )
    ends = pl.concat(
        [
            pairs.select(
                pl.col("a").alias("entity"), "bin", pl.col("b").alias("other"), "max_rssi"
            ),
            pairs.select(
                pl.col("b").alias("entity"), "bin", pl.col("a").alias("other"), "max_rssi"
            ),
        ]
    )
    return {"staff": staff, "presses": counted, "exposure": exposure, "ends": ends}


def make_setup(
    presses,
    exposure,
    ends,
    spine,
    *,
    close_rssi=CLOSE_RSSI,
    band=None,
    drop_days=(),
    drop=frozenset(),
    min_gap=0,
    staff=frozenset(),
) -> Setup:
    placed = xp.placed_settings(exposure, spine).with_columns(
        pl.col("bin").dt.epoch("s").alias("bs"),
        pl.col("setting").replace_strict({x: i for i, x in enumerate(SETTINGS)}).alias("si"),
    )
    if drop_days:
        placed = placed.filter(~pl.col("day").is_in(list(drop_days)))
        presses = presses.filter(~pl.col("day").is_in(list(drop_days)))
    p = (
        presses.join(placed.select("entity", "bin", "setting"), on=["entity", "bin"])
        .with_columns(
            pl.col("t").dt.epoch("s").alias("ts"),
            pl.when(pl.col("entity").is_in(list(staff)))
            .then(pl.lit("staff"))
            .otherwise(pl.lit("participant"))
            .alias("group"),
        )
        .sort("ts", "entity")
        .select("entity", "ts", "day", "phase", "setting", "group")
    )
    e = ends.filter(pl.col("max_rssi") >= close_rssi).with_columns(
        pl.col("bin").dt.epoch("s").alias("bs")
    )
    triples = list(e.select("entity", "bs", "other", "max_rssi").iter_rows())
    return Setup(
        presses=p,
        exposure=placed.select("entity", "bs", "day", "phase", "setting"),
        close=CloseIndex({(a, b, o) for a, b, o, _ in triples}, bin_size=BIN_S),
        rssi={(a, b, o): r for a, b, o, r in triples},
        setting_of=dict(
            zip(zip(placed["entity"], placed["bs"], strict=True), placed["si"], strict=True)
        ),
        band=band or {},
        days=sorted(p["day"].unique().to_list()),
        drop=set(drop),
        min_gap=min_gap,
    )


def observed_pairs(s: Setup, window: int = WINDOW) -> pl.DataFrame:
    """The observed co-located pairs, one row each: first and second person, gap, day, phase."""
    a, b, gap, close = pairs_of(s, s.ts, window)
    a, b, gap = a[close], b[close], gap[close]
    ent = s.entity
    return pl.DataFrame(
        {
            "i": a,
            "j": b,
            "first": [ent[i] for i in a],
            "second": [ent[j] for j in b],
            "gap": gap,
            "day": [s.days[s.day[i]] for i in a],
            "phase": [PHASES[s.phase[i]] for i in a],
            "setting": [SETTINGS[s.setting_of[(ent[i], s.ts[i] - s.ts[i] % BIN_S)]] for i in a],
            "band": [
                TIE_BANDS[s.band.get(tuple(sorted((ent[i], ent[j]))), 0)][2]
                for i, j in zip(a, b, strict=True)
            ],
            "group_first": [s.group[i] for i in a],
            "group_second": [s.group[j] for j in b],
        },
        schema_overrides={"gap": pl.Int64, "i": pl.Int64, "j": pl.Int64},
    )


def size_people(s: Setup) -> tuple[list[int], int]:
    """Distinct people in the observed groups of each size in ``SIZE_LABELS``, and in triangles:
    the small-cell count for the group-size table, built the way ``statistics`` builds groups."""
    a, b, gap, close = pairs_of(s, s.ts, LATENCY_WINDOW)
    c = close & (gap <= WINDOW)
    ca, cb, day = a[c], b[c], s.day[a[c]]
    people = [set() for _ in SIZE_LABELS]
    for d in range(len(s.days)):
        m = day == d
        for g in group_members(s.entity, ca[m], cb[m]):
            people[min(len(g), 5) - 2] |= g
    nb: dict[int, set] = {}
    for u, v in zip(ca.tolist(), cb.tolist(), strict=True):
        nb.setdefault(u, set()).add(v)
        nb.setdefault(v, set()).add(u)
    tri = set()
    for u, v in zip(ca.tolist(), cb.tolist(), strict=True):
        for w in nb[u] & nb[v]:
            trio = {s.entity[u], s.entity[v], s.entity[w]}
            if len(trio) == 3:
                tri |= trio
    return [len(x) for x in people], len(tri)


def people_per(pairs: pl.DataFrame, col: str, labels: list) -> list[int]:
    out = []
    for lab in labels:
        f = pairs.filter(pl.col(col) == lab)
        out.append(len(set(f["first"]) | set(f["second"])))
    return out


# --- 4. who goes first ---------------------------------------------------------------------------


def who_first(
    pairs: pl.DataFrame, person: pl.DataFrame, days: list, *, min_gap: int, seed: int = SEED
) -> pl.DataFrame:
    """Bradley-Terry logits on standardised person covariates, interval over resampled days."""
    o = pairs.filter(pl.col("gap") >= min_gap)
    rows = []
    for covs in (["trust"], ["lust"], ["trust", "lust"], ["activity"]):
        p = person.drop_nulls(covs)
        z = {
            r["entity"]: [r[c] for c in covs]
            for r in p.with_columns(
                [((pl.col(c) - pl.col(c).mean()) / pl.col(c).std()) for c in covs]
            ).iter_rows(named=True)
        }
        u = o.filter(pl.col("first").is_in(list(z)) & pl.col("second").is_in(list(z)))
        diff = np.array(
            [np.subtract(z[f], z[s_]) for f, s_ in zip(u["first"], u["second"], strict=True)]
        )
        dayi = np.array([days.index(d) for d in u["day"]])
        people = len(set(u["first"]) | set(u["second"]))
        if people < MIN_GROUP or len(u) < MIN_GROUP:
            for c in covs:
                rows.append(
                    {
                        "model": "+".join(covs),
                        "covariate": c,
                        "pairs": u.height,
                        "people": people,
                        "suppressed": True,
                    }
                )
            continue
        est = first_mover_logit(diff)
        rng = np.random.default_rng(seed)
        draws = []
        for _ in range(N_BOOT // 2):
            pick = rng.integers(0, len(days), len(days))
            idx = np.concatenate([np.flatnonzero(dayi == d) for d in pick])
            if len(idx) > len(covs):
                draws.append(first_mover_logit(diff[idx]))
        draws = np.array(draws)
        for k, c in enumerate(covs):
            d = draws[:, k][np.isfinite(draws[:, k])]
            lo, hi = np.quantile(d, [0.025, 0.975])
            rows.append(
                {
                    "model": "+".join(covs),
                    "covariate": c,
                    "pairs": u.height,
                    "people": people,
                    "odds_ratio_per_sd": float(np.exp(est[k])),
                    "lo": float(np.exp(lo)),
                    "hi": float(np.exp(hi)),
                    "suppressed": False,
                }
            )
    return pl.DataFrame(rows, infer_schema_length=None)


def random_order(o: pl.DataFrame, rng: np.random.Generator):
    """``N_SHUFFLE`` draws of which ordered pairs swap under random order of the presses: one
    uniform key per press, so pairs that share a press (a group moment) stay dependent, as they
    are in the data; flipping pairs one by one would understate the null's spread."""
    i, j = o["i"].to_numpy(), o["j"].to_numpy()
    n = int(max(i.max(), j.max())) + 1 if len(i) else 0
    for _ in range(N_SHUFFLE):
        u = rng.random(n)
        yield (u[i] > u[j]).tolist()


def first_share(pairs: pl.DataFrame, *, min_gap: int, min_pairs: int, seed: int = SEED) -> dict:
    """Is being first a trait? People's share of firsts against random order, and split halves."""
    o = pairs.filter(pl.col("gap") >= min_gap)
    rng = np.random.default_rng(seed)

    def dispersion(first, second):
        f = pl.DataFrame({"e": first, "w": 1}).vstack(pl.DataFrame({"e": second, "w": 0}))
        g = f.group_by("e").agg(pl.col("w").sum().alias("k"), pl.len().alias("n"))
        g = g.filter(pl.col("n") >= min_pairs)
        x = ((g["k"] - g["n"] / 2) ** 2 / (g["n"] / 4)).to_numpy()
        return float(x.mean()) if len(x) else float("nan"), g

    first, second = o["first"].to_list(), o["second"].to_list()
    obs, g = dispersion(first, second)
    null = []
    for flip in random_order(o, rng):
        f2 = [s_ if fl else f for f, s_, fl in zip(first, second, flip, strict=True)]
        s2 = [f if fl else s_ for f, s_, fl in zip(first, second, flip, strict=True)]
        null.append(dispersion(f2, s2)[0])
    share = (g["k"] / g["n"]).to_numpy()
    # Split halves: odd vs even camp days.
    odd = o.with_columns((pl.col("day").dt.day() % 2 == 1).alias("odd"))
    halves = []
    for flag in (True, False):
        h = odd.filter(pl.col("odd") == flag)
        f = pl.DataFrame({"e": h["first"], "w": 1}).vstack(pl.DataFrame({"e": h["second"], "w": 0}))
        halves.append(
            f.group_by("e")
            .agg((pl.col("w").mean()).alias(f"s{int(flag)}"), pl.len().alias("n"))
            .filter(pl.col("n") >= 3)
            .drop("n")
        )
    j = halves[0].join(halves[1], on="e")
    rho = spearman_ci(j["s1"].to_numpy(), j["s0"].to_numpy())
    return {
        "ordered_pairs": o.height,
        "people_with_min_pairs": g.height,
        "min_pairs": min_pairs,
        "share_first_quartiles": [float(q) for q in np.quantile(share, [0.25, 0.5, 0.75])]
        if g.height >= MIN_GROUP
        else None,
        "dispersion_observed": obs,
        "dispersion_null_mean": float(np.mean(null)),
        "dispersion_null_95": [float(q) for q in np.quantile(null, [0.025, 0.975])],
        "dispersion_ratio": obs / float(np.mean(null)),
        "split_half_people": j.height,
        "split_half_spearman": rho if j.height >= MIN_GROUP else None,
    }


def spearman_ci(x: np.ndarray, y: np.ndarray) -> dict:
    from scipy.stats import spearmanr

    n = len(x)
    r = float(spearmanr(x, y).statistic) if n > 3 else float("nan")
    se = 1 / np.sqrt(max(n - 3, 1))
    z = np.arctanh(np.clip(r, -0.999999, 0.999999))
    return {
        "rho": r,
        "lo": float(np.tanh(z - 1.96 * se)),
        "hi": float(np.tanh(z + 1.96 * se)),
        "n": n,
    }


def course_first(pairs: pl.DataFrame, course: dict, *, min_gap: int, seed: int = SEED):
    """Cross-course ordered pairs: each course's share of firsts, against random order."""
    o = (
        pairs.filter(pl.col("gap") >= min_gap)
        .with_columns(
            pl.col("first").replace_strict(course, default=None).alias("cf"),
            pl.col("second").replace_strict(course, default=None).alias("cs"),
        )
        .filter(
            pl.col("cf").is_not_null() & pl.col("cs").is_not_null() & (pl.col("cf") != pl.col("cs"))
        )
    )
    cf, cs = o["cf"].to_list(), o["cs"].to_list()
    courses = sorted(set(cf) | set(cs))

    def stat(cf, cs):
        k = {c: 0 for c in courses}
        n = {c: 0 for c in courses}
        for a, b in zip(cf, cs, strict=True):
            k[a] += 1
            n[a] += 1
            n[b] += 1
        share = {c: k[c] / n[c] for c in courses if n[c]}
        chi = sum((k[c] - n[c] / 2) ** 2 / (n[c] / 4) for c in courses if n[c])
        return share, chi

    share, chi = stat(cf, cs)
    rng = np.random.default_rng(seed)
    null = []
    for flip in random_order(o, rng):
        null.append(
            stat(
                [b if f else a for a, b, f in zip(cf, cs, flip, strict=True)],
                [a if f else b for a, b, f in zip(cf, cs, flip, strict=True)],
            )[1]
        )
    people = {}
    for e, c in list(zip(o["first"], o["cf"], strict=True)) + list(
        zip(o["second"], o["cs"], strict=True)
    ):
        people.setdefault(c, set()).add(e)
    rows = []
    shown = sorted(
        (c for c in courses if len(people.get(c, ())) >= MIN_GROUP), key=lambda c: share[c]
    )
    for i, c in enumerate(shown):
        rows.append(
            {"course": f"course {i + 1}", "people": len(people[c]), "share_first": share[c]}
        )
    return pl.DataFrame(rows), {
        "cross_course_ordered_pairs": o.height,
        "courses_shown": len(shown),
        "courses_withheld": len(courses) - len(shown),
        "heterogeneity_chi2": chi,
        "null_mean": float(np.mean(null)),
        "null_95": [float(q) for q in np.quantile(null, [0.025, 0.975])],
        "ratio": chi / float(np.mean(null)),
    }


def staff_first(pairs: pl.DataFrame, days: list, *, min_gap: int, seed: int = SEED) -> dict:
    """Mixed participant-staff ordered pairs: the share in which the staff member went first."""
    m = pairs.filter((pl.col("gap") >= min_gap) & (pl.col("group_first") != pl.col("group_second")))
    staff = set(m.filter(pl.col("group_first") == "staff")["first"]) | set(
        m.filter(pl.col("group_second") == "staff")["second"]
    )
    parts = (set(m["first"]) | set(m["second"])) - staff
    out = {
        "mixed_ordered_pairs": m.height,
        "staff_people": len(staff),
        "participant_people": len(parts),
    }
    if len(staff) < MIN_GROUP or len(parts) < MIN_GROUP:
        return out | {"suppressed": True}
    y = (m["group_first"] == "staff").to_numpy().astype(float)
    dayi = np.array([days.index(d) for d in m["day"]])
    rng = np.random.default_rng(seed)
    draws = []
    for _ in range(N_BOOT):
        pick = rng.integers(0, len(days), len(days))
        idx = np.concatenate([np.flatnonzero(dayi == d) for d in pick])
        if len(idx):
            draws.append(y[idx].mean())
    lo, hi = np.quantile(draws, [0.025, 0.975])
    return out | {
        "share_staff_first": float(y.mean()),
        "lo": float(lo),
        "hi": float(hi),
        "suppressed": False,
    }


# --- main ----------------------------------------------------------------------------------------


def headline(r: Run, variant: str) -> list[dict]:
    rows = []
    for key, label in (
        ("close", "co-located pairs <= 5 min"),
        ("gap_under_60s", "co-located pairs < 1 min apart"),
        ("gap_2_15min", "co-located pairs 2-15 min apart"),
        ("size3", "groups of 3+ people"),
        ("triangles", "co-located triangles"),
    ):
        t = r.table(key, [label]).row(0, named=True)
        rows.append({"variant": variant, **t})
    tie = r.table("tie", [b[2] for b in TIE_BANDS])
    for row in tie.iter_rows(named=True):
        rows.append({"variant": variant, **row, "category": f"tie: {row['category']}"})
    return rows


def main() -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    layout = paths.study(cp.STUDY)
    spine = Spine.load(layout.spine)
    out = layout.derived / "analyses" / SLUG
    out.mkdir(parents=True, exist_ok=True)
    data = xp.load(layout, spine)
    band = tie_bands(data["ends"])
    qa: dict = {"base": data["qa"]}
    base = (data["presses"], data["exposure"], data["ends"], spine)

    main_setup = make_setup(*base, band=band)
    qa["presses"] = main_setup.presses.height
    qa["pressers"] = main_setup.presses["entity"].n_unique()
    runs = {"main": run(main_setup, "person-day-phase")}
    m = runs["main"]
    obs = observed_pairs(main_setup)
    obs_lat = observed_pairs(main_setup, LATENCY_WINDOW)
    qa["observed_colocated_5min"] = obs.height
    qa["people_in_colocated_5min"] = len(set(obs["first"]) | set(obs["second"]))

    # 1. Where and when.
    where = pl.concat(
        [
            m.table("setting", SETTINGS, people_per(obs, "setting", SETTINGS)).with_columns(
                pl.lit("setting").alias("by"), pl.lit("person-day-phase").alias("null")
            ),
            m.table("phase", PHASES, people_per(obs, "phase", PHASES)).with_columns(
                pl.lit("phase").alias("by"), pl.lit("person-day-phase").alias("null")
            ),
            m.table(
                "day", [str(d) for d in main_setup.days], people_per(obs, "day", main_setup.days)
            ).with_columns(
                pl.lit("day").alias("by"),
                pl.lit("person-day-phase").alias("null"),
                pl.lit(None, pl.Float64).alias("ratio_lo"),
                pl.lit(None, pl.Float64).alias("ratio_hi"),
            ),
        ]
    )
    runs["setting null"] = run(main_setup, "person-day-phase-setting")
    where = pl.concat(
        [
            where,
            runs["setting null"]
            .table("setting", SETTINGS, people_per(obs, "setting", SETTINGS))
            .with_columns(
                pl.lit("setting").alias("by"), pl.lit("person-day-phase-setting").alias("null")
            ),
        ]
    )
    where.write_csv(out / "where_when.csv")

    # 2. Latency.
    lat_people = []
    for lo, hi in itertools.pairwise(GAP_EDGES):
        f = obs_lat.filter(
            (pl.col("gap") > lo if lo else pl.col("gap") >= 0) & (pl.col("gap") <= hi)
        )
        lat_people.append(len(set(f["first"]) | set(f["second"])))
    latency = m.table("latency", GAP_LABELS, lat_people).with_columns(
        pl.Series("width_s", np.diff(GAP_EDGES).astype(float))
    )
    latency.write_csv(out / "latency.csv")

    # 3. Size.
    sp, tp = size_people(main_setup)
    size = pl.concat([m.table("size", SIZE_LABELS, sp), m.table("triangles", ["triangles"], [tp])])
    size.write_csv(out / "group_size.csv")

    # 5. Network relation.
    tie = m.table(
        "tie", [b[2] for b in TIE_BANDS], people_per(obs, "band", [b[2] for b in TIE_BANDS])
    )
    pairs_ever = pl.DataFrame({"band": list(band.values())})["band"].value_counts()
    all_share = {TIE_BANDS[k][2]: n / len(band) for k, n in pairs_ever.iter_rows()}
    tie = tie.with_columns(
        (pl.col("observed") / pl.col("observed").sum()).alias("share_observed"),
        (pl.col("null_mean") / pl.col("null_mean").sum()).alias("share_null"),
        pl.col("category")
        .replace_strict(all_share, default=0.0)
        .alias("share_all_pairs_ever_close"),
    )
    tie.write_csv(out / "tie_strength.csv")
    qa["participant_pairs_ever_close"] = len(band)

    # 4. Who goes first.
    comps = pl.read_parquet(layout.derived / "analyses" / "confirmatory" / "composites.parquet")
    counts = main_setup.presses.group_by("entity").len()
    person = counts.join(
        comps.select("entity", "trust", "lust"), on="entity", how="left"
    ).with_columns(pl.col("len").log().alias("activity"))
    wf = pl.concat(
        [
            who_first(obs, person, main_setup.days, min_gap=g).with_columns(
                pl.lit(g).alias("min_gap_s")
            )
            for g in (ORDER_MIN_S, NEAR_S)
        ],
        how="diagonal",
    )
    trait = first_share(obs, min_gap=ORDER_MIN_S, min_pairs=MIN_GROUP)
    courses, course_qa = course_first(obs, cp.course_of(spine), min_gap=ORDER_MIN_S)
    courses.write_csv(out / "who_first_course.csv")
    qa["first_trait"] = trait
    qa["first_course"] = course_qa

    # Staff, a separate group: participants and staff together, against the same null.
    st = staff_data(layout, spine, data)
    qa["staff"] = {
        "people_consented": len(st["staff"]),
        "presses": st["presses"].height,
        "pressers": st["presses"]["entity"].n_unique(),
    }
    staff_setup = make_setup(
        pl.concat([data["presses"], st["presses"].select(data["presses"].columns)]),
        pl.concat([data["exposure"], st["exposure"]]),
        pl.concat([data["ends"], st["ends"]]),
        spine,
        band=band,
        staff=st["staff"],
    )
    staff_run = run(staff_setup, "person-day-phase")
    sobs = observed_pairs(staff_setup)
    kinds = ["participant-participant", "participant-staff", "staff-staff"]
    kind_people = []
    for k in range(3):
        f = sobs.filter(
            (pl.col("group_first") == "staff").cast(int)
            + (pl.col("group_second") == "staff").cast(int)
            == k
        )
        staff_people = set(f.filter(pl.col("group_first") == "staff")["first"]) | set(
            f.filter(pl.col("group_second") == "staff")["second"]
        )
        n = len(set(f["first"]) | set(f["second"]))
        kind_people.append(n if k == 0 else min(n, len(staff_people)))
    staff_tab = staff_run.table("kind", kinds, kind_people)
    staff_tab.write_csv(out / "staff_pairs.csv")
    qa["staff"]["first_in_mixed_pairs"] = staff_first(sobs, staff_setup.days, min_gap=ORDER_MIN_S)
    wf.write_csv(out / "who_first.csv")

    # 6. Robustness.
    top = (
        obs.with_columns(
            pl.concat_list(
                pl.min_horizontal("first", "second"), pl.max_horizontal("first", "second")
            ).alias("p")
        )
        .group_by("p")
        .len()
        .sort("len", descending=True)
        .head(TOP_PAIRS)
    )
    drop = {tuple(p) for p in top["p"].to_list()}
    qa["top_pairs_share_of_colocated_5min"] = float(top["len"].sum() / obs.height)
    variants = {
        "-70 dBm": make_setup(*base, close_rssi=-70, band=band),
        "-75 dBm": make_setup(*base, close_rssi=-75, band=band),
        "without 24-27 Aug": make_setup(*base, band=band, drop_days=DROP_DAYS),
        f"without top {TOP_PAIRS} person pairs": make_setup(*base, band=band, drop=drop),
        f"without pairs < {NEAR_S} s": make_setup(*base, band=band, min_gap=NEAR_S),
    }
    rob = headline(m, "main") + headline(runs["setting null"], "null within setting")
    runs["person-day null"] = run(main_setup, "person-day")
    rob += headline(runs["person-day null"], "null within person-day")
    wf_rob = []
    for name, s in variants.items():
        runs[name] = run(s, "person-day-phase")
        rob += headline(runs[name], name)
        wf_rob.append(
            who_first(observed_pairs(s), person, s.days, min_gap=ORDER_MIN_S).with_columns(
                pl.lit(name).alias("variant")
            )
        )
    robust = pl.DataFrame(rob, infer_schema_length=None)
    robust.write_csv(out / "robustness.csv")
    pl.concat(wf_rob, how="diagonal").write_csv(out / "who_first_robustness.csv")

    # --- figures (aggregates only) ---
    plt.rcParams.update({"font.size": 10, "axes.spines.top": False, "axes.spines.right": False})
    tag = "Exploratory, DSA 2026"

    def forest(ax, t, title, xlabel="observed / shuffled (null within person, day and phase)"):
        t = t.filter(~pl.col("suppressed"))
        y = np.arange(t.height)[::-1]
        r = t["ratio"].to_numpy()
        ax.errorbar(
            r,
            y,
            xerr=[r - t["ratio_lo"].to_numpy(), t["ratio_hi"].to_numpy() - r],
            fmt="o",
            color=BLUE,
            ecolor=BLUE,
            ms=5,
            capsize=2,
            lw=1.2,
        )
        ax.axvline(1, color=GRAY, lw=1, ls="--")
        ax.set_yticks(
            y,
            [
                f"{c} (n={p})" if p is not None else c
                for c, p in zip(t["category"], t["people"], strict=True)
            ],
        )
        ax.set_xlabel(xlabel)
        ax.set_title(title, loc="left", fontsize=10)

    # Figure 1: where and when.
    fig, axes = plt.subplots(1, 3, figsize=(15, 4.6), gridspec_kw={"width_ratios": [1, 1, 1.4]})
    forest(
        axes[0],
        where.filter((pl.col("by") == "setting") & (pl.col("null") == "person-day-phase")),
        "by setting",
    )
    forest(axes[1], where.filter(pl.col("by") == "phase"), "by phase of day")
    dd = where.filter(pl.col("by") == "day")
    x = np.arange(dd.height)
    axes[2].fill_between(
        x,
        dd["null_lo"].to_numpy(),
        dd["null_hi"].to_numpy(),
        color=GRAY,
        alpha=0.3,
        step="mid",
        label="shuffled, 95% band",
    )
    axes[2].plot(x, dd["observed"].to_numpy(), "o-", color=ORANGE, lw=2, ms=4, label="observed")
    axes[2].set_xticks(x, [d[5:] for d in dd["category"]], rotation=60)
    axes[2].set_ylabel("co-located press pairs within 5 min")
    axes[2].set_title("by camp day", loc="left", fontsize=10)
    axes[2].legend(frameon=False)
    for ax in axes[:2]:
        ax.set_xlabel("observed / shuffled")
    fig.suptitle(
        f"{tag}: where and when collective moments happen (n = people involved; "
        "intervals resample camp days)",
        fontsize=10,
        x=0.01,
        ha="left",
    )
    fig.tight_layout()
    fig.savefig(out / "fig_cascades_where_when.png", dpi=180)
    plt.close(fig)

    # Figure 2: latency.
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.2))
    w = latency["width_s"].to_numpy() / 60
    x = np.arange(latency.height)
    axes[0].fill_between(
        x,
        latency["null_lo"].to_numpy() / w,
        latency["null_hi"].to_numpy() / w,
        color=GRAY,
        alpha=0.3,
        label="shuffled, 95% band",
    )
    axes[0].plot(x, latency["null_mean"].to_numpy() / w, color=GRAY, lw=1.5)
    axes[0].plot(
        x, latency["observed"].to_numpy() / w, "o-", color=ORANGE, lw=2, ms=5, label="observed"
    )
    axes[0].set_yscale("log")
    axes[0].set_xticks(x, GAP_LABELS, rotation=30)
    axes[0].set_ylabel("co-located pairs per minute of gap")
    axes[0].set_xlabel("gap between the two presses")
    axes[0].legend(frameon=False)
    axes[0].set_title("how far apart the two presses are", loc="left", fontsize=10)
    lt = latency.filter(~pl.col("suppressed"))
    r = lt["ratio"].to_numpy()
    xx = np.arange(lt.height)
    axes[1].bar(xx, r, color=BLUE, width=0.6)
    axes[1].errorbar(
        xx,
        r,
        yerr=[r - lt["ratio_lo"].to_numpy(), lt["ratio_hi"].to_numpy() - r],
        fmt="none",
        ecolor="black",
        capsize=2,
        lw=0.8,
    )
    axes[1].axhline(1, color=GRAY, lw=1, ls="--")
    axes[1].set_xticks(xx, lt["category"].to_list(), rotation=30)
    axes[1].set_ylabel("observed / shuffled")
    axes[1].set_title("excess by gap", loc="left", fontsize=10)
    fig.suptitle(f"{tag}: latency of collective moments", fontsize=10, x=0.01, ha="left")
    fig.tight_layout()
    fig.savefig(out / "fig_cascades_latency.png", dpi=180)
    plt.close(fig)

    # Figure 3: size.
    fig, ax = plt.subplots(figsize=(7, 4.2))
    sz = size.filter(pl.col("category") != "triangles")
    x = np.arange(sz.height)
    ax.bar(x - 0.18, sz["observed"].to_numpy(), width=0.36, color=ORANGE, label="observed")
    nm = sz["null_mean"].to_numpy()
    ax.bar(x + 0.18, nm, width=0.36, color=GRAY, label="shuffled mean (95% band)")
    ax.errorbar(
        x + 0.18,
        nm,
        yerr=[nm - sz["null_lo"].to_numpy(), sz["null_hi"].to_numpy() - nm],
        fmt="none",
        ecolor="black",
        capsize=2,
        lw=0.8,
    )
    ax.set_yscale("log")
    ax.set_xticks(
        x,
        [
            f"{c} people\n(x{r:.1f})"
            for c, r in zip(sz["category"], sz["ratio"].fill_null(float("nan")), strict=True)
        ],
    )
    ax.set_ylabel("groups of co-located presses (log)")
    ax.legend(frameon=False)
    ax.set_title(f"{tag}: group moments by size", loc="left", fontsize=10)
    fig.tight_layout()
    fig.savefig(out / "fig_cascades_size.png", dpi=180)
    plt.close(fig)

    # Figure 4: who goes first.
    fig, ax = plt.subplots(figsize=(7.5, 3.8))
    w1 = wf.filter(
        (pl.col("min_gap_s") == ORDER_MIN_S)
        & ~pl.col("suppressed")
        & pl.col("model").is_in(["trust", "lust", "activity"])
    )
    y = np.arange(w1.height)[::-1]
    r = w1["odds_ratio_per_sd"].to_numpy()
    ax.errorbar(
        r,
        y,
        xerr=[r - w1["lo"].to_numpy(), w1["hi"].to_numpy() - r],
        fmt="o",
        color=BLUE,
        capsize=2,
        ms=5,
    )
    ax.axvline(1, color=GRAY, lw=1, ls="--")
    labels = {
        "trust": "trust in life (baseline)",
        "lust": "lust for life (baseline)",
        "activity": "own press count (log)",
    }
    ax.set_yticks(
        y, [f"{labels[c]} ({n} people)" for c, n in zip(w1["covariate"], w1["people"], strict=True)]
    )
    ax.set_xlabel("odds of pressing first, per SD of difference")
    ax.set_title(
        f"{tag}: who presses first in a co-located pair\n"
        f"(presses at least {ORDER_MIN_S} s apart; intervals resample camp days)",
        loc="left",
        fontsize=10,
    )
    fig.tight_layout()
    fig.savefig(out / "fig_cascades_who_first.png", dpi=180)
    plt.close(fig)

    # Figure 5: ties.
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.2))
    x = np.arange(tie.height)
    for k, (col, lab, colr) in enumerate(
        (
            ("share_all_pairs_ever_close", "all pairs ever close", GRAY),
            ("share_null", "shuffled co-located pairs", BLUE),
            ("share_observed", "observed co-located pairs", ORANGE),
        )
    ):
        axes[0].bar(x + (k - 1) * 0.26, tie[col].to_numpy(), width=0.26, color=colr, label=lab)
    axes[0].set_xticks(x, [f"{c}" for c in tie["category"]])
    axes[0].set_xlabel("days the pair was tied (>= 60 close minutes)")
    axes[0].set_ylabel("share")
    axes[0].legend(frameon=False)
    axes[0].set_title("tie strength of the pair", loc="left", fontsize=10)
    forest(axes[1], tie, "excess by tie strength", xlabel="observed / shuffled")
    fig.suptitle(
        f"{tag}: collective moments and the co-presence network", fontsize=10, x=0.01, ha="left"
    )
    fig.tight_layout()
    fig.savefig(out / "fig_cascades_ties.png", dpi=180)
    plt.close(fig)

    # Figure 6: robustness.
    fig, ax = plt.subplots(figsize=(8, 4.2))
    rb = robust.filter(pl.col("category") == "co-located pairs <= 5 min")
    y = np.arange(rb.height)[::-1]
    r = rb["ratio"].to_numpy()
    ax.errorbar(
        r,
        y,
        xerr=[r - rb["ratio_lo"].to_numpy(), rb["ratio_hi"].to_numpy() - r],
        fmt="o",
        color=BLUE,
        capsize=2,
        ms=5,
    )
    ax.axvline(1, color=GRAY, lw=1, ls="--")
    ax.set_yticks(y, rb["variant"].to_list())
    ax.set_xlim(left=0)
    ax.set_xlabel("co-located press pairs within 5 min, observed / shuffled")
    ax.set_title(f"{tag}: the collective-moment excess under each variant", loc="left", fontsize=10)
    fig.tight_layout()
    fig.savefig(out / "fig_cascades_robustness.png", dpi=180)
    plt.close(fig)

    qa["settings"] = {
        "min_group": MIN_GROUP,
        "close_rssi": CLOSE_RSSI,
        "window_s": WINDOW,
        "latency_window_s": LATENCY_WINDOW,
        "order_min_s": ORDER_MIN_S,
        "n_shuffle": N_SHUFFLE,
        "n_boot": N_BOOT,
        "seed": SEED,
        "tie_min": TIE_MIN,
        "top_pairs": TOP_PAIRS,
    }
    (out / "qa_cascades.json").write_text(json.dumps(qa, indent=2, default=str), encoding="utf-8")
    with pl.Config(tbl_rows=200, tbl_cols=20, fmt_str_lengths=40, tbl_width_chars=250):
        print(json.dumps(qa, indent=2, default=str))
        for name, t in (
            ("where", where),
            ("latency", latency),
            ("size", size),
            ("tie", tie),
            ("who_first", wf),
            ("courses", courses),
            ("staff", staff_tab),
            ("robustness", robust),
        ):
            print(name, t)


if __name__ == "__main__":
    main()
