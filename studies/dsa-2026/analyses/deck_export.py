"""The team-meeting deck's share of the public site asset (``site_export.py`` calls it).

Research question: none of its own. The deck (``social_energy/site/static/deck/``) walks the team
through where the DSA 2026 data stands and what the analyses found so far. Its numbers, like the
site's, reach the page only through the release asset: this module reads outputs the analyses and
ingests already wrote and turns them into camp-level rows and named numbers. Nothing is
recomputed and no result is written in code.

Sources, all under ``$SOCIAL_ENERGY_DATA/dsa-2026/derived/``:

- ``data_state``: records in and kept per source, from the ingest QA (``beacons/qa.json``,
  ``analyses/exploratory/qa_presses.json``, ``survey/scoring/submissions.parquet``,
  ``analyses/exploratory/eda/qa_eda.json``, ``analyses/exploratory-membrane/qa.json``).
- ``gradient_pairs`` / ``gradient_presses``: ``analyses/exploratory/gradients/`` (PR #25), main
  model only (person dummies, log close minutes; all partners for presses).
- ``eda_press_profile``: ``analyses/exploratory/eda/presses_profile.csv``, one series.
- ``membrane_reasons``: ``analyses/exploratory-membrane/descriptives.csv``, openers and closers.
- Numbers: the same files plus EDA settings contrasts and synchrony, interview agreement,
  convergence and behaviour.

Every row carries the people behind it and goes through ``check_aggregates`` (cells under
``min_group`` dropped) in ``site_export.finish``. A number is written only when the people
behind it reach ``min_group``; a missing file leaves its rows and numbers out, with a log line.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

import polars as pl

from social_energy.site.aggregates import GRADIENT_MEASURES, REASONS, TERCILES, is_number

#: ``pair_effects.csv`` samples -> the deck's ``sample`` key.
GRADIENT_SAMPLES = {"all": "all", "within course": "within", "between course": "between"}
#: Interview codebook groups -> the deck's ``direction`` key.
REASON_GROUPS = {"openers": "opens", "closers": "closes"}
#: The one EDA series the deck draws: skin-conductance responses (main rule), z-scored within
#: person-day, unadjusted, around all presses, all clock minutes, against the person-day null.
EDA_PROFILE = {
    "column": "z_pd_scr_main",
    "adjusted": False,
    "null": "person-day",
    "presses": "all",
    "outcome": "eda",
    "clock": "all",
}
#: The meal contrast in the deck: meal time vs course block, movement and clock hour held.
EDA_MEAL = {"contrast": "setting", "level": "meal time", "reference": "course block",
            "adjustment": "movement + time", "clock": "all"}  # fmt: skip
#: Synchrony of skin-conductance responses >= 0.2 uS between close and apart pairs.
EDA_SYNC_SIGNAL = "scr_amp02"
#: The interview's primary change measure (lenient), as in the 22 Oct material.
MEMBRANE_CHANGE = "D_academy_lenient"
#: ``put``'s default: a number that is not about a group of people (a share of minutes).
NO_PEOPLE = object()


def _r(v: object, digits: int = 4) -> float | None:
    return round(float(v), digits) if is_number(v) else None


def _pct(v: object) -> float | None:
    return round(100 * float(v), 2) if is_number(v) else None


def _one(df: pl.DataFrame, **eq) -> dict | None:
    """The single row of ``df`` matching every column == value, else None."""
    for col, value in eq.items():
        if col not in df.columns:
            return None
        df = df.filter(pl.col(col) == value)
    return df.row(0, named=True) if df.height == 1 else None


# --- rows -------------------------------------------------------------------------------------


def data_state_rows(qa: dict, n_nodes: int, log: list[str]) -> list[dict]:
    """Per source: records in (``raw``), records kept (``clean``), people the kept ones cover.

    ``qa`` maps ``beacons``, ``presses``, ``eda``, ``interviews`` to their QA dicts and
    ``survey`` to the submissions table; a missing entry leaves its source out.
    """
    rows = []

    def add(source: str, people: object, raw: object, clean: object) -> None:
        if all(is_number(v) for v in (people, raw, clean)):
            rows.append({"source": source, "people": people, "raw": raw, "clean": clean})
        else:
            log.append(f"data_state {source}: a count is missing")

    if b := qa.get("beacons"):
        contacts = b.get("contacts")
        bad = b.get("contacts_not_ok")
        add("beacons", n_nodes, contacts,
            contacts - bad if is_number(contacts) and is_number(bad) else None)  # fmt: skip
    if p := qa.get("presses"):
        press = p.get("press", {})
        add("presses", press.get("pressers"), press.get("rows"), press.get("episodes"))
    survey = qa.get("survey")
    if survey is not None:
        kept = survey.filter(~pl.col("duplicate_submission"))
        add("survey", kept.filter(pl.col("study_id").is_not_null()).height, survey.height,
            kept.height)  # fmt: skip
    if e := qa.get("eda"):
        m = e.get("all", {}).get("minutes", {})
        add("eda", m.get("usable_people"), m.get("person_minutes"), m.get("usable_minutes"))
        add("heart_rate", m.get("hr_people"), m.get("person_minutes"), m.get("hr_minutes"))
    if i := qa.get("interviews"):
        add("interviews", i.get("main_people"), i.get("coded"), i.get("main_people"))
    return rows


def gradient_pair_rows(df: pl.DataFrame, log: list[str]) -> list[dict]:
    """Main model: person dummies, log(1 + close minutes); one row per measure x sample."""
    rows = []
    main = df.filter(pl.col("person_fe") & (pl.col("outcome") == "log_close"))
    for r in main.iter_rows(named=True):
        sample = GRADIENT_SAMPLES.get(r["sample"])
        if sample is None or r["measure"] not in GRADIENT_MEASURES:
            log.append(f"gradient_pairs {r['sample']} {r['measure']}: not drawn")
            continue
        rows.append(
            {"measure": r["measure"], "sample": sample, "people": r["people"],
             "r": _r(r["partial_r"]), "null_lo": _r(r["null_lo"]), "null_hi": _r(r["null_hi"])}
        )  # fmt: skip
    return rows


def gradient_press_rows(df: pl.DataFrame, log: list[str]) -> list[dict]:
    """Co-press share by distance tercile, all partners; people = those who co-pressed."""
    rows = []
    for r in df.filter(pl.col("partners") == "all").iter_rows(named=True):
        if r["measure"] not in ("trust", "lust") or r["tercile"] not in TERCILES:
            log.append(f"gradient_presses {r['measure']} {r['tercile']}: not drawn")
            continue
        if r["withheld"]:
            log.append(f"gradient_presses {r['measure']} {r['tercile']}: withheld")
            continue
        rows.append(
            {"measure": r["measure"], "tercile": r["tercile"], "people": r["people_copressing"],
             "share": _pct(r["copress_share"]), "time_null": _pct(r["time_null_mean"])}
        )  # fmt: skip
    return rows


def eda_profile_rows(df: pl.DataFrame, log: list[str]) -> list[dict]:
    sub = df
    for col, value in EDA_PROFILE.items():
        sub = sub.filter(pl.col(col) == value)
    if sub.is_empty():
        log.append("eda_press_profile: the series is missing")
    rows = []
    for r in sub.sort("offset").iter_rows(named=True):
        rows.append(
            {"offset": r["offset"], "people": r["people"], "observed": _r(r["observed"]),
             "null_lo": _r(r["null_lo"]), "null_hi": _r(r["null_hi"]),
             "suppressed": r["suppressed"]}
        )  # fmt: skip
    return rows


def reason_rows(df: pl.DataFrame, log: list[str]) -> list[dict]:
    """What opens and closes the membrane; 'other' and withheld cells are left out."""
    rows = []
    for r in df.filter(pl.col("group").is_in(list(REASON_GROUPS))).iter_rows(named=True):
        if r["level"] not in REASONS:
            log.append(f"membrane_reasons {r['level']}: no deck key")
            continue
        rows.append(
            {"reason": r["level"], "direction": REASON_GROUPS[r["group"]], "people": r["n"],
             "share": _pct(r["share"]), "suppressed": bool(r["withheld"])}
        )  # fmt: skip
    return rows


# --- numbers ----------------------------------------------------------------------------------


def deck_numbers(src: dict, *, min_group: int, log: list[str]) -> dict:
    """The deck's placeholders. ``src`` holds the loaded sources; a missing one is skipped."""
    n: dict = {}

    def put(key: str, value: object, people: object = NO_PEOPLE) -> None:
        if not is_number(value):
            log.append(f"numbers {key}: source missing or not finite; left out")
        elif people is not NO_PEOPLE and not (is_number(people) and people >= min_group):
            log.append(f"numbers {key}: {people!r} people, under {min_group}; left out")
        else:
            n[key] = value

    if b := src.get("beacons"):
        put("beacon_reboots", b.get("reboots"))
    if e := src.get("eda"):
        m = e.get("all", {}).get("minutes", {})
        c = e.get("certain", {}).get("minutes", {})
        put("eda_wearers", m.get("usable_people"), m.get("usable_people"))
        put("eda_certain_wearers", c.get("usable_people"), c.get("usable_people"))
        put("hr_wearers", m.get("hr_people"), m.get("hr_people"))
        put("eda_usable_minutes", m.get("usable_minutes"), m.get("usable_people"))
        sources = m.get("clock_source_minutes", {})
        total = sum(v for v in sources.values() if is_number(v))
        for name in ("sync", "rate", "box"):
            v = sources.get(name)
            put(f"eda_clock_{name}_pct", 100 * v / total if is_number(v) and total else None)
        unc, worn = m.get("clock_uncertain_minutes"), m.get("person_minutes")
        put("eda_clock_uncertain_pct",
            100 * unc / worn if is_number(unc) and is_number(worn) and worn else None)  # fmt: skip
        p = e.get("all", {}).get("presses_eda", {})
        put("eda_presses", p.get("presses_eligible"), p.get("pressers_eligible"))
        put("eda_pressers", p.get("pressers_eligible"), p.get("pressers_eligible"))
    if (df := src.get("eda_contrasts")) is not None:
        for key, measure in (("eda_meal_scr", "scr_main"), ("eda_meal_hr", "hr")):
            r = _one(df, measure=measure, **EDA_MEAL) or {}
            put(key, r.get("estimate_sd"), r.get("people"))
            if key == "eda_meal_scr":
                put("eda_meal_scr_lo", r.get("lo"), r.get("people"))
                put("eda_meal_scr_hi", r.get("hi"), r.get("people"))
    if (df := src.get("eda_synchrony")) is not None:
        for key, label in (("eda_sync_close", "close"), ("eda_sync_apart", "apart")):
            r = _one(df, signal=EDA_SYNC_SIGNAL, label=label, clock="all") or {}
            put(key, r.get("sync"), r.get("people"))
    if i := src.get("interviews"):
        put("interviews_coded", i.get("coded"), i.get("coded"))
        put("interviews_people", i.get("main_people"), i.get("main_people"))
    if (df := src.get("membrane_descriptives")) is not None:
        for key, group, level in (
            ("membrane_opened_pct", "direction", "opened"),
            ("membrane_stable_pct", "direction", "stable"),
            ("membrane_selective_pct", "selective", "True"),
        ):
            r = _one(df.with_columns(pl.col("level").cast(pl.Utf8)), group=group, level=level)
            r = r or {}
            put(key, _pct(r.get("share")) if not r.get("withheld") else None, r.get("n"))
    if (df := src.get("membrane_agreement")) is not None:
        r = _one(df, code="M_now_lenient") or {}
        put("membrane_kappa_now", r.get("kappa_w"), r.get("n_rated_by_both"))
    if (df := src.get("membrane_convergence")) is not None:
        for comp in ("trust", "lust"):
            r = _one(df, variant="main", composite=comp) or {}
            put(f"membrane_{comp}_rho", r.get("rho"), r.get("n"))
            if comp == "trust":
                put("membrane_trust_rho_lo", r.get("rho_lo"), r.get("n"))
                put("membrane_trust_rho_hi", r.get("rho_hi"), r.get("n"))
    if (df := src.get("membrane_behaviour")) is not None:
        r = _one(df, variant="main", outcome="cross_share", predictor=MEMBRANE_CHANGE) or {}
        for key, col in (("membrane_mixing_sd", "std"), ("membrane_mixing_sd_lo", "std_lo"),
                         ("membrane_mixing_sd_hi", "std_hi")):  # fmt: skip
            put(key, r.get(col), r.get("n"))
    if g := src.get("gradients_qa"):
        put("gradient_people", g.get("unit"), g.get("unit"))
        put("gradient_pairs", g.get("pairs"), g.get("unit"))
    if (df := src.get("gradient_pairs")) is not None:
        for key, sample in (("gradient_trust_scales_pct", "all"),
                            ("gradient_trust_scales_within_pct", "within course")):  # fmt: skip
            r = _one(df, sample=sample, person_fe=True, outcome="log_close",
                     measure="trust_scales") or {}  # fmt: skip
            put(key, _pct(r.get("pct_change_per_sd")), r.get("people"))
    if (df := src.get("gradient_presses")) is not None:
        for key, tercile in (("gradient_excess_near", "near"), ("gradient_excess_far", "far")):
            r = _one(df, measure="trust", partners="all", tercile=tercile) or {}
            withheld = r.get("withheld")
            put(key, r.get("excess_over_time_null") if not withheld else None,
                r.get("people_copressing"))  # fmt: skip

    # Whole numbers for counts and percentages, two decimals for effects.
    out = {}
    for key, value in n.items():
        if key.endswith("_pct"):
            out[key] = round(value)
        elif isinstance(value, int):
            out[key] = value
        else:
            out[key] = round(value, 2)
    return out


