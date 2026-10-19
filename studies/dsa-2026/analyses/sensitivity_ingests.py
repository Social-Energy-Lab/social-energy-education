"""Beacon ingests rebuilt with one setting changed, for sensitivities 2 and 3 of the analysis plan.

``research/analysis-plan.md`` reruns every confirmatory result on these. Each variant changes one
setting of ``study.yaml``'s beacon config, ingests the raw logs again into a folder of its own and
builds the tables ``outcomes.py`` reads from it, so the main ingest is never touched:

* ``hand_split_fill`` (sensitivity 2): readouts our ID repair leaves ambiguous (clock anchors, then
  witnesses) take the beacon team's hand label instead of staying unsettled. The labels come from
  their relabelled copies of the 13-15 Aug logs (``raw/beacons-reference/**/Logs_cleaned/``, the
  same files ``id_repair_benchmark.py`` compares against), matched line by line to our raw logs
  (``beacons.reference_labels``) and passed as ``id_fallback``: they settle nothing anchors or
  witnesses settle. Readouts the hand split did not label (no copy, or a split label) stay
  ambiguous, and their unsettled windows stay out as in the main run.
* ``no_drift`` (sensitivity 3): no clock-drift correction, ``clock_rate_ppm`` 0 instead of the
  study's rate. Its lost windows are computed from power cycles at the same rate 0.

Per variant, under ``$SOCIAL_ENERGY_DATA/dsa-2026/derived/sensitivity/<variant>/``:
``beacons/`` (the ingest, as ``social-energy ingest-beacons`` writes it, plus
``hand_labels.parquet`` for the hand-split fill), ``analyses/copresence-by-phase/``
(``copresence_by_phase.py build``) and ``analyses/beacon-diagnostics/{lost,unsettled}_windows``.

Reads the spine (resolution, exclusions, consent), so rerun after a spine change. Then run
``outcomes.py``, which adds one row per participant for each variant built here.

    uv run --extra analysis python studies/dsa-2026/analyses/sensitivity_ingests.py [variant ...]
"""

from __future__ import annotations

import dataclasses
import json
import sys
from pathlib import Path

import polars as pl

sys.path.insert(0, str(Path(__file__).parent))
import beacon_diagnostics as bd
import copresence_by_phase as cp
from id_repair_benchmark import HAND_SPLIT_GLOB

from social_energy import cli, paths
from social_energy.beacons import BeaconConfig, reference_labels
from social_energy.study import StudyConfig

VARIANTS = ["hand_split_fill", "no_drift"]


def hand_split_pairs(layout: paths.StudyLayout) -> list[tuple[Path, Path]]:
    """(raw log, the beacon team's relabelled copy of it), for every copy that has its original."""
    pairs = []
    for copy in sorted(layout.raw.glob(HAND_SPLIT_GLOB)):
        original = layout.raw / "beacons" / "Logs" / copy.name.replace("_cleaned", "")
        if not original.exists():
            raise SystemExit(f"no raw log for the hand-split copy {copy.name}")
        pairs.append((original, copy))
    if not pairs:
        raise SystemExit(f"no hand-split copies under {layout.raw} matching {HAND_SPLIT_GLOB}")
    return pairs


def config_for(
    variant: str, study: StudyConfig, layout: paths.StudyLayout
) -> tuple[BeaconConfig, pl.DataFrame | None]:
    """The study's beacon config with the variant's one change, and the hand labels it used."""
    config = study.beacon_config()
    if variant == "no_drift":
        return dataclasses.replace(config, clock_rate_ppm=0.0), None
    if variant == "hand_split_fill":
        labels = reference_labels(hand_split_pairs(layout), config)
        settled = labels.drop_nulls("beacon")
        fallback = tuple(zip(settled["readout_key"], settled["beacon"], strict=True))
        return dataclasses.replace(config, id_fallback=fallback), labels
    raise SystemExit(f"unknown variant {variant!r}; known: {VARIANTS}")


def run(variant: str) -> None:
    study = StudyConfig.load(cp.STUDY_YAML)
    layout = paths.study(cp.STUDY)
    config, labels = config_for(variant, study, layout)
    root = cp.derived_root(variant)
    if cli.ingest_beacons(study, config, root / "beacons") != 0:
        raise SystemExit(f"{variant}: ingest failed")
    if labels is not None:
        labels.write_parquet(root / "beacons" / "hand_labels.parquet")
    cp.build(variant, upstream=False)
    lost, unsettled = bd.write_windows(variant, config.clock_rate_ppm)
    qa = json.loads((root / "beacons" / "qa.json").read_text())
    print(
        json.dumps(
            {
                "variant": variant,
                "ids_ambiguous": qa["ids_ambiguous"],
                "ids_witnessed": qa["ids_witnessed"],
                "ids_fallback": qa["ids_fallback"],
                "lost_windows": lost.height,
                "unsettled_windows": unsettled.height,
            }
        ),
        flush=True,
    )


def main() -> None:
    chosen = sys.argv[1:] or VARIANTS
    for variant in chosen:
        if variant not in VARIANTS:
            raise SystemExit(f"unknown variant {variant!r}; known: {VARIANTS}")
    for variant in chosen:
        run(variant)


if __name__ == "__main__":
    main()
