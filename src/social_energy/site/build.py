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
from pathlib import Path

from .. import paths
from ..explorer.synthetic import synthetic_inputs
from ..study import ExplorerConfig
from ..synth import CampSpec, generate
from .aggregates import check_aggregates, synthetic_aggregates
from .public import write_public_bundle
from .validate import validate_site_data

EXPLORER_STATIC = Path(__file__).resolve().parents[1] / "explorer" / "static"
SITE_STATIC = Path(__file__).resolve().parent / "static"
SYNTHETIC_PEOPLE = 40
SYNTHETIC_COURSES = 4


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


def synthetic_site_data(
    out_dir: Path, config: ExplorerConfig, *, timezone: str, seed: int = 0
) -> Path:
    """Write a synthetic public data directory (bundle plus aggregates) to ``out_dir``."""
    out_dir = paths.refuse_inside_repo(out_dir)
    with tempfile.TemporaryDirectory(prefix="see-synth-") as tmp:
        inp = synthetic_inputs(generate(_synthetic_spec(seed), Path(tmp) / "camp"))
    # A few courses, assigned deterministically, so the dots get course colours.
    nodes = {entity: str(i % SYNTHETIC_COURSES + 1) for i, entity in enumerate(sorted(inp.nodes))}
    inp = replace(inp, nodes=nodes)
    third = inp.n_bins // 3
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
    if data_dir is not None:
        validate_site_data(data_dir)
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
        shutil.copytree(data_dir, target)
    validate_site_data(target, **({"min_group": config.min_group} if config else {}))
    return out
