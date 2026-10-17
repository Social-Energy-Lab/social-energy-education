"""BLE proximity beacons: logger files → canonical contact, self-report and eco tables."""

from .cycles import (
    estimate_clock_rate,
    lost_windows,
    power_cycles,
    read_clock_anchors,
    read_deliveries,
)
from .ingest import BeaconConfig, BeaconTables, ingest_logs, ingest_logs_to
from .presses import press_episodes
from .witness import decide, ingest_with_witnesses, votes_from_tables, witness_votes

__all__ = [
    "BeaconConfig",
    "BeaconTables",
    "decide",
    "estimate_clock_rate",
    "ingest_logs",
    "ingest_logs_to",
    "ingest_with_witnesses",
    "lost_windows",
    "power_cycles",
    "press_episodes",
    "read_clock_anchors",
    "read_deliveries",
    "votes_from_tables",
    "witness_votes",
]
