"""Exploratory tier, self-report presses: company, collective moments, places and programme.

``research/analysis-plan.md`` (frozen 2026-10-19), section "Exploratory analyses". **Every result
here is exploratory**: no error control, two-sided, effect sizes with 95% intervals and no
p-values, distributions rather than people, cells of fewer than ``MIN_GROUP`` people withheld.

Common ground, as C4 (``outcomes.py``): press episodes from ``self_report_context.press_episodes``
(main accidental-run rule), participants with ``self_report`` and ``beacons`` consent, from the
instruction (14 Aug 08:45) to the handover. Exposure is a 5-minute bin in which the person's tag
was seen, less lost and unsettled windows (``outcomes.removed_bins``); a press counts only in an
exposure bin. Company: participants at close range in the bin (pair's strongest reading at least
``CLOSE_RSSI``), from ``copresence_by_phase.py build``.

**Moved moments in company.** ``self_report_context.py`` compares presses with the pooled
ordinary bins of all pressers. Here each person is their own control: for each presser, close
others at their press bins minus at their own other exposure bins (``within_person_contrast``),
unmatched, matched within the same camp day and phase of day, and within the same day and clock
hour. The mean over people with a bootstrap interval over people; the same for being alone (no
one close). Beside it, a conditional logit of "a press in this bin" on the number of close others
with strata person x day x phase (its interval treats strata as independent, so it is
optimistic). Variants: -70 and -75 dBm for "close", and days up to ``LAST_GOOD_DAY`` only.

**Collective moments.** Pairs of presses by different participants within ``WINDOWS`` of each
other, and how many of those pairs had the two at close range in either press's bin
(``co_events``). Null: every press moved to a random exposure bin of the same person on the same
camp day (keeps each person's daily rate and only places them where their tag was heard), and a
stricter one within the same day and phase. ``N_SHUFFLE`` shuffles each.

**Places and programme items.** Presses per 10 exposure hours by zone (the room tag the person
heard most in the bin; ``unplaced`` when none) and by setting `[inferred: our classification]`:
``plenum`` (inside a plenum event window of the spine; a missing end is filled with the median
known plenum length), ``course block`` (morning or afternoon phase, placed in the courses zone),
``meal time``, ``KüA evening`` (19:30-22:30), ``late evening`` (22:30-02:00), ``night``, ``other
daytime``. Formal (course block, plenum) against informal (KüA evening, late evening) as a rate
ratio. And by programme item kind from the spine's events: a bin counts for an event when the
event is all-camp, or when the person was placed in one of its rooms; missing ends are filled
with the median known length of that kind (else ``NOMINAL_MIN``), with a variant on known ends
only. Intervals resample people.

    uv run --extra analysis python studies/dsa-2026/analyses/exploratory_presses.py

Writes CSVs, ``qa_presses.json`` and figures to
``$SOCIAL_ENERGY_DATA/dsa-2026/derived/analyses/exploratory/``. Nothing per person is written.
"""

from __future__ import annotations

import json
import sys
from datetime import timedelta
from pathlib import Path

import numpy as np
import polars as pl

sys.path.insert(0, str(Path(__file__).parent))
import copresence_by_phase as cp
import outcomes as oc
import self_report_context as srx

from social_energy import paths
from social_energy.exploratory import (
    bootstrap_mean,
    co_events,
    null_compare,
    person_rates,
    shuffle_events,
    within_person_contrast,
)
from social_energy.spine import Spine

SLUG = "exploratory"
MIN_GROUP = 5
CLOSE_RSSI = cp.CLOSE_RSSI
CLOSE_VARIANTS = [-65, -70, -75]
LAST_GOOD_DAY = srx.LAST_GOOD_DAY
BIN_S = 300
WINDOWS = [120, 300, 600]
#: Pairs closer than this are also reported apart: two tags in one bag pressed by the same push
#: would look like a co-located co-press seconds apart.
NEAR_S = 10
#: Setting rates are also reported from this day on, when trying the button out is over.
SETTLED_FROM = "2026-08-16"
N_SHUFFLE = 1000
N_BOOT = 4000
SEED = 20261020
NOMINAL_MIN = 60
FORMAL = ["course block", "plenum"]
INFORMAL = ["KüA evening", "late evening"]
SETTING_ORDER = ["course block", "plenum", "meal time", "other daytime", "KüA evening",
                 "late evening", "night"]  # fmt: skip
