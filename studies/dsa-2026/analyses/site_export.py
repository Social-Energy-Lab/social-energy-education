"""Export DSA 2026 to the public site's data asset (``social_energy.site``), locally.

Research question: none of its own. The asset feeds the public site: a coarse, course-free copy of
the explorer bundle for the hero, and camp-level aggregates for the story chapters, read from the
outputs the analyses already wrote. Nothing is recomputed here and no result is written in code.

Inputs and filters:

- Bundle: exactly as ``explorer_export.py``. Pairs, tags heard per 5-minute bin from
  ``copresence_by_phase.py build`` (which must have run); press episodes from
  ``self_report_context.press_episodes`` (``self_report`` consent); nodes are participants with
  ``beacons`` consent, never staff. ``write_public_bundle`` then keeps close pairs only
  (``cp.CLOSE_RSSI``), hides the night, shuffles nodes and courses and drops rooms and RSSI.
  Special days are the excursion and rotation days from ``study.yaml`` ``explorer.notes``; the
  shaded days are ``explorer.shade``, relabelled by the bundle writer.
- Aggregates, from ``derived/analyses/`` (the main variant of each analysis only, never a
  sensitivity variant), one section per chapter as in ``social_energy.site.aggregates``:
  ``day_phase`` (``copresence-by-phase/day_phase.csv``, daytime phases), ``daily_mixing``
  (``exploratory/rhythm_daily_mixing.csv``, arrival day left out as in the rhythm figure),
  ``persistence`` (``exploratory/rhythm_persistence_rates.csv``, tied again within three days;
  people from ``rhythm_new_ties.parquet``), ``moments_*`` (``exploratory/cascades/``: the main
  null within person x day x phase), ``places`` (``exploratory/places_setting.csv``) and
  ``confirmatory`` (``confirmatory/results.csv``, standardised effects and rate ratios). Shares
  become percentages; categories become the copy's keys, and a row without a key is dropped and
  printed. ``check_aggregates`` then drops every row under ``min_group`` people.

Output, outside the repository: ``$SOCIAL_ENERGY_DATA/dsa-2026/derived/site/data/`` and
``site-data.zip`` beside it, files at the zip's root. ``validate_site_data`` must accept it. It
is camp-level, but it is still derived from data about minors: published only when the research
lead says so.

    uv run --extra analysis python studies/dsa-2026/analyses/site_export.py
    uv run social-energy site-build studies/dsa-2026/study.yaml --data <data dir> --out <dir>
"""

from __future__ import annotations

import json
import re
import shutil
import sys
import zipfile
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import polars as pl

sys.path.insert(0, str(Path(__file__).parent))
import copresence_by_phase as cp
import self_report_context as sr

from social_energy import paths
from social_energy.explorer import BundleInput
from social_energy.site.aggregates import AGGREGATE_SECTIONS, NUMBERS, check_aggregates
from social_energy.site.public import write_public_bundle
from social_energy.site.validate import validate_site_data
from social_energy.spine import Spine
from social_energy.study import StudyConfig

BIN_SECONDS = 300
MAX_ZIP_BYTES = 3 * 1024 * 1024
#: Which ``explorer.notes`` entries are special days on the site, by the copy key they get.
SPECIAL_DAYS = ("excursion", "rotation")
#: The arrival day is a partial day: the rhythm figure leaves it out of the mixing series.
ARRIVAL = date(2026, 8, 13)
#: The site shows no night (``privacy_night``), so the day chapter draws daytime phases only.
HIDDEN_PHASES = {"night"}
#: The bundle's label for ``explorer.shade``; the copy knows it as ``label_records_missing``.
SHADE_LABEL = "records missing"
#: The setting names of ``places_setting.csv`` -> the copy's ``setting_<key>``.
SETTINGS = {
    "plenum": "plenum",
    "course block": "course_block",
    "meal time": "meal_time",
    "KüA evening": "kua_evening",
    "late evening": "late_evening",
    "other daytime": "other_daytime",
    "night": "night",
}
#: ``confirmatory/results.csv`` tests -> the copy's ``test_<key>`` and the forest plot's scale.
TESTS = {"C1": ("c1", "sd"), "C2": ("c2", "sd"), "C4_trust": ("c4_trust", "rr"),
         "C4_lust": ("c4_lust", "rr")}  # fmt: skip
#: The cascades' headline: co-located presses at most 5 min apart, main null.
HEADLINE = "co-located pairs <= 5 min"


def _r(v: float | None, digits: int = 4) -> float | None:
    return None if v is None else round(float(v), digits)


def _pct(v: float | None) -> float | None:
    return None if v is None else round(100 * float(v), 2)


