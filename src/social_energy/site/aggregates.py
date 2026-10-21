"""The aggregates schema for the public site: camp-level numbers with a small-cell rule.

Every row names how many ``people`` stand behind it; a row with fewer than ``min_group``
people (or none stated) is dropped. Only the keys listed here can ever reach the site.
"""

from __future__ import annotations

import copy
import math
import random

AGGREGATE_SECTIONS: dict[str, tuple[str, ...]] = {
    "day_phase": ("day", "phase", "people", "others", "share_no_one"),
    "daily_mixing": ("day", "kind", "people", "cross_share", "expected"),
    "persistence": ("origin", "people", "new_ties", "share", "lo", "hi"),
    "moments_latency": ("band", "people", "ratio", "ratio_lo", "ratio_hi"),
    "moments_size": ("size", "people", "ratio", "ratio_lo", "ratio_hi"),
    "moments_headline": ("people", "observed", "null_mean", "ratio", "lo", "hi"),
    "places": ("setting", "people", "rate", "lo", "hi"),
    "confirmatory": ("test", "label", "people", "estimate", "lo", "hi", "scale"),
}
NUMBERS = "numbers"
SCALES = ("sd", "rr")
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
)


def is_number(v: object) -> bool:
    return isinstance(v, int | float) and not isinstance(v, bool) and math.isfinite(v)


def check_aggregates(agg: dict, min_group: int = 5) -> dict:
    """Copy of ``agg`` with small or unstated-people rows dropped and unknown keys removed."""
    out = {}
    for section, rows in agg.items():
        if section == NUMBERS:
            out[section] = {k: v for k, v in rows.items() if k in NUMBER_KEYS and is_number(v)}
        elif section in AGGREGATE_SECTIONS:
            allowed = AGGREGATE_SECTIONS[section]
            out[section] = [
                {k: copy.deepcopy(v) for k, v in row.items() if k in allowed}
                for row in rows
                if is_number(row.get("people"))
                and row["people"] >= min_group
                and not row.get("suppressed")
            ]
    return out


def synthetic_aggregates(seed: int = 0) -> dict:
    """Plausible random values for every section; ``people >= 5``. For previews and tests."""
    rng = random.Random(seed)

    def people() -> int:
        return rng.randint(5, 60)

    def ci(lo: float, hi: float) -> dict:
        a, b = sorted((rng.uniform(lo, hi), rng.uniform(lo, hi)))
        return {"lo": round(a, 3), "hi": round(b, 3)}

    def val(lo: float, hi: float) -> float:
        return round(rng.uniform(lo, hi), 3)

    def synthetic_number(key: str) -> float:
        # Counts are integers, ratios sit near 1, company_gain may take either sign, the rest
        # are shares in percent.
        if key.startswith("n_"):
            return rng.randint(30, 600)
        if key.startswith(("cascade_", "latency_", "plenum_")):
            return val(0.5, 3)
        if key == "company_gain":
            return val(-2, 2)
        return val(0, 100)

    def around(lo: float, hi: float, w_lo: float, w_hi: float) -> dict:
        est = rng.uniform(lo, hi)
        a, b = est - rng.uniform(w_lo, w_hi), est + rng.uniform(w_lo, w_hi)
        return {
            "estimate": round(est, 3),
            "lo": round(max(a, 0.05) if lo > 0 else a, 3),
            "hi": round(b, 3),
        }

    numbers = {k: synthetic_number(k) for k in NUMBER_KEYS}
    # A range reads lo <= value <= hi.
    trio = ("cascade_excess_lo", "cascade_excess", "cascade_excess_hi")
    numbers.update(zip(trio, sorted(numbers[k] for k in trio), strict=True))
    pair = ("mixing_ordinary_lo", "mixing_ordinary_hi")
    numbers.update(zip(pair, sorted(numbers[k] for k in pair), strict=True))
    return {
        "day_phase": [
            {
                "day": d,
                "phase": p,
                "people": people(),
                "others": val(0, 8),
                "share_no_one": val(0, 100),
            }
            for d in range(3)
            for p in range(2)
        ],
        "daily_mixing": [
            {
                "day": d,
                "kind": k,
                "people": people(),
                "cross_share": val(0, 100),
                "expected": val(0, 100),
            }
            for d in range(3)
            for k in ("ordinary", "excursion")
        ],
        "persistence": [
            {
                "origin": o,
                "people": people(),
                "new_ties": val(0, 10),
                "share": val(0, 100),
                **ci(0, 100),
            }
            for o in ("ordinary", "excursion")
        ],
        "moments_latency": [
            {
                "band": b,
                "people": people(),
                "ratio": val(0.5, 3),
                "ratio_lo": val(0.3, 1),
                "ratio_hi": val(1, 4),
            }
            for b in ("0-10", "10-30", "30-60")
        ],
        "moments_size": [
            {
                "size": s,
                "people": people(),
                "ratio": val(0.5, 3),
                "ratio_lo": val(0.3, 1),
                "ratio_hi": val(1, 4),
            }
            for s in ("2", "3-4", "5+")
        ],
        "moments_headline": [
            {
                "people": people(),
                "observed": val(0, 200),
                "null_mean": val(0, 200),
                "ratio": val(0.5, 3),
                **ci(0.3, 4),
            }
        ],
        "places": [
            {"setting": s, "people": people(), "rate": val(0, 5), **ci(0, 5)}
            for s in ("dining", "lecture", "outdoors")
        ],
        # Effects in SD around 0; rate ratios around 1 (always positive). Each interval holds
        # its estimate.
        "confirmatory": [
            {"test": t, "label": t, "people": people(), "scale": sc, **around(*null_band)}
            for t, sc, null_band in (
                ("c1", "sd", (-0.6, 0.6, 0.1, 0.45)),
                ("c2", "sd", (-0.6, 0.6, 0.1, 0.45)),
                ("c4_trust", "rr", (0.6, 1.6, 0.15, 0.5)),
                ("c4_lust", "rr", (0.6, 1.6, 0.15, 0.5)),
            )
        ],
        NUMBERS: numbers,
    }