BLUE, ORANGE, GRAY = cp.BLUE, cp.ORANGE, cp.GRAY


def epoch(col: str) -> pl.Expr:
    return pl.col(col).dt.epoch("s")


# --- inputs --------------------------------------------------------------------------------------


def load(layout, spine) -> dict:
    participants = {p.ref for p in spine.people if p.role == "participant"}
    beacon_ok = {f"person:{p}" for p in spine.consented("beacons")}
    raters = {f"person:{p}" for p in spine.consented("self_report")} & beacon_ok & participants
    presses, press_qa = srx.press_episodes(layout, spine, participants, raters)
    lo, hi = pl.select(srx.local(srx.INSTRUCTION)).item(), pl.select(srx.local(cp.HANDOVER)).item()
    seen = cp.load_all("seen").filter(
        pl.col("entity").is_in(list(raters)) & (pl.col("bin") >= lo) & (pl.col("bin") < hi)
    )
    removed = oc.removed_bins(spine)
    exposure = seen.join(removed, on=["entity", "bin"], how="anti").select(
        "entity", "bin", "day", "phase"
    )
    counted = presses.join(exposure.select("entity", "bin"), on=["entity", "bin"])
    pairs = cp.load_all("pairs").filter(
        pl.col("a").is_in(list(participants))
        & pl.col("b").is_in(list(participants))
        & (pl.col("bin") >= lo)
        & (pl.col("bin") < hi)
    )
    ends = pl.concat(
        [
            pairs.select(pl.col("a").alias("entity"), "bin", pl.col("b").alias("other"),
                         "max_rssi"),
            pairs.select(pl.col("b").alias("entity"), "bin", pl.col("a").alias("other"),
                         "max_rssi"),
        ]
    )  # fmt: skip
    qa = {
        "press": press_qa,
        "raters": len(raters),
        "exposure_bins": exposure.height,
        "exposure_people": exposure["entity"].n_unique(),
        "presses": presses.height,
        "presses_in_exposure": counted.height,
        "pressers_in_exposure": counted["entity"].n_unique(),
    }
    return {"exposure": exposure, "presses": counted, "ends": ends, "qa": qa}


# --- 3. moved moments in company -----------------------------------------------------------------


def company_bins(exposure, presses, ends, close_rssi) -> pl.DataFrame:
    """Every exposure bin of each presser with ``close``, ``alone``, ``event`` and ``hour``."""
    n_close = (
        ends.filter(pl.col("max_rssi") >= close_rssi)
        .group_by("entity", "bin")
        .agg(pl.col("other").n_unique().alias("close"))
    )
    events = presses.select("entity", "bin").unique().with_columns(pl.lit(True).alias("event"))
    pressers = presses["entity"].unique().implode()
    return (
        exposure.filter(pl.col("entity").is_in(pressers))
        .join(n_close, on=["entity", "bin"], how="left")
        .join(events, on=["entity", "bin"], how="left")
        .with_columns(
            pl.col("close").fill_null(0).cast(pl.Float64),
            pl.col("event").fill_null(False),
            pl.col("bin").dt.convert_time_zone(cp.TZ).dt.hour().alias("hour"),
        )
        .with_columns((pl.col("close") == 0).cast(pl.Float64).alias("alone"))
    )