# --- reading ----------------------------------------------------------------------------------


def _load(path: Path, reader: Callable, log: list[str]):
    if not path.exists():
        log.append(f"deck: {path.name} missing; its rows and numbers are left out")
        return None
    return reader(path)


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def read_deck(derived: Path, n_nodes: int, log: list[str]) -> tuple[dict, dict]:
    """(sections before the small-cell rule, sources for ``deck_numbers``)."""
    a = derived / "analyses"
    ex, grad = a / "exploratory", a / "exploratory" / "gradients"
    mem = a / "exploratory-membrane"
    src = {
        "beacons": _load(derived / "beacons" / "qa.json", _json, log),
        "presses": _load(ex / "qa_presses.json", _json, log),
        "survey": _load(
            derived / "survey" / "scoring" / "submissions.parquet", pl.read_parquet, log
        ),
        "eda": _load(ex / "eda" / "qa_eda.json", _json, log),
        "interviews": _load(mem / "qa.json", _json, log),
        "eda_contrasts": _load(ex / "eda" / "settings_contrasts.csv", pl.read_csv, log),
        "eda_synchrony": _load(ex / "eda" / "synchrony.csv", pl.read_csv, log),
        "eda_profile": _load(ex / "eda" / "presses_profile.csv", pl.read_csv, log),
        "membrane_descriptives": _load(mem / "descriptives.csv", pl.read_csv, log),
        "membrane_agreement": _load(mem / "agreement.csv", pl.read_csv, log),
        "membrane_convergence": _load(mem / "convergence.csv", pl.read_csv, log),
        "membrane_behaviour": _load(mem / "behaviour.csv", pl.read_csv, log),
        "gradients_qa": _load(grad / "qa_gradients.json", _json, log),
        "gradient_pairs": _load(grad / "pair_effects.csv", pl.read_csv, log),
        "gradient_presses": _load(grad / "press_terciles.csv", pl.read_csv, log),
    }
    sections = {
        "data_state": data_state_rows(
            {k: src[k] for k in ("beacons", "presses", "survey", "eda", "interviews")},
            n_nodes,
            log,
        ),
        "gradient_pairs": [],
        "gradient_presses": [],
        "eda_press_profile": [],
        "membrane_reasons": [],
    }
    if src["gradient_pairs"] is not None:
        sections["gradient_pairs"] = gradient_pair_rows(src["gradient_pairs"], log)
    if src["gradient_presses"] is not None:
        sections["gradient_presses"] = gradient_press_rows(src["gradient_presses"], log)
    if src["eda_profile"] is not None:
        sections["eda_press_profile"] = eda_profile_rows(src["eda_profile"], log)
    if src["membrane_descriptives"] is not None:
        sections["membrane_reasons"] = reason_rows(src["membrane_descriptives"], log)
    return sections, src
