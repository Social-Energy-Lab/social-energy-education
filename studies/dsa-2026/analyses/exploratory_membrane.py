"""Exploratory tier, the interview membrane codes against the survey and the sensors.

``docs/plans/ongoing/interview-membrane.md``, section "Exploratory analyses, fixed before coding".
**Every result here is exploratory**: no error control, two-sided, effect sizes with 95% intervals
and no p-values, distributions rather than people. The codes come from
``studies/dsa-2026/research/membrane-codebook.md`` (a draft the research team has not agreed), so
the construct is `[inferred]` throughout.

Inputs: the coders' JSON files under ``derived/interview-membrane/{codes,codes-second}/`` (one per
interview, named by the recording key), linked to people through the spine's ``interview:<key>``
assignments. Unit: participants with ``interview_in_person`` consent and a coded interview; staff
are left out. Each analysis then needs its own other module (``survey``; ``beacons`` and
``self_report``), as the confirmatory and exploratory scripts it reuses already apply.

0. **Agreement** between the first coder and the independent second coder on the shared sample:
   quadratic-weighted kappa on the three state codes, exact agreement on the categorical ones.
1. **Convergence:** ``M_everyday`` against the trust and lust composites (Spearman).
2. **Opening and behaviour:** the change over the academy, three ways (``D_academy``,
   ``D_academy_lenient`` and ``change_signed``; codebook, "Variants under comparison") against
   presses per exposure hour and co-located press pairs per exposure hour (NB2, exposure offset),
   network strength and cross-course share (OLS, HC3); interview day as covariate. Beside it,
   Spearman.
   *Added after coding (logged in the plan):* ``opened`` (the coded ``direction`` is "opened") as a
   second predictor, because the codebook's 4-versus-5 rule leaves ``D_academy`` at 0 for several
   people who describe opening.
3. **The academy against everyday life:** ``D_vs_everyday = M_now - M_everyday`` against the mean
   z-score of the survey's gradient items (our pooling `[inferred]`).
4. **Placed episodes:** for opening and closing episodes placed on a date, the person's presses per
   exposure hour and close participants per exposure bin that camp day, against their own other
   days (log rate ratio and difference, bootstrapped over people).
5. **Descriptives:** the state codes, ``direction``, ``selective``, opener and closer categories.

Sensitivities: without ``led`` state codes; without ``low``-confidence state codes; without
interviews held on 24-27 Aug (analyses 2 and 4).

Any cell, model or category with fewer than ``MIN_GROUP`` people is withheld. Run after
``confirmatory.py``, ``outcomes.py`` and ``copresence_by_phase.py build``:

    uv run --extra analysis python studies/dsa-2026/analyses/exploratory_membrane.py

Writes CSVs and ``qa.json`` to
``$SOCIAL_ENERGY_DATA/dsa-2026/derived/analyses/exploratory-membrane/``.
"""

from __future__ import annotations

import json
import math
import sys
from collections import Counter
from datetime import date
from pathlib import Path

import numpy as np
import polars as pl

sys.path.insert(0, str(Path(__file__).parent))
import confirmatory as conf
import exploratory_presses as xp
import exploratory_survey as xs

from social_energy import paths
from social_energy.confirmatory import design, negbin, ols_hc3
from social_energy.exploratory import bootstrap_mean, co_event_pairs
from social_energy.spine import Spine
from social_energy.stats import correlation, weighted_kappa

SLUG = "exploratory-membrane"
MIN_GROUP = 5
LEVELS = [1, 2, 3, 4, 5]
STATES = ["M_everyday", "M_arrival", "M_now"]
#: The change over the academy, measured three ways (codebook, "Variants under comparison").
CHANGES = ["D_academy", "D_academy_lenient", "change_signed", "opened"]
SIGN = {"opened": 1.0, "closed": -1.0, "stable": 0.0}
LOW_COVERAGE = (date(2026, 8, 24), date(2026, 8, 27))
WINDOW_S = 300
N_BOOT = 4000
SEED = 20261021
VARIANTS = ("main", "no_led", "no_low_confidence", "no_24_27_aug")