def clogit(bins: pl.DataFrame) -> dict:
    """Conditional logit of ``event`` on ``close``, strata person x day x phase."""
    import warnings

    from statsmodels.discrete.conditional_models import ConditionalLogit

    b = bins.with_columns(
        pl.concat_str("entity", pl.col("day").cast(pl.String), "phase").alias("stratum")
    )
    keep = b.group_by("stratum").agg(pl.col("event").any().alias("e"), (~pl.col("event")).any()
                                     .alias("n")).filter(pl.col("e") & pl.col("n"))  # fmt: skip
    b = b.filter(pl.col("stratum").is_in(keep["stratum"].implode()))
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        res = ConditionalLogit(
            b["event"].cast(pl.Float64).to_numpy(),
            b.select("close").to_numpy(),
            groups=b["stratum"].to_numpy(),
        ).fit(disp=0)
    est, se = float(res.params[0]), float(res.bse[0])
    return {"or_per_close_other": np.exp(est), "lo": np.exp(est - 1.96 * se),
            "hi": np.exp(est + 1.96 * se), "strata": keep.height, "bins": b.height,
            "people": b["entity"].n_unique()}  # fmt: skip


def moved_in_company(data: dict) -> tuple[pl.DataFrame, pl.DataFrame, list[dict]]:
    rows, clog = [], []
    main_diffs = None
    for close_rssi in CLOSE_VARIANTS:
        for days in ("all", "to_last_good_day"):
            if days != "all" and close_rssi != CLOSE_RSSI:
                continue
            exposure, presses = data["exposure"], data["presses"]
            if days != "all":
                last = pl.lit(LAST_GOOD_DAY).str.to_date()
                exposure = exposure.filter(pl.col("day") <= last)
                presses = presses.filter(pl.col("day") <= last)
            bins = company_bins(exposure, presses, data["ends"], close_rssi)
            variant = f"{close_rssi} dBm" + ("" if days == "all" else f", to {LAST_GOOD_DAY}")
            for match, strata in (("none", []), ("day x phase", ["day", "phase"]),
                                  ("day x hour", ["day", "hour"])):  # fmt: skip
                for value in ("close", "alone"):
                    c = within_person_contrast(bins, value=value, event="event", strata=strata)
                    m = bootstrap_mean(c["diff"].to_list(), n_boot=N_BOOT, seed=SEED)
                    rows.append({
                        "variant": variant, "matched": match, "value": value, "people": m.n,
                        "events": int(c["events"].sum()),
                        "mean_at_press": float(c["at_event"].mean()),
                        "mean_baseline": float(c["baseline"].mean()),
                        "mean_diff": m.estimate, "lo": m.lo, "hi": m.hi,
                        "median_diff": float(c["diff"].median()),
                        "share_people_positive": float((c["diff"] > 0).mean()),
                        "share_people_negative": float((c["diff"] < 0).mean()),
                    })  # fmt: skip
                    if (close_rssi, days, match, value) == (CLOSE_RSSI, "all", "day x phase",
                                                            "close"):  # fmt: skip
                        main_diffs = c["diff"]
            clog.append({"variant": variant, **clogit(bins)})
    return pl.DataFrame(rows), pl.DataFrame(clog), main_diffs


# --- 4. collective moments -----------------------------------------------------------------------


