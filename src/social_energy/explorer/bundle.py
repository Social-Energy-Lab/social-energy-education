"""The explorer bundle: an ID-free binary copy of already-filtered presence tables.

The bundle is what the browser app reads. It is written only outside the repository, and it
carries no study IDs, device IDs or names: nodes are shuffled indices ``0..N-1`` and the mapping
back to the spine is not written anywhere. Filtering (consent, exclusions, participants only) is
the caller's job and happens before ``write_bundle``; rows the bundle cannot place (an entity
that is not a node, a bin outside the range, an RSSI below the floor) are dropped and counted.

Layout: ``meta.json`` plus one ``.bin`` file per table. A ``.bin`` file is its columns
concatenated, little-endian, each ``count`` long; ``meta["files"]`` lists the columns in order.

    pairs.bin    bin u16 · a u16 · b u16 · rssi i8        (a < b; sorted by bin)
    seen.bin     bin u16 · node u16                       (sorted by bin)
    rooms.bin    bin u16 · node u16 · loc u16             (sorted by bin)
    presses.bin  sec u32 · node u16                       (seconds since t0; sorted)
    bins.bin     phase u8 · day u8                        (one row per bin)
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import polars as pl

from .. import paths
from ..study import ExplorerConfig

VERSION = 1
DTYPES = {"u8": np.uint8, "i8": np.int8, "u16": np.uint16, "u32": np.uint32}
COLUMNS = {
    "pairs": [("bin", "u16"), ("a", "u16"), ("b", "u16"), ("rssi", "i8")],
    "seen": [("bin", "u16"), ("node", "u16")],
    "rooms": [("bin", "u16"), ("node", "u16"), ("loc", "u16")],
    "presses": [("sec", "u32"), ("node", "u16")],
    "bins": [("phase", "u8"), ("day", "u8")],
}


@dataclass(frozen=True)
class BundleInput:
    t0: datetime  # UTC, start of bin 0
    n_bins: int
    bin_seconds: int
    nodes: dict[str, str | None]  # entity -> course key (None = unknown)
    locations: dict[str, tuple[str, str]]  # location entity -> (label, zone)
    pairs: pl.DataFrame  # a, b, bin (UTC), max_rssi
    seen: pl.DataFrame  # entity, bin
    rooms: pl.DataFrame  # entity, bin, location
    presses: pl.DataFrame  # entity, t (UTC)
    rssi_floor: int  # weakest RSSI kept in pairs


def _bin_index(col: str, inp: BundleInput) -> pl.Expr:
    t0 = pl.lit(inp.t0).dt.convert_time_zone("UTC")
    return ((pl.col(col) - t0).dt.total_seconds() // inp.bin_seconds).cast(pl.Int64)


def _in_range(k: pl.Expr, n: int) -> pl.Expr:
    return (k >= 0) & (k < n)


def _local_to_bin(value: str, tz: ZoneInfo, inp: BundleInput) -> int:
    t = datetime.fromisoformat(value).replace(tzinfo=tz).astimezone(UTC)
    k = int((t - inp.t0).total_seconds() // inp.bin_seconds)
    return min(max(k, 0), inp.n_bins)


def _write(out_dir: Path, name: str, frame: dict[str, np.ndarray]) -> dict:
    cols = COLUMNS[name]
    count = len(frame[cols[0][0]])
    with (out_dir / f"{name}.bin").open("wb") as f:
        for col, dtype in cols:
            dt = np.dtype(DTYPES[dtype]).newbyteorder("<")
            f.write(np.asarray(frame[col]).astype(dt).tobytes())
    return {"count": count, "columns": [list(c) for c in cols]}


def write_bundle(
    inp: BundleInput,
    out_dir: Path,
    config: ExplorerConfig,
    *,
    timezone: str,
    mode: str = "team",
    qa: dict | None = None,
    seed: int | None = None,
) -> dict:
    """Write the bundle for ``inp`` to ``out_dir`` (outside the repo). Returns its meta."""
    out_dir = paths.refuse_inside_repo(out_dir)
    if inp.n_bins > 65535 or len(inp.nodes) > 65535 or len(inp.locations) > 65535:
        raise ValueError("bundle indices are 16-bit: too many bins, nodes or locations")
    out_dir.mkdir(parents=True, exist_ok=True)
    tz = ZoneInfo(timezone)
    qa = dict(qa or {})

    # Nodes: shuffled from OS entropy (seed=None), so the order cannot be recomputed from this
    # public code and says nothing about study IDs. A seed is for tests only.
    entities = sorted(inp.nodes)
    order = np.random.default_rng(seed).permutation(len(entities))
    node_of = {e: int(order[i]) for i, e in enumerate(entities)}
    courses = list(config.courses)
    for e in entities:
        key = inp.nodes[e]
        if key is not None and key not in courses:
            courses.append(key)
    node_course = [-1] * len(entities)
    for e, i in node_of.items():
        key = inp.nodes[e]
        node_course[i] = courses.index(key) if key is not None else -1

    loc_entities = sorted(inp.locations)
    zones = sorted({zone for _, zone in inp.locations.values()})
    loc_of = {e: i for i, e in enumerate(loc_entities)}

    def node_expr(col: str) -> pl.Expr:
        return pl.col(col).replace_strict(node_of, default=None, return_dtype=pl.Int64)

    # Pairs.
    p = inp.pairs.with_columns(
        _bin_index("bin", inp).alias("k"), node_expr("a").alias("na"), node_expr("b").alias("nb")
    )
    has_node = pl.col("na").is_not_null() & pl.col("nb").is_not_null()
    qa["pairs_no_node"] = p.filter(~has_node).height
    p = p.filter(has_node)
    qa["pairs_out_of_range"] = p.filter(~_in_range(pl.col("k"), inp.n_bins)).height
    p = p.filter(_in_range(pl.col("k"), inp.n_bins))
    qa["pairs_below_floor"] = p.filter(pl.col("max_rssi") < inp.rssi_floor).height
    p = p.filter(pl.col("max_rssi") >= inp.rssi_floor).sort("k")
    na, nb = p["na"].to_numpy(), p["nb"].to_numpy()
    pairs = {
        "bin": p["k"].to_numpy(),
        "a": np.minimum(na, nb),
        "b": np.maximum(na, nb),
        "rssi": np.clip(p["max_rssi"].to_numpy(), -128, 127),
    }

    # Seen and rooms.
    s = (
        inp.seen.with_columns(_bin_index("bin", inp).alias("k"), node_expr("entity").alias("n"))
        .filter(pl.col("n").is_not_null() & _in_range(pl.col("k"), inp.n_bins))
        .select("k", "n")
        .unique()
        .sort("k", "n")
    )
    r = inp.rooms.with_columns(
        _bin_index("bin", inp).alias("k"),
        node_expr("entity").alias("n"),
        pl.col("location").replace_strict(loc_of, default=None, return_dtype=pl.Int64).alias("l"),
    )
    placed = pl.col("n").is_not_null() & pl.col("l").is_not_null()
    qa["rooms_dropped"] = r.filter(~(placed & _in_range(pl.col("k"), inp.n_bins))).height
    r = r.filter(placed & _in_range(pl.col("k"), inp.n_bins)).sort("k", "n")

    # Presses.
    t0 = pl.lit(inp.t0).dt.convert_time_zone("UTC")
    pr = inp.presses.with_columns(
        (pl.col("t") - t0).dt.total_seconds().alias("sec"), node_expr("entity").alias("n")
    )
    qa["presses_without_node"] = pr.filter(pl.col("n").is_null()).height
    pr = pr.filter(pl.col("n").is_not_null())
    span = inp.n_bins * inp.bin_seconds
    in_span = (pl.col("sec") >= 0) & (pl.col("sec") < span)
    qa["presses_out_of_range"] = pr.filter(~in_span).height
    pr = pr.filter(in_span).sort("sec")

    # Per-bin phase and camp day, in local time.
    day_start = datetime.strptime(config.day_start, "%H:%M")
    shift = timedelta(hours=day_start.hour, minutes=day_start.minute)
    phase, day, days = [], [], []
    first_day = None
    for k in range(inp.n_bins):
        local = (inp.t0 + timedelta(seconds=k * inp.bin_seconds)).astimezone(tz)
        phase.append(config.phase_of(local.time()) if config.phases else 0)
        camp_day = (local - shift).date()
        first_day = first_day or camp_day
        index = (camp_day - first_day).days
        day.append(index)
        if not days or days[-1]["index"] != index:
            days.append({"index": index, "label": camp_day.strftime("%a %d %b"), "start_bin": k})

    files = {
        "pairs": _write(out_dir, "pairs", pairs),
        "seen": _write(out_dir, "seen", {"bin": s["k"].to_numpy(), "node": s["n"].to_numpy()}),
        "rooms": _write(
            out_dir,
            "rooms",
            {"bin": r["k"].to_numpy(), "node": r["n"].to_numpy(), "loc": r["l"].to_numpy()},
        ),
        "presses": _write(
            out_dir, "presses", {"sec": pr["sec"].to_numpy(), "node": pr["n"].to_numpy()}
        ),
        "bins": _write(out_dir, "bins", {"phase": np.array(phase), "day": np.array(day)}),
    }

    def ranges(items: list[dict], label: str) -> list[dict]:
        return [
            {
                "start_bin": _local_to_bin(item["start"], tz, inp),
                "end_bin": _local_to_bin(item["end"], tz, inp),
                label: item[label],
            }
            for item in items
        ]

    meta = {
        "version": VERSION,
        "mode": mode,
        "timezone": timezone,
        "t0": inp.t0.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "bin_seconds": inp.bin_seconds,
        "n_bins": inp.n_bins,
        "rssi_floor": inp.rssi_floor,
        "nodes": [{"course": c} for c in node_course],
        "courses": [{"key": k, "name": config.courses.get(k, k)} for k in courses],
        "locations": [
            {"label": inp.locations[e][0], "zone": zones.index(inp.locations[e][1])}
            for e in loc_entities
        ],
        "zones": zones,
        "phases": [name for name, _ in config.phases] or ["all"],
        "days": days,
        "notes": ranges(config.notes, "text"),
        "shade": ranges(config.shade, "label"),
        "defaults": config.defaults,
        "min_group": config.min_group,
        "qa": qa,
        "files": files,
    }
    (out_dir / "meta.json").write_text(json.dumps(meta, indent=1), encoding="utf-8")
    return meta


def read_bundle(bundle_dir: Path) -> tuple[dict, dict[str, dict[str, np.ndarray]]]:
    """Read a bundle back: its meta and, per table, its columns as numpy arrays."""
    bundle_dir = Path(bundle_dir)
    meta = json.loads((bundle_dir / "meta.json").read_text(encoding="utf-8"))
    tables = {}
    for name, spec in meta["files"].items():
        data = (bundle_dir / f"{name}.bin").read_bytes()
        offset, cols = 0, {}
        for col, dtype in spec["columns"]:
            dt = np.dtype(DTYPES[dtype]).newbyteorder("<")
            cols[col] = np.frombuffer(data, dtype=dt, count=spec["count"], offset=offset)
            offset += dt.itemsize * spec["count"]
        tables[name] = cols
    return meta, tables
