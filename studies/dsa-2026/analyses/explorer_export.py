"""Export DSA 2026 to an explorer bundle (``social_energy.explorer``), locally.

Research question: none of its own. The bundle feeds the team's interactive explorer, which
mirrors ``copresence_by_phase.py`` (RQ3) and ``self_report_context.py`` (RQ1).

Inputs and filters are those analyses' own, unchanged:

- Pairs, tags heard and rooms per 5-minute bin from ``copresence_by_phase.py build`` (the
  upstream ``Output/`` tables; window, spine resolution, exclusion windows, ``beacons`` consent),
  which must have run first. Pairs are kept down to the study's person-tag RSSI threshold, so the
  explorer's close-range slider can range over everything the build kept.
- Press episodes from ``self_report_context.press_episodes`` (``self_report`` consent).
- Nodes: participants with ``beacons`` consent. Their course comes from the spine.

The **person view** (``social_energy.explorer.person``) adds, per node and each only for people
who consented to its module (staff are never nodes):

- Survey (``survey``): the trust and lust composites from ``confirmatory.py``
  (``composites.parquet``), every block B and C scale and gradient score from
  ``social-energy score-survey`` and the recoded items, kept submissions linked by platform
  account exactly as ``confirmatory.linked_submissions`` does. One wave, ``pre``: no post wave was
  fielded at DSA 2026 (``docs/context/instruments/survey.md``).
- Interview membrane codes (``interview_in_person``): the coder files that
  ``exploratory_membrane.py`` reads (``codes-reviewed/`` once the human check has been applied,
  else ``codes/``), reduced to codes. Evidence, notes and free-text labels are never read into
  the bundle; an ``other:<label>`` category becomes ``other``, an episode keeps only its day.
  The interview's start comes from its recording key.
- EDA and heart rate (``eda``): ``exploratory_eda.build_minutes`` on the "all" clock, i.e. both
  SCR rules and PPG heart rate on worn minutes outside exclusion windows, with the clock flag.
- Programme items: the spine's events with missing ends filled as ``exploratory_presses`` fills
  them (``event_windows``); which item applies to a person is decided in the view by the same
  rule as ``exploratory_presses.event_bins`` (all-camp, or placed in one of its rooms).
- Age and gender from the spine.

Run after ``confirmatory.py``, ``exploratory_eda.py``'s inputs (``ingest-eda``,
``eda-heart-rate``) and the membrane coding.

The bundle is written to ``$SOCIAL_ENERGY_DATA/dsa-2026/derived/explorer/bundle/``. It carries no
study IDs, but it is pseudonymised individual data about minors: team use only, never shared.
The team bundle stays internal; the public route is ``site_export.py``, which never reads the
person data.

    uv run --extra analysis python studies/dsa-2026/analyses/explorer_export.py
    uv run social-energy explore studies/dsa-2026/study.yaml
"""

from __future__ import annotations

import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import polars as pl

sys.path.insert(0, str(Path(__file__).parent))
import confirmatory as conf
import copresence_by_phase as cp
import exploratory_eda as xe
import exploratory_membrane as em
import exploratory_presses as xp
import self_report_context as sr

from social_energy import paths
from social_energy.explorer import BundleInput, write_bundle
from social_energy.explorer.person import PersonData
from social_energy.spine import Spine
from social_energy.study import StudyConfig
from social_energy.survey import load_codebook
from social_energy.survey.score import recode

BIN_SECONDS = 300
WAVE = "pre"
BLOCKS = {"trust_in_life": "trust", "lust_for_life": "lust"}
#: The codebook's opener and closer categories (``research/membrane-codebook.md``).
CATEGORIES = {
    "people", "being_heard", "vulnerability", "course", "arts", "nature", "programme", "freedom",
    "fatigue", "withdrawal_need", "conflict", "pressure", "safety", "loss", "topic", "end",
}  # fmt: skip
CONFIDENCE = {"high", "medium", "low"}
DIRECTIONS = {"opened", "closed", "stable", "fluctuated", "na"}
STATES = [*em.STATES, "M_now_lenient"]


# --- person view ---------------------------------------------------------------------------------


