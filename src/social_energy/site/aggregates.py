"""The aggregates schema for the public site: camp-level numbers with a small-cell rule.

Every row names how many ``people`` stand behind it; a row with fewer than ``min_group``
people (or none stated) is dropped. Only the keys listed here can ever reach the site.
"""

from __future__ import annotations

import math
import random
import re

AGGREGATE_SECTIONS: dict[str, tuple[str, ...]] = {
    "day_phase": ("day", "phase", "people", "others", "share_no_one"),
    "daily_mixing": ("day", "kind", "people", "cross_share", "expected"),
    "persistence": ("origin", "people", "new_ties", "share", "lo", "hi"),
    "moments_latency": ("band", "people", "ratio", "ratio_lo", "ratio_hi"),
    "moments_size": ("size", "people", "ratio", "ratio_lo", "ratio_hi"),
    "moments_headline": ("people", "observed", "null_mean", "ratio", "lo", "hi"),
    "places": ("setting", "people", "rate", "lo", "hi"),
    # No label: the page names each test from the copy (``test_<id>``).
    "confirmatory": ("test", "people", "estimate", "lo", "hi", "scale"),
    # The team-meeting deck (static/deck/). ``raw`` and ``clean`` are record counts per source;
    # ``people`` is how many people the cleaned records cover.
    "data_state": ("source", "people", "raw", "clean"),
    # Partial r of membrane distance with close minutes, and its permutation null band.
    "gradient_pairs": ("measure", "sample", "people", "r", "null_lo", "null_hi"),
    # Co-press share (percent) by membrane-distance tercile, and its time-shuffle null.
    "gradient_presses": ("measure", "tercile", "people", "share", "time_null"),
    # Skin conductance around a press, minute offsets, against the shuffled-press band.
    "eda_press_profile": ("offset", "people", "observed", "null_lo", "null_hi"),
    # Share of interviewees (percent) naming what opens or closes their membrane.
    "membrane_reasons": ("reason", "direction", "people", "share"),
}
NUMBERS = "numbers"
SCALES = ("sd", "rr")
#: The copy's ``setting_<key>`` keys.
SETTINGS = (
    "plenum",
    "course_block",
    "meal_time",
    "kua_evening",
    "late_evening",
    "other_daytime",
    "night",
)
#: Kinds of day: ``origin_<key>`` in the copy, and ``label_<key>`` for the special ones.
DAY_KINDS = ("ordinary", "excursion", "rotation")
#: The pre-registered tests, by their ``test_<key>`` copy key.
TESTS = ("c1", "c2", "c4_trust", "c4_lust")
#: A lowercase ASCII word, as phase names are (``phase_<name>`` in the copy).
SAFE_NAME = re.compile(r"[a-z][a-z_]{0,31}")
#: A latency band or group size: a number, a range or an open end ("0-10", "3-4", "5+").
BAND = re.compile(r"\d{1,5}(-\d{1,5}|\+)?")
ISO_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
#: The deck's sources, membrane distances, samples and interview reasons (``deck_*`` copy).
DATA_SOURCES = ("beacons", "presses", "survey", "eda", "heart_rate", "interviews")
GRADIENT_MEASURES = ("trust", "lust", "trust_scales", "lust_scales", "all_scales")
GRADIENT_SAMPLES = ("all", "within", "between")
TERCILES = ("near", "middle", "far")
REASON_DIRECTIONS = ("opens", "closes")
REASONS = (
    "people",
    "programme",
    "arts",
    "vulnerability",
    "freedom",
    "being_heard",
    "course",
    "nature",
    "conflict",
    "fatigue",
    "withdrawal_need",
    "pressure",
    "safety",
    "loss",
    "end",
)
# Shares are percentages 0-100.
NUMBER_KEYS = (
    "n_participants",
    "n_presses",
    "n_confirmatory",
    "cascade_excess",
    "cascade_excess_lo",
    "cascade_excess_hi",
    "latency_0_10_ratio",
    "mixing_ordinary_lo",
    "mixing_ordinary_hi",
    "mixing_random",
    "mixing_excursion",
    "mixing_rotation",
    "persistence_ordinary",
    "persistence_excursion",
    "company_gain",
    "plenum_vs_course",
    # The team-meeting deck. Shares are percentages 0-100; rho, r and SD effects as they are.
    "beacon_reboots",
    "eda_wearers",
    "eda_certain_wearers",
    "hr_wearers",
    "eda_usable_minutes",
    "eda_clock_sync_pct",
    "eda_clock_rate_pct",
    "eda_clock_box_pct",
    "eda_clock_uncertain_pct",
    "eda_presses",
    "eda_pressers",
    "eda_meal_scr",
    "eda_meal_scr_lo",
    "eda_meal_scr_hi",
    "eda_meal_hr",
    "eda_sync_close",
    "eda_sync_apart",
    "interviews_coded",
    "interviews_people",
    "membrane_opened_pct",
    "membrane_stable_pct",
    "membrane_selective_pct",
    "membrane_kappa_now",
    "membrane_trust_rho",
    "membrane_trust_rho_lo",
    "membrane_trust_rho_hi",
    "membrane_lust_rho",
    "membrane_mixing_sd",
    "membrane_mixing_sd_lo",
    "membrane_mixing_sd_hi",
    "gradient_people",
    "gradient_pairs",
    "gradient_trust_scales_pct",
    "gradient_trust_scales_within_pct",
    "gradient_excess_near",
    "gradient_excess_far",
)


