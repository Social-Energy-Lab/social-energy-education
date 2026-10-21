"""The public bundle: a coarser, course-free copy of the explorer bundle for a public site.

Compared with the team bundle it drops locations, rooms, RSSI values, course names and the QA
counts. Pairs are kept only when close; presses are reduced to a 5-minute bin; the night is
removed entirely and course indices are permuted once, so a published index names no course.
Output goes outside the repository only. Filtering is the caller's job, as for ``write_bundle``.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import polars as pl

from .. import paths
from ..explorer.bundle import (
    VERSION,
    BundleInput,
    _bin_index,
    _in_range,
    _local_to_bin,
    _write,
)
from ..study import ExplorerConfig

PUBLIC_COLUMNS = {
    "pairs": [("bin", "u16"), ("a", "u16"), ("b", "u16")],
    "seen": [("bin", "u16"), ("node", "u16")],
    "presses": [("bin", "u16"), ("node", "u16")],
    "bins": [("phase", "u8"), ("day", "u8"), ("shown", "u8")],
}
PUBLIC_META_KEYS = {
    "version",
    "mode",
    "synthetic",
    "timezone",
    "t0",
    "bin_seconds",
    "n_bins",
    "nodes",
    "n_courses",
    "phases",
    "days",
    "special_days",
    "shade",
    "files",
}


def _is_night(clock: time, start: time, end: time) -> bool:
    """Whether ``clock`` is in [start, end), wrapping past midnight; equal bounds mean never."""
    if start == end:
        return False
    if start < end:
        return start <= clock < end
    return clock >= start or clock < end


def write_public_bundle(
    inp: BundleInput,
    out_dir: Path,
    config: ExplorerConfig,
    *,
    timezone: str,
    close_rssi: int = -65,
    night: tuple[str, str] = ("00:00", "06:00"),
    special_days: list[dict] = (),
    shade_label: str = "records missing",
    synthetic: bool = False,
    seed: int | None = None,
) -> dict:
    """Write the public bundle for ``inp`` to ``out_dir`` (outside the repo). Returns its meta."""
    out_dir = paths.refuse_inside_repo(out_dir)
    if inp.n_bins > 65535 or len(inp.nodes) > 65535:
        raise ValueError("bundle indices are 16-bit: too many bins or nodes")
    out_dir.mkdir(parents=True, exist_ok=True)
    tz = ZoneInfo(timezone)

    # Nodes and courses: both permuted from OS entropy (seed is for tests only).
    rng = np.random.default_rng(seed)
    entities = sorted(inp.nodes)
    order = rng.permutation(len(entities))
    node_of = {e: int(order[i]) for i, e in enumerate(entities)}
    keys = sorted({k for k in inp.nodes.values() if k is not None})
    course_order = rng.permutation(len(keys))
    course_of = {k: int(course_order[i]) for i, k in enumerate(keys)}
    node_course = [-1] * len(entities)
    for e, i in node_of.items():
        key = inp.nodes[e]
        node_course[i] = course_of[key] if key is not None else -1

    # Per-bin phase, camp day and whether the bin is shown (night is judged on the bin start).
    night_start, night_end = (time.fromisoformat(v) for v in night)
    day_start = datetime.strptime(config.day_start, "%H:%M")
    shift = timedelta(hours=day_start.hour, minutes=day_start.minute)
    phase, day, shown, days = [], [], [], []
    first_day = None
    for k in range(inp.n_bins):
        local = (inp.t0 + timedelta(seconds=k * inp.bin_seconds)).astimezone(tz)
        phase.append(config.phase_of(local.time()) if config.phases else 0)
        camp_day = (local - shift).date()
        first_day = first_day or camp_day
        index = (camp_day - first_day).days
        day.append(index)
        shown.append(0 if _is_night(local.time(), night_start, night_end) else 1)
        if not days or days[-1]["index"] != index:
            days.append({"index": index, "label": camp_day.strftime("%a %d %b"), "start_bin": k})
    shown_arr = np.array(shown)

    def node_expr(col: str) -> pl.Expr:
        return pl.col(col).replace_strict(node_of, default=None, return_dtype=pl.Int64)

    shown_bins = [k for k, v in enumerate(shown) if v]

    def visible(k: pl.Expr) -> pl.Expr:
        return k.is_in(shown_bins)

    p = inp.pairs.with_columns(
        _bin_index("bin", inp).alias("k"), node_expr("a").alias("na"), node_expr("b").alias("nb")
    ).filter(
        pl.col("na").is_not_null()
        & pl.col("nb").is_not_null()
        & (pl.col("max_rssi") >= close_rssi)
        & _in_range(pl.col("k"), inp.n_bins)
    )
    p = p.filter(visible(pl.col("k"))).with_columns(
        a=pl.min_horizontal("na", "nb"), b=pl.max_horizontal("na", "nb")
    )
    # Sorted on permuted indices, so row order cannot echo the original entity order.
    p = p.sort("k", "a", "b")
    pairs = {"bin": p["k"].to_numpy(), "a": p["a"].to_numpy(), "b": p["b"].to_numpy()}

    s = (
        inp.seen.with_columns(_bin_index("bin", inp).alias("k"), node_expr("entity").alias("n"))
        .filter(pl.col("n").is_not_null() & _in_range(pl.col("k"), inp.n_bins))
        .filter(visible(pl.col("k")))
        .select("k", "n")
        .unique()
        .sort("k", "n")
    )

    pr = (
        inp.presses.with_columns(_bin_index("t", inp).alias("k"), node_expr("entity").alias("n"))
        .filter(pl.col("n").is_not_null() & _in_range(pl.col("k"), inp.n_bins))
        .filter(visible(pl.col("k")))
        .select("k", "n")
        .sort("k", "n")
    )

    files = {
        "pairs": _write(out_dir, "pairs", pairs, PUBLIC_COLUMNS),
        "seen": _write(
            out_dir, "seen", {"bin": s["k"].to_numpy(), "node": s["n"].to_numpy()}, PUBLIC_COLUMNS
        ),
        "presses": _write(
            out_dir,
            "presses",
            {"bin": pr["k"].to_numpy(), "node": pr["n"].to_numpy()},
            PUBLIC_COLUMNS,
        ),
        "bins": _write(
            out_dir,
            "bins",
            {"phase": np.array(phase), "day": np.array(day), "shown": shown_arr},
            PUBLIC_COLUMNS,
        ),
    }

    shade = [
        {
            "start_bin": _local_to_bin(item["start"], tz, inp),
            "end_bin": _local_to_bin(item["end"], tz, inp),
            "label": shade_label,
        }
        for item in config.shade
    ]
    meta = {
        "version": VERSION,
        "mode": "public",
        "synthetic": bool(synthetic),
        "timezone": timezone,
        "t0": inp.t0.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "bin_seconds": inp.bin_seconds,
        "n_bins": inp.n_bins,
        "nodes": [{"course": c} for c in node_course],
        "n_courses": len(keys),
        "phases": [name for name, _ in config.phases] or ["all"],
        "days": days,
        "special_days": [dict(d) for d in special_days],
        "shade": shade,
        "files": files,
    }
    (out_dir / "meta.json").write_text(json.dumps(meta, indent=1), encoding="utf-8")
    return meta