def survey_inputs(layout, config: StudyConfig, spine: Spine) -> dict:
    """Scales (blocks B and C), composites, scale scores and items of kept, linked submissions."""
    codebook = load_codebook(config.survey_scoring_config().codebook)
    groups = {k: g for k, g in codebook.groups.items() if g.role in BLOCKS}
    core = {s for block in conf.SCALES.values() for s in block}
    scales = [
        {"key": k, "label": g.concept, "block": BLOCKS[g.role], "kind": g.kind, "core": k in core,
         "parent": g.parent, "items": g.codes, "range": list(g.range)}
        for k, g in sorted(groups.items(), key=lambda kv: (kv[1].block, kv[0]))
    ]  # fmt: skip
    scoring = layout.derived / "survey" / "scoring"
    linked, _ = conf.linked_submissions(pl.read_parquet(scoring / "submissions.parquet"), spine)
    scores = (
        pl.read_parquet(scoring / "scores.parquet")
        .filter(~pl.col("duplicate_submission") & pl.col("group").is_in(list(groups)))
        .join(linked, on="respondent")
        .select("entity", pl.lit(WAVE).alias("wave"), "group", "mean")
    )
    items = (
        recode(pl.read_parquet(layout.derived / "survey" / "items.parquet"), codebook)
        .filter(pl.col("group").is_in(list(groups)) & pl.col("value").is_not_null())
        .join(linked, on="respondent")
        .select("entity", pl.lit(WAVE).alias("wave"), "group", "item",
                pl.col("value").cast(pl.Float64))
    )  # fmt: skip
    # Single-item groups score as their one recoded item, as in confirmatory.scale_scores.
    single = [k for k, g in groups.items() if g.kind == "items" and len(g.items) == 1]
    from_items = items.filter(pl.col("group").is_in(single)).select(
        "entity", "wave", "group", pl.col("value").alias("mean")
    )
    comps = pl.read_parquet(
        layout.derived / "analyses" / "confirmatory" / "composites.parquet"
    ).select("entity", pl.lit(WAVE).alias("wave"), "trust", "lust")
    return {
        "scales": scales,
        "composites": comps,
        "scale_scores": pl.concat([scores, from_items]),
        "items": items,
    }


def _state(code: dict) -> dict:
    v = code.get("value")
    out = {"value": v if isinstance(v, int) and not isinstance(v, bool) else None,
           "confidence": code.get("confidence") if code.get("confidence") in CONFIDENCE else None,
           "led": bool(code.get("led")), "varies": bool(code.get("varies"))}  # fmt: skip
    if "reviewed" in code:
        out["reviewed"] = code["reviewed"] if code["reviewed"] in (True, False, "unsure") else None
    return out


def _category(c: object) -> str:
    return c if c in CATEGORIES else "other"


def membrane_codes(code: dict, derived: dict) -> dict:
    """The codes of one interview: values only, never evidence, notes or free labels."""
    out = {s: _state(code[s]) for s in STATES if isinstance(code.get(s), dict)}
    d = code.get("direction", {})
    out["direction"] = {
        "value": d.get("value") if d.get("value") in DIRECTIONS else None,
        "confidence": d.get("confidence") if d.get("confidence") in CONFIDENCE else None,
    }
    if isinstance(code.get("change_amount"), dict):
        out["change_amount"] = _state(code["change_amount"])
    sel = code.get("selective", {})
    out["selective"] = bool(sel.get("value")) if isinstance(sel, dict) else bool(sel)
    for flag in ("block", "primed", "known_elsewhere"):
        out[flag] = bool(code.get(flag))
    for k in ("D_academy", "D_academy_lenient", "D_vs_everyday", "change_signed"):
        v = derived.get(k)
        out[k] = None if v is None else float(v)
    out["openers"] = sorted({_category(o.get("category")) for o in code.get("openers", [])})
    out["closers"] = sorted({_category(o.get("category")) for o in code.get("closers", [])})
    episodes = []
    for e in code.get("episodes", []):
        try:
            day = date.fromisoformat((e.get("when") or "")[:10]).isoformat()
        except ValueError:
            day = None
        episodes.append({
            "direction": e.get("direction") if e.get("direction") in ("open", "close") else None,
            "category": _category(e.get("category")),
            "day": day,
        })  # fmt: skip
    out["episodes"] = episodes
    return out


