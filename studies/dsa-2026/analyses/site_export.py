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
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import polars as pl

sys.path.insert(0, str(Path(__file__).parent))
import copresence_by_phase as cp
import self_report_context as sr

from social_energy import paths
from social_energy.explorer import BundleInput
from social_energy.explorer.bundle import _local_to_bin
from social_energy.site.aggregates import (
    AGGREGATE_SECTIONS,
    NUMBERS,
    check_aggregates,
    is_number,
)
from social_energy.site.public import SHADE_LABEL, write_public_bundle
from social_energy.site.validate import validate_site_data
from social_energy.spine import Spine
from social_energy.study import StudyConfig

BIN_SECONDS = 300
MAX_ZIP_BYTES = 3 * 1024 * 1024
#: Which ``explorer.notes`` entries are special days on the site, by the copy key they get.
SPECIAL_DAYS = ("excursion", "rotation")
#: The site shows no night (``privacy_night``), so the day chapter draws daytime phases only.
HIDDEN_PHASES = {"night"}
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
    """Rounded, or None when the source value is missing or not finite."""
    return round(float(v), digits) if is_number(v) else None


def _pct(v: float | None) -> float | None:
    return round(100 * float(v), 2) if is_number(v) else None


def _seconds_band(label: str) -> str | None:
    """'0-10 s' -> '0-10', '1-2 min' -> '60-120'; None when the label is not a band."""
    m = re.fullmatch(r"(\d+)-(\d+) (s|min)", label.strip())
    if not m:
        return None
    k = 60 if m[3] == "min" else 1
    return f"{int(m[1]) * k}-{int(m[2]) * k}"


# --- sections: one pure function per chapter, source table(s) in, site rows out -------------


def day_phase_rows(df: pl.DataFrame, days: set[str], log: list[str]) -> list[dict]:
    rows = []
    for r in df.iter_rows(named=True):
        if r["phase"] in HIDDEN_PHASES or r["day"] not in days:
            log.append(f"day_phase {r['day']} {r['phase']}: night or outside the bundle")
            continue
        rows.append(
            {"day": r["day"], "phase": r["phase"], "people": r["people"],
             "others": _r(r["others"]), "share_no_one": _pct(r["share_no_one"])}
        )  # fmt: skip
    return rows


def mixing_rows(df: pl.DataFrame, days: set[str], arrival: str, log: list[str]) -> list[dict]:
    """Main variant, one row per day in the bundle, arrival day left out, shares in percent."""
    rows = []
    for r in df.filter(pl.col("variant") == "main").sort("day").iter_rows(named=True):
        if r["day"] == arrival or r["day"] not in days:
            log.append(f"daily_mixing {r['day']}: arrival day or outside the bundle")
            continue
        rows.append(
            {"day": r["day"], "kind": r["kind"], "people": r["people"],
             "cross_share": _pct(r["cross_share"]), "expected": _pct(r["expected"])}
        )  # fmt: skip
    return rows


def persistence_rows(rates: pl.DataFrame, ties: pl.DataFrame, log: list[str]) -> list[dict]:
    """Tied again within three days, main variant; people from the per-tie table."""
    rows = []
    rates = rates.filter(
        (pl.col("variant") == "main")
        & (pl.col("follow_up") == "all")
        & (pl.col("origin") == "all")
        & (pl.col("outcome") == "again_3")
    )
    for r in rates.iter_rows(named=True):
        if r["kind"] not in ("ordinary", *SPECIAL_DAYS):
            log.append(f"persistence {r['kind']}: no origin_ copy key")
            continue
        sub = ties.filter(pl.col("has_3") & (pl.col("kind") == r["kind"]))
        if sub.height != r["new_ties"]:
            raise SystemExit(f"persistence {r['kind']}: new_ties table and rates disagree")
        rows.append(
            {"origin": r["kind"], "people": len(set(sub["a"]) | set(sub["b"])),
             "new_ties": r["new_ties"], "share": _pct(r["share"]), "lo": _pct(r["lo"]),
             "hi": _pct(r["hi"])}
        )  # fmt: skip
    return rows