def cascades(data: dict) -> tuple[pl.DataFrame, dict]:
    presses = data["presses"].with_columns(epoch("t").alias("ts"), epoch("bin").alias("bs"))
    exposure = data["exposure"].with_columns(epoch("bin").alias("bs"))
    ends = (
        data["ends"].filter(pl.col("max_rssi") >= CLOSE_RSSI).with_columns(epoch("bin").alias("bs"))
    )
    close = set(ends.select("entity", "bs", "other").iter_rows())
    ent = presses["entity"].to_list()
    widths = [NEAR_S, *WINDOWS]
    observed = {w: co_events(ent, presses["ts"].to_numpy(), close, window=w, bin_size=BIN_S)
                for w in widths}  # fmt: skip
    rows, nulls = [], {}
    for name, keys in (("person-day", ["day"]), ("person-day-phase", ["day", "phase"])):
        stratum = presses.select(pl.concat_str([pl.col(k).cast(pl.String) for k in keys]))
        stratum = stratum.to_series().to_list()
        ex = exposure.with_columns(
            pl.concat_str([pl.col(k).cast(pl.String) for k in keys]).alias("s")
        )
        pools = {(e, s): np.asarray(b) for e, s, b in
                 ex.group_by("entity", "s").agg(pl.col("bs")).iter_rows()}  # fmt: skip
        rng = np.random.default_rng(SEED)
        draws = {w: ([], []) for w in widths}
        for _ in range(N_SHUFFLE):
            t = shuffle_events(ent, stratum, pools, rng, bin_size=BIN_S)
            for w in widths:
                c, a = co_events(ent, t, close, window=w, bin_size=BIN_S)
                draws[w][0].append(c)
                draws[w][1].append(a)
        for w, near in [(w, False) for w in WINDOWS] + [(w, True) for w in WINDOWS]:
            for k, label in ((0, "co-located pairs"), (1, "any pairs")):
                obs, null = observed[w][k], np.asarray(draws[w][k])
                if near:  # pairs more than NEAR_S apart only
                    obs, null = obs - observed[NEAR_S][k], null - np.asarray(draws[NEAR_S][k])
                n = null_compare(obs, null)
                rows.append({"null": name, "window_min": w / 60,
                             "excluding_under_s": NEAR_S if near else 0, "statistic": label,
                             "observed": n.observed, "null_mean": n.null_mean,
                             "null_lo": n.null_lo, "null_hi": n.null_hi, "ratio": n.ratio,
                             "share_null_at_least_observed": n.share_null_at_least,
                             "shuffles": n.n_shuffles})  # fmt: skip
        nulls[name] = draws
    # The observed co-located pairs within 5 min, described in aggregate: how far apart, how
    # close the tags were, and whether a few person pairs carry them.
    t = presses.sort("ts")
    ts, es, ph = t["ts"].to_numpy(), t["entity"].to_list(), t["phase"].to_list()
    rssi = {(a, b, o): r for a, b, o, r in ends.select("entity", "bs", "other", "max_rssi")
            .iter_rows()}  # fmt: skip
    found = []
    for i in range(len(ts)):
        j = i + 1
        while j < len(ts) and ts[j] - ts[i] <= 300:
            bi, bj = ts[i] - ts[i] % BIN_S, ts[j] - ts[j] % BIN_S
            r = rssi.get((es[i], bi, es[j]), rssi.get((es[j], bj, es[i])))
            if es[i] != es[j] and r is not None:
                found.append({"gap_s": int(ts[j] - ts[i]), "rssi": r, "phase": ph[i],
                              "pair": tuple(sorted((es[i], es[j])))})  # fmt: skip
            j += 1
    f = pl.DataFrame(found)
    per_pair = f.group_by("pair").len().sort("len", descending=True)["len"]
    info = {
        "observed": observed,
        "nulls": nulls,
        "colocated_5min": {
            "pairs_of_presses": f.height,
            "people_involved": len({p for pr in f["pair"] for p in pr}),
            "person_pairs": per_pair.len(),
            "share_from_top_5_person_pairs": float(per_pair.head(5).sum() / f.height),
            "share_under_10s": float((f["gap_s"] < NEAR_S).mean()),
            "share_under_60s": float((f["gap_s"] < 60).mean()),
            "gap_s_median": float(f["gap_s"].median()),
            "rssi_median": float(f["rssi"].median()),
            "share_rssi_at_least_-50": float((f["rssi"] >= -50).mean()),
            "by_phase": dict(f.group_by("phase").len().iter_rows()),
        },
    }
    return pl.DataFrame(rows), info


# --- 5. places and programme items ---------------------------------------------------------------