#: Deck numbers that are counts (whole numbers in the synthetic demo).
DECK_COUNTS = (
    "beacon_reboots",
    "eda_wearers",
    "eda_certain_wearers",
    "hr_wearers",
    "eda_usable_minutes",
    "eda_presses",
    "eda_pressers",
    "interviews_coded",
    "interviews_people",
    "gradient_people",
    "gradient_pairs",
)


def is_number(v: object) -> bool:
    return isinstance(v, int | float) and not isinstance(v, bool) and math.isfinite(v)


def _index_or(pattern: re.Pattern):
    def ok(v: object) -> bool:
        if isinstance(v, int) and not isinstance(v, bool):
            return 0 <= v < 1000
        return isinstance(v, str) and pattern.fullmatch(v) is not None

    return ok


def _one_of(values: tuple[str, ...]):
    return lambda v: isinstance(v, str) and v in values


def _matches(pattern: re.Pattern):
    return lambda v: isinstance(v, str) and pattern.fullmatch(v) is not None


#: The categorical fields and what they may hold; every other field must be a finite number.
CATEGORIES = {
    "day": _index_or(ISO_DATE),
    "phase": _index_or(SAFE_NAME),
    "kind": _one_of(DAY_KINDS),
    "origin": _one_of(DAY_KINDS),
    "setting": _one_of(SETTINGS),
    "test": _one_of(TESTS),
    "scale": _one_of(SCALES),
    "band": _matches(BAND),
    "size": _matches(BAND),
    "source": _one_of(DATA_SOURCES),
    "measure": _one_of(GRADIENT_MEASURES),
    "sample": _one_of(GRADIENT_SAMPLES),
    "tercile": _one_of(TERCILES),
    "reason": _one_of(REASONS),
    "direction": _one_of(REASON_DIRECTIONS),
}


def bad_field(row: dict, allowed: tuple[str, ...]) -> str | None:
    """The first field of ``row`` that is unknown or holds a value the site may not show."""
    for key, value in row.items():
        if key not in allowed:
            return key
        check = CATEGORIES.get(key, is_number)
        if not check(value):
            return key
    return None


def check_aggregates(agg: dict, min_group: int = 5) -> dict:
    """Copy of ``agg`` with small or unstated-people rows dropped and unknown keys removed."""
    out = {}
    for section, rows in agg.items():
        if section == NUMBERS:
            out[section] = {k: v for k, v in rows.items() if k in NUMBER_KEYS and is_number(v)}
        elif section in AGGREGATE_SECTIONS:
            allowed = AGGREGATE_SECTIONS[section]
            kept = (
                # A missing value (None) is left out, as a key the row never had.
                {k: v for k, v in row.items() if k in allowed and v is not None}
                for row in rows
                if is_number(row.get("people"))
                and row["people"] >= min_group
                and not row.get("suppressed")
            )
            # A value outside its enumeration, or not a finite number, drops the whole row.
            out[section] = [row for row in kept if bad_field(row, allowed) is None]
    return out