# --- codes ----------------------------------------------------------------------------------------


def read_codes(folder: Path) -> dict[str, dict]:
    return {f.stem: json.loads(f.read_text()) for f in sorted(folder.glob("*.json"))}


def state(code: dict, name: str, variant: str) -> float | None:
    s = code[name]
    v = s["value"]
    if not isinstance(v, int):
        return None
    if variant == "no_led" and s.get("led"):
        return None
    if variant == "no_low_confidence" and s.get("confidence") == "low":
        return None
    return float(v)


def code_frame(codes: dict[str, dict], people: dict[str, str], variant: str) -> pl.DataFrame:
    rows = []
    for key, c in codes.items():
        if key not in people:
            continue
        day = date(int(key[:4]), int(key[4:6]), int(key[6:8]))
        if variant == "no_24_27_aug" and LOW_COVERAGE[0] <= day <= LOW_COVERAGE[1]:
            continue
        r = {"entity": people[key], "key": key, "interview_day": float(day.day)}
        r |= {s: state(c, s, variant) for s in STATES}
        r["M_now_lenient"] = state(c, "M_now_lenient", variant) if "M_now_lenient" in c else None
        amount = state(c, "change_amount", variant) if "change_amount" in c else None
        r["direction"] = c["direction"]["value"]
        sign = SIGN.get(r["direction"])
        r["change_amount"] = amount
        r["change_signed"] = None if amount is None or sign is None else sign * amount
        r["opened"] = None if r["direction"] == "na" else float(r["direction"] == "opened")
        r["selective"] = bool(c["selective"]["value"])
        r["primed"] = bool(c.get("primed"))
        rows.append(r)
    f = pl.DataFrame(rows, infer_schema_length=None)
    return f.with_columns(
        (pl.col("M_now") - pl.col("M_arrival")).alias("D_academy"),
        (pl.col("M_now") - pl.col("M_everyday")).alias("D_vs_everyday"),
        (pl.col("M_now_lenient") - pl.col("M_arrival")).alias("D_academy_lenient"),
        (pl.col("M_now_lenient") - pl.col("M_everyday")).alias("D_vs_everyday_lenient"),
    )


def agreement(first: dict[str, dict], second: dict[str, dict]) -> pl.DataFrame:
    shared = sorted(set(first) & set(second))
    rows = []
    scales = [(s, LEVELS) for s in [*STATES, "M_now_lenient"]] + [("change_amount", [0, 1, 2, 3])]
    for s, levels in scales:
        a = [first[k].get(s, {}).get("value") for k in shared]
        b = [second[k].get(s, {}).get("value") for k in shared]
        k = weighted_kappa(a, b, levels=levels)
        both_na = sum(x == "na" and y == "na" for x, y in zip(a, b, strict=True))
        rows.append({"code": s, "items": len(shared), "n_rated_by_both": k.n, "kappa_w": k.kappa,
                     "exact": k.exact, "within_one": k.within_one, "both_na": both_na})  # fmt: skip
    for field in ("direction", "selective", "primed", "known_elsewhere"):

        def get(c: dict, field: str = field):
            v = c.get(field)
            return v["value"] if isinstance(v, dict) else v

        same = [get(first[k]) == get(second[k]) for k in shared]
        rows.append({"code": field, "items": len(shared), "n_rated_by_both": len(shared),
                     "exact": sum(same) / len(shared) if shared else None})  # fmt: skip
    return pl.DataFrame(rows, infer_schema_length=None)


# --- per-person behaviour -------------------------------------------------------------------------


