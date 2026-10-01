"""Explorer inputs from a synthetic camp: for tests, development and a public demo.

Runs the synthetic camp through the real pipeline (ingest, spine resolution, presence), so a
bundle made here exercises the same code paths as one made from field data.
"""

from __future__ import annotations

from datetime import timedelta

import polars as pl

from ..beacons import BeaconConfig, ingest_logs
from ..presence import copresence, room_per_bin
from ..spine import Spine
from ..synth import SyntheticCamp
from .bundle import BundleInput

BIN_SECONDS = 300


def synthetic_inputs(camp: SyntheticCamp) -> BundleInput:
    """Bundle inputs for every person in ``camp``; each room is its own zone."""
    spec = camp.spec
    config = BeaconConfig(
        timezone=spec.timezone,
        valid_from=spec.start.date(),
        valid_to=(spec.start + timedelta(hours=spec.hours)).date(),
        ambiguous_id_cutoff=camp.id_bug_cutoff,
    )
    tables = ingest_logs(camp.log_paths, config)
    spine = Spine.load(camp.spine_dir)
    contacts = spine.resolve(
        tables.contacts, device_col="beacon", time_col="t", kind="beacon", out="observer_entity"
    )
    contacts = spine.resolve(
        contacts, device_col="observed", time_col="t", kind="beacon", out="observed_entity"
    ).filter(pl.col("ok") & pl.col("observer_entity").is_not_null())
    contacts = contacts.filter(pl.col("observed_entity").is_not_null())
    reports = spine.resolve(
        tables.self_reports, device_col="beacon", time_col="t", kind="beacon", out="entity"
    ).filter(pl.col("ok") & pl.col("entity").is_not_null())

    people = sorted({p.ref for p in spine.people})
    rooms = {loc.ref: (loc.label, loc.zone) for loc in spine.locations}
    pairs = copresence(contacts, every=f"{BIN_SECONDS}s")
    seen = (
        pl.concat(
            [
                contacts.select(pl.col("observer_entity").alias("entity"), "t"),
                contacts.select(pl.col("observed_entity").alias("entity"), "t"),
            ]
        )
        .filter(pl.col("entity").is_in(people))
        .select("entity", pl.col("t").dt.truncate(f"{BIN_SECONDS}s").alias("bin"))
        .unique()
    )
    t0 = seen["bin"].min()
    n_bins = int((seen["bin"].max() - t0) / timedelta(seconds=BIN_SECONDS)) + 1
    # Two synthetic "courses", alternating, so course views have something to show.
    nodes = {p: f"{i % 2 + 1}" for i, p in enumerate(people)}
    return BundleInput(
        t0=t0,
        n_bins=n_bins,
        bin_seconds=BIN_SECONDS,
        nodes=nodes,
        locations=rooms,
        pairs=pairs.select("a", "b", "bin", "max_rssi"),
        seen=seen,
        rooms=room_per_bin(contacts, every=f"{BIN_SECONDS}s").select("entity", "bin", "location"),
        presses=reports.select("entity", "t"),
        rssi_floor=int(pairs["max_rssi"].min()) if pairs.height else -128,
    )