def latency_rows(df: pl.DataFrame, log: list[str]) -> list[dict]:
    rows = []
    for r in df.iter_rows(named=True):
        band = _seconds_band(r["category"])
        if band is None:
            log.append(f"moments_latency {r['category']}: not a band")
            continue
        rows.append(
            {"band": band, "people": r["people"], "ratio": _r(r["ratio"]),
             "ratio_lo": _r(r["ratio_lo"]), "ratio_hi": _r(r["ratio_hi"]),
             "suppressed": r["suppressed"]}
        )  # fmt: skip
    return rows


def size_rows(df: pl.DataFrame, log: list[str]) -> list[dict]:
    """Group sizes; rows stating no people are kept here and dropped by the small-cell rule."""
    rows = []
    for r in df.iter_rows(named=True):
        if not re.match(r"\d", str(r["category"])):
            log.append(f"moments_size {r['category']}: not a group size")
            continue
        rows.append(
            {"size": str(r["category"]), "people": r["people"], "ratio": _r(r["ratio"]),
             "ratio_lo": _r(r["ratio_lo"]), "ratio_hi": _r(r["ratio_hi"]),
             "suppressed": r["suppressed"]}
        )  # fmt: skip
    return rows


def headline_rows(rob: pl.DataFrame, main: pl.DataFrame, qa: dict) -> list[dict]:
    """The main row of the robustness table (it carries the day-bootstrap interval).

    ``cascades.csv`` holds the same observed count from a separate run of shuffles, and the
    cascades QA the number of people behind it; both must agree with the row.
    """
    rob = rob.filter((pl.col("variant") == "main") & (pl.col("category") == HEADLINE))
    main = main.filter(
        (pl.col("null") == "person-day-phase")
        & (pl.col("window_min") == 5)
        & (pl.col("excluding_under_s") == 0)
        & (pl.col("statistic") == "co-located pairs")
    )
    if rob.height != 1 or main.height != 1 or rob["observed"][0] != main["observed"][0]:
        raise SystemExit("cascades: headline row missing or its sources disagree")
    if qa.get("observed_colocated_5min") != rob["observed"][0]:
        raise SystemExit("cascades: qa people count is not for the headline row")
    h = rob.row(0, named=True)
    return [
        {"people": qa.get("people_in_colocated_5min"), "observed": _r(h["observed"]),
         "null_mean": _r(h["null_mean"]), "ratio": _r(h["ratio"]), "lo": _r(h["ratio_lo"]),
         "hi": _r(h["ratio_hi"])}
    ]  # fmt: skip


def place_rows(df: pl.DataFrame, log: list[str]) -> list[dict]:
    rows = []
    for r in df.iter_rows(named=True):
        key = SETTINGS.get(r["category"])
        if key is None:
            log.append(f"places {r['category']}: no setting_ copy key")
            continue
        rows.append(
            {"setting": key, "people": r["people_exposed"], "rate": _r(r["rate"]),
             "lo": _r(r["lo"]), "hi": _r(r["hi"]), "suppressed": r["suppressed"]}
        )  # fmt: skip
    return rows


def confirmatory_rows(df: pl.DataFrame, log: list[str]) -> list[dict]:
    """Main variant, the four pre-registered tests: standardised effects and rate ratios."""
    rows = []
    for r in df.filter(pl.col("variant") == "main").iter_rows(named=True):
        if r["test"] not in TESTS:
            log.append(f"confirmatory {r['test']}: not a pre-registered test the copy knows")
            continue
        key, scale = TESTS[r["test"]]
        rows.append(
            {"test": key, "people": r["n"], "estimate": _r(r["std_estimate"]),
             "lo": _r(r["std_lo"]), "hi": _r(r["std_hi"]), "scale": scale}
        )  # fmt: skip
    return rows