def _seconds_band(label: str) -> str | None:
    """'0-10 s' -> '0-10', '1-2 min' -> '60-120'; None when the label is not a band."""
    m = re.fullmatch(r"(\d+)-(\d+) (s|min)", label.strip())
    if not m:
        return None
    k = 60 if m[3] == "min" else 1
    return f"{int(m[1]) * k}-{int(m[2]) * k}"


def special_days(ex, tz: ZoneInfo, t0: datetime) -> list[dict]:
    """The excursion and rotation days of ``explorer.notes`` as bin ranges, labelled by copy key."""
    out = []
    for note in ex.notes:
        label = next((k for k in SPECIAL_DAYS if note["text"].startswith(k)), None)
        if label is None:
            continue
        bins = [
            int((datetime.fromisoformat(note[end]).replace(tzinfo=tz) - t0).total_seconds())
            // BIN_SECONDS
            for end in ("start", "end")
        ]
        out.append({"start_bin": bins[0], "end_bin": bins[1], "label": label})
    return out


def aggregates(analyses: Path, days: set[str], dropped: list[str]) -> dict:
    """Map the analyses' outputs onto the site's sections; ``dropped`` collects rows left out."""
    agg: dict = {}

    dp = pl.read_csv(analyses / "copresence-by-phase" / "day_phase.csv")
    agg["day_phase"] = []
    for r in dp.iter_rows(named=True):
        if r["phase"] in HIDDEN_PHASES or r["day"] not in days:
            dropped.append(f"day_phase {r['day']} {r['phase']}: night or outside the bundle")
            continue
        agg["day_phase"].append(
            {"day": r["day"], "phase": r["phase"], "people": r["people"],
             "others": _r(r["others"]), "share_no_one": _pct(r["share_no_one"])}
        )  # fmt: skip

    mix = pl.read_csv(analyses / "exploratory" / "rhythm_daily_mixing.csv").filter(
        pl.col("variant") == "main"
    )
    agg["daily_mixing"] = []
    for r in mix.sort("day").iter_rows(named=True):
        if r["day"] == ARRIVAL.isoformat() or r["day"] not in days:
            dropped.append(f"daily_mixing {r['day']}: arrival day or outside the bundle")
            continue
        agg["daily_mixing"].append(
            {"day": r["day"], "kind": r["kind"], "people": r["people"],
             "cross_share": _pct(r["cross_share"]), "expected": _pct(r["expected"])}
        )  # fmt: skip

    rates = pl.read_csv(analyses / "exploratory" / "rhythm_persistence_rates.csv").filter(
        (pl.col("variant") == "main")
        & (pl.col("follow_up") == "all")
        & (pl.col("origin") == "all")
        & (pl.col("outcome") == "again_3")
    )
    ties = pl.read_parquet(analyses / "exploratory" / "rhythm_new_ties.parquet")
    agg["persistence"] = []
    for r in rates.iter_rows(named=True):
        if r["kind"] not in ("ordinary", *SPECIAL_DAYS):
            dropped.append(f"persistence {r['kind']}: no origin_ copy key")
            continue
        sub = ties.filter(pl.col("has_3") & (pl.col("kind") == r["kind"]))
        if sub.height != r["new_ties"]:
            raise SystemExit(f"persistence {r['kind']}: new_ties table and rates disagree")
        people = len(set(sub["a"]) | set(sub["b"]))
        agg["persistence"].append(
            {"origin": r["kind"], "people": people, "new_ties": r["new_ties"],
             "share": _pct(r["share"]), "lo": _pct(r["lo"]), "hi": _pct(r["hi"])}
        )  # fmt: skip

    casc = analyses / "exploratory" / "cascades"
    agg["moments_latency"] = []
    for r in pl.read_csv(casc / "latency.csv").iter_rows(named=True):
        band = _seconds_band(r["category"])
        if band is None:
            dropped.append(f"moments_latency {r['category']}: not a band")
            continue
        agg["moments_latency"].append(
            {"band": band, "people": r["people"], "ratio": _r(r["ratio"]),
             "ratio_lo": _r(r["ratio_lo"]), "ratio_hi": _r(r["ratio_hi"]),
             "suppressed": r["suppressed"]}
        )  # fmt: skip
    agg["moments_size"] = []
    for r in pl.read_csv(casc / "group_size.csv").iter_rows(named=True):
        if not re.match(r"\d", str(r["category"])):
            dropped.append(f"moments_size {r['category']}: not a group size")
            continue
        if r["people"] is None:
            dropped.append(f"moments_size {r['category']}: the table states no people")
        agg["moments_size"].append(
            {"size": str(r["category"]), "people": r["people"], "ratio": _r(r["ratio"]),
             "ratio_lo": _r(r["ratio_lo"]), "ratio_hi": _r(r["ratio_hi"]),
             "suppressed": r["suppressed"]}
        )  # fmt: skip

    # The headline: robustness.csv's main row carries the day-bootstrap interval; cascades.csv
    # holds the same observed count (a separate run of shuffles, so a slightly different mean).
    rob = pl.read_csv(casc / "robustness.csv").filter(
        (pl.col("variant") == "main") & (pl.col("category") == HEADLINE)
    )
    main = pl.read_csv(analyses / "exploratory" / "cascades.csv").filter(
        (pl.col("null") == "person-day-phase")
        & (pl.col("window_min") == 5)
        & (pl.col("excluding_under_s") == 0)
        & (pl.col("statistic") == "co-located pairs")
    )
    qa = json.loads((casc / "qa_cascades.json").read_text(encoding="utf-8"))
    if rob.height != 1 or main.height != 1 or rob["observed"][0] != main["observed"][0]:
        raise SystemExit("cascades: headline row missing or its sources disagree")
    if qa.get("observed_colocated_5min") != rob["observed"][0]:
        raise SystemExit("cascades: qa people count is not for the headline row")
    h = rob.row(0, named=True)
    agg["moments_headline"] = [
        {"people": qa["people_in_colocated_5min"], "observed": h["observed"],
         "null_mean": _r(h["null_mean"]), "ratio": _r(h["ratio"]), "lo": _r(h["ratio_lo"]),
         "hi": _r(h["ratio_hi"])}
    ]  # fmt: skip

    agg["places"] = []
    for r in pl.read_csv(analyses / "exploratory" / "places_setting.csv").iter_rows(named=True):
        key = SETTINGS.get(r["category"])
        if key is None:
            dropped.append(f"places {r['category']}: no setting_ copy key")
            continue
        agg["places"].append(
            {"setting": key, "people": r["people_exposed"], "rate": _r(r["rate"]),
             "lo": _r(r["lo"]), "hi": _r(r["hi"]), "suppressed": r["suppressed"]}
        )  # fmt: skip

    conf = pl.read_csv(analyses / "confirmatory" / "results.csv").filter(
        pl.col("variant") == "main"
    )
    agg["confirmatory"] = []
    for r in conf.iter_rows(named=True):
        if r["test"] not in TESTS:
            dropped.append(f"confirmatory {r['test']}: not a pre-registered test the copy knows")
            continue
        key, scale = TESTS[r["test"]]
        agg["confirmatory"].append(
            {"test": key, "label": key, "people": r["n"], "estimate": _r(r["std_estimate"]),
             "lo": _r(r["std_lo"]), "hi": _r(r["std_hi"]), "scale": scale}
        )  # fmt: skip

    agg[NUMBERS] = numbers(agg, analyses)
    return agg


