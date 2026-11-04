"""Cross-course mixing outside class hours, and without room neighbours. EXPLORATORY.

Research question: the exploratory item "The programme's rhythm" of ``research/analysis-plan.md``,
asked again after the beacon team's question: the reported cross-course share counts the whole camp
day, and courses sit together in class by design. How much of "special days mix more" is ordinary
days containing class? Do room neighbours, who sleep side by side whatever their course, matter?
Nothing here is a test: two-sided, effect sizes with 95 % bootstrap intervals, no p-values.

Unit: the person-period for the contrast, each person against themselves, special days against
ordinary days; the day for the daily shares. Definitions are ``exploratory_rhythm.py``'s: close
5-minute bins at -65 dBm or stronger from either partner, a tie at 60 close minutes in a camp day,
a day counting for a person seen for an hour, participants with ``beacons`` consent. A tie counts
only the minutes each exposure keeps, so a shorter day makes fewer ties; hence the 30-minute rows.

Exposures, as pair-bins kept:

* ``all_day``: as reported.
* ``class_only``: the timetabled course hours (``study.yaml``, ``course_hours``): a check that the
  clock finds class, where ties should barely cross courses.
* ``no_class``: without those hours. A special day keeps what its own timetable leaves, so the
  rotation slots and the excursion stay in.
* ``no_class_no_night``: also without 02:00-07:30.
* ``no_class_no_room``: ``no_class`` without pairs sharing a sleeping room.
* ``no_class_no_neighbours``: also without pairs in rooms numbered next to each other in the same
  list `[inferred]`: that numbers run along a corridor is a guess, and apartments are unknown.

Sleeping rooms are in the private roster (``context/personal/``), kept off the spine. They are read
at run time, held in memory, and only aggregates are written. The random-mixing share is not
adjusted for the pairs a room rule removes; they are a small part of all possible pairs.

Run after ``copresence_by_phase.py build`` and ``exploratory_rhythm.py``'s inputs. Writes
``daily.csv``, ``contrast.csv``, ``qa.json`` to
``$SOCIAL_ENERGY_DATA/dsa-2026/derived/analyses/exploratory/mixing-outside-class/``.

    uv run --extra analysis python studies/dsa-2026/analyses/exploratory_mixing_outside_class.py
"""

from __future__ import annotations

import json
import sys
from datetime import date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import polars as pl

sys.path.insert(0, str(Path(__file__).parent))
import copresence_by_phase as cp
import exploratory_rhythm as er

from social_energy import paths
from social_energy.outcomes import daily_close_ties, present_days
from social_energy.rhythm import daily_mixing, period_mixing
from social_energy.spine import Spine
from social_energy.study import StudyConfig

ROSTER_GLOB = "*StudyIDs*.md"
NIGHT = (time(2, 0), time(7, 30))
TIE_MINUTES = (60, 30)
EXPOSURES = (
    "all_day",
    "class_only",
    "no_class",
    "no_class_no_night",
    "no_class_no_room",
    "no_class_no_neighbours",
)


def course_windows(
    days: list[date], course_hours: dict, timezone: str
) -> list[tuple[datetime, datetime]]:
    """Each day's timetabled course hours in UTC, from ``study.yaml``'s ``course_hours``."""
    tz, utc = ZoneInfo(timezone), ZoneInfo("UTC")
    exceptions = {str(k): v for k, v in course_hours.get("exceptions", {}).items()}
    windows = []
    for day in days:
        for start, end in exceptions.get(str(day), course_hours["default"]):
            windows.append(
                tuple(
                    datetime.combine(day, time.fromisoformat(t), tz).astimezone(utc)
                    for t in (start, end)
                )
            )
    return windows


def in_windows(col: str, windows: list[tuple[datetime, datetime]]) -> pl.Expr:
    """True where ``col`` falls in one of the windows, start included."""
    expr = pl.lit(False)
    for start, end in windows:
        expr = expr | pl.col(col).is_between(start, end, closed="left")
    return expr


def sleeping_rooms(roster: str) -> dict[str, tuple[int, int]]:
    """Entity -> (which list, room number), from every roster table with a ``Zimmer`` column.

    Room numbers restart in each list, so a room is the pair. Rows without a numeric study ID or a
    numeric room are left out: they are not in the spine, or no room is known.
    """
    rooms: dict[str, tuple[int, int]] = {}
    header, which = None, 0
    for line in roster.splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if not line.startswith("|"):
            header = None
        elif "Zimmer" in cells and "Study-ID" in cells:
            header, which = cells, which + 1
        elif header and len(cells) == len(header):
            sid, room = cells[header.index("Study-ID")], cells[header.index("Zimmer")]
            if sid.isdigit() and room.isdigit():
                rooms[f"person:{sid}"] = (which, int(room))
    return rooms