def membrane_inputs(layout, spine: Spine, tz: ZoneInfo) -> tuple[dict, dict, str]:
    """Codes and interview start per participant, and which coder folder they came from."""
    root = layout.derived / "interview-membrane"
    folder = root / "codes-reviewed" if (root / "codes-reviewed").is_dir() else root / "codes"
    codes = em.read_codes(folder)
    participants = {p.ref for p in spine.people if p.role == "participant"}
    people = {k: e for k, e in spine.account_entities("interview").select("account", "entity")
              .iter_rows() if e in participants}  # fmt: skip
    derived = {r["key"]: r for r in em.code_frame(codes, people, "main").iter_rows(named=True)}
    membrane, interviews = {}, {}
    for key, code in codes.items():
        if key not in people:
            continue
        membrane[people[key]] = membrane_codes(code, derived.get(key, {}))
        start = datetime.strptime(key, "%Y%m%d_%H%M%S").replace(tzinfo=tz)
        interviews[people[key]] = start.astimezone(ZoneInfo("UTC"))
    return membrane, interviews, folder.name


def eda_inputs(layout, spine: Spine) -> pl.DataFrame:
    """Worn person-minutes outside exclusions: both SCR rules, heart rate and the clock flag."""
    pm, counts = xe.load_person_minutes(layout, spine)
    m = xe.build_minutes(pm, counts, clock="all").filter(pl.col("worn_s") > 0)
    uncertain = pl.col("clock_uncertain").fill_null(True) | (
        pl.col("hr_ok") & pl.col("hr_clock_uncertain").fill_null(True)
    )
    return m.select(
        "entity", "minute", pl.col("scr_main").alias("scr"),
        pl.col("scr_amp02").alias("scr_strict"), "hr", "usable", "hr_ok",
        uncertain.alias("clock_uncertain"),
    )  # fmt: skip


def event_inputs(spine: Spine) -> pl.DataFrame:
    """Programme items with filled ends, their label, and whether the end was known."""
    windows = xp.event_windows(spine, known_only=False)
    label = {e.id: e.label for e in spine.events}
    known = {e.id: e.end is not None and e.start is not None and e.end > e.start
             for e in spine.events}  # fmt: skip
    return windows.select(
        pl.col("event").replace_strict(label).alias("label"),
        "kind", "start", "end",
        pl.col("event").replace_strict(known).alias("end_known"),
        "all_camp", "locations",
    )  # fmt: skip


def person_data(layout, study: StudyConfig, spine: Spine, nodes: list[str]) -> PersonData:
    participants = {p.ref for p in spine.people if p.role == "participant"}
    consent = {
        m: frozenset(participants & {f"person:{p}" for p in spine.consented(m)})
        for m in ("survey", "interview_in_person", "eda", "self_report")
    }
    attributes = {p.ref: {"age": p.age, "gender": p.gender} for p in spine.people
                  if p.ref in set(nodes)}  # fmt: skip
    membrane, interviews, coded = membrane_inputs(layout, spine, ZoneInfo(study.timezone))
    return PersonData(
        consent=consent,
        attributes=attributes,
        **survey_inputs(layout, study, spine),
        membrane=membrane,
        interviews=interviews,
        eda=eda_inputs(layout, spine),
        events=event_inputs(spine),
        notes={
            "waves": "Baseline survey only: no post wave was fielded at this academy.",
            "membrane": (
                "Interview codes after the human check."
                if coded == "codes-reviewed"
                else "Interview codes are model-coded; the human check is still open."
            ),
        },
    )


# --- export --------------------------------------------------------------------------------------


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

    pairs = cp.load_all("pairs").filter(pl.col("a").is_in(nodes) & pl.col("b").is_in(nodes))
    seen = cp.load_all("seen").filter(pl.col("entity").is_in(nodes))
    rooms = cp.load_all("rooms").filter(pl.col("entity").is_in(nodes))
    presses, qa = sr.press_episodes(layout, spine, participants, consented_sr)

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
        persons=person_data(layout, study, spine, nodes),
    )
    out = layout.derived / "explorer" / "bundle"
    meta = write_bundle(inp, out, ex, timezone=study.timezone, mode="team", qa=qa)
    print(f"{out}: {len(meta['nodes'])} nodes, {meta['n_bins']} bins")
    print({k: v for k, v in meta["qa"].items()})


if __name__ == "__main__":
    main()