def event_windows(spine: Spine, known_only: bool) -> pl.DataFrame:
    """Event id, kind, all_camp, locations, start, end (UTC); missing ends filled per kind."""
    evs = [e for e in spine.events if e.start is not None]
    known = {}
    for e in evs:
        if e.end is not None and e.end > e.start:
            known.setdefault(e.kind, []).append((e.end - e.start).total_seconds() / 60)
    rows = []
    for e in evs:
        end = e.end
        if end is None or end <= e.start:
            if known_only:
                continue
            minutes = float(np.median(known[e.kind])) if e.kind in known else NOMINAL_MIN
            end = e.start + timedelta(minutes=minutes)
        rows.append({"event": e.id, "kind": e.kind, "all_camp": "all_camp" in e.tags,
                     "locations": [f"location:{loc}" for loc in e.locations],
                     "start": e.start, "end": end})  # fmt: skip
    return pl.DataFrame(rows).with_columns(
        pl.col("start").dt.convert_time_zone("UTC"), pl.col("end").dt.convert_time_zone("UTC")
    )


def event_bins(windows: pl.DataFrame, placed: pl.DataFrame) -> pl.DataFrame:
    """(entity, bin, kind) for each exposure bin inside an event that applies to the person."""
    w = windows.with_columns(
        pl.datetime_ranges(pl.col("start").dt.truncate(cp.BIN), pl.col("end"), interval=cp.BIN,
                           closed="left").alias("bin")
    ).explode("bin", empty_as_null=True)  # fmt: skip
    allc = w.filter(pl.col("all_camp")).select("bin", "kind", "event")
    loc = (
        w.filter(~pl.col("all_camp"))
        .explode("locations", empty_as_null=True)
        .select("bin", "kind", "event", pl.col("locations").alias("location"))
    )
    a = placed.join(allc, on="bin")
    b = placed.join(loc, on=["bin", "location"])
    cols = ["entity", "bin", "kind"]
    return pl.concat([a.select(cols), b.select(cols)]).unique()


def settings(placed: pl.DataFrame, plenum_bins: pl.DataFrame) -> pl.DataFrame:
    p = placed.join(plenum_bins.with_columns(pl.lit(True).alias("plen")), on="bin", how="left")
    phase = pl.col("phase")
    return p.with_columns(
        pl.when(pl.col("plen").fill_null(False))
        .then(pl.lit("plenum"))
        .when(phase.is_in(["morning", "afternoon"]) & (pl.col("zone") == "courses"))
        .then(pl.lit("course block"))
        .when(phase.is_in(["midday", "dinner"]))
        .then(pl.lit("meal time"))
        .when(phase == "evening")
        .then(pl.lit("KüA evening"))
        .when(phase == "late")
        .then(pl.lit("late evening"))
        .when(phase == "night")
        .then(pl.lit("night"))
        .otherwise(pl.lit("other daytime"))
        .alias("setting")
    ).drop("plen")


RATIOS = {
    "informal / formal": (INFORMAL, FORMAL),
    "KüA evening / course block": (["KüA evening"], ["course block"]),
    "late evening / course block": (["late evening"], ["course block"]),
    "plenum / course block": (["plenum"], ["course block"]),
    "meal time / course block": (["meal time"], ["course block"]),
}


def ratios(r, label: str) -> pl.DataFrame:
    rows = []
    for name, (num, den) in RATIOS.items():
        i = r.ratio(num, den)
        rows.append({"days": label, "ratio": name, "estimate": i.estimate, "lo": i.lo,
                     "hi": i.hi})  # fmt: skip
    return pl.DataFrame(rows)


def placed_settings(exposure: pl.DataFrame, spine: Spine) -> pl.DataFrame:
    """Exposure bins with ``location``, ``zone`` (``unplaced`` when none) and ``setting``."""
    zone = {loc.ref: loc.zone for loc in spine.locations}
    rooms = cp.load_all("rooms").select("entity", "bin", "location")
    placed = exposure.join(rooms, on=["entity", "bin"], how="left").with_columns(
        pl.col("location").replace_strict(zone, default=None).fill_null("unplaced").alias("zone")
    )
    windows = event_windows(spine, known_only=False)
    plen = windows.filter(pl.col("kind") == "plenum").with_columns(
        pl.datetime_ranges(pl.col("start").dt.truncate(cp.BIN), pl.col("end"), interval=cp.BIN,
                           closed="left").alias("bin")
    ).explode("bin", empty_as_null=True).select("bin").unique()  # fmt: skip
    return settings(placed, plen)


