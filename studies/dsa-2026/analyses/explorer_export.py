"""Export DSA 2026 to an explorer bundle (``social_energy.explorer``), locally.

Research question: none of its own. The bundle feeds the team's interactive explorer, which
mirrors ``copresence_by_phase.py`` (RQ3) and ``self_report_context.py`` (RQ1).

Inputs and filters are those analyses' own, unchanged:

- Pairs, tags heard and rooms per 5-minute bin from ``copresence_by_phase.py build`` (the
  upstream ``Output/`` tables; window, spine resolution, exclusion windows, ``beacons`` consent),
  which must have run first. Pairs are kept down to the study's person-tag RSSI threshold, so the
  explorer's close-range slider can range over everything the build kept.
- Press episodes from ``self_report_context.press_episodes`` (``self_report`` consent).
- Nodes: participants with ``beacons`` consent. Their course comes from the local roster.

The bundle is written to ``$SOCIAL_ENERGY_DATA/dsa-2026/derived/explorer/bundle/``. It carries no
study IDs, but it is pseudonymised individual data about minors: team use only, never shared.

    uv run --extra analysis python studies/dsa-2026/analyses/explorer_export.py
    uv run social-energy explore studies/dsa-2026/study.yaml
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import polars as pl

sys.path.insert(0, str(Path(__file__).parent))
import copresence_by_phase as cp
import self_report_context as sr

from social_energy import paths
from social_energy.explorer import BundleInput, write_bundle
from social_energy.spine import Spine
from social_energy.study import StudyConfig

BIN_SECONDS = 300


def main() -> None:
    study = StudyConfig.load(cp.STUDY_YAML)
    ex = study.explorer_config()
    layout = paths.study(cp.STUDY)
    spine = Spine.load(layout.spine)

    participants = {p.ref for p in spine.people if p.role == "participant"}
    nodes = sorted(participants & {f"person:{p}" for p in spine.consented("beacons")})
    consented_sr = {f"person:{p}" for p in spine.consented("self_report")}
    roster = next((layout.root / "context" / "personal").glob("*StudyIDs*.md"))
    course = cp.course_of(roster)

    tz = ZoneInfo(study.timezone)
    start = datetime.fromisoformat(f"{cp.FIRST_DAY} {ex.day_start}").replace(tzinfo=tz)
    end = datetime.fromisoformat(f"{cp.LAST_DAY} {ex.day_start}").replace(tzinfo=tz)
    n_bins = int((end - start) / timedelta(seconds=BIN_SECONDS))

    pairs = cp.load_all("pairs").filter(pl.col("a").is_in(nodes) & pl.col("b").is_in(nodes))
    seen = cp.load_all("seen").filter(pl.col("entity").is_in(nodes))
    rooms = cp.load_all("rooms").filter(pl.col("entity").is_in(nodes))
    presses, qa = sr.press_episodes(layout, spine, participants, consented_sr)

    inp = BundleInput(
        t0=start.astimezone(ZoneInfo("UTC")),
        n_bins=n_bins,
        bin_seconds=BIN_SECONDS,
        nodes={p: course.get(p) for p in nodes},
        locations={loc.ref: (loc.label, loc.zone) for loc in spine.locations},
        pairs=pairs.select("a", "b", "bin", "max_rssi"),
        seen=seen.select("entity", "bin"),
        rooms=rooms.select("entity", "bin", "location"),
        presses=presses.select("entity", "t"),
        rssi_floor=study.raw["beacons"]["rssi_threshold_dbm"]["person_tag"],
    )
    out = layout.derived / "explorer" / "bundle"
    meta = write_bundle(inp, out, ex, timezone=study.timezone, mode="team", qa=qa)
    print(f"{out}: {len(meta['nodes'])} nodes, {meta['n_bins']} bins")
    print({k: v for k, v in meta["qa"].items()})


if __name__ == "__main__":
    main()