def shared_moments(data: dict) -> pl.DataFrame:
    """Per presser: co-located press pairs within ``WINDOW_S`` they are part of, and exposure."""
    p = data["presses"].with_columns(xp.epoch("t").alias("ts"))
    ends = data["ends"].filter(pl.col("max_rssi") >= xp.CLOSE_RSSI)
    close = {(e, int(b.timestamp()), o) for e, b, o in ends.select("entity", "bin", "other")
             .iter_rows()}  # fmt: skip
    ent = p["entity"].to_list()
    pairs = co_event_pairs(ent, p["ts"].to_numpy(), close, window=WINDOW_S, bin_size=xp.BIN_S)
    count = Counter()
    for a, b in zip(pairs.first[pairs.close], pairs.second[pairs.close], strict=True):
        count[ent[a]] += 1
        count[ent[b]] += 1
    hours = (
        data["exposure"]
        .group_by("entity")
        .len()
        .with_columns((pl.col("len") * xp.BIN_S / 3600).alias("exposure_hours_sm"))
    )
    return hours.select(
        "entity",
        "exposure_hours_sm",
        pl.col("entity").replace_strict(dict(count), default=0).alias("shared_pairs"),
    )


def gradient_scores(layout: paths.StudyLayout, unit: pl.DataFrame) -> pl.DataFrame:
    scores = pl.read_parquet(layout.derived / "survey" / "scoring" / "scores.parquet")
    g = scores.filter((pl.col("kind") == "gradient") & ~pl.col("duplicate_submission"))
    g = g.join(unit.select("entity", "respondent"), on="respondent").drop_nulls("mean")
    g = g.with_columns(
        ((pl.col("mean") - pl.col("mean").mean().over("group"))
         / pl.col("mean").std().over("group")).alias("z")
    )  # fmt: skip
    return g.group_by("entity").agg(pl.col("z").mean().alias("gradient"), pl.len().alias("n_grad"))


# --- models ---------------------------------------------------------------------------------------


def spearman(f: pl.DataFrame, x: str, y: str) -> dict:
    c = correlation(f[x].to_list(), f[y].to_list(), method="spearman")
    return {"n": c.n, "rho": c.r, "rho_lo": c.lo, "rho_hi": c.hi}


def model(f: pl.DataFrame, outcome: str, predictor: str, kind: str, exposure: str | None) -> dict:
    d = design(f, outcome=outcome, predictor=predictor, covariates=["interview_day"],
               exposure=exposure)  # fmt: skip
    n = d.X.shape[0]
    if n < MIN_GROUP * 3 or np.ptp(d.X[:, 1]) == 0:
        return {"n_model": n}
    try:
        fit = negbin(d) if kind == "negbin" else ols_hc3(d)
    except (ValueError, np.linalg.LinAlgError):
        return {"n_model": n}
    if kind == "negbin":
        return {"n_model": n, "rr_per_sd": fit.std_estimate, "rr_lo": fit.std_lo,
                "rr_hi": fit.std_hi, "converged": fit.converged}  # fmt: skip
    return {"n_model": n, "std": fit.std_estimate, "std_lo": fit.std_lo, "std_hi": fit.std_hi}


BEHAVIOUR = [
    ("presses_per_hour", "press_episodes", "negbin", "exposure_hours"),
    ("shared_moments_per_hour", "shared_pairs", "negbin", "exposure_hours_sm"),
    ("strength_min_per_day", "strength_min_per_day", "ols", None),
    ("cross_share", "cross_share", "ols", None),
]


def behaviour(f: pl.DataFrame, variant: str) -> list[dict]:
    rows = []
    for label, outcome, kind, exposure in BEHAVIOUR:
        g = f
        if exposure is not None:
            rate = pl.col(outcome) / pl.col(exposure)
            g = f.filter(pl.col(exposure) > 0).with_columns(rate.alias(label))
        for pred in CHANGES:
            r = {"variant": variant, "outcome": label, "predictor": pred,
                 **spearman(g, pred, label), **model(g, outcome, pred, kind, exposure)}  # fmt: skip
            if r["n"] < MIN_GROUP * 3:
                r = {k: v for k, v in r.items() if k in ("variant", "outcome", "predictor", "n")}
            rows.append(r)
    return rows


# --- placed episodes ------------------------------------------------------------------------------