def places(data: dict, spine: Spine) -> dict:
    placed = placed_settings(data["exposure"], spine)
    presses = data["presses"].join(placed.select("entity", "bin", "zone", "setting"),
                                   on=["entity", "bin"])  # fmt: skip
    out = {}
    for cat in ("zone", "setting"):
        r = person_rates(presses, placed, category=cat, bin_hours=BIN_S / 3600, n_boot=N_BOOT,
                         seed=SEED)  # fmt: skip
        out[cat] = r.table(min_people=MIN_GROUP, per=10)
        if cat == "setting":
            out["formal_vs_informal"] = r.ratio(INFORMAL, FORMAL)
            out["ratios"] = ratios(r, "all days")
    settled = pl.lit(SETTLED_FROM).str.to_date()
    r = person_rates(presses.filter(pl.col("day") >= settled),
                     placed.filter(pl.col("day") >= settled), category="setting",
                     bin_hours=BIN_S / 3600, n_boot=N_BOOT, seed=SEED)  # fmt: skip
    out["setting_settled"] = r.table(min_people=MIN_GROUP, per=10)
    out["ratios"] = pl.concat([out["ratios"], ratios(r, f"from {SETTLED_FROM}")])
    for known_only in (False, True):
        w = event_windows(spine, known_only=known_only)
        eb = event_bins(w, placed.select("entity", "bin", "location"))
        pe = data["presses"].join(eb, on=["entity", "bin"])
        r = person_rates(pe, eb, category="kind", bin_hours=BIN_S / 3600, n_boot=N_BOOT,
                         seed=SEED)  # fmt: skip
        out["kind_known_only" if known_only else "kind"] = r.table(min_people=MIN_GROUP, per=10)
    out["placed_share"] = float((placed["zone"] != "unplaced").mean())
    return out


# --- main ----------------------------------------------------------------------------------------


