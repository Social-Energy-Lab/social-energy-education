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
from .purge import (
    ManifestError,
    PurgedDeviceError,
    check_purged,
    find_purged_lines,
    purge_devices,
)
from .witness import decide, ingest_with_witnesses, votes_from_tables, witness_votes

__all__ = [
    "BeaconConfig",
    "BeaconTables",
    "ManifestError",
    "PurgedDeviceError",
    "check_purged",
    "decide",
    "estimate_clock_rate",
    "find_purged_lines",
    "ingest_logs",
    "ingest_logs_to",
    "ingest_with_witnesses",
    "lost_windows",
    "power_cycles",
    "press_episodes",
    "purge_devices",
    "read_clock_anchors",
    "read_deliveries",
    "votes_from_tables",
    "witness_votes",
]