def episode_days(codes: dict[str, dict], people: dict[str, str]) -> pl.DataFrame:
    rows = []
    for key, c in codes.items():
        if key not in people:
            continue
        for e in c.get("episodes", []):
            when = e.get("when") or ""
            try:
                d = date.fromisoformat(when[:10])
            except ValueError:
                continue
            rows.append({"entity": people[key], "day": d, "direction": e["direction"],
                         "key": key})  # fmt: skip
    if not rows:
        return pl.DataFrame(schema={"entity": pl.String, "day": pl.Date, "direction": pl.String,
                                    "key": pl.String})  # fmt: skip
    return pl.DataFrame(rows).unique(["entity", "day", "direction"])


def episodes(data: dict, placed: pl.DataFrame, variant: str) -> list[dict]:
    if variant == "no_24_27_aug":
        placed = placed.filter(~pl.col("day").is_between(*LOW_COVERAGE))
    ex = data["exposure"].select("entity", "bin", pl.col("day").cast(pl.Date))
    presses = data["presses"].select("entity", "bin").group_by("entity", "bin").len("presses")
    close = (
        data["ends"].filter(pl.col("max_rssi") >= xp.CLOSE_RSSI).group_by("entity", "bin")
        .len("close_others")
    )  # fmt: skip
    bins = (
        ex.join(presses, on=["entity", "bin"], how="left")
        .join(close, on=["entity", "bin"], how="left")
        .fill_null(0)
    )
    per_day = bins.group_by("entity", "day").agg(
        pl.len().alias("bins"), pl.col("presses").sum(), pl.col("close_others").mean()
    )
    rows = []
    for direction in ("open", "close"):
        ep = placed.filter(pl.col("direction") == direction)
        lr, dc = [], []
        for ent, day in ep.select("entity", "day").iter_rows():
            mine = per_day.filter(pl.col("entity") == ent)
            on, off = mine.filter(pl.col("day") == day), mine.filter(pl.col("day") != day)
            if on.is_empty() or off.is_empty():
                continue
            h_on, h_off = on["bins"].sum() / 12, off["bins"].sum() / 12
            lr.append(math.log((on["presses"].sum() + 0.5) / h_on)
                      - math.log((off["presses"].sum() + 0.5) / h_off))  # fmt: skip
            dc.append(float(on["close_others"].mean() - off["close_others"].mean()))
        people = ep.join(per_day.select("entity").unique(), on="entity")["entity"].n_unique()
        r = {"variant": variant, "direction": direction, "episodes": len(lr), "people": people}
        if people >= MIN_GROUP:
            a = bootstrap_mean(lr, n_boot=N_BOOT, seed=SEED)
            b = bootstrap_mean(dc, n_boot=N_BOOT, seed=SEED)
            r |= {"press_rate_ratio": math.exp(a.estimate), "prr_lo": math.exp(a.lo),
                  "prr_hi": math.exp(a.hi), "close_others_diff": b.estimate,
                  "cod_lo": b.lo, "cod_hi": b.hi}  # fmt: skip
        rows.append(r)
    return rows


# --- descriptives ---------------------------------------------------------------------------------


def descriptives(f: pl.DataFrame, codes: dict[str, dict], people: dict[str, str]) -> pl.DataFrame:
    rows = []

    def add(group: str, level: str, n: int, total: int) -> None:
        rows.append({"group": group, "level": level, "n": n if n >= MIN_GROUP else None,
                     "share": n / total if n >= MIN_GROUP and total else None,
                     "withheld": n < MIN_GROUP})  # fmt: skip

    total = f.height
    cols = [*STATES, "M_now_lenient", "change_amount", "D_academy", "D_academy_lenient",
            "change_signed", "D_vs_everyday", "direction", "selective", "primed"]  # fmt: skip
    for col in cols:
        for level, n in Counter(str(v) for v in f[col].to_list()).items():
            add(col, level, n, total)
    for side in ("openers", "closers"):
        per_person = Counter()
        for key, c in codes.items():
            if key in people and people[key] in set(f["entity"]):
                for cat in {o["category"].split(":")[0] for o in c.get(side, [])}:
                    per_person[cat] += 1
        for cat, n in per_person.items():
            add(side, cat, n, total)
    return pl.DataFrame(rows).sort("group", "level")