def synthetic_aggregates(
    seed: int = 0, *, n_participants: int = 60, n_presses: int | None = None
) -> dict:
    """Plausible random values for every section; ``5 <= people <= n_participants``.

    For previews and tests. Pass the synthetic camp's node and press counts so the copy's
    numbers describe the camp the hero plays.
    """
    rng = random.Random(seed)

    def people() -> int:
        return rng.randint(5, n_participants)

    def val(lo: float, hi: float) -> float:
        return round(rng.uniform(lo, hi), 3)

    def synthetic_number(key: str) -> float:
        # Counts are integers, ratios sit near 1, company_gain may take either sign, the rest
        # are shares in percent.
        if key.startswith("n_") or key in DECK_COUNTS:
            return rng.randint(30, 600)
        if key.startswith(("eda_meal", "eda_sync", "membrane_trust", "membrane_lust")):
            return val(-0.4, 0.4)
        if key.startswith("membrane_mixing") or key == "membrane_kappa_now":
            return val(0.05, 0.9)
        if key.startswith("gradient_") and key.endswith("_pct"):
            return val(-9, 2)
        if key.startswith("gradient_excess"):
            return val(1, 3)
        if key.startswith(("cascade_", "latency_", "plenum_")):
            return val(0.5, 3)
        if key == "company_gain":
            return val(-2, 2)
        # Shares in percent, in the ranges the synthetic rows use.
        ranges = {
            "mixing_ordinary_lo": (8, 15),
            "mixing_ordinary_hi": (15, 22),
            "mixing_random": (55, 62),
            "mixing_excursion": (40, 65),
            "mixing_rotation": (20, 40),
        }
        return val(*ranges.get(key, (15, 60)))

    def around(lo: float, hi: float, w_lo: float, w_hi: float) -> dict:
        est = rng.uniform(lo, hi)
        a, b = est - rng.uniform(w_lo, w_hi), est + rng.uniform(w_lo, w_hi)
        return {
            "estimate": round(est, 3),
            "lo": round(max(a, 0.05) if lo > 0 else a, 3),
            "hi": round(b, 3),
        }

    def ratio_row(key: str, value: str) -> dict:
        est = around(0.5, 3, 0.2, 0.8)
        return {
            key: value,
            "people": people(),
            "ratio": est["estimate"],
            "ratio_lo": est["lo"],
            "ratio_hi": est["hi"],
        }

    latency = [ratio_row("band", b) for b in ("0-10", "10-30", "30-60")]
    size = [ratio_row("size", s) for s in ("2", "3-4", "5+")]
    est = around(0.8, 2.5, 0.1, 0.5)
    null_mean = val(20, 120)
    headline = {
        "people": people(),
        "observed": round(null_mean * est["estimate"], 3),
        "null_mean": null_mean,
        "ratio": est["estimate"],
        "lo": est["lo"],
        "hi": est["hi"],
    }

    mixing = [
        {
            "day": d,
            "kind": "excursion" if d == 1 else "ordinary",
            "people": people(),
            "cross_share": val(40, 65) if d == 1 else val(8, 22),
            "expected": val(55, 62),
        }
        for d in range(4)
    ]
    persistence = [
        {
            "origin": o,
            "people": people(),
            "new_ties": val(0, 10),
            "share": est["estimate"],
            "lo": est["lo"],
            "hi": est["hi"],
        }
        for o in ("ordinary", "excursion")
        for est in [around(15, 60, 4, 12)]
    ]

    numbers = {k: synthetic_number(k) for k in NUMBER_KEYS}
    numbers.update(_synthetic_deck_numbers(rng))
    numbers["n_participants"] = n_participants
    if n_presses is not None:
        numbers["n_presses"] = n_presses
    # The copy's numbers are the rows the charts draw, so text and chart agree.
    numbers["cascade_excess"] = headline["ratio"]
    numbers["cascade_excess_lo"] = headline["lo"]
    numbers["cascade_excess_hi"] = headline["hi"]
    numbers["latency_0_10_ratio"] = latency[0]["ratio"]
    ordinary = [r["cross_share"] for r in mixing if r["kind"] == "ordinary"]
    numbers["mixing_ordinary_lo"] = min(ordinary)
    numbers["mixing_ordinary_hi"] = max(ordinary)
    numbers["mixing_random"] = round(sum(r["expected"] for r in mixing) / len(mixing), 3)
    numbers["mixing_excursion"] = next(r["cross_share"] for r in mixing if r["kind"] == "excursion")
    for r in persistence:
        numbers[f"persistence_{r['origin']}"] = r["share"]
    # One sample for all four tests, as in the study, and the copy's count is that sample.
    n_confirmatory = people()
    numbers["n_confirmatory"] = n_confirmatory
    return {
        # Four camp days and six daytime phases (indices into meta.phases), day 1 the special
        # day, as in the synthetic camp that build.py writes.
        "day_phase": [
            {
                "day": d,
                "phase": p,
                "people": people(),
                "others": val(0, 8),
                "share_no_one": val(0, 100),
            }
            for d in range(4)
            for p in range(6)
        ],
        "daily_mixing": mixing,
        "persistence": persistence,
        "moments_latency": latency,
        "moments_size": size,
        "moments_headline": [headline],
        "places": [
            {
                "setting": s,
                "people": people(),
                "rate": est["estimate"],
                "lo": est["lo"],
                "hi": est["hi"],
            }
            for s in (
                "plenum",
                "course_block",
                "meal_time",
                "kua_evening",
                "late_evening",
                "other_daytime",
            )
            for est in [around(0.5, 5, 0.2, 1)]
        ],
        # Effects in SD around 0; rate ratios around 1 (always positive). Each interval holds
        # its estimate.
        "confirmatory": [
            {"test": t, "people": n_confirmatory, "scale": sc, **around(*null_band)}
            for t, sc, null_band in (
                ("c1", "sd", (-0.6, 0.6, 0.1, 0.45)),
                ("c2", "sd", (-0.6, 0.6, 0.1, 0.45)),
                ("c4_trust", "rr", (0.6, 1.6, 0.15, 0.5)),
                ("c4_lust", "rr", (0.6, 1.6, 0.15, 0.5)),
            )
        ],
        **_synthetic_deck_sections(rng, people),
        NUMBERS: numbers,
    }


