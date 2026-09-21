"""A synthetic camp with known ground truth.

It writes a spine and beacon logs in the exact text format of the real logger,
reproducing the traps seen in the field: a tag reboot, a mid-camp tag swap, a lost
tag that keeps recording, and the logger bug that printed IDs 48-57 as "0"-"9".

Tests use it as an oracle. Ingest the logs, resolve them through the spine, and
check that the true contacts come back. Contacts are recorded between everyone in
the same location at each scan, so with ``detection_p=1`` the truth is exact.
Location tags advertise but are not read out.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import polars as pl
import yaml


@dataclass(frozen=True)
class CampSpec:
    start: datetime = datetime(2026, 8, 14, 8, 0, 0)  # local wall-clock time
    hours: int = 12
    timezone: str = "Europe/Berlin"
    # Person IDs double as their first beacon IDs (as at DSA 2026). 44..55 crosses
    # the 48-57 range affected by the logger ID bug.
    people: tuple[int, ...] = tuple(range(44, 56))
    rooms: tuple[tuple[int, str], ...] = ((114, "course-a"), (115, "course-b"), (116, "plenum"))
    scan_interval_s: int = 300
    readout_every_h: int = 3
    detection_p: float = 1.0
    self_reports_per_person: int = 2
    seed: int = 7
    # (beacon, hours after start): the tag reboots, uptime restarts at 0
    reboot: tuple[int, float] | None = (45, 4.5)
    # (person, new beacon, hours after start): the person's tag is replaced
    swap: tuple[int, int, float] | None = (46, 99, 5.0)
    # (person, from h, to h): the tag is lost; it lies in course-a and keeps recording
    lost: tuple[int, float, float] | None = (47, 2.0, 4.0)
    # hours after start before which the logger prints IDs 48..57 as "0".."9"
    id_bug_until_h: float | None = 7.0


@dataclass
class SyntheticCamp:
    spec: CampSpec
    spine_dir: Path
    log_paths: list[Path]
    truth_contacts: pl.DataFrame  # observer_entity, observed_entity, t (UTC)
    truth_self_reports: pl.DataFrame  # entity, t (UTC)
    id_bug_cutoff: datetime | None  # local wall-clock time
    notes: dict[str, object] = field(default_factory=dict)


def _local_str(t: datetime) -> str:
    return t.strftime("%Y-%m-%d %H:%M:%S")


def _validate(spec: CampSpec) -> None:
    room_tags = {tag for tag, _ in spec.rooms}
    if room_tags & set(spec.people):
        raise ValueError(f"room tags {sorted(room_tags & set(spec.people))} collide with people")
    if spec.swap and (spec.swap[1] in spec.people or spec.swap[1] in room_tags):
        raise ValueError(f"swap beacon {spec.swap[1]} is already in use")


def generate(spec: CampSpec, out_dir: Path) -> SyntheticCamp:
    _validate(spec)
    rng = random.Random(spec.seed)
    tz = ZoneInfo(spec.timezone)
    out_dir = Path(out_dir)
    spine_dir, log_dir = out_dir / "spine", out_dir / "raw" / "beacons"
    spine_dir.mkdir(parents=True, exist_ok=True)
    log_dir.mkdir(parents=True, exist_ok=True)

    start = spec.start
    end = start + timedelta(hours=spec.hours)
    at = lambda h: start + timedelta(hours=h)  # noqa: E731

    # ---- who wears which beacon when ------------------------------------------------
    wear: list[tuple[int, int, datetime, datetime | None]] = []  # beacon, person, from, to
    for p in spec.people:
        if spec.swap and spec.swap[0] == p:
            wear.append((p, p, start, at(spec.swap[2])))
            wear.append((spec.swap[1], p, at(spec.swap[2]), None))
        else:
            wear.append((p, p, start, None))
    person_beacons = sorted({b for b, *_ in wear})

    def wearer(beacon: int, t: datetime) -> int | None:
        for b, p, t0, t1 in wear:
            if b == beacon and t0 <= t and (t1 is None or t < t1):
                return p
        return None

    # ---- where is everyone ----------------------------------------------------------
    half = len(spec.people) // 2
    course = {p: ("course-a" if i < half else "course-b") for i, p in enumerate(spec.people)}

    def room_of_person(p: int, t: datetime) -> str:
        hour = int((t - start).total_seconds() // 3600)
        if hour % 4 == 0:
            return "plenum"
        if rng_hourly(p, hour) < 0.2:
            return "course-b" if course[p] == "course-a" else "course-a"  # visiting
        return course[p]

    hourly_cache: dict[tuple[int, int], float] = {}

    def rng_hourly(p: int, hour: int) -> float:
        key = (p, hour)
        if key not in hourly_cache:
            hourly_cache[key] = rng.random()
        return hourly_cache[key]

    def is_lost(beacon: int, t: datetime) -> bool:
        return bool(
            spec.lost and beacon == spec.lost[0] and at(spec.lost[1]) <= t < at(spec.lost[2])
        )

    def room_of_beacon(beacon: int, t: datetime) -> str | None:
        if is_lost(beacon, t):
            return "course-a"
        p = wearer(beacon, t)
        return None if p is None else room_of_person(p, t)

    room_beacons = {name: bid for bid, name in spec.rooms}

    # ---- beacon clocks ----------------------------------------------------------------
    boots: dict[int, list[datetime]] = {
        b: [start - timedelta(seconds=rng.randint(3_600, 50_000))] for b in person_beacons
    }
    if spec.reboot:
        boots[spec.reboot[0]].append(at(spec.reboot[1]))

    def uptime(beacon: int, t: datetime) -> int:
        boot = max(b for b in boots[beacon] if b <= t)
        return int((t - boot).total_seconds())

    # ---- simulate scans ---------------------------------------------------------------
    records: dict[int, list[tuple[datetime, str]]] = {b: [] for b in person_beacons}
    truth, truth_sr = [], []
    t = start
    while t < end:
        where = {b: room_of_beacon(b, t) for b in person_beacons}
        for observer, room in where.items():
            if room is None:
                continue
            others = [b for b, r in where.items() if r == room and b != observer]
            for observed in [*others, room_beacons[room]]:
                if rng.random() > spec.detection_p:
                    continue
                is_room = observed == room_beacons[room]
                rssi = -rng.randint(55, 95) if is_room else -rng.randint(40, 79)
                records[observer].append(
                    (t, f"ID2: {observed}, Timer: {uptime(observer, t)}, RSSI: {rssi}")
                )
                if not is_lost(observer, t):
                    observed_entity = (
                        f"location:{room}" if is_room else f"person:{wearer(observed, t)}"
                    )
                    if is_room or not is_lost(observed, t):
                        truth.append((f"person:{wearer(observer, t)}", observed_entity, t))
        t += timedelta(seconds=spec.scan_interval_s)

    for p in spec.people:
        for _ in range(spec.self_reports_per_person):
            t_sr = start + timedelta(seconds=rng.randrange(0, spec.hours * 3600))
            beacon = next(b for b in person_beacons if wearer(b, t_sr) == p)
            if is_lost(beacon, t_sr):
                continue
            records[beacon].append((t_sr, f"Self-report time: {uptime(beacon, t_sr)}"))
            truth_sr.append((f"person:{p}", t_sr))

    # ---- readouts → log files -----------------------------------------------------------
    id_bug_cutoff = at(spec.id_bug_until_h) if spec.id_bug_until_h is not None else None
    readout_times = [
        at(h) for h in range(spec.readout_every_h, spec.hours + 1, spec.readout_every_h)
    ]
    log_paths = []
    exported: dict[int, datetime] = {b: start - timedelta(days=1) for b in person_beacons}
    for base_time in readout_times:
        lines = []
        for j, beacon in enumerate(person_beacons):
            pc = base_time + timedelta(seconds=20 * j)
            pending = sorted(
                (r for r in records[beacon] if exported[beacon] < r[0] <= pc),
                key=lambda r: (r[0], not r[1].startswith("Self")),
            )
            exported[beacon] = pc
            header = str(beacon)
            if id_bug_cutoff and pc < id_bug_cutoff and 48 <= beacon <= 57:
                header = chr(beacon)
            prefix = f"{_local_str(pc)},ID: {header},"
            contacts = [text for _, text in pending if text.startswith("ID2")]
            reports = [text for _, text in pending if text.startswith("Self")]
            lines += [
                prefix + "Status: 0",
                prefix + f"Current Timer: {uptime(beacon, pc)}",
                prefix + f"Contact Count: {len(contacts)}",
                prefix + "Voltage: 3000",
                *(prefix + text for text in reports),
                *(prefix + text for text in contacts),
                prefix + "Transfer complete. Disconnecting",
            ]
        path = log_dir / f"dsa_{base_time:%Y%m%d_%H%M}.log"
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        log_paths.append(path)

    # ---- spine files ----------------------------------------------------------------------
    def dump(name: str, content) -> None:
        (spine_dir / f"{name}.yaml").write_text(yaml.safe_dump(content, sort_keys=False))

    dump("meta", {"study_id": "synthetic-camp", "timezone": spec.timezone})
    dump(
        "people",
        [{"id": str(p), "role": "participant", "consent": ["beacons", "self_report"]}
         for p in spec.people],
    )  # fmt: skip
    dump(
        "locations",
        [{"id": name, "label": name, "zone": name, "kind": "room"} for _, name in spec.rooms],
    )
    assignments = [
        {"device": f"beacon:{b}", "entity": f"person:{p}", "start": _local_str(t0),
         **({"end": _local_str(t1)} if t1 else {})}
        for b, p, t0, t1 in wear
    ] + [
        {"device": f"beacon:{bid}", "entity": f"location:{name}", "start": _local_str(start)}
        for bid, name in spec.rooms
    ]  # fmt: skip
    dump("assignments", assignments)
    dump("events", [])
    dump(
        "exclusions",
        [{"target": f"person:{spec.lost[0]}", "start": _local_str(at(spec.lost[1])),
          "end": _local_str(at(spec.lost[2])), "reason": "tag lost"}] if spec.lost else [],
    )  # fmt: skip

    def utc(values: list[datetime]) -> list[datetime]:
        return [v.replace(tzinfo=tz).astimezone(ZoneInfo("UTC")) for v in values]

    truth_df = pl.DataFrame(
        {
            "observer_entity": [o for o, _, _ in truth],
            "observed_entity": [d for _, d, _ in truth],
            "t": utc([t for *_, t in truth]),
        },
        schema_overrides={"t": pl.Datetime("us", "UTC")},
    )
    truth_sr_df = pl.DataFrame(
        {"entity": [e for e, _ in truth_sr], "t": utc([t for _, t in truth_sr])},
        schema_overrides={"t": pl.Datetime("us", "UTC")},
    )
    return SyntheticCamp(spec, spine_dir, log_paths, truth_df, truth_sr_df, id_bug_cutoff)