def numbers(agg: dict, analyses: Path) -> dict:
    """The copy's placeholders, from the rows the charts draw (bundle counts are added later)."""
    n: dict = {}
    head = agg["moments_headline"][0]
    n["cascade_excess"], n["cascade_excess_lo"], n["cascade_excess_hi"] = (
        head["ratio"], head["lo"], head["hi"])  # fmt: skip
    first = [r for r in agg["moments_latency"] if r["band"] == "0-10"]
    if len(first) == 1:
        n["latency_0_10_ratio"] = first[0]["ratio"]
    ordinary = [r["cross_share"] for r in agg["daily_mixing"] if r["kind"] == "ordinary"]
    if ordinary:
        n["mixing_ordinary_lo"], n["mixing_ordinary_hi"] = min(ordinary), max(ordinary)
        expected = [r["expected"] for r in agg["daily_mixing"]]
        n["mixing_random"] = round(sum(expected) / len(expected), 2)
    for kind in SPECIAL_DAYS:
        rows = [r["cross_share"] for r in agg["daily_mixing"] if r["kind"] == kind]
        if len(rows) == 1:
            n[f"mixing_{kind}"] = rows[0]
    for r in agg["persistence"]:
        if r["origin"] in ("ordinary", "excursion"):
            n[f"persistence_{r['origin']}"] = r["share"]
    # The prose reads whole percentages and ratios to two decimals; the charts keep the rows.
    for key, value in n.items():
        n[key] = round(value) if key.startswith(("mixing_", "persistence_")) else round(value, 2)
    people = {r["people"] for r in agg["confirmatory"]}
    if len(people) == 1:
        n["n_confirmatory"] = people.pop()

    company = pl.read_csv(analyses / "exploratory" / "company_within_person.csv").filter(
        (pl.col("variant") == "-65 dBm")
        & (pl.col("matched") == "day x phase")
        & (pl.col("value") == "close")
    )
    if company.height == 1:
        n["company_gain"] = _r(company["mean_diff"][0], 2)
    ratio = pl.read_csv(analyses / "exploratory" / "places_ratios.csv").filter(
        (pl.col("days") == "all days") & (pl.col("ratio") == "plenum / course block")
    )
    if ratio.height == 1:
        n["plenum_vs_course"] = _r(ratio["estimate"][0], 2)
    return n