# --- numbers: only from rows that survived the small-cell rule --------------------------------


def numbers(
    checked: dict,
    company: pl.DataFrame,
    ratios: pl.DataFrame,
    *,
    min_group: int,
    log: list[str],
) -> dict:
    """The copy's placeholders, from the surviving rows the charts draw; missing -> left out."""
    n: dict = {}

    def put(key: str, value: object) -> None:
        if is_number(value):
            n[key] = value
        else:
            log.append(f"numbers {key}: source missing, small or not finite; left out")

    def rows(section: str) -> list[dict]:
        return checked.get(section, [])

    head = rows("moments_headline")
    if len(head) == 1:
        for key, col in (("cascade_excess", "ratio"), ("cascade_excess_lo", "lo"),
                         ("cascade_excess_hi", "hi")):  # fmt: skip
            put(key, head[0].get(col))
    first = [r for r in rows("moments_latency") if r["band"] == "0-10"]
    if len(first) == 1:
        put("latency_0_10_ratio", first[0].get("ratio"))
    mixing = rows("daily_mixing")
    ordinary = [r["cross_share"] for r in mixing if r["kind"] == "ordinary"]
    ordinary = [v for v in ordinary if is_number(v)]
    if ordinary:
        put("mixing_ordinary_lo", min(ordinary))
        put("mixing_ordinary_hi", max(ordinary))
    expected = [r.get("expected") for r in mixing]
    if expected:
        put("mixing_random", sum(expected) / len(expected) if all(map(is_number, expected))
            else None)  # fmt: skip
    for kind in SPECIAL_DAYS:
        hit = [r for r in mixing if r["kind"] == kind]
        if len(hit) == 1:
            put(f"mixing_{kind}", hit[0].get("cross_share"))
    for r in rows("persistence"):
        if r["origin"] in ("ordinary", "excursion"):
            put(f"persistence_{r['origin']}", r.get("share"))
    people = {r["people"] for r in rows("confirmatory")}
    if len(people) == 1:
        put("n_confirmatory", people.pop())

    c = company.filter(
        (pl.col("variant") == f"{cp.CLOSE_RSSI} dBm")
        & (pl.col("matched") == "day x phase")
        & (pl.col("value") == "close")
    )
    if c.height == 1 and is_number(c["people"][0]) and c["people"][0] >= min_group:
        put("company_gain", c["mean_diff"][0])
    else:
        log.append("numbers company_gain: row missing or under min_group; left out")
    settings = {r["setting"] for r in rows("places")}
    ratio = ratios.filter(
        (pl.col("days") == "all days") & (pl.col("ratio") == "plenum / course block")
    )
    if {"plenum", "course_block"} <= settings and ratio.height == 1:
        put("plenum_vs_course", ratio["estimate"][0])
    else:
        log.append("numbers plenum_vs_course: a place row was dropped or the ratio is missing")

    # The prose reads whole percentages and ratios to two decimals; the charts keep the rows.
    for key, value in n.items():
        n[key] = round(value) if key.startswith(("mixing_", "persistence_")) else round(value, 2)
    return n


def finish(
    sections: dict,
    company: pl.DataFrame,
    ratios: pl.DataFrame,
    *,
    min_group: int,
    log: list[str],
) -> tuple[dict, dict]:
    """Small-cell rule first, then the numbers from what survived. Returns (checked, numbers)."""
    for section, rows in sections.items():
        if any("course" in row for row in rows):
            raise SystemExit(f"{section}: a course-level row must never reach the site")
    checked = check_aggregates(sections, min_group=min_group)
    for section, rows in sections.items():
        if len(checked[section]) < len(rows):
            log.append(f"{section}: {len(rows) - len(checked[section])} small or unstated rows")
    return checked, numbers(checked, company, ratios, min_group=min_group, log=log)


