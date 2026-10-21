"""Assemble the static public site: app files plus a validated ``data/`` directory.

The data is either a public bundle prepared elsewhere (``data_dir``) or a synthetic camp that
runs through the real pipeline, so CI and previews need no research data. Nothing is considered
built until ``validate_site_data`` accepts the copied ``data/``.
"""

from __future__ import annotations

import json
import shutil
import tempfile
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import polars as pl

from .. import paths
from ..explorer.synthetic import synthetic_inputs
from ..study import ExplorerConfig
from ..synth import CampSpec, generate
from .aggregates import check_aggregates, synthetic_aggregates
from .public import write_public_bundle
from .validate import SiteDataError, validate_site_data

EXPLORER_STATIC = Path(__file__).resolve().parents[1] / "explorer" / "static"
SITE_STATIC = Path(__file__).resolve().parent / "static"
SYNTHETIC_PEOPLE = 40
SYNTHETIC_COURSES = 4
#: Share of people who leave their course group in an hour: ordinary day, evening, special day.
MIX_DAY, MIX_EVENING, MIX_SPECIAL = 0.06, 0.3, 0.55
EVENING = (19, 23)  # local hours [start, end)


def _synthetic_spec(seed: int) -> CampSpec:
    # Many people, a long stretch, none of the field-data faults the default spec exercises.
    people = tuple(range(44, 44 + SYNTHETIC_PEOPLE))
    return CampSpec(
        hours=72,
        people=people,
        rooms=((201, "course-a"), (202, "course-b"), (203, "plenum")),
        reboot=None,
        swap=None,
        lost=None,
        id_bug_until_h=None,
        seed=seed,
    )


