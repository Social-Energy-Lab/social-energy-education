"""The person view's part of the explorer bundle: one person, their moments, the people around.

Team mode only. ``write_bundle`` calls ``write_person`` when its input carries ``PersonData``;
the public bundle (``site.public``) never reads it. Everything here is keyed by the same shuffled
node index as the rest of the bundle, so the views can jump between each other.

What the caller passes, already filtered by the analyses' own rules (participants only,
exclusion windows applied):

* ``consent``: per module, the entities allowed in it. Applied here again, so a table that
  slipped past the caller's filter is dropped and counted in the QA, never shown.
* ``attributes``: age and gender per entity (course is already a node attribute).
* ``scales``: what the survey measures, in display order (key, label, block ``trust`` or
  ``lust``, kind, whether it is in the composite, item codes, range). No item wording.
* ``composites``, ``scale_scores`` and ``items``: per entity and ``wave``. Scales and composites
  get a z-score against the bundle's people with a value (the camp), per wave.
* ``membrane``: interview codes per entity, as plain values. Free text is refused: every key and
  string value must be a short token or a date, so no evidence, quote or note can ride along.
* ``interviews``: when each entity's interview started (UTC).
* ``eda``: one row per worn person-minute outside exclusions (``minute`` UTC, ``scr`` and
  ``scr_strict`` in SCRs per minute when the minute is usable, ``hr`` in bpm when it is an HR
  minute, ``usable``, ``hr_ok``, ``clock_uncertain``).
* ``events``: programme items (label, kind, start, end, ``end_known``, ``all_camp``,
  ``locations``), ends already filled the way the analyses fill them.

Layout added to the bundle:

    eda.bin      min u32 · node u16 · scr u16 · scr_strict u16 · hr u8 · flags u8
                 (minutes since t0; rates x100, 65535 = none; hr 0 = none;
                  flags 1 usable, 2 hr_ok, 4 clock_uncertain; sorted by node, then minute)
    person.json  scales, waves, events, the moment rule, and one entry per node
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import numpy as np
import polars as pl

PERSON_VERSION = 1
NONE_U16 = 65535
EDA_COLUMNS = [
    ("min", "u32"),
    ("node", "u16"),
    ("scr", "u16"),
    ("scr_strict", "u16"),
    ("hr", "u8"),
    ("flags", "u8"),
]
USABLE, HR_OK, CLOCK_UNCERTAIN = 1, 2, 4
#: The ``eda`` input table.
EDA_SCHEMA = {
    "entity": pl.String,
    "minute": pl.Datetime("us", "UTC"),
    "scr": pl.Float64,
    "scr_strict": pl.Float64,
    "hr": pl.Float64,
    "usable": pl.Boolean,
    "hr_ok": pl.Boolean,
    "clock_uncertain": pl.Boolean,
}
#: Modules the person view reads, each gating its own part of a person's entry.
MODULES = ("survey", "interview_in_person", "eda", "self_report")
#: Membrane codes: keys and string values must look like this, so free text cannot pass.
TOKEN = re.compile(r"[A-Za-z][A-Za-z0-9_]{0,31}")
DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
#: How the view finds EDA moments (third-person "special moments"): exploratory, not validated.
DEFAULT_MOMENT_RULE = {
    # SCR rate at least this many SDs above the person-day's mean. 2.0 fired ~8 times per
    # person-day on DSA 2026, several times the button-press rate; 2.5 gives ~3, about the same.
    "z": 2.5,
    "min_usable_minutes": 30,  # a person-day needs this many usable minutes to have moments
    "merge_minutes": 2,  # moment minutes this close join one moment, timed at its first
}


class PersonDataError(ValueError):
    """Person data the bundle must not carry."""


@dataclass(frozen=True)
class PersonData:
    consent: dict[str, frozenset[str]]
    attributes: dict[str, dict] = field(default_factory=dict)
    scales: list[dict] = field(default_factory=list)
    composites: pl.DataFrame | None = None  # entity, wave, trust, lust
    scale_scores: pl.DataFrame | None = None  # entity, wave, group, mean
    items: pl.DataFrame | None = None  # entity, wave, group, item, value
    membrane: dict[str, dict] = field(default_factory=dict)
    interviews: dict[str, datetime] = field(default_factory=dict)
    eda: pl.DataFrame | None = None
    events: pl.DataFrame | None = None
    moment_rule: dict = field(default_factory=lambda: dict(DEFAULT_MOMENT_RULE))
    #: Shown with the profile, e.g. that no post wave was fielded.
    notes: dict[str, str] = field(default_factory=dict)


def check_codes(value: object, where: str = "membrane") -> None:
    """Raise unless ``value`` holds only numbers, booleans, None, tokens and dates."""
    if value is None or isinstance(value, bool | int | float):
        return
    if isinstance(value, str):
        if TOKEN.fullmatch(value) or DATE.fullmatch(value):
            return
        raise PersonDataError(f"{where}: {value[:12]!r}... is not a code (free text refused)")
    if isinstance(value, list):
        for i, v in enumerate(value):
            check_codes(v, f"{where}[{i}]")
        return
    if isinstance(value, dict):
        for k, v in value.items():
            if not isinstance(k, str) or not TOKEN.fullmatch(k):
                raise PersonDataError(f"{where}: key {str(k)[:12]!r} is not a code")
            check_codes(v, f"{where}.{k}")
        return
    raise PersonDataError(f"{where}: {type(value).__name__} is not allowed")


def _z(values: dict[str, float]) -> dict[str, float | None]:
    xs = np.array([v for v in values.values() if v is not None and np.isfinite(v)], dtype=float)
    if len(xs) < 2 or xs.std(ddof=1) == 0:
        return {e: None for e in values}
    mu, sd = xs.mean(), xs.std(ddof=1)
    return {e: (None if v is None or not np.isfinite(v) else float((v - mu) / sd))
            for e, v in values.items()}  # fmt: skip


def _round(x: float | None, nd: int = 3) -> float | None:
    return None if x is None or not np.isfinite(x) else round(float(x), nd)


def _survey(
    data: PersonData, allowed: set[str]
) -> tuple[dict[str, dict], list[str], dict, dict[str, int]]:
    """Per entity and wave: composites, scales and items with z vs the camp; item means."""
    out: dict[str, dict] = {}
    waves: list[str] = []
    item_means: dict = {}
    qa = {"survey_rows_without_consent": 0}
    frames = [f for f in (data.composites, data.scale_scores, data.items) if f is not None]
    for f in frames:
        qa["survey_rows_without_consent"] += f.filter(~pl.col("entity").is_in(allowed)).height
        waves += [w for w in f["wave"].unique().sort().to_list() if w not in waves]
    for wave in waves:
        if data.composites is not None:
            c = data.composites.filter((pl.col("wave") == wave) & pl.col("entity").is_in(allowed))
            for block in ("trust", "lust"):
                raw = dict(zip(c["entity"], c[block], strict=True))
                z = _z(raw)
                for e, v in raw.items():
                    if v is None:
                        continue
                    w = out.setdefault(e, {}).setdefault(wave, {})
                    w[block] = [_round(v), _round(z[e])]
        if data.scale_scores is not None:
            s = data.scale_scores.filter((pl.col("wave") == wave) & pl.col("entity").is_in(allowed))
            for group, g in s.group_by("group"):
                raw = dict(zip(g["entity"], g["mean"], strict=True))
                z = _z(raw)
                for e, v in raw.items():
                    if v is None:
                        continue
                    w = out.setdefault(e, {}).setdefault(wave, {}).setdefault("scales", {})
                    w[group[0]] = [_round(v), _round(z[e])]
        if data.items is not None:
            order = {s["key"]: list(s.get("items", [])) for s in data.scales}
            it = data.items.filter((pl.col("wave") == wave) & pl.col("entity").is_in(allowed))
            means = {}
            for (e, group), g in it.group_by("entity", "group"):
                codes = order.get(group)
                if not codes:
                    continue
                val = dict(zip(g["item"], g["value"], strict=True))
                row = [_round(val.get(code), 2) for code in codes]
                w = out.setdefault(e, {}).setdefault(wave, {}).setdefault("items", {})
                w[group] = row
            for group, codes in order.items():
                g = it.filter(pl.col("group") == group)
                if g.height:
                    m = g.group_by("item").agg(pl.col("value").mean())
                    mm = dict(zip(m["item"], m["value"], strict=True))
                    means[group] = [_round(mm.get(code), 2) for code in codes]
            item_means[wave] = means
    return out, waves, item_means, qa


def _types(survey: dict[str, dict], wave: str) -> dict[str, dict[str, str]]:
    """High or low trust and lust per entity: at or above the camp median is high."""
    out: dict[str, dict[str, str]] = {}
    for block in ("trust", "lust"):
        vals = {e: w[wave][block][0] for e, w in survey.items() if block in w.get(wave, {})}
        if not vals:
            continue
        med = float(np.median(list(vals.values())))
        for e, v in vals.items():
            out.setdefault(e, {})[block] = "high" if v >= med else "low"
    return {e: t for e, t in out.items() if len(t) == 2}


def eda_frame(
    eda: pl.DataFrame, node_of: dict[str, int], allowed: set[str], t0: datetime, n_min: int
) -> tuple[dict[str, np.ndarray], dict[str, int]]:
    """The eda table's columns (sorted by node, then minute) and the rows it dropped."""
    qa = {"eda_minutes_without_consent": eda.filter(~pl.col("entity").is_in(allowed)).height}
    t0e = pl.lit(t0).dt.convert_time_zone("UTC")
    e = eda.filter(pl.col("entity").is_in(allowed)).with_columns(
        ((pl.col("minute") - t0e).dt.total_seconds() // 60).alias("m"),
        pl.col("entity").replace_strict(node_of, default=None, return_dtype=pl.Int64).alias("n"),
    )
    qa["eda_minutes_no_node"] = e.filter(pl.col("n").is_null()).height
    e = e.filter(pl.col("n").is_not_null())
    in_range = (pl.col("m") >= 0) & (pl.col("m") < n_min)
    qa["eda_minutes_out_of_range"] = e.filter(~in_range).height
    e = e.filter(in_range).unique(["n", "m"]).sort("n", "m")

    def rate(col: str) -> np.ndarray:
        x = e[col].cast(pl.Float64).to_numpy()
        ok = np.isfinite(x) & e["usable"].to_numpy()
        return np.where(ok, np.clip(np.round(x * 100), 0, NONE_U16 - 1), NONE_U16)

    hr = e["hr"].cast(pl.Float64).to_numpy()
    hr_ok = np.isfinite(hr) & e["hr_ok"].to_numpy()
    flags = (
        e["usable"].to_numpy().astype(np.uint8) * USABLE
        + hr_ok.astype(np.uint8) * HR_OK
        + e["clock_uncertain"].fill_null(True).to_numpy().astype(np.uint8) * CLOCK_UNCERTAIN
    )
    cols = {
        "min": e["m"].to_numpy(),
        "node": e["n"].to_numpy(),
        "scr": rate("scr"),
        "scr_strict": rate("scr_strict"),
        "hr": np.where(hr_ok, np.clip(np.round(np.nan_to_num(hr)), 1, 255), 0),
        "flags": flags,
    }
    return cols, qa


def _events(events: pl.DataFrame | None, to_bin, loc_of: dict[str, int], n_bins: int) -> list:
    if events is None:
        return []
    out = []
    for r in events.sort("start").iter_rows(named=True):
        a, b = to_bin(r["start"]), to_bin(r["end"])
        if b <= 0 or a >= n_bins:
            continue
        out.append({
            "label": r["label"],
            "kind": r["kind"],
            "start_bin": max(a, 0),
            "end_bin": min(max(b, a + 1), n_bins),
            "end_known": bool(r["end_known"]),
            "all_camp": bool(r["all_camp"]),
            "locs": sorted(loc_of[x] for x in (r["locations"] or []) if x in loc_of),
        })  # fmt: skip
    return out


def person_json(
    data: PersonData,
    node_of: dict[str, int],
    loc_of: dict[str, int],
    *,
    t0: datetime,
    bin_seconds: int,
    n_bins: int,
) -> tuple[dict, dict[str, int]]:
    """The ``person.json`` document and its QA counts."""
    unknown = sorted(set(data.consent) - set(MODULES))
    if unknown:
        raise PersonDataError(f"unknown consent modules: {unknown}")
    allowed = {m: set(data.consent.get(m, ())) for m in MODULES}
    survey, waves, item_means, qa = _survey(data, allowed["survey"])
    first_wave = waves[0] if waves else None
    types = _types(survey, first_wave) if first_wave else {}

    membrane = {}
    qa["membrane_without_consent"] = 0
    for e, codes in data.membrane.items():
        if e not in allowed["interview_in_person"]:
            qa["membrane_without_consent"] += 1
            continue
        check_codes(codes, f"membrane of node {node_of.get(e, '?')}")
        membrane[e] = codes
    interviews = {e: t for e, t in data.interviews.items() if e in allowed["interview_in_person"]}

    people = [None] * len(node_of)
    for e, i in node_of.items():
        attrs = data.attributes.get(e, {})
        t = interviews.get(e)
        people[i] = {
            "age": attrs.get("age"),
            "gender": attrs.get("gender"),
            "survey": survey.get(e),
            "type": types.get(e),
            "membrane": membrane.get(e),
            "interview_sec": None if t is None else int((t - t0).total_seconds()),
            "eda": e in allowed["eda"],
            "self_report": e in allowed["self_report"],
        }
    for p in people:
        check_codes(p["gender"], "gender")
        if p["age"] is not None and not isinstance(p["age"], int):
            raise PersonDataError("age must be whole years")

    def to_bin(t: datetime) -> int:
        return int((t - t0).total_seconds() // bin_seconds)

    doc = {
        "version": PERSON_VERSION,
        "waves": waves,
        "scales": data.scales,
        "item_means": item_means,
        "events": _events(data.events, to_bin, loc_of, n_bins),
        "moment_rule": data.moment_rule,
        "notes": data.notes,
        "people": people,
    }
    qa |= {
        "person_survey": sum(1 for p in people if p["survey"]),
        "person_membrane": sum(1 for p in people if p["membrane"]),
        "person_eda": sum(1 for p in people if p["eda"]),
    }
    return doc, qa


def write_person_json(out_dir: Path, doc: dict) -> None:
    text = json.dumps(doc, separators=(",", ":"), allow_nan=False)
    (out_dir / "person.json").write_text(text, encoding="utf-8")