def room_pairs(rooms: dict[str, tuple[int, int]], *, adjacent: bool = False) -> pl.Expr:
    """Whether a pair (columns ``a``, ``b``) shares a room, or with ``adjacent`` is next door.

    A person with no known room shares none.
    """
    reach = 1 if adjacent else 0
    near = [
        f"{a}|{b}"
        for a, (list_a, room_a) in rooms.items()
        for b, (list_b, room_b) in rooms.items()
        if a != b and list_a == list_b and abs(room_a - room_b) <= reach
    ]
    return pl.concat_str("a", "b", separator="|").is_in(near)


def exposures(
    pairs: pl.DataFrame,
    windows: list[tuple[datetime, datetime]],
    rooms: dict[str, tuple[int, int]],
    timezone: str,
) -> dict[str, pl.DataFrame]:
    """The pair-bins each exposure keeps."""
    in_class = in_windows("bin", windows)
    clock = pl.col("bin").dt.convert_time_zone(timezone).dt.time()
    night = clock.is_between(*NIGHT, closed="left")
    no_class = pairs.filter(~in_class)
    return {
        "all_day": pairs,
        "class_only": pairs.filter(in_class),
        "no_class": no_class,
        "no_class_no_night": no_class.filter(~night),
        "no_class_no_room": no_class.filter(~room_pairs(rooms)),
        "no_class_no_neighbours": no_class.filter(~room_pairs(rooms, adjacent=True)),
    }


def main() -> None:
    layout = paths.study(cp.STUDY)
    spine = Spine.load(layout.spine)
    study = StudyConfig.load(cp.STUDY_YAML)
    out = er.out_dir() / "mixing-outside-class"
    out.mkdir(parents=True, exist_ok=True)

    frame = spine.people_frame().filter(pl.col("role") == "participant")
    beacon_ok = {f"person:{p}" for p in spine.consented("beacons")}
    people = sorted(set(frame["entity"]) & beacon_ok)
    all_groups = dict(zip(frame["entity"], frame["course"], strict=True))
    groups = {p: all_groups[p] for p in people}
    in_days = pl.col("day").is_in(er.DAYS)
    pairs = cp.load_all("pairs").filter(
        pl.col("a").is_in(people) & pl.col("b").is_in(people) & in_days
    )
    seen = cp.load_all("seen").filter(pl.col("entity").is_in(people) & in_days)
    present = present_days(seen, min_bins=cp.PRESENT_MIN_BINS)

    roster = next((layout.root / "context" / "personal").glob(ROSTER_GLOB))
    rooms = {
        p: r for p, r in sleeping_rooms(roster.read_text(encoding="utf-8")).items() if p in groups
    }
    days = [er.ARRIVAL + timedelta(d) for d in range(len(er.DAYS) + 1)]
    windows = course_windows(days, study.raw["course_hours"], study.timezone)
    kept = exposures(pairs, windows, rooms, study.timezone)

    period_all = {d: er.kind_of(d) for d in er.DAYS if d != er.ARRIVAL}
    period_no_dip = {d: k for d, k in period_all.items() if d not in er.DIP}
    daily_rows, contrast_rows = [], []
    for name in EXPOSURES:
        for minutes in TIE_MINUTES:
            ties = daily_close_ties(
                kept[name],
                close_rssi=er.VARIANTS["main"]["close_rssi"],
                min_minutes=minutes,
                bin_minutes=er.BIN_MINUTES,
            )
            label = [pl.lit(name).alias("exposure"), pl.lit(minutes).alias("tie_minutes")]
            daily_rows.append(
                daily_mixing(ties, present, groups).with_columns(
                    *label,
                    pl.col("day").map_elements(er.kind_of, return_dtype=pl.String).alias("kind"),
                )
            )
            for days_label, period in (("all", period_all), ("without_24_27", period_no_dip)):
                pm = period_mixing(ties, present, groups, period)
                for special in er.SPECIAL.values():
                    contrast_rows.append(
                        {"exposure": name, "tie_minutes": minutes, "days": days_label}
                        | er.mixing_contrast(pm, special)
                    )
    pl.concat(daily_rows).sort("exposure", "tie_minutes", "day").write_csv(out / "daily.csv")
    pl.DataFrame(contrast_rows, infer_schema_length=None).write_csv(out / "contrast.csv")

    same = pairs.filter(room_pairs(rooms))
    known = [p for p in people if groups[p] is not None]
    qa = {
        "exploratory": True,
        "participants_with_beacon_consent": len(people),
        "with_course": len(known),
        "with_known_room": sum(p in rooms for p in known),
        "course_hour_windows": len(windows),
        "pair_bins": pairs.height,
        "pair_bins_kept": {k: v.height for k, v in kept.items()},
        "same_room_pairs_with_bins": same.select("a", "b").unique().height,
    }
    (out / "qa.json").write_text(json.dumps(qa, indent=2), encoding="utf-8")
    print(json.dumps(qa, indent=2))


if __name__ == "__main__":
    main()