# --- main -----------------------------------------------------------------------------------------


def main() -> None:
    layout = paths.study(conf.STUDY)
    spine = Spine.load(layout.spine)
    out = layout.derived / "analyses" / SLUG
    out.mkdir(parents=True, exist_ok=True)
    root = layout.derived / "interview-membrane"
    first, second = read_codes(root / "codes"), read_codes(root / "codes-second")

    participants = {p.ref for p in spine.people if p.role == "participant"}
    consented = {f"person:{p}" for p in spine.consented("interview_in_person")}
    accounts = spine.account_entities("interview")
    people = {k: e for k, e in accounts.select("account", "entity").iter_rows()
              if e in participants and e in consented}  # fmt: skip
    qa: dict = {"coded": len(first), "second_coded": len(second),
                "linked_participants_consented": len(set(first) & set(people)),
                "dropped_staff_or_no_consent": len(set(first) - set(people))}  # fmt: skip

    agreement(first, second).write_csv(out / "agreement.csv")

    unit, _ = xs.unit_frame(layout, spine)
    outcomes = pl.read_parquet(layout.derived / "analyses" / "outcomes" / "outcomes.parquet")
    outcomes = outcomes.filter(pl.col("variant") == "main")
    data = xp.load(layout, spine)
    sm = shared_moments(data)
    grad = gradient_scores(layout, unit)
    placed = episode_days(first, people)

    conv, beh, gr, eps = [], [], [], []
    for v in VARIANTS:
        f = code_frame(first, people, v)
        if v == "main":
            descriptives(f, first, people).write_csv(out / "descriptives.csv")
            qa["main_people"] = f.height
        s = f.join(unit.select("entity", "trust", "lust"), on="entity")
        for comp in ("trust", "lust"):
            conv.append({"variant": v, "composite": comp, **spearman(s, "M_everyday", comp)})
        b = (
            f.join(outcomes.select("entity", "press_episodes", "exposure_hours",
                                   "strength_min_per_day", "cross_share"), on="entity")
            .join(sm, on="entity", how="left")
        )  # fmt: skip
        beh += behaviour(b, v)
        g = f.join(grad, on="entity")
        for x in ("D_vs_everyday", "D_vs_everyday_lenient"):
            gr.append({"variant": v, "measure": x, **spearman(g, x, "gradient")})
        if v in ("main", "no_24_27_aug"):
            eps += episodes(data, placed, v)

    def guard(rows: list[dict]) -> pl.DataFrame:
        t = pl.DataFrame(rows, infer_schema_length=None)
        if "n" in t.columns:
            keep = [c for c in t.columns if c in ("variant", "composite", "measure", "n")]
            t = t.with_columns(
                [
                    pl.when(pl.col("n") < MIN_GROUP).then(None).otherwise(pl.col(c)).alias(c)
                    for c in t.columns
                    if c not in keep
                ]
            )
        return t

    guard(conv).write_csv(out / "convergence.csv")
    pl.DataFrame(beh, infer_schema_length=None).write_csv(out / "behaviour.csv")
    guard(gr).write_csv(out / "gradient.csv")
    pl.DataFrame(eps, infer_schema_length=None).write_csv(out / "episodes.csv")
    qa["placed_episodes"] = placed.height
    qa["settings"] = {"min_group": MIN_GROUP, "window_s": WINDOW_S, "close_rssi": xp.CLOSE_RSSI,
                      "low_coverage": [str(d) for d in LOW_COVERAGE], "seed": SEED}  # fmt: skip
    (out / "qa.json").write_text(json.dumps(qa, indent=2), encoding="utf-8")
    print(json.dumps(qa, indent=2))


if __name__ == "__main__":
    main()