def read_sections(analyses: Path, days: set[str], arrival: str, log: list[str]) -> dict:
    """Read the analyses' outputs into the site's sections (before the small-cell rule)."""
    ex = analyses / "exploratory"
    casc = ex / "cascades"
    return {
        "day_phase": day_phase_rows(
            pl.read_csv(analyses / "copresence-by-phase" / "day_phase.csv"), days, log
        ),
        "daily_mixing": mixing_rows(
            pl.read_csv(ex / "rhythm_daily_mixing.csv"), days, arrival, log
        ),
        "persistence": persistence_rows(
            pl.read_csv(ex / "rhythm_persistence_rates.csv"),
            pl.read_parquet(ex / "rhythm_new_ties.parquet"),
            log,
        ),
        "moments_latency": latency_rows(pl.read_csv(casc / "latency.csv"), log),
        "moments_size": size_rows(pl.read_csv(casc / "group_size.csv"), log),
        "moments_headline": headline_rows(
            pl.read_csv(casc / "robustness.csv"),
            pl.read_csv(ex / "cascades.csv"),
            json.loads((casc / "qa_cascades.json").read_text(encoding="utf-8")),
        ),
        "places": place_rows(pl.read_csv(ex / "places_setting.csv"), log),
        "confirmatory": confirmatory_rows(
            pl.read_csv(analyses / "confirmatory" / "results.csv"), log
        ),
    }


def main() -> None:
    study = StudyConfig.load(cp.STUDY_YAML)
    ex = study.explorer_config()
    layout = paths.study(cp.STUDY)
    spine = Spine.load(layout.spine)
    arrival = str(study.raw["dates"]["arrival"])

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

    inp = BundleInput(
        t0=start.astimezone(ZoneInfo("UTC")),
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
    special = [
        {"start_bin": _local_to_bin(note["start"], tz, inp),
         "end_bin": _local_to_bin(note["end"], tz, inp), "label": label}
        for note in ex.notes
        for label in [next((k for k in SPECIAL_DAYS if note["text"].startswith(k)), None)]
        if label is not None
    ]  # fmt: skip
    site = layout.derived / "site"
    out = paths.refuse_inside_repo(site / "data")
    if out.exists():
        shutil.rmtree(out)
    meta = write_public_bundle(
        inp,
        out,
        ex,
        timezone=study.timezone,
        close_rssi=cp.CLOSE_RSSI,
        special_days=special,
        shade_label=SHADE_LABEL,
    )

    log: list[str] = []
    analyses = layout.derived / "analyses"
    sections = read_sections(analyses, days, arrival, log)
    checked, nums = finish(
        sections,
        pl.read_csv(analyses / "exploratory" / "company_within_person.csv"),
        pl.read_csv(analyses / "exploratory" / "places_ratios.csv"),
        min_group=ex.min_group,
        log=log,
    )
    # What the hero can show: nodes, and presses left after the night is removed.
    nums["n_participants"] = len(meta["nodes"])
    nums["n_presses"] = meta["files"]["presses"]["count"]
    checked[NUMBERS] = nums
    assert set(checked) <= {*AGGREGATE_SECTIONS, NUMBERS}
    (out / "aggregates.json").write_text(
        json.dumps(checked, indent=1, ensure_ascii=False, allow_nan=False), encoding="utf-8"
    )
    validate_site_data(out, min_group=ex.min_group)

    archive = site / "site-data.zip"
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as z:
        for f in sorted(out.iterdir()):
            z.write(f, arcname=f.name)
    size = archive.stat().st_size
    if size >= MAX_ZIP_BYTES:
        raise SystemExit(f"{archive}: {size} bytes, over 3 MB; aggregate pairs to 15-minute bins")
    print(f"{out}: {len(meta['nodes'])} nodes, {meta['n_bins']} bins")
    print(f"{archive}: {size} bytes")
    print(f"numbers: {sorted(nums)}")
    print("log:", *log, sep="\n  ")


if __name__ == "__main__":
    main()