def main() -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    layout = paths.study(cp.STUDY)
    spine = Spine.load(layout.spine)
    out = layout.derived / "analyses" / SLUG
    out.mkdir(parents=True, exist_ok=True)
    data = load(layout, spine)
    qa = data["qa"]
    plt.rcParams.update({"font.size": 10, "axes.spines.top": False, "axes.spines.right": False})

    # 3. Moved moments in company.
    company, clog, diffs = moved_in_company(data)
    company.write_csv(out / "company_within_person.csv")
    clog.write_csv(out / "company_clogit.csv")
    fig, ax = plt.subplots(figsize=(7, 4))
    ax.hist(diffs.to_numpy(), bins=20, color=BLUE, alpha=0.85)
    ax.axvline(0, color=GRAY, lw=1)
    main_row = company.filter((pl.col("variant") == f"{CLOSE_RSSI} dBm")
                              & (pl.col("matched") == "day x phase")
                              & (pl.col("value") == "close")).row(0, named=True)  # fmt: skip
    ax.axvline(main_row["mean_diff"], color=ORANGE, lw=1.5,
               label=f"mean {main_row['mean_diff']:.2f} "
                     f"(95% CI {main_row['lo']:.2f} to {main_row['hi']:.2f})")  # fmt: skip
    ax.set_xlabel("close participants at own presses minus own other moments, same day and phase")
    ax.set_ylabel("participants")
    ax.legend(frameon=False)
    ax.set_title("Exploratory: company at presses, each participant against themselves",
                 loc="left", fontsize=10)  # fmt: skip
    fig.tight_layout()
    fig.savefig(out / "fig_company_within_person.png", dpi=160)
    plt.close(fig)

    # 4. Collective moments.
    casc, cinfo = cascades(data)
    casc.write_csv(out / "cascades.csv")
    qa["cascades_colocated_5min"] = cinfo["colocated_5min"]
    fig, axes = plt.subplots(1, 2, figsize=(11, 4))
    for ax, name in zip(axes, ("person-day", "person-day-phase"), strict=True):
        null = cinfo["nulls"][name][300][0]
        ax.hist(null, bins=range(0, int(max(max(null), cinfo["observed"][300][0])) + 3),
                color=GRAY, alpha=0.8, label="shuffled presses")  # fmt: skip
        ax.axvline(cinfo["observed"][300][0], color=ORANGE, lw=2, label="observed")
        ax.set_title(f"Co-located press pairs within 5 min; null within {name}", loc="left",
                     fontsize=10)  # fmt: skip
        ax.set_xlabel("pairs of presses")
        ax.legend(frameon=False)
    fig.suptitle("Exploratory: collective moments", fontsize=10, x=0.01, ha="left")
    fig.tight_layout()
    fig.savefig(out / "fig_cascades_null.png", dpi=160)
    plt.close(fig)

    # 5. Places and programme items.
    pl_out = places(data, spine)
    for k in ("zone", "setting", "setting_settled", "kind", "kind_known_only", "ratios"):
        pl_out[k].write_csv(out / f"places_{k}.csv")
    fi = pl_out["formal_vs_informal"]
    qa["formal_vs_informal_rate_ratio"] = {"informal_over_formal": fi.estimate, "lo": fi.lo,
                                           "hi": fi.hi}  # fmt: skip
    qa["placed_share_of_exposure"] = pl_out["placed_share"]
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.2))
    st = pl_out["setting"].filter(~pl.col("suppressed"))
    st = st.sort(pl.col("category").replace_strict({s: i for i, s in enumerate(SETTING_ORDER)}))
    zt = pl_out["zone"].filter(~pl.col("suppressed")).sort("rate", descending=True)
    for ax, t, title in ((axes[0], st, "by setting"),
                         (axes[1], zt, "by zone (room tag heard most)")):  # fmt: skip
        x = np.arange(t.height)
        r = t["rate"].to_numpy()
        colors = [ORANGE if c in INFORMAL else BLUE if c in FORMAL else GRAY
                  for c in t["category"]]  # fmt: skip
        ax.bar(x, r, color=colors, width=0.65)
        ax.errorbar(x, r, yerr=[r - t["lo"].to_numpy(), t["hi"].to_numpy() - r], fmt="none",
                    ecolor="black", capsize=2, lw=0.8)  # fmt: skip
        ax.set_xticks(x, t["category"].to_list(), rotation=35, ha="right")
        ax.set_ylabel("presses per 10 exposure hours")
        ax.set_title(title, loc="left", fontsize=10)
    fig.suptitle(f"Exploratory: where presses happen (informal/formal rate ratio "
                 f"{fi.estimate:.2f}, 95% CI {fi.lo:.2f} to {fi.hi:.2f})", fontsize=10, x=0.01,
                 ha="left")  # fmt: skip
    fig.tight_layout()
    fig.savefig(out / "fig_places_settings.png", dpi=160)
    plt.close(fig)

    qa["settings"] = {"min_group": MIN_GROUP, "close_rssi": CLOSE_RSSI, "windows_s": WINDOWS,
                      "n_shuffle": N_SHUFFLE, "n_boot": N_BOOT, "seed": SEED,
                      "nominal_min": NOMINAL_MIN}  # fmt: skip
    (out / "qa_presses.json").write_text(json.dumps(qa, indent=2, default=str), encoding="utf-8")
    with pl.Config(tbl_rows=200, tbl_cols=20, fmt_str_lengths=40, tbl_width_chars=200):
        print(json.dumps(qa, indent=2, default=str))
        print(company)
        print(clog)
        print(casc)
        for k in ("zone", "setting", "setting_settled", "kind", "kind_known_only", "ratios"):
            print(k, pl_out[k])


if __name__ == "__main__":
    main()