def _synthetic_deck_numbers(rng: random.Random) -> dict:
    """Deck numbers that must agree with each other: EDA clock shares sum to 100."""
    sync = round(rng.uniform(40, 70), 1)
    rate = round(rng.uniform(15, 100 - sync - 5), 1)
    return {
        "eda_clock_sync_pct": sync,
        "eda_clock_rate_pct": rate,
        "eda_clock_box_pct": round(100 - sync - rate, 1),
        "eda_clock_uncertain_pct": round(100 - sync, 1),
    }


def _synthetic_deck_sections(rng: random.Random, people) -> dict:
    """Invented rows for the deck's charts, with the same schema the export writes."""

    def val(lo: float, hi: float) -> float:
        return round(rng.uniform(lo, hi), 3)

    state = []
    for source in DATA_SOURCES:
        raw = rng.randint(50, 50_000)
        state.append(
            {"source": source, "people": people(), "raw": raw,
             "clean": round(raw * rng.uniform(0.4, 0.98))}
        )  # fmt: skip
    pairs = []
    for measure in GRADIENT_MEASURES:
        for sample in GRADIENT_SAMPLES:
            half = val(0.03, 0.1)
            pairs.append(
                {"measure": measure, "sample": sample, "people": people(),
                 "r": val(-half * 1.2, half * 1.2), "null_lo": -half, "null_hi": half}
            )  # fmt: skip
    presses = []
    for measure in ("trust", "lust"):
        for tercile in TERCILES:
            null = val(2, 5)
            presses.append(
                {"measure": measure, "tercile": tercile, "people": people(),
                 "share": round(null * rng.uniform(1.4, 2.6), 3), "time_null": null}
            )  # fmt: skip
    profile = []
    for offset in range(-10, 11):
        half = val(0.15, 0.3)
        profile.append(
            {"offset": offset, "people": people(), "observed": val(-half, half),
             "null_lo": -half, "null_hi": half}
        )  # fmt: skip
    reasons = [
        {"reason": r, "direction": d, "people": people(), "share": val(10, 90)}
        for r, d in (
            ("people", "opens"), ("programme", "opens"), ("arts", "opens"),
            ("freedom", "opens"), ("being_heard", "opens"), ("conflict", "closes"),
            ("fatigue", "closes"), ("pressure", "closes"),
        )
    ]  # fmt: skip
    return {
        "data_state": state,
        "gradient_pairs": pairs,
        "gradient_presses": presses,
        "eda_press_profile": profile,
        "membrane_reasons": reasons,
    }