def _course_pairs(inp, nodes: dict[str, str], special: tuple[int, int], timezone: str, seed: int):
    """Close pairs for a camp with course structure, replacing the generator's dense ones.

    Every hour each person either stays with their course (in one of two small groups) or
    joins one of a few mixed groups; more people mix in the evening and on the special day.
    Members of a group are close in each bin of the hour in which both were heard, with a
    small dropout. The synthetic generator has no courses, so without this the demo network
    is one ball.
    """
    rng = np.random.default_rng(seed)
    tz = ZoneInfo(timezone)
    people = sorted(nodes)
    course = np.array([int(nodes[p]) for p in people])
    seen = inp.seen.with_columns(
        ((pl.col("bin") - inp.t0).dt.total_seconds() // inp.bin_seconds).alias("k")
    )
    heard = {(e, int(k)) for e, k in zip(seen["entity"], seen["k"], strict=True)}
    per_hour = 3600 // inp.bin_seconds
    rows_a, rows_b, rows_k = [], [], []
    for h0 in range(0, inp.n_bins, per_hour):
        local = (inp.t0 + timedelta(seconds=h0 * inp.bin_seconds)).astimezone(tz)
        if special[0] <= h0 < special[1]:
            mix = MIX_SPECIAL
        elif EVENING[0] <= local.hour < EVENING[1]:
            mix = MIX_EVENING
        else:
            mix = MIX_DAY
        n_mixed = max(2, round(mix * len(people) / 5))
        group = np.where(
            rng.random(len(people)) < mix,
            1000 + rng.integers(0, n_mixed, len(people)),
            course * 10 + rng.integers(0, 2, len(people)),
        )
        members: dict[int, list[int]] = {}
        for i, g in enumerate(group):
            members.setdefault(int(g), []).append(i)
        for idx in members.values():
            for x in range(len(idx)):
                for y in range(x + 1, len(idx)):
                    a, b = sorted((people[idx[x]], people[idx[y]]))
                    for k in range(h0, min(h0 + per_hour, inp.n_bins)):
                        if (a, k) in heard and (b, k) in heard and rng.random() > 0.15:
                            rows_a.append(a)
                            rows_b.append(b)
                            rows_k.append(k)
    t0 = pl.lit(inp.t0).dt.convert_time_zone("UTC")
    return pl.DataFrame(
        {"a": rows_a, "b": rows_b, "k": rows_k}, schema_overrides={"k": pl.Int64}
    ).select(
        "a",
        "b",
        (t0 + pl.duration(seconds=pl.col("k") * inp.bin_seconds)).alias("bin"),
        pl.lit(-60, dtype=pl.Int64).alias("max_rssi"),
    )


def synthetic_site_data(
    out_dir: Path, config: ExplorerConfig, *, timezone: str, seed: int = 0
) -> Path:
    """Write a synthetic public data directory (bundle plus aggregates) to ``out_dir``."""
    out_dir = paths.refuse_inside_repo(out_dir)
    with tempfile.TemporaryDirectory(prefix="see-synth-") as tmp:
        inp = synthetic_inputs(generate(_synthetic_spec(seed), Path(tmp) / "camp"))
    # A few courses, assigned deterministically, so the dots get course colours.
    nodes = {entity: str(i % SYNTHETIC_COURSES + 1) for i, entity in enumerate(sorted(inp.nodes))}
    third = inp.n_bins // 3
    pairs = _course_pairs(inp, nodes, (third, 2 * third), timezone, seed)
    inp = replace(inp, nodes=nodes, pairs=pairs.cast(inp.pairs.schema))
    write_public_bundle(
        inp,
        out_dir,
        config,
        timezone=timezone,
        special_days=[{"start_bin": third, "end_bin": 2 * third, "label": "excursion"}],
        synthetic=True,
        seed=seed,
    )
    agg = check_aggregates(synthetic_aggregates(seed), min_group=config.min_group)
    (out_dir / "aggregates.json").write_text(
        json.dumps(agg, indent=1, allow_nan=False), encoding="utf-8"
    )
    return out_dir


def _allowed_files(data_dir: Path) -> list[str]:
    """The files the site may serve; any other entry means the export is wrong."""
    meta = json.loads((data_dir / "meta.json").read_text(encoding="utf-8"))
    allowed = ["meta.json", "aggregates.json", *(f"{n}.bin" for n in sorted(meta.get("files", {})))]
    for entry in sorted(data_dir.iterdir()):
        if entry.name not in allowed or entry.is_symlink() or not entry.is_file():
            raise SiteDataError(f"{entry.name} is not part of the public data; the export is wrong")
    for name in allowed:
        if not (data_dir / name).is_file():
            raise SiteDataError(f"{name} is listed in the public data but missing")
    return allowed


def build_site(
    out: Path,
    data_dir: Path | None,
    *,
    config: ExplorerConfig | None = None,
    timezone: str | None = None,
    seed: int = 0,
) -> Path:
    """Build the site into ``out`` (outside the repo) and return it.

    With ``data_dir`` the public data is validated, copied and validated again; without it a
    synthetic camp is generated, which needs ``config`` and ``timezone``.
    """
    out = paths.refuse_inside_repo(out)
    if data_dir is None and (config is None or timezone is None):
        raise ValueError("a synthetic build needs config and timezone")
    min_group = config.min_group if config else 5
    if data_dir is not None:
        data_dir = Path(data_dir).resolve()
        if data_dir == out or out in data_dir.parents:
            raise ValueError(f"data dir {data_dir} is inside the output {out}, which is rebuilt")
        validate_site_data(data_dir, min_group=min_group)
        allowed = _allowed_files(data_dir)
    out.mkdir(parents=True, exist_ok=True)
    shutil.copytree(SITE_STATIC, out, dirs_exist_ok=True)
    (out / "vendor").mkdir(exist_ok=True)
    shutil.copy2(EXPLORER_STATIC / "vendor" / "d3.min.js", out / "vendor" / "d3.min.js")
    shutil.copy2(EXPLORER_STATIC / "model.js", out / "model.js")
    target = out / "data"
    if target.exists():
        shutil.rmtree(target)
    if data_dir is None:
        synthetic_site_data(target, config, timezone=timezone, seed=seed)
    else:
        target.mkdir()
        for name in allowed:
            shutil.copy2(data_dir / name, target / name)
    validate_site_data(target, min_group=min_group)
    return out