def main() -> None:
    study = StudyConfig.load(cp.STUDY_YAML)
    ex = study.explorer_config()
    layout = paths.study(cp.STUDY)
    spine = Spine.load(layout.spine)

    participants = {p.ref for p in spine.people if p.role == "participant"}
    nodes = sorted(participants & {f"person:{p}" for p in spine.consented("beacons")})
    consented_sr = {f"person:{p}" for p in spine.consented("self_report")}
    course = cp.course_of(spine)

    tz = ZoneInfo(study.timezone)
    start = datetime.fromisoformat(f"{cp.FIRST_DAY} {ex.day_start}").replace(tzinfo=tz)
    end = datetime.fromisoformat(f"{cp.LAST_DAY} {ex.day_start}").replace(tzinfo=tz)
    n_bins = int((end - start) / timedelta(seconds=BIN_SECONDS))
    days = {
        (cp.FIRST_DAY + timedelta(days=i)).isoformat()
        for i in range((cp.LAST_DAY - cp.FIRST_DAY).days)
    }

    pairs = cp.load_all("pairs").filter(pl.col("a").is_in(nodes) & pl.col("b").is_in(nodes))
    seen = cp.load_all("seen").filter(pl.col("entity").is_in(nodes))
    rooms = cp.load_all("rooms").filter(pl.col("entity").is_in(nodes))
    presses, _ = sr.press_episodes(layout, spine, participants, consented_sr)
    presses = presses.filter(pl.col("entity").is_in(nodes))

    t0 = start.astimezone(ZoneInfo("UTC"))
    inp = BundleInput(
        t0=t0,
        n_bins=n_bins,
        bin_seconds=BIN_SECONDS,
        nodes={p: course.get(p) for p in nodes},
        locations={loc.ref: (loc.label, loc.zone) for loc in spine.locations},
        pairs=pairs.select("a", "b", "bin", "max_rssi"),
        seen=seen.select("entity", "bin"),
        rooms=rooms.select("entity", "bin", "location"),
        presses=presses.select("entity", "t"),
        rssi_floor=study.raw["beacons"]["rssi_threshold_dbm"]["person_tag"],
    )
    site = layout.derived / "site"
    out = site / "data"
    if out.exists():
        shutil.rmtree(out)
    meta = write_public_bundle(
        inp,
        out,
        ex,
        timezone=study.timezone,
        close_rssi=cp.CLOSE_RSSI,
        special_days=special_days(ex, tz, t0),
        shade_label=SHADE_LABEL,
    )

    dropped: list[str] = []
    agg = aggregates(layout.derived / "analyses", days, dropped)
    agg[NUMBERS]["n_participants"] = len(meta["nodes"])
    utc = ZoneInfo("UTC")
    in_range = presses.filter(
        (pl.col("t") >= start.astimezone(utc)) & (pl.col("t") < end.astimezone(utc))
    )
    agg[NUMBERS]["n_presses"] = in_range.height
    for section in AGGREGATE_SECTIONS:
        if any("course" in row for row in agg.get(section, [])):
            raise SystemExit(f"{section}: a course-level row must never reach the site")
    checked = check_aggregates(agg, min_group=ex.min_group)
    for section, rows in agg.items():
        if section != NUMBERS and len(checked[section]) < len(rows):
            dropped.append(f"{section}: {len(rows) - len(checked[section])} small or unstated rows")
    (out / "aggregates.json").write_text(
        json.dumps(checked, indent=1, ensure_ascii=False, allow_nan=False), encoding="utf-8"
    )
    validate_site_data(out, min_group=ex.min_group)

    archive = site / "site-data.zip"
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as z:
        for f in sorted(out.iterdir()):
            z.write(f, arcname=f.name)
    size = archive.stat().st_size
    print(f"{out}: {len(meta['nodes'])} nodes, {meta['n_bins']} bins")
    print(f"{archive}: {size} bytes" + ("" if size < MAX_ZIP_BYTES else " (over 3 MB)"))
    print(f"numbers: {sorted(checked[NUMBERS])}")
    print("dropped:", *dropped, sep="\n  ")


if __name__ == "__main__":
    main()
